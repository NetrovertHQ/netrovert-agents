---
name: Shared contacts
description: >-
  Use whenever the user mentions, pitches, DMs, or talks about any person or
  company, or before suggesting/drafting outreach to someone, so every bot stays
  in sync on contacts.
---
# Shared contacts
One file every bot shares: <outreach-folder>/contacts.md (plus tracker.md and warm-list.md for job outreach history).

## Before replying about or suggesting a person
1. Search for the name or handle: `rg -i "<name or handle>" <outreach-folder>/`
2. Use what is there. Don't ask the user to repeat context that's already recorded.

## Whenever the user mentions a person (new or update)
1. Append or update one line in contacts.md in this format: `- Name (@handle) | who they are | status / last touch (date) | notes`
2. Only record facts the user said or that you verified, such as their bio. Never guess handles.
3. Edit the person's existing line instead of adding a duplicate.
4. Do it quietly, with no need to announce it.
