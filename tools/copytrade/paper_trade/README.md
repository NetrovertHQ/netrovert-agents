# paper_trade — paper-trade auditor (tool #5)

**Simulation only.** No keys, no wallets, no orders — it never trades. It only reads prices and the other tools' output.

```
python3 paper_trade.py open <token> --source wallet:<nick>|xcall:<handle>|manual [--chain solana] [--signal-id ID]
python3 paper_trade.py ingest [--scan-file scan.json] [--no-xcalls]   # new wallet_tracker buys/sells + new x_calls
python3 paper_trade.py update                                         # walk hourly candles for open live trades
python3 paper_trade.py report [--book live|backtest|all]              # writes results/report.md
python3 paper_trade.py backtest [--wallets "E/acc guy,Nullmask winner"] [--days 30] [--reuse]
```

## Rules (all in config.json)
- Entry: current DexScreener price (best-liquidity pair) for `open`; the **close of the hourly candle containing the buy** for backtests. Notional $100.
- token_check (`--no-narrative`) runs before every open; verdict and score are stored. `gate: true` = KILL trades are tracked as shadow (`gated_out`) and left out of the headline numbers; `gate: false` = everything counts. The report always shows gate OFF / gate ON / KILL-only side by side.
- SL −30% (= 1R). TP ladder: half at +50%, rest at +100%. SL stays at −30% on the remainder. Max hold 72h (exit at candle close).
- Costs: 3% round trip on Solana (1.5% on entry, 1.5% on exit), 2% elsewhere.
- Candle walk starts at the candle *after* entry. If SL and TP are both inside one candle, SL wins. A gap through the SL fills at the open.
- Wallet sells are mirrored: exit at the close of the sell candle (unless the SL is hit in that candle).
- One open position per token per source. Signals dedupe on id (`wallet:<tx>:<mint>`, `xcall:<post_id>:<mint>`).
- R = net PnL / ($100 × 30%). Max DD = peak-to-trough on an equity curve starting at $1,000, trades ordered by exit time.
- Bar: ≥40 trades, ≥33% win rate, ≥+0.4R expectancy, ≤20% max DD → PASS / FAIL / NOT ENOUGH TRADES (plus “on track” / “failing so far”).

## Routine use
`ingest` without `--scan-file` runs `wallet_tracker scan --json` itself, which **moves the wallet baseline**. If the hourly routine already runs `scan`, save its JSON and pass `--scan-file` instead, so neither one steals the other's alerts. Test-* wallets are ignored. Signals older than 6h are not opened (price would be stale). Then run `update` and `report`.

## Backtest
- Runs `wallet_tracker scan <label> --backfill 1000 --json --no-check` per wallet. **The wallet's state file is backed up and restored**, so the live baseline doesn't move.
- Helius cost: the tracker's page cap (5 × 100 txs) + 1 baseline call ≈ 60 credits per wallet. `--reuse` replays the cached `cache/backfill.json` (0 credits).
- Candles: GeckoTerminal hourly, one cached file per pool in `cache/`.

## Known biases / limits
- **token_check runs today, not at the buy time.** Dead tokens now fail liquidity, so KILL in a backtest partly means "it died later". This look-ahead flatters the gate. Live trades don't have this problem.
- Hourly candles: entry can be up to 1h off the wallet's fill. Inside a candle, the order of events is guessed (SL first).
- Buys made before a pool existed (pump.fun bonding curve) or on pools GeckoTerminal doesn't have are skipped and counted.
- The backfill is capped by pages, so very active wallets get fewer than 30 days.
- Only the deepest pool's price is used; thin pools can show wicks that would not fill $100 cleanly.

## EVM / Robinhood backtests
- `wallet_tracker scan <label> --backfill N --backfill-days D` walks public-RPC `eth_getLogs` back up to D days. The Robinhood RPC allows 30k-block ranges; the chain makes about 10 blocks/s. Swaps are built once at the end; before this, they were rebuilt after every chunk. Blockscout for Robinhood is behind Cloudflare.
- `config.backtest_candles` sets the candle size per chain: Robinhood uses 5-minute GeckoTerminal candles. `--max-buys N` caps the run to the latest N buys.
- A wallet sell inside the entry candle exits at the entry price (costs only), shown as `mirror_sell_same_candle`.
