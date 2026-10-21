# netrovert-agents

Netrovert ([@netrovertHQ](https://x.com/netrovertHQ)) is a crypto and AI content creator based in Lagos. This repo documents the team of 11 AI agents, running on Grok Bot, that help run the career and community side of things, plus the shared playbooks they follow.

Nothing here posts or sends on its own. The agents research, draft, and track; Netrovert approves and sends.

## The agents

- **Job Seeking**: Finds roles and freshly funded projects, researches leads, drafts pitches, fills and submits applications. Runs a daily scan and a morning check-in on replies and follow-ups.
- **Current Jobs**: Keeps track of active client work, deliverables, and deadlines.
- **Bounties and Hackathons**: Scans bounty boards and hackathons, breaks each one down (rules, prizes, where to submit, sponsor risk) and suggests how to win it.
- **New Connections**: Suggests people to connect with on X each day and drafts the DMs.
- **Reply Guy**: Drafts replies and quote posts on X in Netrovert's voice for mutuals and people worth engaging.
- **Community Pulse**: Watches community health across Discord, Telegram, and X group chats. Weekly pulse, unanswered questions, and a foul-language watch.
- **NFT Tracker**: Spots early, pre-mint NFT projects on X and watches established collections for whale sweeps.
- **Video Generation**: Generates and edits video clips for content and video bounties.
- **Relocation Assistant**: Researches relocation options, visas, and logistics.
- **Brainstorming / Research / Writing**: General thinking partner for ideas, research, and drafts.
- **Copy Trading**: Monitors wallets and tokens, with a rug-risk check before anything is flagged. Playbooks: smart-money finder, wallet tracker, Fomo leaderboard wallets, X call tracker, token safety check.

## How they work together

- **Shared contacts file**: one contacts list every agent reads before suggesting or drafting outreach, so no one gets pitched twice and context isn't lost.
- **Shared memory**: profile, voice, rates, and preferences are saved once and used by every agent.
- **Shared skills / playbooks**: the files in `playbooks/` are reusable instructions any agent can load (e.g. the cold DM rules are used by Job Seeking, New Connections, and NFT Tracker).
- **Scheduled routines**: each agent runs its own daily or weekly routines (scans, check-ins, pulses) and stays silent when there's nothing new. A shared usage-cap playbook pauses all of them at once when needed.

## Playbooks

| Playbook | Purpose |
|---|---|
| [ats-check-before-applying](playbooks/ats-check-before-applying/SKILL.md) | Check a CV/application against the company's applicant tracking system before submitting. |
| [bounty-hackathon-breakdown](playbooks/bounty-hackathon-breakdown/SKILL.md) | Standard card for any bounty or hackathon: rules, prizes, route to winning, sponsor risk. |
| [bounty-hunter-getting-started](playbooks/bounty-hunter-getting-started/SKILL.md) | First-run setup for the Bounties and Hackathons agent. |
| [cold-dm-sweet-spot](playbooks/cold-dm-sweet-spot/SKILL.md) | Rules for short, human cold DMs with the ask up front. |
| [community-foul-language-watch](playbooks/community-foul-language-watch/SKILL.md) | Flag abusive messages, count strikes, remove repeat offenders only with approval. |
| [community-pulse-getting-started](playbooks/community-pulse-getting-started/SKILL.md) | Connect Discord, Telegram, and X group chats to Community Pulse. |
| [community-pulse-weekly](playbooks/community-pulse-weekly/SKILL.md) | Weekly community report: volume, active members, who went quiet, top questions. |
| [community-unanswered-questions](playbooks/community-unanswered-questions/SKILL.md) | Find member questions nobody answered. |
| [daily-usage-cap](playbooks/daily-usage-cap/SKILL.md) | Pause all agents' routines for the day when the usage cap is hit. |
| [fomo-leaderboard-wallets](playbooks/fomo-leaderboard-wallets/SKILL.md) | Pull top traders and their wallets from the Fomo (fomo.family) leaderboard, read-only, for smart-money scoring. |
| [getting-started](playbooks/getting-started/SKILL.md) | First-run setup for the Job Seeking agent. |
| [identify-contest-from-prize-pool](playbooks/identify-contest-from-prize-pool/SKILL.md) | Find the real contest behind a teaser that only shows a prize pool. |
| [nft-early-project-scan](playbooks/nft-early-project-scan/SKILL.md) | Find pre-mint NFT projects on X and draft collab DMs. |
| [nft-sweep-watch](playbooks/nft-sweep-watch/SKILL.md) | Detect whale sweeps on established NFT collections. |
| [nft-tracker-getting-started](playbooks/nft-tracker-getting-started/SKILL.md) | First-run setup for the NFT Tracker agent. |
| [pitch-funded-project](playbooks/pitch-funded-project/SKILL.md) | Pitch a freshly funded project for a paid content or community role. |
| [reply-guy-getting-started](playbooks/reply-guy-getting-started/SKILL.md) | First-run setup for the Reply Guy agent. |
| [reply-to-lead](playbooks/reply-to-lead/SKILL.md) | Draft a reply when a pitched lead responds, sends an offer, or asks for samples. |
| [shared-contacts](playbooks/shared-contacts/SKILL.md) | Keep one shared contacts file in sync across all agents. |
| [smart-money-finder](playbooks/smart-money-finder/SKILL.md) | Score and rank crypto wallets worth copying by realized PnL, win rate, and copyability. |
| [token-safety-check](playbooks/token-safety-check/SKILL.md) | PASS/WARN/KILL rug-risk check before flagging any token. |
| [video-bounty-playbook](playbooks/video-bounty-playbook/SKILL.md) | Patterns for planning and posting video bounty entries. |
| [wallet-tracker](playbooks/wallet-tracker/SKILL.md) | Watch crypto wallets for new buys and sells and alert with a token safety verdict. |
| [x-call-tracker](playbooks/x-call-tracker/SKILL.md) | Track and grade token calls posted by X accounts and rank which callers are worth following. |

## Tools

Source code for the Copy Trading bot lives in `tools/copytrade/`. Each folder has its own README.

- `token_check/`: PASS/WARN/KILL rug-risk check for a token (used by the token safety check playbook).
- `wallet_tracker/`: watches wallets on Solana and EVM chains for new buys and sells.
- `smart_money/`: scores and discovers wallets by PnL, win rate and copyability.
- `x_calls/`: extracts and grades token calls posted on X.
- `paper_trade/`: paper-trades copied buys to test strategies without real money.
- `tg_bot/`: Netro Signal ([@netrosignal_bot](https://t.me/netrosignal_bot)), a Telegram bot that answers BUY / CAREFUL / SKIP for a token. It never holds keys or trades.
  Shipped from user feedback in one night (Oct 20-21, 2026): launch alerts, MEV-protected Jupiter links, practice limit orders and DCA, and faster replies under load, after [@phantom_zxx](https://x.com/phantom_zxx) asked for them. See `tools/copytrade/tg_bot/README.md`.

Secrets come from environment variables only (see `tools/copytrade/.env.example`). Config, watchlists, state, caches and results are not in the repo. Each tool expects its own local `config.json`.

## How to use these playbooks

- Each folder in `playbooks/` holds one `SKILL.md`. Its frontmatter has a `name` and a `description` that says when the playbook should be used.
- Drop a folder into any agent that supports skills, and the agent can load it when the description matches the task.
- Or skip the agent and read a playbook as a plain checklist.
- Adapt the placeholders (for example `<outreach-folder>`) to your own files, accounts, and tools before using them.
