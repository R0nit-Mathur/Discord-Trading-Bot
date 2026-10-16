"""Clover Legends community marketplace. Run --sync explicitly to register commands."""
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from core import Catalog, InvalidOffer, Store
from recovery import HistoryIndex
from health import make_app
from aiohttp import web

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
catalog = Catalog(ROOT / 'catalog.json')
db_path = Path(os.getenv('DATABASE_PATH', ':memory:'))
store = Store(':memory:' if str(db_path) == ':memory:' else db_path if db_path.is_absolute() else ROOT / db_path)
log = logging.getLogger('clover')
RULES = ('Both players must be level 100+. Each side has 9 slots; a material stack uses one slot. '
         'Only spare, unequipped spellbooks from your bag can be traded; Robux-bought books cannot. '
         'The recipient needs free bag space for books. Any in-game offer change resets both Accept buttons. '
         'Negotiate in DMs and complete the exchange in Clover Legends. No cross-trading, links, Robux, or begging.')
HELP = '''**Post in a configured trading channel**
`Time x1 => Light x1`
`Trading 250 Ancient Sap + Fire for offers`
`:cl_book_time: => :cl_book_light:` (or select the actual mapped server emojis)
One post is one offer. Use exact item names, quantities, and one separator. Repeated emojis count copies.
🔎 Bot reaction = indexed. ⚠️ = not indexed; fix the format or item.
React ✅ **on your own post**, or edit ✅ into it, when the whole offer is no longer available.
Edit your post to remove just one item. Remove your ✅ and use `/renew` to reopen. The bot may also show ✅ to preserve closed status.
**Commands**
`/search` find sellers using text or a mapped emoji, with item autocomplete.
`/myoffers` see your active listings and their IDs.
`/close` close your whole listing. `/renew` refresh or reopen your listing for 24 hours.
`/items` browse tradeable names. `/rules` show the game restrictions.
**Moderators**: `/setup`, `/emoji_sync`, `/emoji_bind`, `/status`.
Active offers are member claims, not verified in-game inventory. This launch does not award trade counts.'''


