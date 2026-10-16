# Launch Clover Trading Desk on Render

This version uses **Discord interactions and bot-authored trade cards**, so it does not require Message Content approval. It does not request Server Members or Presence access either.


## Testing now: one channel for the desk and offers

The default testing destination is **1550152526333092030**. On startup the bot searches its own messages in that channel and reuses the Trading Desk, or posts one if missing. Each offer is sent there as a text summary plus an embed card with Trade / DM and Manage offer buttons.

Deploy the latest commit; no extra setting is required for this default. For clarity you may set `TEST_CHANNEL_ID=1550152526333092030` in Render. This setting overrides `TRADING_CHANNEL_IDS` while active. Both `/setup` and `/panel` refuse other destinations during testing.

Give the bot View Channel, Read Message History, Send Messages and Embed Links in the test channel. The channel must belong to the configured `GUILD_ID` server. If setup is invalid, `/ready` reports not configured and logs explain the missing access.

When finished, set `TEST_CHANNEL_ID=off` and use your intended `TRADING_CHANNEL_IDS`. The manual `/panel` announcement flow below applies when testing mode is off.

## Upgrade your existing Render service

1. Deploy the latest commit on the GitHub repository's `main` branch.
2. Keep the start command `python bot.py`, build command `pip install -r requirements.txt`, health path `/health`, and Free plan.
3. Keep your private `DISCORD_TOKEN` directly in Render. Keep the existing `GUILD_ID` and `TRADING_CHANNEL_IDS`.
4. Set `SYNC_COMMANDS=1` for this deployment. It registers the new `/offer` and `/panel` commands and updates the old ones. After you see the registration/ready log, set it to `0` and redeploy.
5. In Discord Developer Portal, leave all three privileged intent switches OFF. This build never requests those intents. Leave Interactions Endpoint URL blank; do not put the health URL there.
6. Open your Render service URL and `/ready`. Both `discord_ready` and `configured` should be true.
7. In Discord, run `/status`. It should say **Trading Desk • no privileged intents** and show your configured trading channel and mapped spellbook count.
8. Run `/panel`, selecting the **trading announcement channel**, then pin the posted Trading Desk.
9. Click Create trade or use `/offer`, finish the private builder and publish your first card.

The announcement channel is for the entry panel. The `TRADING_CHANNEL_IDS` variable should contain channels where published trade cards should appear. Do not add the announcement channel unless it should also receive offers.

## Environment variables

```dotenv
DISCORD_TOKEN=YOUR_PRIVATE_TOKEN_ENTERED_ONLY_IN_RENDER
GUILD_ID=YOUR_DISCORD_SERVER_ID
TRADING_CHANNEL_IDS=YOUR_TRADING_CHANNEL_ID
TEST_CHANNEL_ID=1550152526333092030
DATABASE_PATH=:memory:
SYNC_COMMANDS=1
EMOJI_MAP_JSON={}
PYTHON_VERSION=3.14.5
```

For multiple trading channels, use comma-separated IDs. The publish destination is the first configured trading channel the member can view/read. Exact `cl_book_...` emoji names are mapped at every connection. Custom bindings require an `EMOJI_MAP_JSON` override saved in Render.

Use Developer Mode in Discord to copy IDs. The Application ID/Public Key are not bot tokens or server IDs. No extra database, disk, webhook, HTTP-interactions endpoint, Roblox login or Studio access is needed.

## Permissions

Install the app with `bot` and `applications.commands` scopes. Give the bot **View Channel, Read Message History, Send Messages and Embed Links** in the trading channels. Give it View Channel, Send Messages and Embed Links in the announcement channel where you post the panel. It doesn't need Administrator or access to member DMs.

Members with Manage Server can run `/panel` and configuration commands. Members with Manage Messages can close someone else's card; the card becomes moderator-locked. Ordinary sellers cannot renew moderator-locked cards.

## What members see

### Trading Desk

A permanent announcement message with four buttons:

- **Create trade**: opens a private builder.
- **Find sellers**: opens an item-search form and matching-item menu.
- **My offers**: private active-card list.
- **Rules**: private game restrictions and guidelines.

### Private builder

- Two spellbook menus, **I offer** and **I want**, each with all 16 books and available server emojis.
- **Edit items / quantities** form for text or mapped emojis. Examples: `Time x2 + Ancient Sap x250`; requested items `Light x1`. Blank requested items means open to offers.
- Optional Roblox username (3–20 letters, numbers or underscores).
- A private preview and requirement confirmation. Changing items resets the confirmation.
- **Publish offer**, or Save changes when editing an existing card.

Only after Publish/Save does the public board change. The draft lasts 15 minutes and is lost on restart; run `/offer` again if it expires. It is an ephemeral interaction, not a new Discord channel.

### Public trade card

The card shows the trader, offered/wanted items with quantities and spellbook emojis, optional Roblox username, open/closed status and expiry.

