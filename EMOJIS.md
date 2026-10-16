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

## Built-in emojis — no files to upload

| Emoji | Meaning |
|---|---|
| ➡️ | Offer / want separator, equivalent to `=>` |
| ❓ | Open to offers, equivalent to the word `offers` |
| ✅ | Seller marks the whole post no longer available; react on the original post or edit it into the post |
| 🔎 | Bot successfully indexed the offer |
| ⚠️ | Bot could not index the offer; correct the item or format |

Do not add ✅ just as decoration: it closes the whole post. Another user's reaction is ignored. The bot may mirror a seller’s close tick with its own ✅ so closure survives cache loss. Remove ✅ from the message and its seller reactions, then run `/renew`; the bot removes its own tick and posts a recoverable renewal receipt.

If you already have custom artwork for the two markers, name it `cl_trade` or `cl_offers` and include it in `/emoji_sync`. No new marker PNGs are required or included: the built-in emojis work immediately.

## Text and emoji examples

```text
:cl_book_time: ➡️ :cl_book_light:
:cl_book_time: :cl_book_time: ➡️ ❓
:cl_book_fire: + Ancient Sap x250 => :cl_book_blood:
Time Spellbook x1 => Light Book x1
```

In Discord, select the uploaded emoji from the picker. The bot also supports literal named shortcodes in posts. Actual pasted custom emojis are identified by their saved Discord ID, not by trusting the displayed name. In this Render version, exact standard names map automatically each time Discord connects. `/emoji_sync apply:true` refreshes the current session immediately after uploads. Custom name overrides must be saved in Render’s `EMOJI_MAP_JSON` to survive sleep.

`/search item:Time` and a pasted mapped Time emoji both resolve to the same item. Discord's autocomplete entries show text names and categories; custom image artwork is not a separate image field in autocomplete choices.

## Other items

All other tradeable materials, keys and accessories work using their catalog names. If you later add artwork, use `cl_item_<item_id>`, for example `cl_item_ancient_sap` or `cl_item_boss_key`, and run `/emoji_sync`. Exact standard filenames restore at reconnect; save custom bindings in Render Environment. These files are not included in the spellbook pack. Long accessory IDs may exceed Discord's name limit; use a shorter server emoji name and `/emoji_bind` for those instead.

Non-tradeable rewards shown in the other screenshots—including Lucky Goggles, Lightning Aura, Fire Aura and Ember Cape—are excluded. No screenshot is taken as permission to change the tradeability catalog.

## Image edits

No artwork changes were necessary for this first pack. The original cropped PNGs are retained at full supplied resolution with their colored backgrounds, and all are below 256 KiB. Discord handles the display scaling. These are screenshot crops, not original transparent asset exports; no transparent-background claim is made.
