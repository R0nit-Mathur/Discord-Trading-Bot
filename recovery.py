"""Lazy, shared recovery of bot-authored cards; never reads ordinary member messages."""
import asyncio
from datetime import datetime, timedelta, timezone
import time


class HistoryIndex:
    def __init__(self, recover, bot_id, refresh_seconds=120):
        self.recover = recover
        self.bot_id = bot_id
        self.refresh_seconds = refresh_seconds
        self.tasks, self.checked, self.errors, self.scanned = {}, {}, {}, {}

    def invalidate(self, channel_id):
        self.checked.pop(channel_id, None)

    def task_for(self, channel):
        key = channel.id
        task = self.tasks.get(key)
        if task and not task.done():
            return task
        if task and not task.cancelled() and not self.errors.get(key) and time.monotonic()-self.checked.get(key,0) < self.refresh_seconds:
            return task
        self.tasks[key] = asyncio.create_task(self.scan(channel))
        return self.tasks[key]

    async def ensure(self, channels, timeout=1.5):
        jobs = [self.task_for(c) for c in channels]
        if jobs:
            await asyncio.wait(jobs, timeout=timeout)
        return any(not t.done() for t in jobs), any(self.errors.get(c.id) for c in channels)

    async def scan(self, channel):
        self.errors.pop(channel.id, None)
        self.scanned[channel.id] = 0
        try:
            after = datetime.now(timezone.utc)-timedelta(hours=24)
            async for message in channel.history(limit=None, after=after, oldest_first=False):
                self.scanned[channel.id] += 1
                if message.author.id == self.bot_id():
                    await self.recover(message)
            self.checked[channel.id] = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.errors[channel.id] = type(error).__name__

    async def close(self):
        jobs = [t for t in self.tasks.values() if not t.done()]
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
