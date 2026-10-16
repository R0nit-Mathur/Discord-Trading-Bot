"""Conservative trade parsing and persistent listing lifecycle; no Discord dependency."""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path


class InvalidOffer(ValueError):
    pass


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class Catalog:
    def __init__(self, path):
        self.data = json.loads(Path(path).read_text())
        self.items = {i['id']: i for i in self.data['items'] if i['enabled']}
        self.names = {}
        for item in self.items.values():
            for name in [item['id'], item['name'], item['emoji_name'], *item['aliases']]:
                self.names[norm(name)] = item['id']
        self.blocked = {norm(n) for i in self.data['blocked_items'] for n in [i['name'], *i['aliases']]}
        self.pattern = re.compile('|'.join(re.escape(n) for n in sorted(self.names, key=len, reverse=True)), re.I)

    def resolve(self, value, mapping):
        match = re.fullmatch(r'<a?:\w+:(\d+)>', value.strip())
        if match:
            target = mapping.get(match[1])
            return target if target in self.items else None
        return self.names.get(norm(value.strip(':')))

    def choices(self, query, mapping):
        exact = self.resolve(query, mapping)
        q = norm(query.strip(':'))
        return sorted([i for i in self.items.values() if not q or i['id'] == exact or
                       any(q in norm(n) for n in [i['name'], i['emoji_name'], *i['aliases']])],
                      key=lambda i: (i['id'] != exact, i['kind'] != 'spellbook', i['name']))[:25]

    def parse(self, text, mapping):
        if '✅' in text:
            raise InvalidOffer('✅ marks this whole offer unavailable. Remove it and use /renew to reopen.')
        if len(text) > 1500 or re.search(r'https?://|discord\.gg|<@|@everyone|@here', text, re.I):
            raise InvalidOffer('Use an item-only offer without links or mentions.')

        def emoji(match):
            target = mapping.get(match[1])
            if target in self.items:
                return ' ' + self.items[target]['name'] + ' '
            if target == 'separator':
                return ' => '
            if target == 'offers':
                return ' offers '
            raise InvalidOffer('An emoji is not mapped. Use the item name or ask a moderator to map it.')

        text = re.sub(r'<a?:\w+:(\d+)>', emoji, text)
        def shortcode(match):
            name = match[1]
            if name == 'cl_trade':
                return ' => '
            if name == 'cl_offers':
                return ' offers '
            item_id = self.resolve(name, {})
            if not item_id:
                raise InvalidOffer('Unknown item shortcode: ' + name)
            return ' ' + self.items[item_id]['name'] + ' '
        text = re.sub(r':([a-zA-Z0-9_]+):', shortcode, text)
        text = re.sub(r'^\s*(?:wtt|trading|trade|offering|offer|selling|have)\b\s*:?', '', text, flags=re.I)
        parts = re.split(r'\s*(?:=>|->|→|➡️?|↔️?|\blooking\s+for\b|\blf\b|\bfor\b|\bwant(?:ing)?\b)\s*:?', text, flags=re.I)
        if len(parts) != 2:
            raise InvalidOffer('Use “Time x1 => Light x1” or “Time => offers”. Put quantities before or after each item.')
        offered = self.side(parts[0])
        wanted = {} if parts[1].strip() == '❓' or norm(parts[1]) in ('offers', 'offer', 'any offers') else self.side(parts[1])
        return offered, wanted

    def side(self, value):
        if re.search(r'-\s*\d|\d[.,]\d', value):
            raise InvalidOffer('Use positive whole-number quantities, without commas or decimal points.')
        text = norm(value.replace('×', ' x ').replace('+', ' ').replace(',', ' ').replace('&', ' '))
        # Match whole restricted names first so e.g. Fire Aura cannot become Fire.
        for blocked in self.blocked:
            if re.search(r'(?<!\w)' + re.escape(blocked) + r'(?!\w)', text):
                raise InvalidOffer('This includes a non-tradeable item: ' + blocked)
        result = {}
        while text:
            prefix = re.match(r'^(\d+)\s*(?:x\s+)?', text)
            quantity = int(prefix[1]) if prefix else None
            if prefix:
                text = text[prefix.end():]
            match = self.pattern.match(text)
            if not match or (match.end() < len(text) and text[match.end()] != ' '):
                raise InvalidOffer('Unrecognized item or extra wording. Use exact item names and “=>”.')
            item_id = self.names[norm(match[0])]
            text = text[match.end():].strip()
            suffix = re.match(r'^x\s*(\d+)(?:\s|$)', text)
            if suffix:
                if quantity is not None:
                    raise InvalidOffer('Give each quantity once.')
                quantity = int(suffix[1])
                text = text[suffix.end():].strip()
            quantity = 1 if quantity is None else quantity
            if not 1 <= quantity <= 1000000:
                raise InvalidOffer('Quantities must be between 1 and 1,000,000.')
            result[item_id] = result.get(item_id, 0) + quantity
        if not result:
            raise InvalidOffer('The offer needs at least one item.')
        slots = sum(q if self.items[i]['kind'] != 'material' and self.items[i].get('max_stack') == 1 else 1
                    for i, q in result.items())
        if slots > 9:
            raise InvalidOffer('Each side can use at most 9 slots. Materials count as one stack per item type.')
        return result

    def display(self, items):
        return ' + '.join(f"{self.items[i]['name']} ×{q}" for i, q in items.items()) or 'Offers'


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(guild TEXT PRIMARY KEY, channels TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS emojis(guild TEXT, emoji TEXT, target TEXT, PRIMARY KEY(guild,emoji));
        CREATE TABLE IF NOT EXISTS offers(
            message TEXT PRIMARY KEY, guild TEXT, channel TEXT, seller TEXT,
            offered TEXT, wanted TEXT, fingerprint TEXT, refreshed REAL, expires REAL,
            state TEXT DEFAULT 'active', reason TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS offers_guild_state ON offers(guild,state,expires);
        ''')

    def channels(self, guild):
        row = self.db.execute('SELECT channels FROM settings WHERE guild=?', (str(guild),)).fetchone()
        return json.loads(row[0]) if row else []

    def configure(self, guild, channel, enabled):
        channels = self.channels(guild)
        if enabled and str(channel) not in channels:
            channels.append(str(channel))
        if not enabled:
            channels = [c for c in channels if c != str(channel)]
            self.db.execute("UPDATE offers SET state='closed', reason='channel disabled' WHERE guild=? AND channel=?", (str(guild), str(channel)))
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (str(guild), json.dumps(channels)))

    def mapping(self, guild):
        return dict(self.db.execute('SELECT emoji,target FROM emojis WHERE guild=?', (str(guild),)))

    def bind(self, guild, emoji, target):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO emojis VALUES (?,?,?)', (str(guild), str(emoji), target))

    def get(self, message):
        return self.db.execute('SELECT * FROM offers WHERE message=?', (str(message),)).fetchone()

    def close(self, message, reason):
        with self.db:
            self.db.execute("UPDATE offers SET state='closed',reason=? WHERE message=?", (reason, str(message)))

    def upsert(self, message, guild, channel, seller, offered, wanted, now=None, renew=False):
        now = time.time() if now is None else now
        a, b = json.dumps(offered, sort_keys=True), json.dumps(wanted, sort_keys=True)
        fingerprint = hashlib.sha256((a + '|' + b).encode()).hexdigest()
        old = self.get(message)
        if old and old['state'] == 'closed' and old['reason'] != 'source needs correction' and not renew:
            return False
        # Editing does not silently extend the 24 hour lifetime. Reposting or /renew does.
        refreshed = now if not old or renew else old['refreshed']
        with self.db:
            newer = self.db.execute("SELECT 1 FROM offers WHERE guild=? AND seller=? AND fingerprint=? AND message<>? AND (refreshed>? OR (refreshed=? AND CAST(message AS INTEGER)>?))", (str(guild), str(seller), fingerprint, str(message), refreshed, refreshed, int(message))).fetchone()
            if not newer:
                self.db.execute("UPDATE offers SET state='closed',reason='replaced by repost' WHERE guild=? AND seller=? AND fingerprint=? AND message<>? AND state='active' AND refreshed<=?", (str(guild), str(seller), fingerprint, str(message), refreshed))
            self.db.execute('INSERT OR REPLACE INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (str(message), str(guild), str(channel), str(seller), a, b, fingerprint,
                             refreshed, refreshed + 86400, 'closed' if newer else 'active', 'replaced by repost' if newer else ''))
        return True

    def prune(self):
        with self.db:
            self.db.execute('DELETE FROM offers WHERE expires<?', (time.time() - 86400,))

    def active(self, guild, item=None, seller=None, now=None):
        now = time.time() if now is None else now
        rows = self.db.execute("SELECT * FROM offers WHERE guild=? AND state='active' AND expires>? ORDER BY refreshed DESC", (str(guild), now)).fetchall()
        return [r for r in rows if (not item or item in json.loads(r['offered'])) and (not seller or r['seller'] == str(seller))]
