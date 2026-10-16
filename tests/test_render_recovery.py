import asyncio
import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from aiohttp.test_utils import make_mocked_request
from core import Store
from health import make_app
from recovery import HistoryIndex, renewal_target
import bot as app


def message(mid, content='Time => Light', age=10, author=2, is_bot=False, reactions=None, embeds=None):
    return NS(id=mid, content=content, author=NS(id=author, bot=is_bot),
              guild=NS(id=1), channel=NS(id=10), created_at=datetime.now(timezone.utc)-timedelta(seconds=age),
              reactions=reactions or [], embeds=embeds or [], add_reaction=AsyncMock(), remove_reaction=AsyncMock())


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = app.store
        app.store = Store(':memory:')
        app.store.configure(1, 10, True)
        self.client = app.Clover()
        self.client._connection.user = NS(id=777)

    async def asyncTearDown(self):
        await self.client.history_index.close()
        app.store.db.close()
        app.store = self.previous

    async def test_cold_rebuild_preserves_original_age(self):
        m = message(100, age=3600)
        await self.client.recover_message(m)
        self.assertAlmostEqual(app.store.get(100)['expires'], m.created_at.timestamp()+86400)

    async def test_expired_original_does_not_get_new_day(self):
        await self.client.recover_message(message(100, age=90000))
        self.assertEqual(app.store.active(1), [])

    async def test_newest_first_does_not_restore_duplicate(self):
        await self.client.recover_message(message(102, age=10))
        await self.client.recover_message(message(101, age=20))
        self.assertEqual([r['message'] for r in app.store.active(1)], ['102'])

    async def test_closed_newest_copy_does_not_resurrect_older_copy(self):
        await self.client.recover_message(message(102, content='Time => Light ✅', age=10))
        await self.client.recover_message(message(101, age=20))
        self.assertEqual(app.store.active(1), [])

    async def test_bot_close_tick_survives_without_seller_tick(self):
        async def users(limit=None):
            yield NS(id=777)
        m = message(100, reactions=[NS(emoji='✅', users=users)])
        await self.client.recover_message(m)
        self.assertEqual(app.store.active(1), [])

    async def test_moderator_lock_survives_restart(self):
        async def users(limit=None):
            yield NS(id=777)
        await self.client.recover_message(message(100, reactions=[NS(emoji='🔒', users=users)]))
        self.assertEqual(app.store.get(100)['reason'], 'moderator closed')

    async def test_other_users_tick_not_a_close(self):
        async def users(limit=None):
            yield NS(id=99)
        await self.client.recover_message(message(100, reactions=[NS(emoji='✅', users=users)]))
        self.assertEqual(len(app.store.active(1)), 1)

    async def test_trusted_renewal_restores_old_source(self):
        source = message(100, age=90000)
        record = message(200, author=777, is_bot=True,
                         embeds=[NS(footer=NS(text='clover:renew:100'))])
        async def history(**kwargs):
            yield record
        channel = NS(id=10, history=history, fetch_message=AsyncMock(return_value=source))
        index = HistoryIndex(self.client.recover_message, lambda: 777)
        pending, failed = await index.ensure([channel], timeout=1)
        self.assertFalse(pending or failed)
        self.assertEqual(len(app.store.active(1)), 1)
        self.assertEqual(app.store.get(100)['refreshed'], record.created_at.timestamp())
        await index.close()

    async def test_forged_renewal_marker_ignored(self):
        forged = message(200, embeds=[NS(footer=NS(text='clover:renew:100'))])
        self.assertIsNone(renewal_target(forged, 777))

    async def test_explicit_renew_lookup_can_recover_expired_source(self):
        await self.client.recover_message(message(100, age=90000), force=True)
        self.assertIsNotNone(app.store.get(100))
        self.assertEqual(app.store.active(1), [])

    async def test_content_close_is_recovered_and_mirrored(self):
        source = message(100, content='Time => Light ✅')
        await self.client.recover_message(source)
        self.assertEqual(app.store.active(1), [])
        source.add_reaction.assert_awaited_once_with('✅')

    async def test_close_then_renew_survive_two_fresh_caches(self):
        source = message(100)
        await self.client.recover_message(source)
        async def bot_users(limit=None):
            yield NS(id=777)
        async def add(emoji):
            if emoji == '✅':
                source.reactions = [NS(emoji='✅', users=bot_users, me=True)]
        source.add_reaction.side_effect = add
        self.client.fetch_source = AsyncMock(return_value=source)
        interaction = NS(guild_id=1, user=NS(id=2), permissions=NS(manage_messages=False),
                         response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        record = message(200, author=777, is_bot=True)
        async def reply(**kwargs):
            record.embeds = [kwargs['embed']]
            return record
        async def remove(emoji, user):
            if emoji == '✅':
                source.reactions = []
        source.reply = AsyncMock(side_effect=reply)
        source.remove_reaction.side_effect = remove
        with patch.object(app, 'bot', self.client):
            await app.close.callback(interaction, '100')
            app.store.db.close()
            app.store = Store(':memory:')
            app.store.configure(1, 10, True)
            await self.client.recover_message(source)
            self.assertEqual(app.store.active(1), [])
            await app.renew.callback(interaction, '100')
            self.assertEqual(len(app.store.active(1)), 1)
            app.store.db.close()
            app.store = Store(':memory:')
            app.store.configure(1, 10, True)
            async def history(**kwargs):
                yield record
                yield source
            channel = NS(id=10, history=history, fetch_message=AsyncMock(return_value=source))
            index = HistoryIndex(self.client.recover_message, lambda: 777)
            pending, failed = await index.ensure([channel], timeout=1)
            self.assertFalse(pending or failed)
            self.assertEqual(len(app.store.active(1)), 1)
            self.assertEqual(app.store.get(100)['refreshed'], record.created_at.timestamp())
            await index.close()

    async def test_loading_search_acknowledges_and_never_claims_empty_market(self):
        self.client.load_history = AsyncMock(return_value=(True, False))
        interaction = NS(guild_id=1, response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        with patch.object(app, 'bot', self.client):
            await app.search.callback(interaction, 'Time')
        interaction.response.defer.assert_awaited_once()
        text = interaction.followup.send.await_args.args[0]
        self.assertIn('still loading', text)
        self.assertNotIn('No checked active', text)

    async def test_missing_history_permissions_report_failure(self):
        async def history(**kwargs):
            raise PermissionError('denied')
            yield
        index = HistoryIndex(AsyncMock(), lambda: 777)
        pending, failed = await index.ensure([NS(id=10, history=history)], timeout=1)
        self.assertFalse(pending)
        self.assertTrue(failed)
        await index.close()

    async def test_searches_share_work_and_timeout_does_not_cancel(self):
        gate = asyncio.Event()
        calls = []
        async def history(**kwargs):
            calls.append(kwargs)
            await gate.wait()
            yield message(100)
        recover = AsyncMock()
        index = HistoryIndex(recover, lambda: 777)
        channel = NS(id=10, history=history)
        pending, failed = await index.ensure([channel], timeout=.01)
        self.assertTrue(pending)
        self.assertFalse(failed)
        await index.ensure([channel], timeout=.01)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0]['limit'])
        gate.set()
        await index.ensure([channel], timeout=1)
        recover.assert_awaited_once()
        await index.ensure([channel], timeout=1)
        self.assertEqual(len(calls), 1)
        await index.close()

    async def test_boot_restores_channels_and_emoji_names(self):
        channel = Mock(spec=app.discord.TextChannel)
        channel.permissions_for.return_value = NS(view_channel=True, read_message_history=True, send_messages=True, add_reactions=True, embed_links=True)
        guild = NS(id=1, me=NS(id=777), get_channel=lambda x: channel if x == 10 else None,
                   emojis=[NS(id=111, name='cl_book_time'), NS(id=222, name='cl_book_light')])
        with patch.dict(os.environ, {'GUILD_ID':'1','TRADING_CHANNEL_IDS':'10','EMOJI_MAP_JSON':'{"333":"separator"}'}), patch.object(self.client, 'get_guild', return_value=guild):
            self.client.restore_configuration()
        self.assertTrue(self.client.configured)
        self.assertEqual(app.store.mapping(1), {'111':'time','222':'light','333':'separator'})


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def response(self, path, state):
        application = make_app(lambda: state)
        request = make_mocked_request('GET', path, app=application)
        info = await application.router.resolve(request)
        return await info.handler(request)

    async def test_liveness_during_discord_startup(self):
        response = await self.response('/health', {'discord_ready':False, 'configured':False})
        self.assertEqual(response.status, 200)
        self.assertFalse(json.loads(response.text)['discord_ready'])

    async def test_readiness_is_honest(self):
        for ready, configured, expected in [(False,False,503),(True,False,503),(True,True,200)]:
            response = await self.response('/ready', {'discord_ready':ready, 'configured':configured})
            self.assertEqual(response.status, expected)

    async def test_wake_page_explains_offline_limit(self):
        response = await self.response('/', {'discord_ready':False,'configured':False})
        self.assertIn('sleeping service cannot receive', response.text)
