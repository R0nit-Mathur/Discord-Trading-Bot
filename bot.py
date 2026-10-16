"""Clover Trading Desk: interactions and our own cards, zero privileged intents."""
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from aiohttp import web

from core import Catalog, InvalidOffer, Store
from market import Card, validate_basket
from recovery import HistoryIndex
from health import make_app

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
catalog = Catalog(ROOT/'catalog.json')
db_path = Path(os.getenv('DATABASE_PATH', ':memory:'))
store = Store(':memory:' if str(db_path)==':memory:' else db_path if db_path.is_absolute() else ROOT/db_path)
log = logging.getLogger('clover')
DEFAULT_TEST_CHANNEL = '1550152526333092030'
DESK_TITLE = '🍀 Clover Trading Desk'


def test_channel_id():
    value = os.getenv('TEST_CHANNEL_ID',DEFAULT_TEST_CHANNEL).strip()
    if value.lower() in ('','off','0'):
        return None
    if not value.isdigit():
        raise InvalidOffer('TEST_CHANNEL_ID must be a Discord text channel ID, or off to disable testing mode.')
    return int(value)


def desk_embed():
    e=discord.Embed(title=DESK_TITLE,colour=0x38BD96,
                    description='**Create a trade in a few clicks.**\n\n✨ **Create trade** — pick what you offer and what you want in a private form, then publish here.\n🔎 **Find sellers** — search current trades.\n📋 **My offers** — edit, renew or close your trades.\n\nEach published trade has a **Trade / DM** button. Negotiate in DMs and exchange items in-game.')
    e.set_footer(text='Level 100+ • 9 slots per side • Trade spare bag copies only')
    return e


DESK_MESSAGE = ('🍀 **Trading desk is open!**\n'
                'Click **Create trade** below. Tell us what you are offering and what you want, '
                'then publish your trade in this channel.')
RULES = ('Both players must be level 100+. Each side has 9 slots; a material stack uses one slot. '
         'Trade spare, unequipped spellbooks from your bag only; Robux-bought books cannot be traded. '
         'The recipient needs free bag space for books. Any in-game offer change resets both Accept buttons. '
         'Negotiate in DMs and exchange items in Clover Legends. No cross-trading, links, Robux or begging.')
HELP = ('**Welcome to Clover Trading**\n'
        'Use **Create offer** on the Trading Desk or `/offer` to open your private builder. '
        'Pick spellbooks from the menus, or use **Edit items** for materials, quantities and your optional Roblox username. '
        'Confirm the trade requirements, review the preview and publish. No ticket channel is created.\n\n'
        '**Find sellers** or `/search` opens private results with links to public trading cards. '
        '**Contact trader** shows their profile and a message you can copy into a DM; the bot sends no unsolicited DMs.\n\n'
        '**Manage offer** lets the owner edit, renew or close a card. An owner’s ✅ reaction also closes it. '
        'Renewal publishes a fresh 24-hour card and closes the old one. Maximum 3 active offers per trader; '
        'publishing cooldown is 60 seconds and renewing an active offer requires waiting 30 minutes.\n\n'
        '`/myoffers` · `/items` · `/rules` · `/help`\n'
        'Moderators: `/panel`, `/status`, `/setup`, `/emoji_sync`, `/emoji_bind`.\n'
        'Ordinary member messages are not read or indexed. Listings are member claims, not verified inventory or completed trades.')


