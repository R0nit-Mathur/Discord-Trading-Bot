"""Offline event tests; no Discord credentials, network calls, or public messages."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ['DATABASE_PATH'] = ':memory:'
import bot as app
from core import Store


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = app.store
        self.tmp = tempfile.TemporaryDirectory()
        app.store = Store(self.tmp.name + '/events.sqlite3')
        app.store.configure(1, 10, True)
        app.store.upsert(100, 1, 10, 2, {'time': 1}, {'light': 1})
        self.message = SimpleNamespace(id=100, guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=10),
                                       author=SimpleNamespace(id=2, bot=False), content='Time => Light',
                                       reactions=[], add_reaction=AsyncMock(), remove_reaction=AsyncMock())
        self.fetch = app.bot.fetch_source
        app.bot.fetch_source = AsyncMock(return_value=self.message)

    async def asyncTearDown(self):
        app.bot.fetch_source = self.fetch
        app.store.db.close()
        app.store = self.previous
        self.tmp.cleanup()

    async def test_only_owner_tick_closes(self):
        p = SimpleNamespace(emoji='✅', guild_id=1, message_id=100, user_id=99)
        await app.bot.on_raw_reaction_add(p)
        self.assertEqual(app.store.get(100)['state'], 'active')
        p.user_id = 2
        await app.bot.on_raw_reaction_add(p)
        self.assertEqual(app.store.get(100)['state'], 'closed')

    async def test_cross_guild_tick_ignored(self):
        await app.bot.on_raw_reaction_add(SimpleNamespace(emoji='✅', guild_id=9, message_id=100, user_id=2))
        self.assertEqual(app.store.get(100)['state'], 'active')

    async def test_tick_in_author_message_closes(self):
        self.message.content += ' ✅'
        await app.bot.index_message(self.message)
        self.assertEqual(app.store.get(100)['state'], 'closed')

    async def test_search_rechecks_missed_edit(self):
        self.message.content = 'Blood => Light'
        row = await app.bot.validate(app.store.get(100))
        self.assertIn('blood', row['offered'])
        self.assertEqual(app.store.active(1, item='time'), [])

    async def test_unknown_edit_is_removed(self):
        self.message.content = 'not a trading post anymore'
        self.assertIsNone(await app.bot.validate(app.store.get(100)))
        self.assertEqual(app.store.get(100)['state'], 'closed')

    async def test_owner_tick_missed_while_offline(self):
        async def users(limit=None):
            yield SimpleNamespace(id=99)
            yield SimpleNamespace(id=2)
        self.message.reactions = [SimpleNamespace(emoji='✅', users=users)]
        self.assertIsNone(await app.bot.validate(app.store.get(100)))
        self.assertEqual(app.store.get(100)['state'], 'closed')

    async def test_other_tick_does_not_hide_search(self):
        async def users(limit=None):
            yield SimpleNamespace(id=99)
        self.message.reactions = [SimpleNamespace(emoji='✅', users=users)]
        self.assertIsNotNone(await app.bot.validate(app.store.get(100)))

    async def test_raw_delete_removes_listing(self):
        await app.bot.on_raw_message_delete(SimpleNamespace(message_id=100))
        self.assertEqual(app.store.active(1), [])

    async def test_owner_permission_guard(self):
        other = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=99), permissions=SimpleNamespace(manage_messages=False))
        with self.assertRaises(app.InvalidOffer):
            app.owned_row(other, '100', moderator=True)
        other.permissions.manage_messages = True
        self.assertEqual(app.owned_row(other, '100', moderator=True)['message'], '100')
        other.guild_id = 9
        with self.assertRaises(app.InvalidOffer):
            app.owned_row(other, '100', moderator=True)

    async def test_commands_serialize_with_autocomplete(self):
        commands = {c.name: c.to_dict(app.tree) for c in app.tree.get_commands()}
        self.assertTrue(commands['search']['options'][0]['autocomplete'])
        self.assertIn('close', commands)
        self.assertIn('renew', commands)
        self.assertNotIn('stock', commands)
        self.assertLessEqual(len(app.HELP), 2000)


if __name__ == '__main__':
    unittest.main()
