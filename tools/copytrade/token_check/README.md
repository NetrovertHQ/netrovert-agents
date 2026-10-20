# token_check — multi-chain rug filter

Based on steps 08-12 of 0xboan's article (checks 1-13; the Grok/X check is left out).

```
python token_check.py <address> [--chain solana|ethereum|base|bsc|arbitrum|polygon|robinhood|...] [--json] [--config path]
                       [--narrative | --no-narrative] [--narrative-file grade.json]
python narrative.py <address> [--chain solana]     # metadata + search queries for the narrative procedure
```
- No `--chain`: a base58 address is treated as Solana. For a 0x address, the tool looks it up on DexScreener and uses the chain of the most liquid pair.
- Exit codes: 0 PASS, 1 WARN, 2 KILL, 3 error (bad address or chain not found). `--json` prints verdict, score, summary, kills/warnings/unknown, the per-check list, sources, and the raw market and security facts.
- Needs: Python 3.8+, `requests`. All sources are free and need no key: DexScreener (all chains), Rugcheck (Solana), GoPlus (EVM).

## How the verdict works
- Every threshold, severity (kill/warn) and score weight is in `config.json`.
- Any failed `kill` check gives KILL. Otherwise, any failed `warn` check, any unknown, or a score under 75 gives WARN. Otherwise PASS.
- The score starts at 100. A failed check subtracts its weight, and an unknown check subtracts half its weight.
- A source that fails (timeout, 429, 5xx; 3 retries with backoff) marks its checks `unknown`. Unknown never counts as a pass.

## Checks (default thresholds)
| check | chain | fails when | severity |
|---|---|---|---|
| rugged | SOL | Rugcheck flags it rugged | kill |
| mint_authority | SOL | mint authority is still live | kill |
| freeze_authority | SOL | freeze authority is still live | kill |
| danger_flags | SOL | Rugcheck reports any danger-level risk | kill |
| risk_score | SOL | Rugcheck normalised score > 40 | warn |
| honeypot | EVM | GoPlus flags honeypot, cannot_sell_all or cannot_buy | kill |
| sell_tax / buy_tax | EVM | over 10% (5-10% only gets a half penalty) | kill / warn |
| owner_can_mint | EVM | token is mintable and ownership is not renounced | kill |
| proxy, blacklist, owner_powers, open_source | EVM | upgradeable, has a blacklist, owner has hidden/pause/balance powers, or source is unverified | warn |
| lp_lock | all | biggest pool is under 90% locked or burned | warn |
| lp_unlocked_tiny | all | LP is unlocked AND liquidity is under $100k | kill |
| top10_holders | all | Established token (pair age >= `new_pair_hours`=24h AND **total liquidity across all its DexScreener pairs** >= `established_min_liquidity_usd`=$500k): over 40% (`max_top10_pct`) → **warn**. New, thin or unknown-age token: over 35% (`max_top10_pct_new`) → **kill**. Pools and lockers excluded | kill / warn |
| dev_wallet | all | creator holds over 5% | warn |
| insiders | SOL | any insider-flagged top holder | warn |
| liquidity | all | deepest pool is under $30k | kill |
| ticket_share | all | a $25 ticket is over 1% of the pool | warn |
| pair_age | all | under 30 min (no max age by default; `max_age_hours` turns one on) | warn |
| sells_exist | all | 20+ buys and 0 sells in the last hour (honeypot shape) | kill |
| volume | all | 24h volume under $10k | warn |
| fdv_liquidity | all | FDV is over 100x liquidity | warn |
| profile | all | no DexScreener profile or socials (weight 0) | warn |

## Known limits
- Neither source tags exchange wallets. Those wallets inflate top-10 numbers on big listed tokens (WIF is at about 45%, so it still fails the 40% limit).
- GoPlus returns partial data (code 3) for tokens only minutes old, so many EVM checks come back unknown.
- DexScreener has no liquidity figure for pump.fun bonding-curve tokens, so the liquidity check comes back unknown.
- USDC-style tokens (proxy, blacklist, centrally minted) score low by design.

## Robinhood Chain
- Identifiers, checked with live calls on 20 Oct 2026: DexScreener `robinhood`, GeckoTerminal `robinhood`, GoPlus chain id `4663` (from `/api/v1/supported_chains`; chainid.network also lists 4663).
- GoPlus returns full contract data on this chain.
- `--chain robinhood` works, and auto-detection picks the chain when the token's deepest pair is on Robinhood.

## Narrative verification (`--narrative`, on by default for Solana)
Narrative is an extra section with a small score effect, set in `config.json` -> `narrative.score_effect`: CONFIRMED +5, UNCONFIRMED 0, NONE -5, CONTRADICTED -15. It never KILLs on its own. CONTRADICTED only downgrades a PASS to WARN.

The X tools run on the agent side, so grading is a documented procedure:
1. Run `python narrative.py <address>`. It collects name, symbol, description, socials, any linked source post IDs, pair creation time, launchpad and creator from DexScreener and Rugcheck, and prints ready-made queries.
2. On X (built-in `x` tools):
   - `get_posts_by_ids` on the linked source posts. Is the post live, deleted or withheld, and when was it posted?
   - `search_posts_all` for the name, `$SYMBOL` and the contract address, and the same queries limited to before token creation.
   - `search_news` for the name.
   - `get_users_by_username` on the subject's official handle, then `from:<official>` searches.
3. Run a web search for the name plus "official", "trailer", "announced" or "leak".
4. Identify the claimed catalyst (game, film, celebrity, product) and its subject, then grade:
   - **CONFIRMED**: the subject's official or verified channel shows the catalyst. This confirms the story only; it does not mean the token is affiliated.
   - **UNCONFIRMED**: plausible but unofficial (a leak, a rumour, an influencer). A deleted or withheld leak stays UNCONFIRMED; it is not proof the story is fake. Watch for official proof.
   - **CONTRADICTED**: the official subject denies the story, or the evidence is shown to be fabricated.
   - **NONE**: no identifiable story.
5. Compare the catalyst date with `pair_created_utc`. A token created before the official proof is front-running a leak, so note that in the timeline.
6. Save `narratives/<address>.json` with `grade`, `catalyst`, `subject`, `reason`, `sources[{url,note}]`, `timeline` and `checked_at`. token_check picks it up automatically, or pass `--narrative-file`. With no file, the section shows `PENDING` plus the queries to run.

Example: Dacity (`nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump`). `narratives/<addr>.json` is the grade now: CONFIRMED by the official trailer. `narratives/archive/dacity_leak_phase.json` is the grade during the leak phase: UNCONFIRMED.
