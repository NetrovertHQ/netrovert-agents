---
name: Practice fill guard
description: >-
  Use when changing Netro Signal practice trading buys or sells, take-profit,
  stop-loss, copy trades, snipes, or when a practice leaderboard spike or stuck
  bag needs the fill rules preserved.
---
# Practice fill guard

Keeps Netro Signal **practice mode** (fake money) from minting thin-pool / fake-depth fills (and stuck bags) off Dex prices. Live logic is in `practice.py` on the VPS: `buy_fill_ok` for buys, `price_ok` for auto TP/SL, `sell_fill_ok` for manual `/sell` and portfolio sell buttons, and copy sells.

**Lagos Life flex (Oct 26 2026, post-contest):** practice pump-% cap disabled (`SUSPECT_PUMP_PCT = None`) so big moons on deep pools can sell/screenshot for free marketing. Depth guards (`LIQ_MAX_FRAC` 0.25, unknown/zero pool liq refuse) stay on. Post Oct 26 unfreeze: `/leaderboard` is live again; `/finalscore` keeps the finals snapshot. Real Swap / live trading untouched.

**Buy receipts MC (Oct 27 2026):** practice buy success lines (confirm / paste-buy / snipe / copy / limit / DCA) and Fake-buy preview lines show Dex market cap when available (`marketCap` else `fdv` on the same best pair as `price()`). Fill guards (`buy_fill_ok` / `sell_fill_ok` / `LIQ_MAX_FRAC` / `SUSPECT_PUMP_PCT`) unchanged.

**PnL trade card layout B (Oct 27 2026):** `/pnl` trade cards (`trade_card` / `_open` / `_closed` / Share PnL `pc:h…`) show stacked muted Dex MC under Entry and Now/Exit when MC is available (`card._stat` sub line). If no MC, price-only card unchanged. Portfolio text bag lines and `portfolio_card` unchanged — do **not** add price/MC compare there. New `_buy` fills store `entry_mc` on the position when Dex MC is cached (first fill only; no migration of old user JSON). Older opens approx `entry_mc ≈ now_mc * (entry_px / now_px)`. Closed trades use stored `entry_mc` or the same approx vs live exit MC from `mcap_for` at render. Reuse `practice.mc_fmt` / `mcap_for` / `buy_px_line`. Do not build Pumpfun editor / chart / backgrounds in this path. Gojo mood preset buttons (Auto/😎/😒/😴/😭/🎉) under trade cards are allowed using existing assets only; do not add chart/uploads/solid-panel backgrounds without owner yes.

## What it blocks (sells / exits)

1. **Unknown or zero pool liquidity** — no auto or manual sell fill.
2. **Sell proceeds over 25% of best-pool liquidity** (`LIQ_MAX_FRAC`) — thin/fake prints.
3. **Pump-% hard cap — DISABLED (Lagos Life flex, Oct 26 2026 post-contest)** — `SUSPECT_PUMP_PCT = None`. `price_ok` and `sell_fill_ok` skip the pump-% branch when it is `None`, so deep-pool moons (100x+) can sell / screenshot for free marketing. Was +1000% (10x) after Oct 25 raise from +500%. Re-enable by setting a float (e.g. `1000.0`) — guarded branches still exist. **Depth guards unchanged** (items 1–2): thin/fake prints still refuse. Residual: a moon on a pool deep enough that sell proceeds ≤ 25% of liq can print a big practice fill (by design for flex).
4. **Drops of −90% or worse** — auto-sell only after a **second reading** (~60s later) from the **same pool** (`price_ok` / `SUSPECT_*` kind `drop90`).
5. **Big SL gaps (since Oct 25 2026)** — when an auto stop-loss would fill far past the user's SL, still above −90%:
   - **Short second-read** when realized pct is ≥ **15 pts past −sl** OR pct ≤ **−50%** (`SL_GAP_PTS` / `SL_GAP_FLOOR`), while still ≤ −sl so SL would fire.
   - Wait **~18s** (`SL_GAP_WAIT`, not 60) then re-read the **same pool** before selling (`price_ok` kind `slgap`; `check_tpsl` sleeps once and retries those tokens in-pass).
   - After second-read: if still past SL, sell at spot; if recovered above SL, don't sell.
   - ≤ −90% keeps the long ~60s second-read unchanged.
6. **Honest gap alert copy** — when a stop-loss sell's realized pct is ≥ **8 pts past −sl** (`HONEST_GAP_PTS`), the alert says the fill gapped, e.g. `Stop-loss hit: sold $SYM at −88% (−$X fake)\n(your SL −30% · price gapped past it)`. Fair fills near SL keep the short line. Same idea on portfolio/copy `apply_stops` stopped tags (`gapped past −SL%`).

