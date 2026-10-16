# Trading Desk verification

The interaction-marketplace build passed **48 offline tests** on Python 3.14.5 / discord.py 2.6.4.

The tests cover:

- Test-channel override replaces old publish destinations.
- Startup entry panel publishes text, embed and Create trade controls, then reuses an existing panel on reconnect.
- Published offers contain both a plain-text offered/wanted summary and an embed with Trade / DM controls.

- No Message Content, Member or Presence privileged intents requested.
- Persistent public panel/card button IDs; private builder ownership and requirement-confirmation gate.
- All 16 spellbook dropdown choices, text/quantity forms, emoji rendering, and catalog/slot restrictions.
- Private draft changes reset confirmation, and unconfirmed drafts cannot publish.
- Public card encode/decode, stable timestamps, owner identity, rejection of other bots/webhooks and malformed cards.
- Search autocomplete, offered versus wanted items, and loading notices that do not claim an empty market.
- Owner-only edits/renewals, moderator-only closure of others' cards, and moderator locks after restart.
- Owner versus non-owner ✅ reactions.
- Close → fresh cache → recovery preserving closed state.
- Renew → fresh card + closed old card → fresh cache → recovery preserving only the new active listing.
- Edits preserve expiry and remain recoverable.
- Three-active-offer limit including renewals of closed cards, and simultaneous Publish clicks producing only one send.
- Recovery processes only this bot's cards, shared scan tasks, warm scan reuse and honest permission-failure state.
- HTTP liveness/readiness handler responses.

The HTTP listener's port binding was also checked with a real localhost request during the preceding Render build; this version retains that listener and changes only the wake page text/status payload. Actual Discord modal rendering, button use across restarts, gateway connection without privileged access and Render deployment must still be checked using START_HERE.md after deploy.

No live bot token was used during this implementation. No member DMs were sent and no live announcement panel was posted. Offline mocks are not a substitute for the launch checklist.