class Clover(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True
        # Deliberately NO message_content, members or presences privileged intents.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.history_index = HistoryIndex(self.recover_message, lambda: self.user.id if self.user else 0)
        self.configured = False
        self.locks = {}
        self.user_locks = {}
        self.published = {}
        self.semaphore = asyncio.Semaphore(4)
        self.desk_lock = asyncio.Lock()

    async def setup_hook(self):
        self.add_view(DeskView())
        self.add_view(CardView())
        if '--sync' in sys.argv or os.getenv('SYNC_COMMANDS','0')=='1':
            gid = os.getenv('GUILD_ID','')
            if not gid.isdigit():
                raise RuntimeError('Set GUILD_ID before registering commands.')
            guild = discord.Object(id=int(gid))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info('Registered Trading Desk commands for configured server.')
        self.reconcile.start()

    def emoji_matches(self, guild):
        expected = {i['emoji_name']:i['id'] for i in catalog.items.values()}
        expected.update(cl_trade='separator', cl_offers='offers')
        grouped = {}
        for emoji in guild.emojis:
            grouped.setdefault(emoji.name, []).append(emoji)
        return [(values[0], expected[name]) for name,values in grouped.items() if name in expected and len(values)==1]

    def restore_configuration(self):
        self.configured = False
        gid = os.getenv('GUILD_ID','')
        guild = self.get_guild(int(gid)) if gid.isdigit() else None
        if not guild:
            log.error('GUILD_ID must identify a server containing this bot.')
            return
        try:
            testing = test_channel_id()
        except InvalidOffer as error:
            log.error('%s',error)
            return
        channels = [str(testing)] if testing else [v.strip() for v in os.getenv('TRADING_CHANNEL_IDS','').split(',') if v.strip()]
        if not channels:
            log.error('Set TRADING_CHANNEL_IDS in Render Environment.')
            return
        # Remove previously enabled destinations on reconnect while testing is active.
        if testing:
            for old in store.channels(guild.id):
                if old not in channels:
                    store.configure(guild.id,old,False)
        for value in channels:
            channel = guild.get_channel(int(value)) if value.isdigit() else None
            if not isinstance(channel, discord.TextChannel):
                log.error('TRADING_CHANNEL_IDS must contain trading text channel IDs.')
                return
            perms = channel.permissions_for(guild.me)
            if not all([perms.view_channel, perms.read_message_history, perms.send_messages, perms.embed_links]):
                log.error('Trading channels need View Channel, Read Message History, Send Messages and Embed Links.')
                return
            store.configure(guild.id, channel.id, True)
        for emoji,target in self.emoji_matches(guild):
            store.bind(guild.id, emoji.id, target)
        try:
            overrides = json.loads(os.getenv('EMOJI_MAP_JSON','{}'))
            if not isinstance(overrides, dict):
                raise ValueError()
            for eid,target in overrides.items():
                if not str(eid).isdigit() or target not in {*catalog.items,'separator','offers'}:
                    raise ValueError()
                store.bind(guild.id,eid,target)
        except (ValueError,TypeError):
            log.error('Invalid EMOJI_MAP_JSON; map emoji IDs to catalog item IDs.')
            return
        self.configured = True

    async def on_ready(self):
        self.restore_configuration()
        for cid in list(self.history_index.checked):
            self.history_index.invalidate(cid)
        log.info('Ready as %s — Trading Desk; no privileged intents requested.',self.user)
        testing = test_channel_id()
        if self.configured and testing:
            try:
                channel = self.get_channel(testing)
                await self.ensure_desk(channel)
            except discord.HTTPException:
                log.exception('Could not post/reuse the testing Trading Desk. Check channel permissions.')

    async def ensure_desk(self,channel):
        async with self.desk_lock:
            # Search own messages so cold starts don't create duplicate entry panels.
            # Reading our own messages needs no privileged Message Content access.
            async for message in channel.history(limit=None,oldest_first=False):
                if message.author.id==self.user.id and not getattr(message,'webhook_id',None) and any(e.title==DESK_TITLE for e in message.embeds):
                    await message.edit(content=DESK_MESSAGE,embed=desk_embed(),view=DeskView())
                    log.info('Reused Trading Desk in testing channel %s',channel.id)
                    return message
            message = await channel.send(content=DESK_MESSAGE,embed=desk_embed(),view=DeskView())
            log.info('Posted Trading Desk in testing channel %s',channel.id)
            return message

    def health_status(self):
        return {'service':'clover-trading','mode':'interaction-marketplace','discord_ready':self.is_ready(),
                'configured':self.configured,'cache':'temporary','privileged_intents':False,
                'history_loading':any(not t.done() for t in self.history_index.tasks.values()),
                'history_errors':len(self.history_index.errors)}

    async def close(self):
        self.reconcile.cancel()
        await self.history_index.close()
        await super().close()

    def emojis(self, guild):
        available = {str(e.id):e for e in guild.emojis}
        return {target:available[eid] for eid,target in store.mapping(guild.id).items() if eid in available and target in catalog.items}

    def remember(self, message, card):
        store.upsert(message.id,message.guild.id,message.channel.id,card.seller,card.offered,card.wanted,now=card.refreshed,renew=True)
        if card.state!='active':
            store.close(message.id,'moderator closed' if card.state=='locked' else 'closed')

    def read(self, message):
        if not message.guild or str(message.channel.id) not in store.channels(message.guild.id):
            raise InvalidOffer('This card is not in a configured trading channel.')
        card = Card.from_message(message,self.user.id,catalog)
        self.remember(message,card)
        return card

    async def recover_message(self,message):
        try:
            self.read(message)
        except InvalidOffer:
            return

    def visible_channels(self,interaction):
        return [c for cid in store.channels(interaction.guild_id) if (c:=self.get_channel(int(cid))) is not None
                and c.permissions_for(interaction.user).view_channel and c.permissions_for(interaction.user).read_message_history]

    async def load_history(self,interaction,timeout=1.5):
        return await self.history_index.ensure(self.visible_channels(interaction),timeout=timeout)

    async def fetch_source(self,row):
        channel = self.get_channel(int(row['channel'])) or await self.fetch_channel(int(row['channel']))
        return await channel.fetch_message(int(row['message']))

    async def has_owner_tick(self,message,seller):
        for reaction in message.reactions:
            if str(reaction.emoji)=='✅':
                async for user in reaction.users(limit=None):
                    if user.id==seller:
                        return True
        return False

    async def validate(self,row):
        async with self.semaphore:
            try:
                source = await self.fetch_source(row)
                card = self.read(source)
                if card.active() and await self.has_owner_tick(source,card.seller):
                    card = replace(card,state='closed')
                    await self.save(source,card)
                return store.get(source.id) if card.active() and store.get(source.id)['state']=='active' else None
            except discord.NotFound:
                store.close(row['message'],'deleted')
            except InvalidOffer:
                store.close(row['message'],'invalid card')
            except discord.HTTPException:
                log.warning('Could not check trading card %s',row['message'])
            return None

    async def save(self,source,card):
        await source.edit(content=card.summary(catalog),embed=card.embed(catalog,self.emojis(source.guild)),view=CardView())
        self.remember(source,card)

    async def source_for(self,interaction,value):
        mid = extract_id(value)
        if not mid:
            raise InvalidOffer('Use the trade card message ID or link.')
        for channel in self.visible_channels(interaction):
            try:
                source = await channel.fetch_message(int(mid))
                self.read(source)
                return source
            except discord.NotFound:
                continue
        raise InvalidOffer('No trading card with that ID in an accessible trading channel.')

    async def publish(self,interaction,offered,wanted,roblox='',renew_source=None):
        validate_basket(catalog,offered)
        if wanted:
            validate_basket(catalog,wanted)
        channels = self.visible_channels(interaction)
        if not channels:
            raise InvalidOffer('No accessible trading channel is configured. Ask a moderator to check Render settings.')
        async with self.user_locks.setdefault((interaction.guild_id,interaction.user.id),asyncio.Lock()):
            pending,failed = await self.load_history(interaction,timeout=4)
            if pending or failed:
                raise InvalidOffer('The trading board is loading or cannot be read yet. Your draft is kept; try Publish again shortly.')
            active = store.active(interaction.guild_id,seller=interaction.user.id)
            replacing_active = renew_source and any(r['message']==str(renew_source.id) for r in active)
            if len(active)>=3 and not replacing_active:
                raise InvalidOffer('You already have 3 active offers. Close an old offer from /myoffers first.')
            now = time.time()
            last = max([self.published.get(interaction.user.id,0),*[r['refreshed'] for r in active]])
            if now-last<60:
                raise InvalidOffer(f'Please wait {max(1,int(60-now+last))} seconds before publishing again.')
            for row in active:
                if (not renew_source or row['message']!=str(renew_source.id)) and json.loads(row['offered'])==offered and json.loads(row['wanted'])==wanted:
                    raise InvalidOffer('You already have this offer on the board. Manage or renew that card instead.')
            card = Card(interaction.user.id,interaction.user.display_name,dict(offered),dict(wanted),now,roblox=roblox)
            # Publish only to an explicitly configured channel, never the announcement/panel channel by accident.
            source = await channels[0].send(content=card.summary(catalog),embed=card.embed(catalog,self.emojis(interaction.guild)),view=CardView())
            self.remember(source,card)
            self.published[interaction.user.id]=now
            if renew_source:
                previous = self.read(renew_source)
                try:
                    await self.save(renew_source,replace(previous,state='closed'))
                except discord.HTTPException:
                    log.warning('Renewed card %s posted, but old card could not be edited.',source.id)
            return source

    @tasks.loop(minutes=15)
    async def reconcile(self):
        store.prune()
        for guild in self.guilds:
            for start in range(0,len(rows:=store.active(guild.id)),20):
                await asyncio.gather(*(self.validate(r) for r in rows[start:start+20]))

    @reconcile.before_loop
    async def before_reconcile(self):
        await self.wait_until_ready()

    async def on_raw_message_delete(self,payload):
        store.close(payload.message_id,'deleted')

    async def on_raw_bulk_message_delete(self,payload):
        for mid in payload.message_ids:
            store.close(mid,'deleted')

    async def on_raw_reaction_add(self,payload):
        if str(payload.emoji)!='✅' or not payload.guild_id or payload.user_id==(self.user.id if self.user else None):
            return
        if str(payload.channel_id) not in store.channels(payload.guild_id):
            return
        try:
            channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
            async with self.locks.setdefault(payload.message_id,asyncio.Lock()):
                source = await channel.fetch_message(payload.message_id)
                card = self.read(source)
                if payload.user_id==card.seller and card.state=='active':
                    await self.save(source,replace(card,state='closed'))
        except (InvalidOffer,discord.HTTPException):
            return


bot = Clover()
tree = bot.tree


def extract_id(value):
    match = re.fullmatch(r'(?:https://discord\.com/channels/\d+/\d+/)?(\d{1,22})/?',value.strip())
    return match[1] if match else None


def require_owner(interaction,card,moderator=False):
    if interaction.user.id!=card.seller and not (moderator and interaction.permissions.manage_messages):
        raise InvalidOffer('Only this trader can manage the offer. Moderators may close it.')


async def explain(interaction,error):
    original = getattr(error,'original',error)
    if isinstance(original,InvalidOffer):
        message = str(original)
    elif isinstance(original,app_commands.MissingPermissions):
        message = 'You need Manage Server to configure the Trading Desk.'
    elif isinstance(original,discord.Forbidden):
        message = 'The bot cannot access that channel or edit this card. Ask a moderator to check permissions.'
    elif isinstance(original,discord.NotFound):
        message = 'That trading card or channel no longer exists.'
    else:
        log.error('Interaction failed',exc_info=(type(original),original,original.__traceback__))
        message = 'Something failed. Please try again; your draft has not been published unless a card link was shown.'
    if interaction.response.is_done():
        await interaction.followup.send(message,ephemeral=True)
    else:
        await interaction.response.send_message(message,ephemeral=True)


class SafeView(discord.ui.View):
    async def on_error(self,interaction,error,item):
        await explain(interaction,error)


class SafeModal(discord.ui.Modal):
    async def on_error(self,interaction,error):
        await explain(interaction,error)


class DeskView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Create trade',emoji='✨',style=discord.ButtonStyle.success,custom_id='clover:desk:create:v2')
    async def create(self,interaction,button):
        await open_builder(interaction)

    @discord.ui.button(label='Find sellers',emoji='🔎',style=discord.ButtonStyle.primary,custom_id='clover:desk:search:v2')
    async def find(self,interaction,button):
        await interaction.response.send_modal(SearchModal())

    @discord.ui.button(label='My offers',emoji='📋',style=discord.ButtonStyle.secondary,custom_id='clover:desk:mine:v2')
    async def mine(self,interaction,button):
        await show_results(interaction,seller=interaction.user.id)

    @discord.ui.button(label='Rules',emoji='📜',style=discord.ButtonStyle.secondary,custom_id='clover:desk:rules:v2')
    async def rules(self,interaction,button):
        await interaction.response.send_message(RULES,ephemeral=True)


class CardView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Trade / DM',emoji='💬',style=discord.ButtonStyle.primary,custom_id='clover:card:contact:v2')
    async def contact(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        source = await interaction.message.fetch()
        card = bot.read(source)
        if not card.active() or await bot.has_owner_tick(source,card.seller):
            raise InvalidOffer('This offer is closed or expired. Use /search to find active sellers.')
        if interaction.user.id==card.seller:
            raise InvalidOffer('This is your offer. Use Manage offer to edit, close or renew it.')
        view = SafeView()
        view.add_item(discord.ui.Button(label='Open trader profile',url=f'https://discord.com/users/{card.seller}'))
        text = f'Hi! I saw your Clover Legends offer: {catalog.display(card.offered)} for {catalog.display(card.wanted)}. Is it still available?\n{source.jump_url}'
        await interaction.followup.send(f'Trader: <@{card.seller}>\nOpen their profile, choose **Message**, then copy this:\n```\n{text}\n```\nIf their DMs are closed, ask them to enable server DMs. The bot has not sent a message for you.',view=view,ephemeral=True)

    @discord.ui.button(label='Manage offer',emoji='⚙️',style=discord.ButtonStyle.secondary,custom_id='clover:card:manage:v2')
    async def manage(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        source = await interaction.message.fetch()
        card = bot.read(source)
        require_owner(interaction,card,moderator=True)
        await interaction.followup.send('Manage this listing below. All changes update the public trading board.',view=ManageView(source.id,source.channel.id,interaction.user.id,editable=interaction.user.id==card.seller),ephemeral=True)


class BookSelect(discord.ui.Select):
    def __init__(self,draft,side,guild):
        self.draft,self.side=draft,side
        emojis = bot.emojis(guild)
        books = sorted([i for i in catalog.items.values() if i['kind']=='spellbook'],key=lambda i:i['name'])
        selected = draft.offered if side=='offered' else draft.wanted
        options = [discord.SelectOption(label=i['name'],value=i['id'],emoji=emojis.get(i['id']),
                   description=i['category'][:100],default=i['id'] in selected) for i in books]
        super().__init__(placeholder='Spellbooks I OFFER' if side=='offered' else 'Spellbooks I WANT',
                         min_values=0,max_values=9,options=options,row=0 if side=='offered' else 1)

    async def callback(self,interaction):
        current = dict(self.draft.offered if self.side=='offered' else self.draft.wanted)
        # Preserve text-added materials and preserve quantities for selected books.
        result = {i:q for i,q in current.items() if catalog.items[i]['kind']!='spellbook'}
        result.update({i:current.get(i,1) for i in self.values})
        if result:
            validate_basket(catalog,result)
        if self.side=='offered':
            self.draft.offered=result
        else:
            self.draft.wanted=result
        self.draft.confirmed=False
        self.draft.refresh_selects()
        await self.draft.redraw(interaction)


class DraftView(SafeView):
    def __init__(self,owner,guild,offered=None,wanted=None,roblox='',source=None):
        super().__init__(timeout=900)
        self.owner,self.guild,self.source=owner,guild,source
        self.offered,self.wanted=dict(offered or {}),dict(wanted or {})
        self.roblox,self.confirmed,self.published,self.message=roblox,False,False,None
        self.add_item(BookSelect(self,'offered',guild))
        self.add_item(BookSelect(self,'wanted',guild))
        self.publish_button.label='Save changes' if source else 'Publish offer'

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message('Open your own builder with /offer.',ephemeral=True)
            return False
        return True

    def preview(self):
        e = discord.Embed(title='Your private trade builder',colour=0x38BD96,
                         description='Pick spellbooks below, or edit the item lists for materials and quantities. Nothing is posted until you confirm.')
        e.add_field(name='I offer',value=catalog.display(self.offered) if self.offered else 'Choose at least one item',inline=False)
        e.add_field(name='I want',value=catalog.display(self.wanted),inline=False)
        e.add_field(name='Roblox username',value=self.roblox or 'Optional — set in Edit items',inline=False)
        e.add_field(name='Trade requirements',value='✅ Confirmed' if self.confirmed else 'Confirm you are level 100+ and offer tradeable bag items only.',inline=False)
        e.set_footer(text='Private draft • expires after 15 minutes or a bot restart')
        return e

    async def redraw(self,interaction=None):
        self.confirm.label='Requirements confirmed' if self.confirmed else 'Confirm requirements'
        self.publish_button.disabled=not bool(self.offered and self.confirmed) or self.published
        if interaction:
            await interaction.response.edit_message(embed=self.preview(),view=self)
        elif self.message:
            await self.message.edit(embed=self.preview(),view=self)

    @discord.ui.button(label='Edit items / quantities',emoji='✏️',style=discord.ButtonStyle.secondary,row=2)
    async def edit_items(self,interaction,button):
        await interaction.response.send_modal(BasketModal(self))

    @discord.ui.button(label='Open to offers',emoji='❓',style=discord.ButtonStyle.secondary,row=2)
    async def open_offers(self,interaction,button):
        self.wanted={}
        self.confirmed=False
        # Rebuild selectors so displayed defaults reflect the current draft.
        self.refresh_selects()
        await self.redraw(interaction)

    def refresh_selects(self):
        for item in list(self.children):
            if isinstance(item,BookSelect):
                self.remove_item(item)
        self.add_item(BookSelect(self,'offered',self.guild))
        self.add_item(BookSelect(self,'wanted',self.guild))

    @discord.ui.button(label='Confirm requirements',emoji='☑️',style=discord.ButtonStyle.secondary,row=3)
    async def confirm(self,interaction,button):
        self.confirmed=not self.confirmed
        await self.redraw(interaction)

    @discord.ui.button(label='Publish offer',emoji='📣',style=discord.ButtonStyle.success,disabled=True,row=3)
    async def publish_button(self,interaction,button):
        if not self.confirmed or self.published:
            raise InvalidOffer('Confirm the requirements first, or open a fresh builder if already published.')
        await interaction.response.defer(ephemeral=True)
        if self.source:
            async with bot.locks.setdefault(self.source.id,asyncio.Lock()):
                source=await self.source.fetch()
                card=bot.read(source)
                require_owner(interaction,card)
                if not card.active():
                    raise InvalidOffer('This offer closed or expired while you edited it. Create a new offer instead.')
                updated=replace(card,offered=dict(self.offered),wanted=dict(self.wanted),roblox=self.roblox)
                updated.validate(catalog)
                await bot.save(source,updated)
        else:
            source=await bot.publish(interaction,self.offered,self.wanted,self.roblox)
        self.published=True
        for item in self.children:
            item.disabled=True
        if self.message:
            await self.message.edit(content='Your offer is live on the trading board.',embed=None,view=self)
        await interaction.followup.send(f'✅ Your offer is ready: {source.jump_url}',ephemeral=True)
        self.stop()


class BasketModal(SafeModal,title='Trade items and quantities'):
    def __init__(self,draft):
        super().__init__()
        self.draft=draft
        self.offering=discord.ui.TextInput(label='Items I offer',style=discord.TextStyle.paragraph,max_length=600,
                                          placeholder='Time x1 + Ancient Sap x250',default=catalog.display(draft.offered) if draft.offered else '')
        self.wanting=discord.ui.TextInput(label='Items I want — blank means offers',style=discord.TextStyle.paragraph,max_length=600,required=False,
                                         placeholder='Light x1',default=catalog.display(draft.wanted) if draft.wanted else '')
        self.username=discord.ui.TextInput(label='Roblox username (optional)',max_length=20,required=False,default=draft.roblox)
        for field in [self.offering,self.wanting,self.username]:
            self.add_item(field)

    async def on_submit(self,interaction):
        if interaction.user.id!=self.draft.owner or self.draft.published:
            raise InvalidOffer('This draft is no longer editable. Use /offer for a new one.')
        offered,wanted=catalog.parse(f'{self.offering.value} => {self.wanting.value or "offers"}',store.mapping(interaction.guild_id))
        card=Card(interaction.user.id,interaction.user.display_name,offered,wanted,time.time(),roblox=self.username.value.strip())
        card.validate(catalog)
        self.draft.offered,self.draft.wanted,self.draft.roblox=offered,wanted,card.roblox
        self.draft.confirmed=False
        self.draft.refresh_selects()
        await interaction.response.defer(ephemeral=True)
        await self.draft.redraw()
        await interaction.followup.send('Draft updated. Check the preview, confirm the requirements and publish.',ephemeral=True)


async def open_builder(interaction,source=None):
    if not interaction.guild:
        raise InvalidOffer('Open the builder inside your trading server.')
    card=bot.read(source) if source else None
    if card:
        require_owner(interaction,card)
    draft=DraftView(interaction.user.id,interaction.guild,card.offered if card else None,card.wanted if card else None,card.roblox if card else '',source)
    await interaction.response.send_message(embed=draft.preview(),view=draft,ephemeral=True)
    draft.message=await interaction.original_response()


class ManageView(SafeView):
    def __init__(self,mid,cid,owner,editable=True):
        super().__init__(timeout=300)
        self.mid,self.cid,self.owner=mid,cid,owner
        self.edit.disabled=not editable
        self.renew.disabled=not editable

    async def interaction_check(self,interaction):
        if interaction.user.id==self.owner:
            return True
        await interaction.response.send_message('Open Manage offer yourself.',ephemeral=True)
        return False

    async def source(self):
        channel=bot.get_channel(self.cid) or await bot.fetch_channel(self.cid)
        return await channel.fetch_message(self.mid)

    @discord.ui.button(label='Edit offer',emoji='✏️',style=discord.ButtonStyle.primary)
    async def edit(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        source=await self.source()
        card=bot.read(source)
        require_owner(interaction,card)
        if not card.active():
            raise InvalidOffer('Closed or expired offers cannot be edited. Renew or create a new one.')
        draft=DraftView(interaction.user.id,interaction.guild,card.offered,card.wanted,card.roblox,source)
        draft.message=await interaction.followup.send(embed=draft.preview(),view=draft,ephemeral=True,wait=True)

    @discord.ui.button(label='Renew 24 hours',emoji='🔄',style=discord.ButtonStyle.secondary)
    async def renew(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        source=await self.source()
        await renew_card(interaction,source)

    @discord.ui.button(label='Close offer',emoji='✅',style=discord.ButtonStyle.danger)
    async def close_offer(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        source=await self.source()
        await close_card(interaction,source)


async def close_card(interaction,source):
    async with bot.locks.setdefault(source.id,asyncio.Lock()):
        source=await source.fetch()
        card=bot.read(source)
        require_owner(interaction,card,moderator=True)
        state='closed' if interaction.user.id==card.seller else 'locked'
        if card.state=='locked':
            state='locked'
        await bot.save(source,replace(card,state=state))
    await interaction.followup.send('✅ Offer closed. Its public card preserves this status after a restart.',ephemeral=True)


async def renew_card(interaction,source):
    async with bot.locks.setdefault(source.id,asyncio.Lock()):
        source=await source.fetch()
        card=bot.read(source)
        require_owner(interaction,card)
        if card.state=='locked':
            raise InvalidOffer('A moderator closed this offer. Contact a moderator.')
        if card.active() and time.time()-card.refreshed<1800:
            raise InvalidOffer('Wait 30 minutes before renewing an active offer. You can edit it now instead.')
        new=await bot.publish(interaction,card.offered,card.wanted,card.roblox,renew_source=source)
    await interaction.followup.send(f'🔄 Renewed for 24 hours: {new.jump_url}\nThe old card is closed.',ephemeral=True)


class SearchModal(SafeModal,title='Find a trading item'):
    query=discord.ui.TextInput(label='Item name or mapped emoji',placeholder='Time, Ancient Sap, or a spellbook emoji',max_length=100)

    async def on_submit(self,interaction):
        choices=catalog.choices(self.query.value,store.mapping(interaction.guild_id))
        if not choices:
            raise InvalidOffer('No matching tradeable item. Try its full name.')
        if len(choices)==1:
            await show_results(interaction,item=choices[0]['id'])
            return
        view=SafeView(timeout=180)
        selector=discord.ui.Select(placeholder='Choose the item you mean',options=[discord.SelectOption(label=i['name'],value=i['id'],description=i['category'][:100]) for i in choices])
        async def select(inter):
            await show_results(inter,item=selector.values[0])
        selector.callback=select
        view.add_item(selector)
        await interaction.response.send_message('Choose a matching item:',view=view,ephemeral=True)


class Results(SafeView):
    def __init__(self,owner,rows,title):
        super().__init__(timeout=180)
        self.owner,self.rows,self.title,self.page=owner,rows,title,0
        self.buttons()

    def buttons(self):
        self.previous.disabled=self.page==0
        self.next.disabled=(self.page+1)*5>=len(self.rows)

    def embed(self):
        e=discord.Embed(title=self.title,colour=0x38BD96,description='Open a trade card and choose Contact trader to start a DM.')
        for row in self.rows[self.page*5:self.page*5+5]:
            link=f"https://discord.com/channels/{row['guild']}/{row['channel']}/{row['message']}"
            e.add_field(name='Available offer',value=f"Trader: <@{row['seller']}>\nOffering: {catalog.display(json.loads(row['offered']))[:300]}\nWants: {catalog.display(json.loads(row['wanted']))[:300]}\nExpires <t:{int(row['expires'])}:R> · [Open trade card]({link})",inline=False)
        e.set_footer(text=f'Page {self.page+1}/{max(1,(len(self.rows)+4)//5)} • Rerun search to refresh')
        return e

    async def interaction_check(self,interaction):
        if interaction.user.id==self.owner:
            return True
        await interaction.response.send_message('Open your own search.',ephemeral=True)
        return False

    @discord.ui.button(label='Previous',style=discord.ButtonStyle.secondary)
    async def previous(self,interaction,button):
        self.page-=1
        self.buttons()
        await interaction.response.edit_message(embed=self.embed(),view=self)

    @discord.ui.button(label='Next',style=discord.ButtonStyle.secondary)
    async def next(self,interaction,button):
        self.page+=1
        self.buttons()
        await interaction.response.edit_message(embed=self.embed(),view=self)


async def show_results(interaction,item=None,seller=None):
    await interaction.response.defer(ephemeral=True,thinking=True)
    pending,failed=await bot.load_history(interaction)
    visible={str(c.id) for c in bot.visible_channels(interaction)}
    candidates=[r for r in store.active(interaction.guild_id,item=item,seller=seller) if r['channel'] in visible][:25]
    rows=[r for r in await asyncio.gather(*(bot.validate(r) for r in candidates)) if r and (not item or item in json.loads(r['offered']))]
    notice='The board is still loading; results are partial. Search again shortly.' if pending else 'Some channels could not be read; check permissions and retry.' if failed else None
    if not rows:
        await interaction.followup.send(notice or 'No active offers yet. Use Create offer or /offer to publish one.',ephemeral=True)
        return
    view=Results(interaction.user.id,rows,'Your active offers' if seller else catalog.items[item]['name']+' • sellers')
    await interaction.followup.send(content=notice,embed=view.embed(),view=view,ephemeral=True)


async def item_autocomplete(interaction,current):
    return [app_commands.Choice(name=(i['name']+' · '+i['category'])[:100],value=i['id']) for i in catalog.choices(current,store.mapping(interaction.guild_id))]


@tree.command(name='offer',description='Open the private trade builder and publish a trading card.')
@app_commands.guild_only()
async def offer(interaction:discord.Interaction):
    await open_builder(interaction)


@tree.command(name='search',description='Find sellers using item-name or mapped-emoji autocomplete.')
@app_commands.guild_only()
@app_commands.autocomplete(item=item_autocomplete)
async def search(interaction:discord.Interaction,item:str):
    target=catalog.resolve(item,store.mapping(interaction.guild_id))
    if not target:
        raise InvalidOffer('Select a tradeable item from autocomplete or paste a mapped emoji.')
    await show_results(interaction,item=target)


@tree.command(name='myoffers',description='See your active trading cards and manage them.')
@app_commands.guild_only()
async def myoffers(interaction:discord.Interaction):
    await show_results(interaction,seller=interaction.user.id)


@tree.command(name='close',description='Close a trading card by its link or message ID.')
@app_commands.guild_only()
async def close(interaction:discord.Interaction,message:str):
    await interaction.response.defer(ephemeral=True)
    await close_card(interaction,await bot.source_for(interaction,message))


@tree.command(name='renew',description='Publish a fresh 24-hour card and close the old one.')
@app_commands.guild_only()
async def renew(interaction:discord.Interaction,message:str):
    await interaction.response.defer(ephemeral=True)
    await renew_card(interaction,await bot.source_for(interaction,message))


@tree.command(name='items',description='Browse tradeable item names; optionally filter by name/category.')
@app_commands.guild_only()
async def items(interaction:discord.Interaction,filter:str=''):
    lines=[f"**{i['name']}** · {i['category']}" for i in catalog.items.values() if filter.lower() in (i['name']+' '+i['category']).lower()]
    text='\n'.join(lines)
    await interaction.response.send_message((text[:1800]+'\nNarrow the filter for more.' if len(text)>1800 else text) or 'No matching items.',ephemeral=True)


@tree.command(name='help',description='How to create, find, contact and manage trading offers.')
async def help_command(interaction:discord.Interaction):
    await interaction.response.send_message(HELP,ephemeral=True)


@tree.command(name='rules',description='Clover Legends trade requirements and community guidelines.')
async def rules(interaction:discord.Interaction):
    await interaction.response.send_message(RULES,ephemeral=True)


@tree.command(name='panel',description='Post the permanent Trading Desk with Create, Search, My offers and Rules buttons.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def panel(interaction:discord.Interaction,channel:discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    testing=test_channel_id()
    if testing and channel.id!=testing:
        raise InvalidOffer(f'Testing mode is active. Use the testing channel {testing}; offers and the desk stay there.')
    source=await bot.ensure_desk(channel)
    await interaction.followup.send(f'Trading Desk posted: {source.jump_url}\nPin it so members can find it. Its buttons work after bot restarts.',ephemeral=True)


@tree.command(name='setup',description='Enable a trading channel for this session; save its ID in Render to retain it.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(interaction:discord.Interaction,channel:discord.TextChannel,enabled:bool=True):
    testing=test_channel_id()
    if testing and enabled and channel.id!=testing:
        raise InvalidOffer(f'Testing mode only publishes to channel {testing}. Set TEST_CHANNEL_ID=off in Render when testing is finished.')
    perms=channel.permissions_for(interaction.guild.me)
    if enabled and not all([perms.view_channel,perms.read_message_history,perms.send_messages,perms.embed_links]):
        raise InvalidOffer('Give the bot View Channel, Read Message History, Send Messages and Embed Links first.')
    store.configure(interaction.guild_id,channel.id,enabled)
    bot.history_index.invalidate(channel.id)
    await interaction.response.send_message(f"Session updated. Save TRADING_CHANNEL_IDS={','.join(store.channels(interaction.guild_id))} in Render to retain it after restart.",ephemeral=True)


@tree.command(name='emoji_sync',description='Preview or refresh exact-name mappings for uploaded server emojis.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def emoji_sync(interaction:discord.Interaction,apply:bool=False):
    matches=bot.emoji_matches(interaction.guild)
    if apply:
        for emoji,target in matches:
            store.bind(interaction.guild_id,emoji.id,target)
    lines='\n'.join(f'{e.name} → {catalog.items[t]["name"] if t in catalog.items else t}' for e,t in matches)
    await interaction.response.send_message(('Mapped' if apply else 'Preview')+f' {len(matches)} emojis.\n'+lines[:1600]+'\nExact standard names restore automatically at restart.',ephemeral=True)


@tree.command(name='emoji_bind',description='Map one differently named server emoji to a tradeable item.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.autocomplete(item=item_autocomplete)
async def emoji_bind(interaction:discord.Interaction,emoji:str,item:str):
    match=re.fullmatch(r'<a?:\w+:(\d+)>',emoji.strip())
    found=discord.utils.get(interaction.guild.emojis,id=int(match[1])) if match else None
    target=catalog.resolve(item,store.mapping(interaction.guild_id))
    if not found or not target:
        raise InvalidOffer('Select an existing server emoji and valid item.')
    store.bind(interaction.guild_id,found.id,target)
    snippet=json.dumps({str(found.id):target})
    await interaction.response.send_message(f'Mapped {found} to {catalog.items[target]["name"]}. Merge this entry into Render EMOJI_MAP_JSON to retain it:\n```json\n{snippet}\n```',ephemeral=True)


@tree.command(name='status',description='Check Trading Desk channels, spellbook emojis and loading state.')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def status(interaction:discord.Interaction):
    mapping=store.mapping(interaction.guild_id)
    books={i['id'] for i in catalog.items.values() if i['kind']=='spellbook'}
    missing=books-set(mapping.values())
    await interaction.response.send_message(f"Mode: Trading Desk • no privileged intents\nChannels: {', '.join('<#'+c+'>' for c in store.channels(interaction.guild_id)) or 'None'}\nSpellbook emojis: {16-len(missing)}/16\nActive cached offers: {len(store.active(interaction.guild_id))}\nHistory loading: {sum(not t.done() for t in bot.history_index.tasks.values())}\nHistory errors: {len(bot.history_index.errors)}\nUse /panel to post the Trading Desk.",ephemeral=True)


tree.error(explain)


async def main():
    token=os.getenv('DISCORD_TOKEN')
    if not token:
        raise SystemExit('Set DISCORD_TOKEN in Render Environment. Never share it in chat.')
    runner=web.AppRunner(make_app(bot.health_status))
    await runner.setup()
    await web.TCPSite(runner,'0.0.0.0',int(os.getenv('PORT','10000'))).start()
    try:
        async with bot:
            await bot.start(token)
    finally:
        await runner.cleanup()


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
