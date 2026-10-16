# Clover Trading Desk

A Discord trading marketplace for Clover Legends. **No Message Content, Member or Presence privileged intents are requested.** Members create offers through buttons, dropdowns and forms; the bot publishes searchable trading cards.


## Current testing channel

This build defaults to testing mode in channel **1550152526333092030**. When connected, it automatically posts or reuses one Trading Desk there. Published offers include a plain-text summary, an embed card and Trade / DM controls in that same channel. Existing production channel settings are ignored while testing mode is active.

No new environment variable is needed for this test deployment. To make it explicit, set `TEST_CHANNEL_ID=1550152526333092030`. When testing is finished, set `TEST_CHANNEL_ID=off`; the bot will use `TRADING_CHANNEL_IDS` again.

## Member flow

1. Click **Create trade** on the Trading Desk, or use `/offer`.
2. Privately choose spellbooks with the 16 uploaded emojis. Use **Edit items / quantities** for materials, accessories, quantities and an optional Roblox username.
3. Review the preview, confirm the level/bag requirements and **Publish offer**.
4. Buyers click **Trade / DM** for the trader's profile and a ready-to-copy DM message. No unsolicited DM is sent and Discord privacy settings still apply.
5. The owner uses **Manage offer** to edit, close or renew. An owner ✅ reaction also closes the card. Negotiations are in DMs; exchanges happen inside Clover Legends.

No new ticket/private channel is created per trade. Ordinary member-authored messages are not read or automatically indexed.

## Render deployment

See **[START_HERE.md](START_HERE.md)** for the migration steps, environment variables and live checklist.

| Setting | Value |
|---|---|
| Service | Web Service · Python · Free |
| Build | `pip install -r requirements.txt` |
| Start | `python bot.py` |
| Health check | `/health` |

Keep your existing token, server and trading channel settings. Set `SYNC_COMMANDS=1` for the first deployment of this version to register `/offer` and `/panel`, then set it back to `0`. All privileged intent switches can remain off. Leave Interactions Endpoint URL blank.

After deployment, run `/panel` and select the trading announcement channel. Pin the resulting Trading Desk message. Publish cards go into the first configured trading channel the member can access, not the panel/announcement channel.

## Commands

`/offer` · `/search` (autocomplete) · `/myoffers` · `/close` · `/renew` · `/items` · `/help` · `/rules`

Moderators: `/panel` · `/setup` · `/emoji_sync` · `/emoji_bind` · `/status`

## Recovery and limits

Cards published by this bot contain their seller, items, quantities, status and expiry in readable embeds. Discord explicitly permits apps to read their own messages without Message Content Intent. After a Render restart, lazy loading rebuilds the temporary index from these bot-authored cards in the last 24 hours. Closed and moderator-locked statuses are recovered from the cards. Renewing creates a fresh card and closes the old one, so renewals stay discoverable in the recovery window.

Main panel/card buttons are persistent across restarts. Private drafts and private management/search sessions are temporary; reopen them if the bot restarts. The maximum is 3 active offers per trader, with a 60-second publication cooldown and a 30-minute minimum before renewing an active offer.

Render Free may sleep. Visit its website and wait for `/ready` before using commands if the bot is offline; Discord Gateway commands cannot wake the sleeping process. No uninterrupted uptime guarantee is made.

## Resources

- [Setup and migration](START_HERE.md)
- [Design](DESIGN.md)
- [Emoji upload names](EMOJIS.md) and [16 PNGs](emojis/ready/)
- [Verification](VERIFICATION.md)
- [Discord's own-message exception](https://docs.discord.com/developers/events/gateway#message-content-intent)

## Tests

Use Python 3.11+ and install `requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
```

Configure secrets in Render or a private `.env`; never commit the token. The catalog contains the user-supplied 76 allowed items. The game enforces player level, actual bag inventory and final trade acceptance. The bot does not handle game items, payments, automated DMs, or verified trade counts.