class Clover(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.warned = {}
        self.semaphore = asyncio.Semaphore(4)
        self.history_index = HistoryIndex(self.recover_message, lambda: self.user.id if self.user else 0)
        self.configured = False

    async def setup_hook(self):
        if '--sync' in sys.argv or os.getenv('SYNC_COMMANDS', '0') == '1':
            guild_id = os.getenv('GUILD_ID')
            if not guild_id:
                raise RuntimeError('Set GUILD_ID before --sync; this build uses server commands.')
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info('Registered commands for configured server.')
        self.reconcile.start()

    async def on_ready(self):
        self.restore_configuration()
        # Reconnects may have missed messages; the next search shares a fresh rebuild.
        for channel in list(self.history_index.checked):
            self.history_index.invalidate(channel)
        log.info('Ready as %s', self.user)

    def restore_configuration(self):
        self.configured = False
        guild_id = os.getenv('GUILD_ID', '')
        guild = self.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if not guild:
            log.error('GUILD_ID must identify a server containing this bot.')
            return
        channels = [v.strip() for v in os.getenv('TRADING_CHANNEL_IDS', '').split(',') if v.strip()]
        if not channels or any(not v.isdigit() or not isinstance(guild.get_channel(int(v)), discord.TextChannel) for v in channels):
            log.error('Set TRADING_CHANNEL_IDS to accessible trading text channel IDs.')
            return
        for channel in channels:
            perms = guild.get_channel(int(channel)).permissions_for(guild.me)
            if not all([perms.view_channel, perms.read_message_history, perms.send_messages, perms.add_reactions, perms.embed_links]):
                log.error('Trading channels need View Channel, Read Message History, Send Messages, Add Reactions and Embed Links.')
                return
            store.configure(guild.id, channel, True)
        expected = {i['emoji_name']: i['id'] for i in catalog.items.values()}
        expected.update(cl_trade='separator', cl_offers='offers')
        grouped = {}
        for emoji in guild.emojis:
            grouped.setdefault(emoji.name, []).append(emoji)
        for name, target in expected.items():
            if len(grouped.get(name, [])) == 1:
                store.bind(guild.id, grouped[name][0].id, target)
        try:
            overrides = json.loads(os.getenv('EMOJI_MAP_JSON', '{}'))
            if not isinstance(overrides, dict):
                raise ValueError('Expected an object')
            for emoji_id, target in overrides.items():
                if not str(emoji_id).isdigit() or target not in {*catalog.items, 'separator', 'offers'}:
                    raise ValueError('Invalid emoji mapping')
                store.bind(guild.id, emoji_id, target)
        except (ValueError, TypeError):
            log.error('EMOJI_MAP_JSON must map emoji IDs to valid catalog item IDs or separator/offers.')
            return
        self.configured = True

    def health_status(self):
        return {'service': 'clover-trading', 'discord_ready': self.is_ready(),
                'configured': self.configured, 'cache': 'temporary',
                'history_loading': any(not t.done() for t in self.history_index.tasks.values()),
                'history_errors': len(self.history_index.errors)}

    async def close(self):
        self.reconcile.cancel()
        await self.history_index.close()
        await super().close()

    async def has_reaction(self, message, emoji, user_ids):
        for reaction in message.reactions:
            if str(reaction.emoji) == emoji:
                async for user in reaction.users(limit=None):
                    if user.id in user_ids:
                        return True
        return False

    async def moderator_locked(self, message):
        return bool(self.user and await self.has_reaction(message, '🔒', {self.user.id}))

    async def recover_message(self, message, renewed_at=None, force=False):
        if message.author.bot or not message.guild or str(message.channel.id) not in store.channels(message.guild.id):
            return
        timestamp = renewed_at or message.created_at.timestamp()
        if timestamp + 86400 <= time.time() and not force:
            return
        row = store.get(message.id)
        if row and (renewed_at is None or row['refreshed'] >= renewed_at):
            return
        try:
            offered, wanted = catalog.parse(message.content.replace('✅', ''), store.mapping(message.guild.id))
            locked = await self.moderator_locked(message)
            closed = '✅' in message.content or await self.owner_tick(message, message.author.id)
            store.upsert(message.id, message.guild.id, message.channel.id, message.author.id,
                         offered, wanted, now=timestamp, renew=bool(renewed_at))
            if locked or closed:
                store.close(message.id, 'moderator closed' if locked else 'seller marked unavailable')
                if closed and not locked and self.user and not any(str(r.emoji) == '✅' and getattr(r, 'me', False) for r in message.reactions):
                    await message.add_reaction('✅')
        except InvalidOffer:
            return

    async def load_history(self, interaction):
        channels = []
        for channel_id in store.channels(interaction.guild_id):
            channel = self.get_channel(int(channel_id))
            if channel and channel.permissions_for(interaction.user).view_channel and channel.permissions_for(interaction.user).read_message_history:
                channels.append(channel)
        return await self.history_index.ensure(channels)

    async def fetch_source(self, row):
        channel = self.get_channel(int(row['channel']))
        if channel is None:
            channel = await self.fetch_channel(int(row['channel']))
        return await channel.fetch_message(int(row['message']))

    async def owner_tick(self, message, seller):
        ids = {int(seller)}
        if self.user:
            ids.add(self.user.id)
        return await self.has_reaction(message, '✅', ids)

    async def validate(self, row):
        async with self.semaphore:
            try:
                if row['channel'] not in store.channels(row['guild']):
                    return None
                message = await self.fetch_source(row)
                if message.author.id != int(row['seller']) or message.author.bot:
                    store.close(row['message'], 'source author changed')
                    return None
                if await self.moderator_locked(message):
                    store.close(row['message'], 'moderator closed')
                    return None
                if '✅' in message.content or await self.owner_tick(message, row['seller']):
                    store.close(row['message'], 'seller marked unavailable')
                    return None
                offered, wanted = catalog.parse(message.content, store.mapping(row['guild']))
                store.upsert(row['message'], row['guild'], row['channel'], row['seller'], offered, wanted)
                current = store.get(row['message'])
                return current if current['state'] == 'active' and current['expires'] > time.time() else None
            except discord.NotFound:
                store.close(row['message'], 'source deleted')
            except InvalidOffer:
                store.close(row['message'], 'source needs correction')
            except (discord.Forbidden, discord.HTTPException):
                # Do not display results that could not be checked. Keep data for later retries.
                log.warning('Could not recheck offer %s', row['message'])
            return None

    @tasks.loop(minutes=15)
    async def reconcile(self):
        store.prune()
        for guild in self.guilds:
            rows = store.active(guild.id)
            # Bounded parallelism; an owner tick made while offline is checked here and during search.
            for start in range(0, len(rows), 20):
                await asyncio.gather(*(self.validate(r) for r in rows[start:start+20]))

    @reconcile.before_loop
    async def before_reconcile(self):
        await self.wait_until_ready()

    async def index_message(self, message):
        if message.author.bot or not message.guild or str(message.channel.id) not in store.channels(message.guild.id):
            return
        old = store.get(message.id)
        if '✅' in message.content:
            if old:
                store.close(message.id, 'seller marked unavailable')
                try:
                    await message.add_reaction('✅')
                    await message.remove_reaction('🔎', self.user)
                except discord.HTTPException:
                    pass
            return
        if old and old['state'] == 'closed' and old['reason'] != 'source needs correction':
            return
        try:
            offered, wanted = catalog.parse(message.content, store.mapping(message.guild.id))
            if await self.moderator_locked(message):
                if old:
                    store.close(message.id, 'moderator closed')
                return
            if await self.owner_tick(message, message.author.id):
                if old:
                    store.close(message.id, 'seller marked unavailable')
                return
            saved = store.upsert(message.id, message.guild.id, message.channel.id, message.author.id,
                                 offered, wanted, now=message.created_at.timestamp() if hasattr(message, 'created_at') else None)
            if saved:
                await message.add_reaction('🔎')
                try:
                    await message.remove_reaction('⚠️', self.user)
                except discord.HTTPException:
                    pass
        except InvalidOffer as error:
            if old:
                store.close(message.id, 'source needs correction')
                try:
                    await message.remove_reaction('🔎', self.user)
                except discord.HTTPException:
                    pass
            # Leave discussion alone; flag only messages that look like an attempted trade.
            looks_like_offer = bool(old or re.search(r'=>|->|→|\btrading\b|\bwtt\b|\blf\b|cl_trade|\bfor\b', message.content, re.I))
            if looks_like_offer:
                await message.add_reaction('⚠️')
                key = (message.guild.id, message.author.id)
                if time.time() - self.warned.get(key, 0) > 60:
                    self.warned[key] = time.time()
                    await message.reply('This offer is not searchable yet: ' + str(error) + ' Use `/help` for examples.', mention_author=False)
        except discord.HTTPException:
            log.warning('Could not acknowledge listing %s; check channel permissions.', message.id)

    async def on_message(self, message):
        await self.index_message(message)

    async def on_raw_message_edit(self, payload):
        if 'content' not in payload.data:
            return
        if not payload.guild_id or str(payload.channel_id) not in store.channels(payload.guild_id):
            return
        try:
            channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
            await self.index_message(await channel.fetch_message(payload.message_id))
        except discord.NotFound:
            store.close(payload.message_id, 'source deleted')
        except discord.HTTPException:
            log.warning('Could not refresh edited offer %s', payload.message_id)

    async def on_raw_message_delete(self, payload):
        store.close(payload.message_id, 'source deleted')

    async def on_raw_bulk_message_delete(self, payload):
        for message in payload.message_ids:
            store.close(message, 'source deleted')

    async def on_raw_reaction_add(self, payload):
        if str(payload.emoji) != '✅':
            return
        row = store.get(payload.message_id)
        if row and str(payload.guild_id) == row['guild'] and str(payload.user_id) == row['seller']:
            store.close(payload.message_id, 'seller marked unavailable')
            try:
                message = await self.fetch_source(row)
                # Bot-owned tick survives process loss even if the seller later removes theirs.
                await message.add_reaction('✅')
                await message.remove_reaction('🔎', self.user)
            except discord.HTTPException:
                pass


bot = Clover()
tree = bot.tree


async def item_autocomplete(interaction, current):
    return [app_commands.Choice(name=(i['name'] + ' · ' + i['category'])[:100], value=i['id'])
            for i in catalog.choices(current, store.mapping(interaction.guild_id))]


def extract_id(value):
    match = re.fullmatch(r'(?:https://discord\.com/channels/\d+/\d+/)?(\d{1,22})/?', value.strip())
    return match[1] if match else None


def owned_row(interaction, value, moderator=False):
    row = store.get(extract_id(value) or '')
    if not row or row['guild'] != str(interaction.guild_id):
        raise InvalidOffer('No listing with that ID in this server. Use `/myoffers` for its ID.')
    if row['seller'] != str(interaction.user.id) and not (moderator and interaction.permissions.manage_messages):
        raise InvalidOffer('Only the listing author can do that. Moderators may use `/close`.')
    return row


async def recover_by_id(interaction, value):
    message_id = extract_id(value)
    if not message_id:
        raise InvalidOffer('Use the original Discord message ID or message link.')
    if store.get(message_id):
        return
    for channel_id in store.channels(interaction.guild_id):
        channel = bot.get_channel(int(channel_id))
        if not channel or not channel.permissions_for(interaction.user).view_channel:
            continue
        try:
            source = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden):
            continue
        await bot.recover_message(source, force=True)
        return


