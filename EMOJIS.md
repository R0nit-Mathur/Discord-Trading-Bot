# Emoji upload guide

Upload only the 16 PNGs in `emojis/ready/`. Name them exactly as below, without `.png`. Lowercase names use `cl_` for Clover Legends, `book_` for spellbooks, and underscores between words. The same names are used by the bot's mapping command.

| Spellbook | Discord emoji name | File |
|---|---|---|
| Fire | `cl_book_fire` | `cl_book_fire.png` |
| Water | `cl_book_water` | `cl_book_water.png` |
| Wind | `cl_book_wind` | `cl_book_wind.png` |
| Chain | `cl_book_chain` | `cl_book_chain.png` |
| Earth | `cl_book_earth` | `cl_book_earth.png` |
| Lightning | `cl_book_lightning` | `cl_book_lightning.png` |
| Mercury | `cl_book_mercury` | `cl_book_mercury.png` |
| Plant | `cl_book_plant` | `cl_book_plant.png` |
| Poison | `cl_book_poison` | `cl_book_poison.png` |
| Blood | `cl_book_blood` | `cl_book_blood.png` |
| Dark | `cl_book_dark` | `cl_book_dark.png` |
| Elder Tree | `cl_book_elder_tree` | `cl_book_elder_tree.png` |
| Null Magic | `cl_book_null_magic` | `cl_book_null_magic.png` |
| Light | `cl_book_light` | `cl_book_light.png` |
| Star | `cl_book_star` | `cl_book_star.png` |
| Time | `cl_book_time` | `cl_book_time.png` |

`emojis/preview.html` shows the complete set. `emojis/manifest.json` records original screenshot filenames, dimensions and file sizes. Chain and Poison were explicitly confirmed by the user. The other books match the supplied artwork; moderators should review the preview before uploading.

## Using the emojis in Trading Desk

The 16 spellbook menus show the uploaded emoji beside each book's name. Cards render the same mapped emoji beside readable item names and quantities. Names remain visible so offers stay understandable if an emoji is missing.

Standard filenames map automatically each time the bot connects. `/emoji_sync apply:true` refreshes the session after uploads. `/emoji_bind` supports differently named existing server emojis; save those overrides in Render's `EMOJI_MAP_JSON` to survive sleep.

Text fields in the private Edit items form accept names, named shortcodes or mapped custom emojis. Examples for Items I offer: `Time x2 + Ancient Sap x250`, or `:cl_book_time: x2`. Items I want can be `Light x1`; blank means open to offers. These examples go into the builder, not ordinary channel messages.

## Built-in controls — no uploads needed

- ✨ Create offer opens a private builder.
- 🔎 Find sellers opens item search.
- 📋 My offers lists your active cards.
- 💬 Contact trader shows the seller's profile and a copyable DM message.
- ⚙️ Manage offer opens owner controls.
- ✅ An owner's reaction on their bot-published card closes it. A non-owner's tick is ignored. The bot saves closed status in the card; removing a tick does not reopen it. Renew explicitly for a fresh card.
- 🔄 Renew publishes a new 24-hour card and closes the old one.

No custom arrow/offers artwork is required; the builder separates offered/wanted fields and provides an Open to offers button. Ordinary member messages are not indexed in this version.

## Other items

All other tradeable materials, keys and accessories work using their catalog names. If you later add artwork, use `cl_item_<item_id>`, for example `cl_item_ancient_sap` or `cl_item_boss_key`, and run `/emoji_sync`. Exact standard filenames restore at reconnect; save custom bindings in Render Environment. These files are not included in the spellbook pack. Long accessory IDs may exceed Discord's name limit; use a shorter server emoji name and `/emoji_bind` for those instead.

Non-tradeable rewards shown in the other screenshots—including Lucky Goggles, Lightning Aura, Fire Aura and Ember Cape—are excluded. No screenshot is taken as permission to change the tradeability catalog.

## Image edits

No artwork changes were necessary for this first pack. The original cropped PNGs are retained at full supplied resolution with their colored backgrounds, and all are below 256 KiB. Discord handles the display scaling. These are screenshot crops, not original transparent asset exports; no transparent-background claim is made.
