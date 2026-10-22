"""Decrypt the matched DM threads locally with an xchat-lite style decrypter and print who replied.
Env (all required, your own values; never commit them):
  XCHAT_USER_ID          your X user id
  XCHAT_KEY_VERSION      your DM key version
  XCHAT_SIGNING_KEYS     path to a JSON file with your signing keys
  XCHAT_LITE             path to xchat_lite.py (run with XCHAT_PYTHON, default python3)
Reads $SCAN_DIR/match.json and files.json, writes $SCAN_DIR/dec.json (private: gitignored)."""
import json, os, subprocess, sys
L = lambda f: (lambda t: json.loads(t[t.find('{'):t.rfind('}') + 1]))(open(f).read())
OUT = os.environ.get("SCAN_DIR", os.path.dirname(os.path.abspath(__file__)))
need = [k for k in ("XCHAT_USER_ID", "XCHAT_KEY_VERSION", "XCHAT_SIGNING_KEYS", "XCHAT_LITE") if not os.environ.get(k)]
if need: sys.exit("missing env: " + ", ".join(need))
ME = os.environ["XCHAT_USER_ID"]; KV = os.environ["XCHAT_KEY_VERSION"]
m = json.load(open(os.path.join(OUT, 'match.json')))['m']; inv = {v: k for k, v in m.items()}
files = json.load(open(os.path.join(OUT, 'files.json')))
keys = L(os.environ["XCHAT_SIGNING_KEYS"]); out = {}
for cid, f in files.items():
    d = L(f)
    inp = {'events': [e['encoded_event'] for e in d['data']], 'conversation_key_events': d['meta'].get('conversation_key_events', []), 'signing_keys': keys}
    r = subprocess.run([os.environ.get("XCHAT_PYTHON", "python3"), os.environ["XCHAT_LITE"], '--user-id', ME, '--key-version', KV, 'decrypt'],
                       input=json.dumps(inp), capture_output=True, text=True)
    try: j = json.loads(r.stdout)
    except Exception: out[inv[cid]] = {'err': r.stderr[-300:]}; continue
    msgs = []
    for x, e in zip(j.get('messages', []), d['data']):
        msgs.append({'at': e['created_at'][:16], 'me': e['sender_id'] == ME, 'text': (x.get('text') or x.get('notice') or '')[:300], 'status': x.get('status'), 'err': x.get('error')})
    out[inv[cid]] = {'cid': cid, 'msgs': sorted(msgs, key=lambda z: z['at'])}
json.dump(out, open(os.path.join(OUT, 'dec.json'), 'w'), ensure_ascii=False, indent=1)
for k, v in out.items():
    print('##', k)
    for x in v.get('msgs', []): print(' ', x['at'], 'ME ' if x['me'] else 'THEM', x['status'], x['text'][:160].replace('\n', ' '), x['err'] or '')
    if 'err' in v: print(v['err'])