class Results(discord.ui.View):
    def __init__(self, owner, rows, title):
        super().__init__(timeout=180)
        self.owner, self.rows, self.title, self.page = owner, rows, title, 0
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 5 >= len(self.rows)

    def embed(self):
        e = discord.Embed(title=self.title, colour=0x4bb586,
                          description='Member-posted offers. Open the original post and negotiate in DMs.')
        for r in self.rows[self.page*5:self.page*5+5]:
            link = f"https://discord.com/channels/{r['guild']}/{r['channel']}/{r['message']}"
            e.add_field(name=f"Offer {r['message']}", value=(f"Seller: <@{r['seller']}>\n"
                        f"Offering: {catalog.display(json.loads(r['offered']))[:300]}\n"
                        f"Wants: {catalog.display(json.loads(r['wanted']))[:300]}\n"
                        f"Updated <t:{int(r['refreshed'])}:R> · expires <t:{int(r['expires'])}:R>\n[View offer]({link})"), inline=False)
        e.set_footer(text=f'Page {self.page+1}/{max(1,(len(self.rows)+4)//5)} · Up to 25 newest offers checked. Rerun /search to refresh.')
        return e

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner:
            return True
        await interaction.response.send_message('Run `/search` to open your own results.', ephemeral=True)
        return False

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


