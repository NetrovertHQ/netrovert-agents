# New Connections: DM reply scan

Three small scripts the New Connections agent uses to see which people it DMed on X have replied. Everything runs locally and nothing is sent.

1. `match.py <users.json> <conversations.json>...`: map usernames to DM conversation ids (`match.json`).
2. `collect.py <dumps_dir>`: find the saved DM-event dumps for those conversations (`files.json`).
3. `dec.py`: decrypt those threads with an xchat-lite style decrypter (not included) and print each thread, marking whether the last message was yours or theirs (`dec.json`).

`dec.py` needs your own `XCHAT_USER_ID`, `XCHAT_KEY_VERSION`, `XCHAT_SIGNING_KEYS` (path to a keys file) and `XCHAT_LITE` (path to the decrypter) in the environment. Keep the keys file outside the repo. Output files hold real usernames and DM text, so `.gitignore` keeps every `*.json` here out of git.
