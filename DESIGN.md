# Render trading design

Members post text/mapped emojis in existing trading text channels, discover sellers through private `/search` results, negotiate in DMs and exchange items inside Clover Legends. No per-deal channel or inventory registration is required.

## Data flow

```text
Discord posts + source reactions + renewal receipts
                      ↓ lazy rebuild on first search
Temporary index in the running Render process
                      ↓ text/emoji autocomplete selection
Private seller results with original-message links
```

The temporary index is disposable. Render environment variables retain channel configuration and custom emoji overrides. Named standard spellbook emojis are rediscovered from Discord after every connection. The first search reads the complete 24-hour active window, not every historic trade ever posted. This follows the listing expiry rule and bounds the amount of meaningful history. An in-window renewal receipt can point to an older original post.

## Lifecycle

| Action | Runtime result | Recoverable Discord evidence |
|---|---|---|
| Valid new offer | Searchable for 24 hours | Source message and creation time |
| Edit | Replace offered/requested items, preserve expiry | Current source content |
| Author reacts ✅ or edits ✅ into post | Close whole listing | Author/source tick; bot may mirror a close tick |
| Another member reacts ✅ | No closure | Reaction author is checked |
| `/close` | Close whole listing | Bot-owned ✅ on original |
| Moderator `/close` | Close and prevent seller renewal | Bot-owned 🔒 on original |
| `/renew` | Reopen/refresh for 24 hours | Bot-authored renewal reply, source ID and timestamp |
| Identical repost by same seller | Supersede previous copy | Newer source message/time |
| Delete source | Remove listing | Original cannot be fetched |
| Render sleep/restart | Forget index | Reconstruct from available Discord sources |

A tick applies to the entire post. Edit a bundle to remove just one item, or post separate independent offers. Removing the seller's ✅ alone does not reopen a post when the bot's tick still exists; use `/renew`. Do not delete the bot's renewal receipts or status reactions if recovery is needed.

## Search experience

`/search item:Time` or a pasted mapped Time emoji resolves to the canonical Time catalog entry. Autocomplete gives matching item names/categories. Search considers offered items only, checks visibility and source state, and shows seller, quantities, requested items, timestamps, expiry and original-post link. Five results appear per page; up to 25 newest matching candidates are rechecked per query. A listing is a member claim rather than certified inventory.

A cold connected bot acknowledges the interaction immediately, starts shared loading, and waits briefly. Available results can be shown with a partial-results notice; an empty incomplete scan is labelled still loading. Concurrent searches reuse the same background job. Successful history scans stay warm for two minutes; reconnects invalidate them.

## Health and sleep

One process hosts HTTP and the Discord Gateway client. `/health` is process liveness and `/ready` checks connection/configuration. The health routes don't expose credentials or community trade data. Render receives HTTP on `0.0.0.0:$PORT`.

A sleeping process cannot receive Gateway slash commands, so a web visit must wake Render first. There is no automatic wake or continuous uptime guarantee. The first cold command can fail if attempted before the process has woken and connected; retry after `/ready` is successful. No health route is configured as a Discord interactions endpoint.

## Reference and scope

Observed Fruity Blox trading used ordinary public emoji/text offers and DMs for negotiation. Its separate shop-stock posts and Vulcan value cards were different features. This bot adds searchable active sellers to that public-post workflow. It does not infer completed trades or award counts from unavailable listings, and does not fabricate an in-game shop feed.
