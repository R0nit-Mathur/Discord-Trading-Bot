# Verification of the Render build

44 offline tests passed on Python 3.14.5 using discord.py 2.6.4. The suite covers:

- Item text, quantities, mapped emoji identity, autocomplete metadata, blocked items and slot limits.
- Offered items versus wanted items, source edits/deletion, seller-only closure and visibility/ownership guards.
- Original 24-hour expiry during cold reconstruction.
- Shared lazy history scans, caller timeouts without cancelling shared work, missing-history failures and warm-cache reuse.
- Bot-owned close ticks, moderator locks, content ticks and authenticated renewal receipts.
- Close → empty cache → recovery → renew → empty cache → recovery using the actual command callbacks and mocked Discord messages.
- Newest-first duplicate recovery, including a closed newest copy that must not resurrect an older duplicate.
- Restoring configured channels and standard emoji names from environment/server metadata.
- Honest loading responses and HTTP liveness/readiness handlers.

A separate real localhost HTTP smoke test returned `/` = 200, `/health` = 200 and `/ready` = 503 while Discord was not connected, as expected. The listener was stopped after the check.

No live Discord token was used and no Render service was deployed during verification. Render deploy, actual channel permissions, live emoji autocomplete, real Discord rate limits and the sleep/wake lifecycle must still be checked with the deployment checklist in START_HERE.md. Offline tests cannot guarantee production uptime.
