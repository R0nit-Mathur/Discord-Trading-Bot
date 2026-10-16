# Discord Trading Bot

A Clover Legends Discord trading bot with text/emoji offer parsing, item autocomplete, private seller search results, seller-only closing reactions, and Render Free deployment support.

## Deploy on Render

Read **[START_HERE.md](START_HERE.md)** for the complete setup and live-server checklist.

| Render setting | Value |
|---|---|
| Service | Web Service · Python · Free |
| Build command | `pip install -r requirements.txt` |
| Start command | `python bot.py` |
| Health check | `/health` |

The included `render.yaml` can also be used as a Render Blueprint. Configure the private `DISCORD_TOKEN`, server `GUILD_ID`, and comma-separated `TRADING_CHANNEL_IDS` in Render Environment. Never commit your bot token or `.env` file. Enable Message Content Intent in the Discord Developer Portal and leave Interactions Endpoint URL blank.

Use `DATABASE_PATH=:memory:`. The runtime index is temporary; the bot reconstructs active offers from the last 24 hours of configured Discord channels. Named spellbook emoji mappings restore automatically. Save custom mapping overrides in `EMOJI_MAP_JSON`.

Register commands on first deployment using `SYNC_COMMANDS=1`, then set it to `0` for normal starts. The Render guide explains each variable.

**Sleep limitation:** a Discord Gateway command cannot wake a sleeping Render service. Visit the service website, wait for `/ready` to succeed, then retry the command. Render Free does not guarantee uninterrupted uptime.

## Main commands

- `/search`: autocomplete by item name or mapped emoji and find current sellers.
- `/myoffers`: see your active listings.
- `/close`: close your listing; moderators can close other listings.
- `/renew`: refresh/reopen a listing with a recoverable Discord receipt.
- `/items`, `/help`, `/rules`: catalog and guidance.
- `/setup`, `/emoji_sync`, `/emoji_bind`, `/status`: moderator configuration.

Post `Time => Light`, `250 Ancient Sap + Fire => offers`, or mapped item emojis in a configured trading channel. The author's ✅ reaction closes the whole listing. Negotiate in DMs and trade in-game.

## Included resources

- [Emoji names and upload guide](EMOJIS.md), [16 spellbook images](emojis/ready/), and [HTML preview](emojis/preview.html).
- [Trading design and recovery model](DESIGN.md).
- [Verification and remaining live checks](VERIFICATION.md).
- The user-supplied 76-item tradeability catalog in `catalog.json`.

## Local development

Use Python 3.11 or newer. Install `requirements.txt`, copy `.env.example` to `.env`, and configure the values privately. Run `python bot.py`. The HTTP listener uses `PORT` (default 10000).

Run offline tests from the repository root:

```sh
python -m unittest discover -s tests -v
```

The current build passed 44 offline tests and a local HTTP smoke check. Deployment on Render and real Discord permissions/interactions still require the live-server checklist. Listings are member claims, not verified game inventory; closing an offer does not award a trade count.
