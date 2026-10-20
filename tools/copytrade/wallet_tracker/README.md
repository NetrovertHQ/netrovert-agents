# wallet_tracker — multi-chain swap alerts for copy-trading

```
python3 wallet_tracker.py add <address> [--chain solana|ethereum|base|bsc|arbitrum|robinhood] [--label NAME]
python3 wallet_tracker.py remove <address|label>
python3 wallet_tracker.py list
python3 wallet_tracker.py scan [address|label] [--json] [--backfill N] [--no-check]
```
- A base58 address defaults to Solana. A 0x address needs `--chain`.
- The first `scan` of a new wallet only records the latest tx (or block) as a baseline. It prints no alerts.
- `--backfill N` prints the wallet's last N swap txs and also sets the baseline.
- `scan` prints one plain-English line per swap: side, amount, symbol, approx USD (current DexScreener price), what was paid or received, time in WAT (UTC+1), token address and explorer link. For each BUY it runs `../token_check/token_check.py --json` and adds the verdict, score and top 3 reasons. Results are cached per token within a scan.
- When nothing is new, it prints nothing and exits 0 (also with `--json`). Errors go to stderr. Exit 3 only when every wallet failed.
- State: `state/<chain>_<address>.json` holds `last_sig` (Solana) or `last_block` (EVM). `wallets.json` is the watchlist; `config.json` holds RPCs, quote tokens and limits.

## Solana via Helius (optional, `HELIUS_API_KEY`)
- When the key is set, Solana uses Helius `getTransactionsForAddress`, with `transactionDetails=full` and filters `status=succeeded`, `tokenAccounts=balanceChanged`, `tokenTransfer.direction=any`. Failed and spam bot txs are dropped before they are returned. Results then go through the same signer and balance-diff parser as the RPC path.
- Normal scan: one `asc` page with `slot >= last_slot`, 100 per page, at most 5 pages. Backfill: `desc` pages until N swap txs are found, plus one `limit=1` call to set the baseline.
- Cost (per Helius docs): 10 credits per call returning ≤100 txs. A quiet wallet costs about 10 credits per scan (measured: 7 Solana calls ≈ 52 credits per full scan of the 5 Solana wallets). Scanning every 5 min ≈ 2,900 credits per wallet per day.
- If the key is missing, or Helius errors (the error is logged without the key), the tool falls back to public RPC. State keeps both `last_sig` and `last_slot`, so switching sources does not re-alert. Old RPC state is migrated with one `getTransaction` call.
- `--verbose` prints the number of Helius calls and credits to stderr.
- Enhanced Transactions `/v0/addresses/<addr>/transactions?type=SWAP` was tested and rejected. For Cented it returned 35 swaps, none of which he signed.

## USD value
- Solana swaps show **USD at fill**: a USDC/USDT/USD1 leg counts 1:1, and a SOL leg uses the Coinbase public 1-minute SOL-USD candle at the tx time (keyless). The JSON field is `usd_source: "trade"`.
- EVM swaps, and Solana token-for-token swaps, use the current DexScreener price (`usd_source: "dexscreener_now"`). Alert text shows "at fill" or "now".

## How swaps are detected
- **Solana**: `getSignaturesForAddress` (paged, `until` = last seen), then `getTransaction` with jsonParsed. Failed txs are skipped without a fetch. Only txs the wallet **signed** count. The tool diffs the wallet's pre/post token balances and its SOL balance (fee removed). A non-quote token going up is a BUY; one going down is a SELL. Quote tokens are SOL/wSOL, USDC, USDT and USD1. Dust SOL moves (< 0.005, i.e. rent), NFTs (0-decimal tokens) and one-way transfers are ignored. Calls are spaced 0.35 s apart with backoff on 429. Caps: 60 fetched txs per scan (180 for backfill) and 20 signature pages.
- **EVM**: the tool reads ERC-20 Transfer logs to and from the wallet and groups them by tx. Only txs sent by the wallet (`tx.from`) count. Native ETH or BNB paid comes from `tx.value`. On sells, the native coin the router unwraps is not visible, so a SELL may show no "for X". Sources are tried in order: Etherscan V2 (only if `ETHERSCAN_API_KEY` is set) → Blockscout v2 (Ethereum) → public RPC `eth_getLogs` in chunks.

## Keyless status (checked with live calls on 20 Oct 2026)
| chain | keyless? | source |
|---|---|---|
| Solana | yes (Helius if `HELIUS_API_KEY`, recommended) | Helius getTransactionsForAddress → api.mainnet-beta.solana.com → publicnode |
| Ethereum | yes | eth.blockscout.com API (fast, deep history) |
| Robinhood (4663) | yes | rpc.mainnet.chain.robinhood.com getLogs, 10k blocks per call |
| Arbitrum | yes | arb1.arbitrum.io/rpc getLogs, 10k blocks per call (~40 min) |
| BSC | yes, limited | bsc.rpc.blxrbdn.com getLogs, 5k blocks per call. A deep backfill is slow |
| Base | yes, limited | base.gateway.tenderly.co getLogs, 1k blocks (~33 min) per call. A deep backfill is slow or capped (`evm_backfill_max_chunks`) |

These explorer APIs block keyless use: Base, Arbitrum and Robinhood Blockscout (Cloudflare challenge), and the Blockscout Pro API (needs a key). Etherscan V2's free tier excludes BSC and Base. Set `ETHERSCAN_API_KEY` for faster scans on chains your plan covers. If the key fails, the tool logs that and falls back.

## Known limits
- Bot-flooded wallets without a Helius key: some famous KOL wallets (Cented, Cupsey) appear in thousands of failed or foreign txs per minute. Public RPC can't page past them, so backfill finds nothing, and between scans a gap of more than about 20k signatures is cut off. Scan often (every 1-2 min) or use a paid indexer (Helius) for those wallets.
- EVM USD is quantity × the current DexScreener price, not the price at fill time.
- For an EVM wallet that is far behind, a scan covers only the latest `evm_max_blocks_per_scan_chunks` chunks.

## Setup

Copy config.example.json to config.json and set your own values. The example numbers are generic placeholders, not tuned settings.
