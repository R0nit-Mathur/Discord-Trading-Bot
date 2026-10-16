"""Lazy, shared channel-history rebuilds. Discord messages are the durable source."""
import asyncio
from datetime import datetime, timedelta, timezone
import re
import time


def renewal_target(message, bot_id):
    if message.author.id != bot_id:
        return None
    for embed in message.embeds:
        footer = getattr(embed.footer, 'text', '') or ''
        match = re.fullmatch(r'clover:renew:(\d{1,22})', footer)
        if match:
            return int(match[1])
    return None


class HistoryIndex:
    def __init__(self, recover, bot_id, refresh_seconds=120):
        self.recover = recover
        self.bot_id = bot_id
        self.refresh_seconds = refresh_seconds
        self.tasks = {}
        self.checked = {}
        self.errors = {}
        self.scanned = {}

    def invalidate(self, channel_id):
        self.checked.pop(channel_id, None)

    def task_for(self, channel):
        key = channel.id
        task = self.tasks.get(key)
        if task and not task.done():
            return task
        if task and not task.cancelled() and not self.errors.get(key) and time.monotonic() - self.checked.get(key, 0) < self.refresh_seconds:
            return task
        self.tasks[key] = asyncio.create_task(self.scan(channel))
        return self.tasks[key]

    async def ensure(self, channels, timeout=1.5):
        jobs = [self.task_for(c) for c in channels]
        if jobs:
            # A caller timeout must not cancel the shared rebuild for the next caller.
            await asyncio.wait(jobs, timeout=timeout)
        pending = any(not t.done() for t in jobs)
        failed = any(self.errors.get(c.id) for c in channels)
        return pending, failed

    async def scan(self, channel):
        key = channel.id
        self.errors.pop(key, None)
        self.scanned[key] = 0
        after = datetime.now(timezone.utc) - timedelta(hours=24)
        renewals = {}
        try:
            # No arbitrary message-count limit; read every post in the active 24-hour window.
            # Newest first gives useful partial results quickly. History paginates via discord.py.
            async for message in channel.history(limit=None, after=after, oldest_first=False):
                self.scanned[key] += 1
                target = renewal_target(message, self.bot_id())
                if target:
                    timestamp = message.created_at.timestamp()
                    renewals[target] = max(timestamp, renewals.get(target, 0))
                elif not message.author.bot:
                    await self.recover(message, None)
            # A renewed original may be older than the history window, so fetch it explicitly.
            for target, timestamp in renewals.items():
                try:
                    message = await channel.fetch_message(target)
                except Exception as error:
                    if getattr(error, 'status', None) == 404:
                        continue
                    raise
                await self.recover(message, timestamp)
            self.checked[key] = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Keep partial data but don't present an incomplete scan as a complete empty market.
            self.errors[key] = type(error).__name__

    async def close(self):
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
