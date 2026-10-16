"""Human-readable, bot-authored trade cards double as recoverable listing records."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time

import discord
from core import InvalidOffer

TITLE = 'Clover Legends • Trade'
FOOTER = 'Clover Trading • Offers last 24 hours'
STATES = {'active': '🟢 Open', 'closed': '✅ Closed', 'locked': '🔒 Closed by moderator'}


def validate_basket(catalog, basket):
    if not isinstance(basket, dict) or not basket:
        raise InvalidOffer('Add at least one item you are offering.')
    if any(i not in catalog.items or type(q) is not int or not 1 <= q <= 1000000 for i, q in basket.items()):
        raise InvalidOffer('Choose valid tradeable items and positive whole quantities.')
    catalog.side(catalog.display(basket))


@dataclass
class Card:
    seller: int
    seller_name: str
    offered: dict
    wanted: dict
    refreshed: float
    state: str = 'active'
    roblox: str = ''

    def __post_init__(self):
        # Discord timestamps have bounded precision; stable whole seconds prevent drift on recovery.
        self.refreshed = int(self.refreshed)

    @property
    def expires(self):
        return self.refreshed + 86400

    def active(self):
        return self.state == 'active' and self.expires > time.time()

    def validate(self, catalog):
        validate_basket(catalog, self.offered)
        if self.wanted:
            validate_basket(catalog, self.wanted)
        if self.state not in STATES or not 0 < self.seller < 2**64 or not 0 <= self.refreshed <= time.time()+60:
            raise InvalidOffer('Invalid trading card.')
        if self.roblox and not re.fullmatch(r'[A-Za-z0-9_]{3,20}', self.roblox):
            raise InvalidOffer('Use a Roblox username with 3–20 letters, numbers or underscores.')

    def embed(self, catalog, emojis=None):
        self.validate(catalog)
        emojis = emojis or {}
        e = discord.Embed(title=TITLE, colour=0x38BD96 if self.active() else 0x747F8D,
                          description='Find a match here. Negotiate in DMs. Exchange items in-game.',
                          timestamp=datetime.fromtimestamp(self.refreshed, timezone.utc))
        e.set_author(name=self.seller_name[:100], url=f'https://discord.com/users/{self.seller}')
        def lines(basket):
            return '\n'.join(f"{str(emojis[i])+' ' if i in emojis else ''}**{catalog.items[i]['name']}** ×{q}" for i,q in basket.items())
        e.add_field(name='Offering', value=lines(self.offered), inline=True)
        e.add_field(name='Looking for', value=lines(self.wanted) if self.wanted else '❓ Open to offers', inline=True)
        e.add_field(name='Trader', value=f'<@{self.seller}>', inline=False)
        e.add_field(name='Status', value=STATES[self.state], inline=True)
        e.add_field(name='Expires', value=f'<t:{int(self.expires)}:R>', inline=True)
        if self.roblox:
            e.add_field(name='Roblox username', value=self.roblox, inline=True)
        e.set_footer(text=FOOTER)
        for item in self.offered:
            emoji = emojis.get(item)
            if emoji and catalog.items[item]['kind'] == 'spellbook':
                e.set_thumbnail(url=str(emoji.url))
                break
        return e

    @classmethod
    def from_message(cls, message, bot_id, catalog):
        if message.author.id != bot_id or getattr(message, 'webhook_id', None) or len(message.embeds) != 1:
            raise InvalidOffer('This is not a trading card published by this bot.')
        e = message.embeds[0]
        if e.title != TITLE or e.footer.text != FOOTER or e.timestamp is None:
            raise InvalidOffer('This is not a supported trading card.')
        owner = re.fullmatch(r'https://discord.com/users/(\d{1,20})', e.author.url or '')
        fields = {f.name: f.value for f in e.fields}
        if not owner or len(fields) != len(e.fields) or not {'Offering','Looking for','Status'} <= fields.keys():
            raise InvalidOffer('The trading card is incomplete.')
        # We only read our own cards, an explicit Discord Message Content exception.
        def basket(value):
            return catalog.side(re.sub(r'<a?:\w+:\d+>', '', value).replace('**', ''))
        states = {v:k for k,v in STATES.items()}
        if fields['Status'] not in states:
            raise InvalidOffer('Unknown listing status.')
        card = cls(int(owner[1]), e.author.name or 'Trader', basket(fields['Offering']),
                   {} if fields['Looking for'] == '❓ Open to offers' else basket(fields['Looking for']),
                   e.timestamp.timestamp(), states[fields['Status']], fields.get('Roblox username',''))
        card.validate(catalog)
        return card
