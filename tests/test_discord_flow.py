"""Interaction-marketplace contracts, including zero privileged intents."""
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

os.environ['DATABASE_PATH']=':memory:'
import bot as app
from core import Store, InvalidOffer


class FlowTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_no_privileged_intents(self):
        self.assertFalse(self.client.intents.message_content)
        self.assertFalse(self.client.intents.members)
        self.assertFalse(self.client.intents.presences)
        self.assertTrue(self.client.intents.guilds)

    async def test_persistent_button_routes(self):
        desk,card=app.DeskView(),app.CardView()
        self.assertTrue(desk.is_persistent())
        self.assertTrue(card.is_persistent())
        ids=[i.custom_id for i in desk.children+card.children]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(i.startswith('clover:') for i in ids))

    async def test_builder_contains_real_spellbook_choices(self):
        guild=NS(id=1,emojis=[])
        draft=app.DraftView(2,guild)
        menus=[c for c in draft.children if isinstance(c,app.BookSelect)]
        self.assertEqual(len(menus),2)
        self.assertEqual(len(menus[0].options),16)
        self.assertEqual(menus[0].max_values,9)
        self.assertTrue(draft.publish_button.disabled)
        draft.offered={'time':1}
        draft.confirmed=True
        await draft.redraw()
        self.assertFalse(draft.publish_button.disabled)

    async def test_non_owner_cannot_use_another_draft(self):
        draft=app.DraftView(2,NS(id=1,emojis=[]))
        inter=NS(user=NS(id=3),response=NS(send_message=AsyncMock()))
        self.assertFalse(await draft.interaction_check(inter))
        inter.response.send_message.assert_awaited_once()

    async def test_text_form_updates_private_draft_and_resets_confirmation(self):
        draft=app.DraftView(2,NS(id=1,emojis=[]))
        draft.confirmed=True
        draft.message=NS(edit=AsyncMock())
        modal=app.BasketModal(draft)
        modal.offering._value='Time x2 + Ancient Sap x250'
        modal.wanting._value='Light x1'
        modal.username._value='Trader_One'
        inter=NS(guild_id=1,user=NS(id=2,display_name='Trader'),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await modal.on_submit(inter)
        self.assertEqual(draft.offered,{'time':2,'ancient_sap':250})
        self.assertEqual(draft.wanted,{'light':1})
        self.assertFalse(draft.confirmed)
        self.assertTrue(draft.publish_button.disabled)
        draft.message.edit.assert_awaited_once()

    async def test_requirements_gate_prevents_publishing(self):
        draft=app.DraftView(2,NS(id=1,emojis=[]),{'time':1},{})
        inter=NS(user=NS(id=2),response=NS(defer=AsyncMock()))
        with self.assertRaises(InvalidOffer):
            await draft.publish_button.callback(inter)
        inter.response.defer.assert_not_awaited()

    async def test_book_selection_preserves_materials_and_visible_defaults(self):
        draft=app.DraftView(2,NS(id=1,emojis=[]),{'time':2,'ancient_sap':250},{})
        draft.confirmed=True
        select=next(c for c in draft.children if isinstance(c,app.BookSelect) and c.side=='offered')
        select._values=['light']
        inter=NS(response=NS(edit_message=AsyncMock()))
        await select.callback(inter)
        self.assertEqual(draft.offered,{'ancient_sap':250,'light':1})
        current=next(c for c in draft.children if isinstance(c,app.BookSelect) and c.side=='offered')
        self.assertEqual([o.value for o in current.options if o.default],['light'])
        self.assertFalse(draft.confirmed)

    async def test_only_owner_edits_moderator_may_close(self):
        card=NS(seller=2)
        other=NS(user=NS(id=3),permissions=NS(manage_messages=False))
        with self.assertRaises(InvalidOffer):
            app.require_owner(other,card)
        other.permissions.manage_messages=True
        with self.assertRaises(InvalidOffer):
            app.require_owner(other,card)
        app.require_owner(other,card,moderator=True)
        view=app.ManageView(100,10,3,editable=False)
        self.assertTrue(view.edit.disabled)
        self.assertTrue(view.renew.disabled)
        self.assertFalse(view.close_offer.disabled)

    async def test_commands_include_builder_and_autocomplete(self):
        data={c.name:c.to_dict(app.tree) for c in app.tree.get_commands()}
        self.assertIn('offer',data)
        self.assertIn('panel',data)
        self.assertTrue(data['search']['options'][0]['autocomplete'])
        self.assertLessEqual(len(app.HELP),2000)

    async def test_boot_accepts_permissions_without_privileged_access(self):
        channel=Mock(spec=app.discord.TextChannel)
        channel.permissions_for.return_value=NS(view_channel=True,read_message_history=True,send_messages=True,embed_links=True)
        guild=NS(id=1,me=NS(id=777),get_channel=lambda x:channel if x==10 else None,
                 emojis=[NS(id=111,name='cl_book_time')])
        with patch.dict(os.environ,{'GUILD_ID':'1','TRADING_CHANNEL_IDS':'10','EMOJI_MAP_JSON':'{}'}),patch.object(self.client,'get_guild',return_value=guild):
            self.client.restore_configuration()
        self.assertTrue(self.client.configured)
        self.assertEqual(app.store.mapping(1),{'111':'time'})

    async def test_loading_search_does_not_claim_empty_market(self):
        inter=NS(guild_id=1,response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        self.client.load_history=AsyncMock(return_value=(True,False))
        self.client.visible_channels=lambda i:[]
        with patch.object(app,'bot',self.client):
            await app.show_results(inter,item='time')
        inter.response.defer.assert_awaited_once()
        self.assertIn('still loading',inter.followup.send.await_args.args[0])


if __name__=='__main__':
    unittest.main()
