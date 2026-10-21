---
name: Paper-trade auditor
description: >-
  Use to test whether copying a wallet or X caller would actually make money,
  with fake trades on real prices, before risking real money.
---
# Paper-trade auditor (fake trades first)

## The idea, in plain words
Every time a wallet or caller we follow buys a token, we pretend to buy it too with a fixed fake amount (`notional_usd`). We watch the real price and close the fake trade when one of these happens first:
- it hits the stop loss (`stop_loss_pct`),
- it hits a take-profit step (`take_profit_ladder`: sell part at each step),
- the max hold time passes (`max_hold_hours`),
- or the wallet we copy sells it (`mirror_wallet_sells`).
We also take off a round-trip cost for fees and slippage (`round_trip_cost_pct`), so the result is realistic.

After enough fake trades (`bar.min_trades`) we give a simple verdict. It PASSES only if all of these are true:
1. The win rate is at least `bar.min_win_rate`.
2. The wins are clearly bigger than the losses (average return per trade, in units of what we risked, is at least `bar.min_expectancy_r`).
3. The fake account never drops more than `bar.max_drawdown_pct` from its best point.
Below the minimum: NOT ENOUGH TRADES yet. Pass = worth copying with small real money. Fail = don't copy. All values live in `config.json` (see `config.example.json`); pick your own.

We run it two ways: copying everything, and copying only tokens that pass the Token safety check, to see if the safety check helps.

## How to run it
Tool lives in `tools/copytrade/paper_trade/` (use `python3`).
- `paper_trade.py backtest --wallets "<nick>,<nick>" --days <N> [--reuse]`: replay the last N days of a wallet's buys. `--reuse` uses saved data so it doesn't re-spend data credits.
- `paper_trade.py ingest --scan-file <scan.json>`: open fake trades from new wallet-tracker alerts and X calls. Always pass the hourly scan's saved output; running a fresh scan here would make the hourly alert miss trades.
- `paper_trade.py update`: close trades that hit their exit.
- `paper_trade.py open <token> --source manual`: one-off fake buy.
- `paper_trade.py report`: verdict per wallet/caller; writes `results/report.md`.

## Explaining results
Use plain words: "won 3 in 10 trades, lost about $X per trade on average, the account fell Y% at worst". Mention honest caveats: prices are hourly so entries are rough; the safety check runs today, not on the day of the buy; tokens with no pool left can't be priced. Never place real trades.
