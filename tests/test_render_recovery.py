import asyncio
import json
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import make_mocked_request
import discord

import bot as app
from core import Store, InvalidOffer
from market import Card
from recovery import HistoryIndex
from health import make_app


def card_message(mid=100,card=None,author=777):
    card=card or Card(2,'Trader',{'time':1},{'light':1},time.time()-120)
    message=NS(id=mid,guild=NS(id=1,emojis=[]),channel=NS(id=10),author=NS(id=author,bot=True),
               embeds=[card.embed(app.catalog)],webhook_id=None,reactions=[],
               created_at=datetime.fromtimestamp(card.refreshed,timezone.utc),jump_url=f'https://discord.com/channels/1/10/{mid}')
    async def edit(**kwargs):
        message.embeds=[kwargs['embed']]
        return message
    message.edit=AsyncMock(side_effect=edit)
    message.fetch=AsyncMock(return_value=message)
    return message


class CardTests(unittest.TestCase):
    def test_card_round_trip_and_original_age(self):
        card=Card(2,'Trader',{'time':2,'ancient_sap':250},{'light':1},time.time()-3600,roblox='Test_User')
        restored=Card.from_message(card_message(card=card),777,app.catalog)
        self.assertEqual(restored,card)
        self.assertAlmostEqual(restored.expires,card.refreshed+86400)

    def test_other_bot_or_webhook_cannot_forge_card(self):
        source=card_message(author=888)
        with self.assertRaises(InvalidOffer):
            Card.from_message(source,777,app.catalog)
        source.author.id=777
        source.webhook_id=900
        with self.assertRaises(InvalidOffer):
            Card.from_message(source,777,app.catalog)

    def test_missing_or_bad_card_fields_rejected(self):
        source=card_message()
        source.embeds[0].set_author(name='Bad',url='https://example.com/2')
        with self.assertRaises(InvalidOffer):
            Card.from_message(source,777,app.catalog)

    def test_closed_and_locked_states_survive_encoding(self):
        for state in ['closed','locked']:
            original=Card(2,'Trader',{'time':1},{},time.time(),state)
            restored=Card.from_message(card_message(card=original),777,app.catalog)
            self.assertEqual(restored.state,state)
            self.assertFalse(restored.active())

    def test_limits_apply_before_publication(self):
        for card in [Card(2,'T',{'time':10},{},time.time()),Card(2,'T',{'fake':1},{},time.time()),
                     Card(2,'T',{'time':1},{},time.time(),roblox='https://bad')]:
            with self.subTest(card=card),self.assertRaises(InvalidOffer):
                card.embed(app.catalog)

    def test_open_offers_and_emoji_rendering_round_trip(self):
        class Emoji:
            url='https://cdn.discordapp.com/emojis/111.png'
            def __str__(self):
                return '<:cl_book_time:111>'
        original=Card(2,'Trader',{'time':1},{},time.time())
        source=card_message(card=original)
        source.embeds=[original.embed(app.catalog,{'time':Emoji()})]
        self.assertIn('<:cl_book_time:111>',source.embeds[0].fields[0].value)
        self.assertEqual(Card.from_message(source,777,app.catalog),original)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous=app.store
        app.store=Store(':memory:')
        app.store.configure(1,10,True)
        self.client=app.Clover()
        self.client._connection.user=NS(id=777)

    async def asyncTearDown(self):
        await self.client.history_index.close()
        app.store.db.close()
        app.store=self.previous

    async def test_cold_recovery_reads_own_cards_only(self):
        await self.client.recover_message(card_message())
        await self.client.recover_message(card_message(101,author=2))
        self.assertEqual([r['message'] for r in app.store.active(1)],['100'])

    async def test_closed_newest_duplicate_keeps_old_copy_out(self):
        now=time.time()
        await self.client.recover_message(card_message(102,Card(2,'T',{'time':1},{},now-10,'closed')))
        await self.client.recover_message(card_message(101,Card(2,'T',{'time':1},{},now-20)))
        self.assertEqual(app.store.active(1),[])

    async def test_close_and_restart_restore_closed_card(self):
        source=card_message()
        inter=NS(user=NS(id=2),permissions=NS(manage_messages=False),followup=NS(send=AsyncMock()))
        with patch.object(app,'bot',self.client):
            await app.close_card(inter,source)
        self.assertEqual(Card.from_message(source,777,app.catalog).state,'closed')
        app.store.db.close()
        app.store=Store(':memory:')
        app.store.configure(1,10,True)
        await self.client.recover_message(source)
        self.assertEqual(app.store.active(1),[])

    async def test_moderator_lock_blocks_seller_renewal_after_restart(self):
        source=card_message()
        mod=NS(user=NS(id=3),permissions=NS(manage_messages=True),followup=NS(send=AsyncMock()))
        owner=NS(user=NS(id=2),permissions=NS(manage_messages=False),followup=NS(send=AsyncMock()))
        with patch.object(app,'bot',self.client):
            await app.close_card(mod,source)
            with self.assertRaises(InvalidOffer):
                await app.renew_card(owner,source)
        self.assertEqual(Card.from_message(source,777,app.catalog).state,'locked')

    async def test_owner_reaction_closes_card_but_other_reaction_does_not(self):
        source=card_message()
        channel=NS(fetch_message=AsyncMock(return_value=source))
        payload=NS(emoji='✅',guild_id=1,channel_id=10,message_id=100,user_id=3)
        with patch.object(self.client,'get_channel',return_value=channel):
            await self.client.on_raw_reaction_add(payload)
            self.assertEqual(Card.from_message(source,777,app.catalog).state,'active')
            payload.user_id=2
            await self.client.on_raw_reaction_add(payload)
        self.assertEqual(Card.from_message(source,777,app.catalog).state,'closed')

    async def test_recovery_expired_card_is_not_active(self):
        source=card_message(card=Card(2,'T',{'time':1},{},time.time()-90000))
        await self.client.recover_message(source)
        self.assertEqual(app.store.active(1),[])

    async def test_shared_lazy_load_and_member_content_never_processed(self):
        gate=asyncio.Event()
        calls=[]
        async def history(**kwargs):
            calls.append(kwargs)
            await gate.wait()
            yield card_message(101,author=2)
            yield card_message(102)
        recover=AsyncMock()
        index=HistoryIndex(recover,lambda:777)
        channel=NS(id=10,history=history)
        pending,failed=await index.ensure([channel],timeout=.01)
        self.assertTrue(pending)
        await index.ensure([channel],timeout=.01)
        self.assertEqual(len(calls),1)
        gate.set()
        await index.ensure([channel],timeout=1)
        recover.assert_awaited_once()
        self.assertEqual(recover.await_args.args[0].id,102)
        await index.ensure([channel],timeout=1)
        self.assertEqual(len(calls),1)
        await index.close()

    async def test_history_failure_is_not_successful_empty_market(self):
        async def history(**kwargs):
            raise PermissionError('denied')
            yield
        index=HistoryIndex(AsyncMock(),lambda:777)
        pending,failed=await index.ensure([NS(id=10,history=history)],timeout=1)
        self.assertFalse(pending)
        self.assertTrue(failed)
        await index.close()

    async def test_publish_limit_applies_to_renewing_closed_source(self):
        channel=NS(id=10,send=AsyncMock())
        self.client.visible_channels=lambda _: [channel]
        self.client.load_history=AsyncMock(return_value=(False,False))
        for mid,item in [(100,'time'),(101,'blood'),(102,'fire')]:
            app.store.upsert(mid,1,10,2,{item:1},{},now=time.time()-3600)
        inter=NS(guild_id=1,user=NS(id=2,display_name='Trader'),guild=NS(id=1,emojis=[]))
        with self.assertRaisesRegex(InvalidOffer,'3 active'):
            await self.client.publish(inter,{'light':1},{},renew_source=NS(id=99))
        channel.send.assert_not_awaited()

    async def test_publish_is_idempotent_under_double_click(self):
        published=card_message(999)
        channel=NS(id=10,send=AsyncMock(return_value=published))
        self.client.visible_channels=lambda _: [channel]
        self.client.load_history=AsyncMock(return_value=(False,False))
        inter=NS(guild_id=1,user=NS(id=2,display_name='Trader'),guild=NS(id=1,emojis=[]))
        results=await asyncio.gather(self.client.publish(inter,{'time':1},{'light':1}),self.client.publish(inter,{'time':1},{'light':1}),return_exceptions=True)
        channel.send.assert_awaited_once()
        self.assertEqual(sum(isinstance(r,InvalidOffer) for r in results),1)

    async def test_renewed_card_survives_cold_restart_without_receipts(self):
        old=card_message(100,Card(2,'Trader',{'time':1},{'light':1},time.time()-4000))
        self.client.read(old)
        new=card_message(999)
        async def send(**kwargs):
            new.embeds=[kwargs['embed']]
            return new
        channel=NS(id=10,send=AsyncMock(side_effect=send))
        self.client.visible_channels=lambda _: [channel]
        self.client.load_history=AsyncMock(return_value=(False,False))
        inter=NS(guild_id=1,guild=NS(id=1,emojis=[]),user=NS(id=2,display_name='Trader'),permissions=NS(manage_messages=False),followup=NS(send=AsyncMock()))
        with patch.object(app,'bot',self.client):
            await app.renew_card(inter,old)
        self.assertEqual(Card.from_message(old,777,app.catalog).state,'closed')
        self.assertTrue(Card.from_message(new,777,app.catalog).active())
        app.store.db.close()
        app.store=Store(':memory:')
        app.store.configure(1,10,True)
        await self.client.recover_message(new)
        await self.client.recover_message(old)
        self.assertEqual([r['message'] for r in app.store.active(1)],['999'])

    async def test_owner_edit_preserves_expiry_and_card_remains_recoverable(self):
        original=Card(2,'Trader',{'time':1},{'light':1},time.time()-3600)
        source=card_message(card=original)
        edited=replace(original,offered={'blood':2})
        await self.client.save(source,edited)
        restored=Card.from_message(source,777,app.catalog)
        self.assertEqual(restored.refreshed,original.refreshed)
        self.assertEqual(restored.offered,{'blood':2})
        self.assertEqual(app.store.active(1,item='time'),[])
        self.assertEqual(len(app.store.active(1,item='blood')),1)


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def response(self,path,state):
        application=make_app(lambda:state)
        request=make_mocked_request('GET',path,app=application)
        resolved=await application.router.resolve(request)
        return await resolved.handler(request)

    async def test_liveness_and_readiness(self):
        self.assertEqual((await self.response('/health',{'discord_ready':False,'configured':False})).status,200)
        self.assertEqual((await self.response('/ready',{'discord_ready':False,'configured':False})).status,503)
        self.assertEqual((await self.response('/ready',{'discord_ready':True,'configured':True})).status,200)


if __name__=='__main__':
    unittest.main()
