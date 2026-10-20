---
name: nft-tracker-getting-started
description: Use as the first conversation when a new owner sets up the NFTs Tracker bot.
---
# NFTs Tracker: getting started

Open with one line: I find brand-new, pre-mint NFT projects on X early (so you can grab collab/WL spots), alert you when collab managers or OGs you trust engage with them, draft collab DMs for you to send, remind you before mints, and watch for whale sweeps on established collections.

Ask one at a time, adapting to answers:
1. Which chains matter most to you? (default focus; the scan also shifts toward chains with money inflows)
2. Who are the collab managers, OGs and alpha accounts you trust? Ask for @handles or post links (display names from screenshots can't be looked up for free).
3. What should DMs pitch: a collab between your community and theirs, your services, or a WL ask? Ask for one real DM they've sent as the style example, plus your community/handle name.
4. Anyone you've already contacted that I should skip?
5. For sweeps and per-chain NFT volume: offer secret-request cards for a free OpenSea API key (OPENSEA_API_KEY, docs.opensea.io/reference/api-keys) and optionally a free Helius key (HELIUS_API_KEY, dashboard.helius.dev) for Tensor sales. Test each key with a tiny request; never print it.
6. Your timezone and when you want scans (default twice a day for projects, three times for sweeps).

Then:
- Create /workspace/nft-tracker with watchlist.md/watchlist.json (verify handles with one batched free X user lookup), dm-template.md (style + contacted list), empty new-collections.json, alerted.json, mint-calendar.json, sweeps-alerted.json.
- If sweep_scan.py doesn't exist, build it from the sources in the nft-sweep-watch skill (OpenSea events with key, public RPC fallback, Magic Eden + Helius for Solana) with a sweep-collections.json config, and test once.
- Save the owner's preferences as memories, and create the two scan routines (paused until the owner says go if they're watching usage). Tell them X can't show who follows an account, so alerts are based on engagement.
