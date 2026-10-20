---
name: nft-sweep-watch
description: >-
  Use when checking established NFT collections on OpenSea/EVM chains, Magic
  Eden or Tensor for whale sweeps (one buyer taking several items near floor in
  a short window).
---
# NFT sweep watch

Goal: flag whale sweeps on older collections: one buyer with >=3 buys (configurable) of the same collection within ~60 minutes, near floor.

Inputs: a tracker folder with `sweep_scan.py` (prototype), `sweep-sources.md` (tested endpoints), a collection list, and `sweeps-alerted.json` (already reported buyer+collection+window).

## Sources (tested keyless unless noted)
- Solana: Magic Eden public API `api-mainnet.magiceden.dev/v2/collections/{symbol}/activities?type=buyNow` and `/stats` (ME fills only, ~180 req/min). Tensor fills need a Tensor or Helius key (env `HELIUS_API_KEY` if present).
- EVM: public RPC `eth_getLogs` Transfer logs on each collection contract (chunks <=5-10k blocks), price from Seaport OrderFulfilled / tx value. With env `OPENSEA_API_KEY`, prefer OpenSea `/api/v2/events/collection/{slug}?event_type=sale&after=<unix>` (all OpenSea chains).
- Floors: OpenSea `/api/v2/collections/{slug}/stats` (keyless) and ME `/stats`.
- Cross-check (optional, few calls): free X search `from:<sweep-alert-account> swept` for structured sweep alerts on other chains.

## Steps
1. Run `sweep_scan.py` with lookback = time since last run (default 6h), threshold >=3 buys / 60 min.
2. Drop: contract buyers (bid pools, AMMs, vaults) unless clearly a sweep, mints, self-transfers, items far above floor, and anything already in `sweeps-alerted.json`.
3. For each real sweep: collection with marketplace link, chain, buyer (short address + explorer link), count, total spent, avg price vs floor, time window, confidence.
4. Save results to a file, append to `sweeps-alerted.json`. If nothing new, send nothing.

No purchases, no wallet actions; read-only.
