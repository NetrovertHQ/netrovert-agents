---
name: Double-check before changing
description: >-
  Use before implementing, shipping, undoing or recommending any change to a
  live product, data or user records (bot code, settings, user balances,
  leaderboards), to verify you're right before acting.
---
# Double-check before changing

Goal: never ship or undo something based on a first guess. Prove the diagnosis, then act.

## 1. Verify the diagnosis
- State the claim in one sentence (for example, "these sells were caused by a bad price").
- Look for evidence that could prove it WRONG, not just evidence that supports it. Re-check the live data a second time, from a second source if possible, and a few minutes later if timing matters.
- Ask: what else could explain this? If an alternative fits the evidence as well, you're not done.
- If you can't confirm it, say so plainly and present it as a guess.

## 2. Check the change itself
- What exactly will change, and for whom? Who could be hurt if you're wrong?
- Is it reversible? Take a backup first (code and any edited data files).
- Does it touch other features? List them and plan to re-test each one.
- Dry-run first: compute the before/after on a copy or in read-only mode and look at the result before writing anything live.

## 3. Tell the owner before acting on anything consequential
- In plain words: what you found, how sure you are, what you'll change, and the expected impact (for example, how rankings or balances will move).
- Wait for a yes on changes to user data, money, rankings or anything public.

## 4. After implementing
- Re-test the changed flow and the core flows around it.
- Re-check the original problem is actually fixed, and look for side effects.
- If something you said earlier turns out wrong, correct it clearly and simply. Don't bury it.