@tree.command(name='search', description='Find active offers selling an item; type a name or paste a mapped emoji.')
@app_commands.guild_only()
@app_commands.autocomplete(item=item_autocomplete)
async def search(interaction: discord.Interaction, item: str):
    item_id = catalog.resolve(item, store.mapping(interaction.guild_id))
    if not item_id:
        await interaction.response.send_message('Select a tradeable item from autocomplete, or paste a mapped server emoji.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    pending, failed = await bot.load_history(interaction)
    candidates = store.active(interaction.guild_id, item=item_id)
    # Check at most 25 newest candidates per request to keep interaction latency bounded.
    rows = [r for r in await asyncio.gather(*(bot.validate(r) for r in candidates[:25]))
            if r and item_id in json.loads(r['offered']) and r['channel'] in store.channels(interaction.guild_id)]
    # Results must also be in channels the requester can read.
    rows = [r for r in rows if (ch := bot.get_channel(int(r['channel']))) is not None
            and ch.permissions_for(interaction.user).view_channel
            and ch.permissions_for(interaction.user).read_message_history]
    if not rows:
        message = ('Trading history is still loading. Run `/search` again shortly; the rebuild continues in the background.' if pending else
                   'Some trading history could not be read. Ask a moderator to check channel permissions, then retry.' if failed else
                   'No checked active offers for **' + catalog.items[item_id]['name'] + '** in the last 24 hours.')
        await interaction.followup.send(message, ephemeral=True)
        return
    view = Results(interaction.user.id, rows, catalog.items[item_id]['name'] + ' · active offers')
    await interaction.followup.send(content='History is still loading; these are partial results. Search again shortly.' if pending else 'Some channels could not be read; results may be incomplete.' if failed else None,
                                    embed=view.embed(), view=view, ephemeral=True)


@tree.command(name='myoffers', description='See your active listings, message links, expiry times and IDs.')
@app_commands.guild_only()
async def myoffers(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    pending, failed = await bot.load_history(interaction)
    rows = [r for r in await asyncio.gather(*(bot.validate(r) for r in store.active(interaction.guild_id, seller=interaction.user.id)[:100])) if r]
    if not rows:
        await interaction.followup.send('History is still loading; try `/myoffers` again shortly.' if pending else 'Some history could not be read; check permissions and retry.' if failed else 'You have no checked active listings. Post `Time => offers` in a configured trading channel.', ephemeral=True)
        return
    view = Results(interaction.user.id, rows, 'Your active offers')
    await interaction.followup.send(content='History is still loading; results are partial.' if pending else 'Some channels could not be read; results may be incomplete.' if failed else None, embed=view.embed(), view=view, ephemeral=True)


@tree.command(name='close', description='Close your entire offer; moderators can close other offers.')
@app_commands.guild_only()
async def close(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    await recover_by_id(interaction, message)
    row = owned_row(interaction, message, moderator=True)
    source = await bot.fetch_source(row)
    moderator = row['seller'] != str(interaction.user.id)
    await source.add_reaction('🔒' if moderator else '✅')
    store.close(row['message'], 'moderator closed' if moderator else 'closed by command')
    await interaction.followup.send('Closed. Its Discord reaction preserves that status after a restart. No trade count was awarded.', ephemeral=True)


@tree.command(name='renew', description='Refresh or reopen your listing for 24 hours. Remove your ✅ first.')
@app_commands.guild_only()
async def renew(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    await recover_by_id(interaction, message)
    row = owned_row(interaction, message)
    if row['reason'] == 'moderator closed':
        raise InvalidOffer('A moderator closed this listing. Contact a moderator before posting a replacement.')
    if row['channel'] not in store.channels(interaction.guild_id):
        raise InvalidOffer('That trading channel is no longer enabled.')
    source = await bot.fetch_source(row)
    if await bot.moderator_locked(source):
        raise InvalidOffer('A moderator closed this listing. Contact a moderator.')
    if source.author.id != interaction.user.id or '✅' in source.content or await bot.has_reaction(source, '✅', {interaction.user.id}):
        raise InvalidOffer('Remove your ✅ reaction from the source post before renewing it.')
    offered, wanted = catalog.parse(source.content, store.mapping(interaction.guild_id))
    receipt = discord.Embed(title='Offer renewed', description=f'Offer {source.id} is available for another 24 hours.', colour=0x4bb586)
    receipt.set_footer(text=f'clover:renew:{source.id}')
    record = await source.reply(embed=receipt, mention_author=False)
    await source.remove_reaction('✅', bot.user)
    store.upsert(row['message'], row['guild'], row['channel'], row['seller'], offered, wanted, now=record.created_at.timestamp(), renew=True)
    await source.add_reaction('🔎')
    await interaction.followup.send('Your offer is active for another 24 hours.', ephemeral=True)


@tree.command(name='items', description='Browse the tradeable item catalog. Filter with a name or category.')
@app_commands.guild_only()
async def items(interaction: discord.Interaction, filter: str = ''):
    found = [i for i in catalog.items.values() if norm_filter(filter, i)]
    body = '\n'.join(f"**{i['name']}** · {i['category']}" for i in found)
    await interaction.response.send_message(body[:1900] + ('\nMore items: narrow the filter.' if len(body) > 1900 else '') if body else 'No matching tradeable items.', ephemeral=True)


def norm_filter(query, item):
    return query.lower() in (item['name'] + ' ' + item['category']).lower()


@tree.command(name='help', description='How to post, search, close and renew trading offers.')
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(HELP, ephemeral=True)


@tree.command(name='rules', description='Clover Legends in-game trading requirements and server trading guidance.')
async def rules(interaction: discord.Interaction):
    await interaction.response.send_message(RULES, ephemeral=True)


@tree.command(name='setup', description='Moderators: enable or disable indexing in a trading text channel.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(interaction: discord.Interaction, channel: discord.TextChannel, enabled: bool = True):
    perms = channel.permissions_for(interaction.guild.me)
    if enabled and not all([perms.view_channel, perms.read_message_history, perms.send_messages, perms.add_reactions, perms.embed_links]):
        raise InvalidOffer('Give the bot View Channel, Read Message History, Send Messages, Add Reactions and Embed Links here first.')
    store.configure(interaction.guild_id, channel.id, enabled)
    bot.history_index.invalidate(channel.id)
    await interaction.response.send_message(f"Indexing {'enabled' if enabled else 'disabled'} in {channel.mention} for this session. Save TRADING_CHANNEL_IDS={','.join(store.channels(interaction.guild_id))} in Render Environment to retain this setting after restart. Search lazily loads the last 24 hours.", ephemeral=True)


@tree.command(name='emoji_sync', description='Preview exact filename matches for existing server emojis; apply to save IDs.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def emoji_sync(interaction: discord.Interaction, apply: bool = False):
    expected = {i['emoji_name']: i['id'] for i in catalog.items.values()}
    expected.update(cl_trade='separator', cl_offers='offers')
    grouped = {}
    for emoji in interaction.guild.emojis:
        grouped.setdefault(emoji.name, []).append(emoji)
    matched, ambiguous = [], []
    for name, target in expected.items():
        values = grouped.get(name, [])
        if len(values) == 1:
            matched.append((values[0], target))
        elif len(values) > 1:
            ambiguous.append(name)
    if apply:
        for emoji, target in matched:
            store.bind(interaction.guild_id, emoji.id, target)
    lines = [f"{e.name} → {catalog.items[t]['name'] if t in catalog.items else t}" for e,t in matched]
    body = '\n'.join(lines) or 'No exact named emojis found. Upload the supplied PNGs first.'
    await interaction.response.send_message(('Saved' if apply else 'Preview only') + f' · {len(matched)} matches\n' + body[:1600] +
                                            ('\nAmbiguous names skipped: ' + ', '.join(ambiguous)[:200] if ambiguous else '') +
                                            ('\nRun `/emoji_sync apply:true` after reviewing.' if not apply else '\nStandard filenames map automatically after restart. Custom bindings need EMOJI_MAP_JSON.'), ephemeral=True)


@tree.command(name='emoji_bind', description='Moderators: bind one existing server emoji to an item or trade marker.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.autocomplete(item=item_autocomplete)
@app_commands.choices(marker=[app_commands.Choice(name='Offer / want separator', value='separator'), app_commands.Choice(name='Open to offers', value='offers')])
async def emoji_bind(interaction: discord.Interaction, emoji: str, item: str | None = None, marker: str | None = None):
    if bool(item) == bool(marker):
        raise InvalidOffer('Choose exactly one item or marker.')
    match = re.fullmatch(r'<a?:\w+:(\d+)>', emoji.strip())
    found = discord.utils.get(interaction.guild.emojis, id=int(match[1])) if match else None
    target = marker or catalog.resolve(item, store.mapping(interaction.guild_id))
    if not found or not target:
        raise InvalidOffer('Select an existing custom emoji from this server and a valid item or marker.')
    store.bind(interaction.guild_id, found.id, target)
    await interaction.response.send_message('Mapped ' + str(found) + ' to ' + (catalog.items[target]['name'] if target in catalog.items else target) +
                                            '. To retain custom bindings across sleep, save this in Render EMOJI_MAP_JSON:\n```json\n' + json.dumps(store.mapping(interaction.guild_id)) + '\n```', ephemeral=True)


@tree.command(name='status', description='Moderators: see indexing channels, emoji mappings and active listing count.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def status(interaction: discord.Interaction):
    mapping = store.mapping(interaction.guild_id)
    books = {i['id'] for i in catalog.items.values() if i['kind'] == 'spellbook'}
    missing = sorted(books - set(mapping.values()))
    await interaction.response.send_message(f"Channels: {', '.join('<#'+c+'>' for c in store.channels(interaction.guild_id)) or 'None'}\n"
                                            f"Active listings: {len(store.active(interaction.guild_id))}\n"
                                            f"Mapped spellbooks: {16-len(missing)}/16\nMissing: {', '.join(missing) or 'None'}\n"
                                            f'History scans running: {sum(not t.done() for t in bot.history_index.tasks.values())}\n'
                                            f'History scan errors: {len(bot.history_index.errors)}\n'
                                            'Temporary cache; channels and custom mapping overrides must be saved in Render Environment.', ephemeral=True)


@tree.error
async def command_error(interaction, error):
    original = getattr(error, 'original', error)
    if isinstance(original, InvalidOffer):
        message = str(original)
    elif isinstance(original, app_commands.MissingPermissions):
        message = 'You need Manage Server to configure this bot.'
    elif isinstance(original, discord.NotFound):
        message = 'The original message no longer exists.'
    elif isinstance(original, discord.Forbidden):
        message = 'The bot cannot access that channel or action. Ask a moderator to check its permissions.'
    else:
        log.error('Command error', exc_info=(type(original), original, original.__traceback__))
        message = 'Something failed. Please try again; moderators can check the bot logs.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise SystemExit('Set DISCORD_TOKEN in .env. Never share it in chat.')
    runner = web.AppRunner(make_app(bot.health_status))
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '10000'))).start()
    try:
        async with bot:
            await bot.start(token)
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
