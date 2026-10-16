# Clover Trading — Render Free deployment

This version runs as a Render **Web Service** with a health endpoint and a temporary in-memory search index. Discord channel history is the source of truth. No external database or persistent disk is required.

## What sleep means

Render Free can sleep after 15 minutes without inbound traffic. Opening its web URL wakes it; Render says waking can take about a minute. This bot connects outward to Discord's Gateway. A Discord slash command or a new trading post does not make an inbound request to Render, so neither can wake a sleeping bot.

Bookmark the service URL. Open it, check `/ready`, then return to Discord once `discord_ready` and `configured` are true. If a command was attempted while asleep, retry it after waking. The health endpoint is not an uptime guarantee or an automatic keep-alive service.

## 1. Upload the files to a GitHub repository

Extract the ZIP. Create a private GitHub repository and upload the **contents** of `clover-trading-bot/` to the repository root. The root should contain `bot.py`, `core.py`, `recovery.py`, `health.py`, `catalog.json`, `requirements.txt`, and `render.yaml`.

Do not upload a `.env` file or your Discord token. The supplied ZIP contains neither. Render deploys from a Git repository; it does not execute an uploaded ZIP directly.

## 2. Configure Discord

In your existing application's Developer Portal:

- **Bot → Privileged Gateway Intents:** enable **Message Content Intent**. Leave Member and Presence intents off.
- Keep **Interactions Endpoint URL blank**: this is a Gateway bot, not an HTTP-interactions bot. Do not put `/health` there.
- Invite with scopes `bot` and `applications.commands`.
- Grant View Channel, Read Message History, Send Messages, Add Reactions, and Embed Links in every configured trading channel. Do not grant Administrator.
- Copy the private **Bot Token** into Render's secret settings in the next step. Public Key and Application ID are not bot tokens.

## 3. Create the Render service

Open Render → **New → Web Service**, connect the repository, and use:

| Setting | Value |
|---|---|
| Runtime | Python |
| Plan | Free |
| Root directory | Leave blank when `bot.py` is at repository root |
| Build command | `pip install -r requirements.txt` |
| Start command | `python bot.py` |
| Health check path | `/health` |

Alternatively create a Render Blueprint from the included `render.yaml`. Check that the plan is Free before deploying.

Add these Render **Environment** values:

| Variable | Value |
|---|---|
| `DISCORD_TOKEN` | Your private bot token; enter only in Render |
| `GUILD_ID` | Your Discord server ID, not the Application ID |
| `TRADING_CHANNEL_IDS` | Trading channel IDs, separated by commas |
| `DATABASE_PATH` | `:memory:` |
| `SYNC_COMMANDS` | `1` for first deployment |
| `EMOJI_MAP_JSON` | `{}` unless you use custom emoji-name overrides |
| `PYTHON_VERSION` | `3.14.5` |

For example, `TRADING_CHANNEL_IDS=123456789012345678,234567890123456789`. Those are examples: replace them with your actual channel IDs. Enable Discord Developer Mode to copy server/channel IDs.

The bot binds to `0.0.0.0` and Render's `PORT` automatically (default 10000). Do not set up a separate Flask/Gunicorn process or multiple workers: one process runs the web listener and Discord client together.

## 4. Deploy and inspect readiness

Deploy, then open the service's `https://...onrender.com/` URL.

- `/health`: HTTP 200 when the web process is alive. JSON reports Discord readiness, configuration readiness, temporary cache mode, loading status and history error count. It exposes no token, server IDs, seller IDs or trade contents.
- `/ready`: HTTP 200 only when Discord is connected and startup configuration is valid; otherwise 503.
- `/`: human-readable wake instructions.

Configure Render's health check as `/health`, not `/ready`, so a slower Discord connection does not cause a restart loop. Invalid credentials make the process fail instead of silently leaving a disconnected web-only service running.

After the first successful command registration, change `SYNC_COMMANDS` to `0` in Render and redeploy. Change it back to `1` only when shipping changed slash-command definitions, then return it to `0`. Autocomplete remains available without resyncing on every wake.

## 5. Check emojis and offers