Do **not**: fill at SL-mark price, change `LIQ_MAX_FRAC`, loosen depth/zero-liq refuses, change `buy_fill_ok`, sellsnap `LONG=False`, or Real Swap for this. Pump-% is intentionally `None` post-contest (Lagos Life); do not re-enable without owner yes.

## What it blocks (buys — since Oct 25 2026)

`buy_fill_ok` mirrors the sell depth rules for **entries**:

1. **Unknown or zero pool liquidity** — hard refuse (no Confirm, no fill). Soft warn alone is not enough.
2. **Buy size over 25% of best-pool liquidity** (`LIQ_MAX_FRAC`) — refuse with the max shown (no silent clamp).

Same rules on **every** entry path: `/buy` → confirm (`pb:`), paste-buy, practice snipe (`ls:` / `mb:`), and copy buys. Do not let snipe or copy skip the guard.

## Bonding / pre-Dex refuse copy (since Oct 25 2026)

Practice still **does not** fill pre-bond / Launchlab tokens (Dex depth required). Copy only:
- `no_price_msg` → "Couldn't find… on Dex yet" / case-sensitive tip / wait until DexScreener lists it
- zero Dex depth buy refuse → "looks early — still bonding or no Dex pool depth"

Do **not** unlock FOMO, GMGN, or GeckoTerminal reserves as buy depth without owner yes. Size-over-25% copy stays separate.

**Bare ticker / ticker+chain (Oct 26 2026):** `/buy` refuses non-address args with no chain hint (`BARE_TICKER_REFUSE`); `/buy SYM rh` (etc.) resolves via DexScreener search on that chain only (`resolve_symbol`) — never blind richest across chains. CA bonding copy above stays for real address misses.

## Where it runs

- Auto TP/SL loop: `check_tpsl` → `price_ok`
- Portfolio stop-loss path: `value(..., apply_stops=True)` → `price_ok`
- Manual `/sell` and `ps:` buttons: `sell()` → `sell_fill_ok`
- Copy-trade sells: `copy_fills` → `sell_fill_ok`
- Buys / snipes / paste / copy buys: → `buy_fill_ok`

It already runs inside the `netro-signal` service. A skill does not execute on the VPS; this recipe is so you **preserve and extend** the guard instead of regressing it.

## Portfolio warm miss + miss copy (since Oct 25 2026)

`warm_user` warms open mints outside LOCK, then does **one short soft Dex retry** (`_SOFT_MISS_TIMEOUT` ~5s, `_SOFT_MISS_MAX` 12) for mints still missing from the pairs cache. `/portfolio` and Menu My Portfolio both call `practice.portfolio` → same helper.

Portfolio / sell refuse copy distinguishes:
- **Feed busy** (PAIRS never written after warm+soft-retry) → `price feed busy · tap Refresh` / sell msg points at Refresh
- **True no price** (Dex probed empty / confirmed miss) → `no live price · can't sell yet`
- **Depth gone** (price OK, liq 0) → `price only · pool depth gone · can't sell yet` (unchanged)

Do **not** add Axiom as a price/liq source without owner yes; Dex best-pool stays the sell/buy depth source.

## When a spike still hits the board

1. Confirm diagnosis from the user’s `practice/users/<chat_id>.json` history (side, via, pct, usd, entry_px, token).
2. Check `bot.log` for `tpsl: blocked` / `held thin liquidity` / `held suspicious`.
3. Backup under `practice/backups/` before editing user data.
4. Void the spiked sell **and every trade after it** (they were funded with fake proceeds). Restore the bag with **no TP/SL** so it cannot instantly re-fire. Dry-run cash/positions first; wait for owner yes on user-data changes.
5. If they sold **manually** after a void, the same void pattern applies — and confirm `sell_fill_ok` is on the manual path so it cannot happen again.

## Do not

- Re-enable the pump-% hard cap (`SUSPECT_PUMP_PCT` float) or change the 25% liquidity cap without owner yes. As of Oct 26 2026 post-contest, pump-% is **disabled** (`None`) for Lagos Life flex; depth/25% stays on.
- Let snipe/copy buys bypass `buy_fill_ok`.
- Leave TP/SL on a restored spike bag.
- Rely on second-reading alone for depth (that failed on AXIS when pump was the only other gate — depth is now the main spike brake).
- Top up practice balances for stuck bags without owner yes (UX or voluntary $0 write-off only).
- Re-freeze `/leaderboard` or delete the `/finalscore` finals snapshot without owner yes. Board is live again; finals stay on `/finalscore`.
- Add FOMO/GMGN scrapes or Gecko depth for practice fills without owner yes.
- Put secrets, VPS hosts, or owner chat ids in this skill.
