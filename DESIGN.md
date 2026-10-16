# Clover Trading Desk design

## Intent-free interaction model

The product uses Discord application commands, buttons, dropdown menus, modals and bot-authored embeds. Message Content, Member and Presence intents are all disabled. This is a supported interaction workflow, not an attempt to access restricted member-message content.

Members don't create a ticket channel. They create a private, temporary draft from a shared announcement panel, then deliberately publish one public trading card. The same interface supports 16 spellbook emoji choices and all 76 allowed items through text/quantity input.

## Member journey

```text
Trading Desk / Create trade
    ↓ private preview and spellbook menus
Edit items / quantities + optional Roblox username
    ↓ confirmation of game trade requirements
Publish to trading channel
    ↓
Buyer searches → opens card → Trade / DM → profile + copyable DM text
    ↓
Members negotiate in DMs and trade inside Clover Legends
    ↓
Owner closes the card or reacts ✅
```

Cards show offered and requested items separately, quantities, seller, status and expiry. No game values or completed-trade claims are invented. Contact does not notify the seller or send a DM automatically. Discord privacy settings still apply.

## Management

An owner can edit an active card, close it, or renew it. Editing preserves expiry. Renewing creates a fresh card and closes the old one so 24-hour history recovery can find it. Moderators can close another member's card into a locked state; they cannot edit or renew that member's offer.

The active listing limit is three per trader, including renewal of closed cards. Publication cooldown is 60 seconds; active-card renewal has a 30-minute minimum. Per-user locks prevent double publishing during concurrent clicks; per-card locks serialize edits/closure/renewal. Identical active offers are rejected.

## Recoverable cards

Discord permits apps to read their own messages without Message Content approval. Every trade card is published by this bot; its author URL identifies the seller, readable fields contain canonical item names/quantities, its timestamp is the listing time, and status is open, closed or moderator-locked. Recovery verifies the bot author, rejects webhook/other-bot messages, validates each catalog item/quantity and ignores ordinary member messages.

After Render discards RAM, lazy loading scans the last 24 hours of these cards in configured channels. No separate persistent database is needed. Main panel/card buttons use fixed persistent custom IDs and reload card state from Discord when clicked. Private draft/search/manage views are intentionally temporary and must be reopened after restart.

The card itself preserves edited and closed status; no hidden base64 payload or machine-looking metadata is shown in the normal user flow. Removing the owner's tick does not reopen an already closed embed; an explicit renewal creates a new card.

## Search and rendering

`/search` accepts an item name, alias or mapped custom emoji and provides autocomplete. The panel's Find sellers form provides a matching-item dropdown when several names match. Results are private, limited to channels the requester can read and to items actually offered. They link directly to public cards, where Trade / DM starts the DM handoff.

Loading jobs are shared per channel, successful history scans stay warm for two minutes, and incomplete results are identified. Each search checks up to 25 newest candidate sources. Cards remain readable when a service sleeps, but buttons/commands require the bot to be running.

## Render

One process serves HTTP health/readiness and Discord Gateway. No privileged intents are requested, so the application can connect without the blocked Message Content grant. A sleeping Render service still needs an HTTP visit to wake; Discord Gateway buttons do not wake it. The health page documents this limit.

The previous natural-message indexing implementation is replaced, not silently retained. Community members must publish cards through Create trade or `/offer`. No cross-user DMs are read; there are no per-deal private channels, automated unsolicited messages, real-money transfers, inventory verification, trade counters or shop stock feed.