The 16 standard spellbook names (`cl_book_fire`, `cl_book_time`, etc.) map automatically from the server's emojis every time the bot connects. No repeated mapping step is necessary for those names. `/emoji_sync` previews matches; `/status` should show 16/16 books if all files were named correctly.

Test:

1. Post `Time => Light` in a configured trading channel; expect 🔎.
2. `/search item:Time`: choose Time from autocomplete; expect a private result linking to that post.
3. `/search item:Light`: the same post should not appear as a Light seller.
4. Another member's ✅ must not close the listing.
5. The author's ✅ must close it. The bot may also add its own ✅ to retain closed state.
6. Remove the author's ✅, then `/renew message:<original message ID or link>` to reopen. The bot removes its own close tick and posts a short renewal receipt in Discord.
7. React ✅ or use `/close` and restart/redeploy. The offer must stay absent after history reloads.
8. Restart with a valid open offer still present. Search should recover it with its original expiry, not grant it a fresh 24 hours.

## Lazy loading

While online, new posts, edits, deletions and seller ticks update the temporary index. First search after waking starts a shared background scan of all messages in the **last 24 hours**, only in configured channels the requester can read. There is no arbitrary message-count cap. Renewals within that window can restore their older original post by ID.

The command acknowledges immediately once the bot is connected. It waits briefly for the shared scan, then returns results already found, clearly labelled partial if loading continues. If nothing has loaded yet, it says to try again shortly; it does not claim no sellers exist. Slow history loading continues in the background, and simultaneous searches share the work. Warm history checks are reused for two minutes. Displayed results are still checked against their originals; up to 25 newest candidates are checked per search, five per result page.

A very busy channel may take longer to scan because Discord paginates/rate-limits history. Cold starts cannot promise an instant final result. Missing permissions are reported as incomplete history, not an empty market. Use `/status` and Render logs to diagnose errors.

## Recoverable state

- Ordinary post creation time sets 24-hour expiry; edits do not extend it.
- Actual seller ✅ reactions, ✅ in post text, bot-owned ✅ from `/close`, and bot-owned 🔒 from moderator closures keep closed listings out after a reset.
- `/renew` writes a small bot-authored reply with a renewal marker and timestamp. Recovery trusts records from this bot's account only. Do not delete renewal receipts while the offer is active.
- Removing the seller's tick alone does not reopen a post if the bot's close tick remains. `/renew` handles removing the bot tick. Moderator lock reactions block seller renewal.
- An identical repost from the same seller supersedes older copies during both live indexing and newest-first recovery.
- Deleting original posts removes them from future searches.

This depends on the messages, reactions and receipts still existing in Discord. Manually removing those source records can change what can be recovered; there is no separate database backup in this version. Don't delete receipts or the bot's status reactions to clean up active listings.

## Configuration across restarts

Save channel IDs in **Render Environment**. `/setup` changes only the current session and tells you the updated `TRADING_CHANNEL_IDS` value to save in Render.

Standard emoji filenames restore automatically. `/emoji_bind` creates a session override and shows JSON to save in **Render's `EMOJI_MAP_JSON`**. Custom bindings that exist only in RAM will be lost on sleep. Example override: `{"123456789012345678":"time"}`. Allowed targets are catalog item IDs, `separator`, or `offers`.

## Scope and validation

The catalog contains the supplied 76 tradeable items; 16 spellbooks have PNG artwork and the rest support text. No unrestricted AI interpretation, player inventory verification, trade-count awards, historic valuations or game-shop stock feed is claimed. The game enforces player level, bag capacity and final trade acceptance. Material stack maxima were not supplied, so the parser uses one slot per material type and does not invent stack limits.

The offline suite and local health HTTP smoke check are included in the validation notes. Live Discord/Render tests still require your token and actual server/channel settings. Run locally with Python 3.11+ and `python -m unittest discover -s tests -v` to repeat offline checks.

Sources: [Render Free sleep and ephemeral storage](https://render.com/docs/free), [Render Web Services and port binding](https://render.com/docs/web-services), [Discord application commands](https://docs.discord.com/developers/interactions/application-commands).
