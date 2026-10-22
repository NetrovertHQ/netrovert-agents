"""Find saved DM-event dumps for the matched conversations.
Usage: python3 collect.py <dumps_dir> [file to skip ...]
Reads $SCAN_DIR/match.json, writes $SCAN_DIR/files.json (default: this folder)."""
import json, glob, os, sys
L = lambda f: (lambda t: json.loads(t[t.find('{'):t.rfind('}') + 1]))(open(f).read())
OUT = os.environ.get("SCAN_DIR", os.path.dirname(os.path.abspath(__file__)))
m = json.load(open(os.path.join(OUT, 'match.json')))['m']
inv = {v: k for k, v in m.items()}
skip = {os.path.abspath(x) for x in sys.argv[2:]}
th = {}; senders = set()
for f in glob.glob(os.path.join(sys.argv[1], '*.txt')):
    if os.path.abspath(f) in skip: continue
    try: d = L(f)
    except Exception: continue
    if not isinstance(d.get('data'), list) or not d['data'] or 'encoded_event' not in d['data'][0]: continue
    cid = d['data'][0].get('conversation_id', '').replace(':', '-')
    if cid not in inv: continue
    th[cid] = {'f': f, 'd': d}
for cid, v in th.items():
    d = v['d']; senders |= {e['sender_id'] for e in d['data'] if e.get('sender_id')}
    print(inv[cid], len(d['data']), d.get('meta', {}).get('has_more'), list(d.get('meta', {}).keys()))
print(len(th), ','.join(sorted(senders)))
json.dump({c: v['f'] for c, v in th.items()}, open(os.path.join(OUT, 'files.json'), 'w'))
