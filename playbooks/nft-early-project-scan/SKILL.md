---
name: nft-early-project-scan
description: >-
  Use when scanning X for brand-new, pre-mint NFT collection accounts to get
  collab/WL spots early, alerting when watchlisted collab managers or OGs engage
  with them, and drafting collab DMs.
---
# Early NFT project scan (X)

Goal: surface NFT projects BEFORE mint and ideally before any collab manager publicly announces them. Already-minted or already-pumping projects are not useful.

Inputs (the routine names the paths): a tracker folder with `watchlist.json` / `watchlist.md` (important people: collab managers, OGs, founders, alpha sources), `new-collections.json` (known candidates), `alerted.json` (handles already sent to the user), a DM template file, a contacted list, and `notes.md` (queries/endpoints that worked).

## Budget rules (strict)
- Use only free public X reads (the built-in `x` namespace). Never use a paid X connection.
- Hard cap per run (the routine sets it; default 60 calls). Batch everything: `get_users_by_usernames` takes up to 100 handles, search queries can OR many `from:`/`@` terms.
- Do processing with code on files, not in chat. Stop after 3 failures and report.
- `search_users` is 403 on free reads; follower/following lists are NOT available. Never claim someone "follows" a project; say "replied / quoted / reposted / tagged".

## 1. Pick chain focus (follow the money)
- Pull DefiLlama per-chain data (free, `https://api.llama.fi/v2/chains` for TVL and `https://api.llama.fi/overview/dexs/<chain>` for DEX volume). Compare 24h/7d change vs the previous run (store in `chain-flow.json`).
- If an OpenSea key is available in env, also sum 1d volume from `/api/v2/collections/{slug}/stats` per chain for tracked collections.
- Allocate search calls: default priority chains get the base share; any chain with a clear inflow (e.g. +15% 7d or a big jump since last run) gets extra calls. Note the focus in the report.

## 2. Discover fresh accounts
- Read posts from watchlist collab managers / OGs / alpha sources since the last run (`from:a OR from:b ...`, `-is:retweet`, recency, `expansions=author_id,entities.mentions.username`, `user.fields=created_at,description,public_metrics`). The mention expansion returns full profiles of tagged accounts.
- Run a few chain queries (see notes.md) for phrases like "mint date", "WL", "GTD", "allowlist", "coming soon", "building on <chain>".
- Keep accounts that: were created within ~21 days (soft 45), have low followers (under ~3k is ideal), describe an NFT collection, and show NO sign of having minted (no "sold out", "minted out", "mint live" in the past, no marketplace trading). Skip tokens, launchpads, alpha hubs, scanners, spam.
- Skip anything in the contacted list or already in `alerted.json` unless there is NEW engagement from a watchlist person.

## 3. Engagement signal
- For candidates, check whether watchlist people replied, quoted, reposted or tagged them (one batched `(from:...) (@cand ...)` query per chunk). Quotes, reposts and direct tags beat replies (replies inherit @-mentions from threads).
- Score: freshness + low followers + number/weight of watchlist engagers (OGs and known collab managers weigh most) + pre-mint status. Rank highest first.

## 4. Alert and drafts
- Only alert on projects that are new since last run or have a new watchlist engagement. For each: handle as a link, chain, created date, followers, mint status/date, who engaged and how, one specific fact.
- Under each, a collab DM draft in the user's template style (short, warm, from the community founder, one specific line about that project, plain English). Drafts are for the user to send themselves; never send anything.
- Append alerted handles with date to `alerted.json`; update `new-collections.json`.
- If nothing new, send nothing.
