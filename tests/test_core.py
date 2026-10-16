import json
import tempfile
import unittest
from pathlib import Path
from core import Catalog, InvalidOffer, Store

ROOT = Path(__file__).resolve().parents[1]


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.c = Catalog(ROOT / 'catalog.json')
        self.mapping = {'111': 'time', '222': 'light', '333': 'separator', '444': 'offers'}

    def test_catalog(self):
        self.assertEqual(len(self.c.items), 76)
        self.assertEqual(sum(i['kind'] == 'spellbook' for i in self.c.items.values()), 16)

    def test_text_and_quantities(self):
        self.assertEqual(self.c.parse('Trading 250 Ancient Sap + Fire for offers', {}),
                         ({'ancient_sap': 250, 'fire': 1}, {}))
        self.assertEqual(self.c.parse('Time x2 => Light x1', {}), ({'time': 2}, {'light': 1}))
        self.assertEqual(self.c.parse('WTT Time Spellbook LF Light Book', {}), ({'time': 1}, {'light': 1}))

    def test_emojis(self):
        self.assertEqual(self.c.parse(':cl_book_time: ➡️ ❓', {}), ({'time': 1}, {}))
        self.assertEqual(self.c.parse('<:clock:111><:clock:111> <:arrow:333> <:sun:222>', self.mapping),
                         ({'time': 2}, {'light': 1}))
        self.assertEqual(self.c.parse('<:clock:111> => <:offers:444>', self.mapping), ({'time': 1}, {}))
        self.assertEqual(self.c.parse(':cl_book_time: => :cl_book_light:', {}), ({'time': 1}, {'light': 1}))

    def test_identity_not_emoji_name(self):
        with self.assertRaises(InvalidOffer):
            self.c.parse('<:cl_book_time:999> => offers', self.mapping)
        self.assertEqual(self.c.resolve('<:anything:111>', self.mapping), 'time')

    def test_restricted_and_unknown(self):
        for text in ['Fire Aura => Time', 'Wind Broom => Fire', 'Robux Spellbook => Time',
                     'Cooked Golden Koi => Time', 'Lucky Goggles => Fire', 'Gems => Time',
                     'VIP Aura => Time', 'Time => Gold Pickaxe', 'Dragon => Time']:
            with self.subTest(text=text), self.assertRaises(InvalidOffer):
                self.c.parse(text, {})

    def test_no_false_seller_or_prose(self):
        for text in ['I really like Time', 'Anyone selling Time?', 'Time => Light => Blood',
                     'Time => offers https://example.com', 'Time for @everyone', 'Time maybe => Light', 'Time => Light ✅']:
            with self.subTest(text=text), self.assertRaises(InvalidOffer):
                self.c.parse(text, {})

    def test_limits(self):
        for text in ['Time x10 => offers', 'Time x0 => Light', '-2 Time => Light',
                     'Time x1.5 => Light', 'Time x2 x3 => Light']:
            with self.subTest(text=text), self.assertRaises(InvalidOffer):
                self.c.parse(text, {})
        self.assertEqual(self.c.parse('250 Ancient Sap => offers', {})[0]['ancient_sap'], 250)

    def test_autocomplete(self):
        self.assertEqual(self.c.choices('<:clock:111>', self.mapping)[0]['id'], 'time')
        self.assertEqual(self.c.choices('cl_book_time', {})[0]['id'], 'time')
        self.assertTrue(all(i['kind'] == 'spellbook' for i in self.c.choices('book', {})))
        self.assertLessEqual(len(self.c.choices('', {})), 25)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'trades.sqlite3'
        self.s = Store(self.path)
        self.s.configure(1, 10, True)

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def add(self, message=100, **kw):
        return self.s.upsert(message, 1, 10, 2, {'time': 1}, {'light': 1}, **kw)

    def test_wanted_item_not_seller_result(self):
        self.add(now=0)
        self.assertEqual(len(self.s.active(1, item='time', now=1)), 1)
        self.assertEqual(self.s.active(1, item='light', now=1), [])
        self.assertEqual(self.s.active(9, item='time', now=1), [])

    def test_edit_preserves_ttl(self):
        self.add(now=0)
        self.s.upsert(100, 1, 10, 2, {'blood': 1}, {}, now=100)
        self.assertEqual(self.s.get(100)['expires'], 86400)
        self.assertEqual(self.s.active(1, item='time', now=101), [])
        self.assertEqual(len(self.s.active(1, item='blood', now=101)), 1)

    def test_close_persists_and_edit_cannot_reopen(self):
        self.add(now=0)
        self.s.close(100, 'seller marked unavailable')
        self.assertFalse(self.add(now=5))
        self.assertEqual(self.s.active(1, now=6), [])
        self.assertTrue(self.add(now=10, renew=True))
        self.assertEqual(self.s.get(100)['expires'], 86410)

    def test_repost_deduplicates_only_same_seller_and_guild(self):
        self.add(now=0)
        self.add(message=101, now=2)
        self.assertEqual([r['message'] for r in self.s.active(1, now=3)], ['101'])
        self.s.upsert(102, 1, 10, 3, {'time': 1}, {'light': 1}, now=4)
        self.assertEqual(len(self.s.active(1, now=5)), 2)

    def test_expiry_and_repair(self):
        self.add(now=0)
        self.assertEqual(self.s.active(1, now=86400), [])
        self.s.close(100, 'source needs correction')
        self.add(now=800)
        self.assertEqual(self.s.get(100)['expires'], 86400)

    def test_restart_and_mapping_persistence(self):
        self.add(now=0)
        self.s.bind(1, 111, 'time')
        self.s.db.close()
        self.s = Store(self.path)
        self.assertEqual(len(self.s.active(1, now=5)), 1)
        self.assertEqual(self.s.mapping(1), {'111': 'time'})
        self.assertEqual(self.s.channels(1), ['10'])

    def test_disable_channel_closes_its_offers(self):
        self.add(now=0)
        self.s.configure(1, 10, False)
        self.assertEqual(self.s.active(1, now=1), [])


if __name__ == '__main__':
    unittest.main()