- **Trade / DM**: private response with the trader's profile and copyable DM text. The user opens the profile and chooses Message. The bot doesn't send the DM and can't override disabled DMs/blocks.
- **Manage offer**: owner-only Edit, Renew and Close controls. Moderators can close other members' offers but cannot edit/renew them.
- Author reacting ✅ closes the whole card. Other users' ✅ reactions are ignored.

Closed cards remain visible with closed status; search excludes them. The Contact button refuses closed/expired cards. A tick is not evidence of a completed trade.

## Commands

| Command | Purpose |
|---|---|
| `/offer` | Open the private builder |
| `/search item:` | Autocomplete by name/alias/mapped emoji and privately find sellers |
| `/myoffers` | Active card links; use Manage offer on a card |
| `/close message:` | Close an owned card by link/ID; moderators may close others |
| `/renew message:` | Create a fresh 24-hour card and close the original |
| `/items filter:` | Browse the catalog by name/category |
| `/help`, `/rules` | Member instructions and restrictions |
| `/panel channel:` | Manage Server: post the persistent Trading Desk |
| `/setup channel: enabled:` | Manage Server: change session channels; save the resulting IDs in Render |
| `/emoji_sync apply:` | Manage Server: preview/refresh standard name mappings |
| `/emoji_bind emoji: item:` | Manage Server: map a custom emoji; save the shown override in Render |
| `/status` | Manage Server: mode, channels, mapped books and scan state |

## Limits and recovery

- Maximum **3 active offers per trader**, including renewals of previously closed cards.
- Minimum **60 seconds between publications**. Active offers can be renewed after **30 minutes**. Closed/expired offers can be renewed subject to the publishing cooldown/active limit.
- Identical active offers are rejected; manage the existing card instead.
- Edits update the same card and preserve its original expiry. To extend expiry, renew.
- Renewals post a fresh card and close the old one. Old card links remain useful for history but are not active search results.
- The bot keeps a temporary in-memory SQLite index. Its own readable cards are the recoverable source of truth. Do not delete a card if you want to retain its listing/history.
- After restart, the first search/publish lazily scans bot-authored cards from the last **24 hours**, newest first, with no arbitrary message-count cap. Ordinary member messages are ignored. Older original cards aren't needed for renewed offers, because renewal creates a new card.
- Concurrent requests share one history scan per channel. While loading, results are labelled partial. Publishing waits briefly for a complete board scan to enforce the active limit; if loading continues, the draft stays available and the user can retry.
- Successful scans are reused for two minutes. Searches check up to the 25 newest matching candidates against their current original cards and show five per page. Warm cached rows are checked for edits, deletion and owner ticks.
- Public panel/card buttons are registered as persistent views at startup. Private drafts/search/manage views must be reopened after a restart.

The previous automatic indexing of member-written offers and old renewal-receipt format is discontinued. Those posts are not imported without Message Content approval. Members should create new cards through `/offer`.

## Render health and sleep

The same process runs HTTP and the Discord client, binding to `0.0.0.0:$PORT` (default 10000).

- `/health` returns 200 when the web process is alive, with non-secret connection/configuration/cache status.
- `/ready` returns 200 only when Discord is connected and configuration is valid; otherwise 503.
- `/` explains how to wake the service and use the Trading Desk.

Use `/health` for Render's health check. A sleeping Gateway bot cannot receive `/offer`, `/search` or button interactions to wake itself. First visit the service website, wait for `/ready`, then retry. This is not a 24/7 uptime guarantee or an external keep-alive service.

## Live launch checklist

1. Confirm Render logs show Ready as … and no PrivilegedIntentsRequired exception.
2. `/status` shows the intended trading channel and 16/16 books when correctly named/uploaded.
3. Post the panel with `/panel` in announcements; verify members can click Create trade.
4. Select Time and Light, confirm requirements and publish. Verify only one public card is created even if Publish is clicked twice.
5. Add `Ancient Sap x250` through Edit items; check quantities and original expiry.
6. Search Time: the card appears. Search Light: it does not appear as a Light seller.
7. Trade / DM as another member: the profile/DM draft is private; no automatic DM is sent.
8. React ✅ as a different member: no closure. React as the owner: the card closes and disappears from search.
9. Try editing or renewing someone else's card: denied. Try a moderator close: permitted, then seller renewal denied.
10. Restart Render. Old panel/card buttons still work. Search reconstructs open cards and keeps closed cards closed.
11. Verify 3-offer limit and cooldowns. For a large channel, confirm loading notices appear instead of false empty results.

This is a marketplace index, not game inventory/level verification. The game enforces eligibility, bag space and final acceptance. No item transfer, payment, trade-count awards, AI message reading, or game-shop stock feed is implemented.

Sources: [Discord own-message exception](https://docs.discord.com/developers/events/gateway#message-content-intent), [Render Free sleep](https://render.com/docs/free).
