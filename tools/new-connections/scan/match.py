"""Map X usernames to their DM conversation ids.
Usage: python3 match.py <users.json> <conversations.json> [more conversations.json ...]
users.json: X users lookup output ({"data": [{"id", "username"}]}). Writes $SCAN_DIR/match.json (default: this folder)."""
import json, os, sys
L = lambda f: (lambda t: json.loads(t[t.find('{'):t.rfind('}') + 1]))(open(f).read())
OUT = os.environ.get("SCAN_DIR", os.path.dirname(os.path.abspath(__file__)))
u = L(sys.argv[1])
ids = {x['id']: x['username'] for x in u['data']}
m = {}
for f in sys.argv[2:]:
    c = L(f); print(c.get('meta'), file=sys.stderr)
    for cv in c['data']:
        if cv.get('type') != 'direct': continue
        for p in cv['participant_ids']:
            if p in ids: m[ids[p]] = cv['id']
json.dump({'ids': ids, 'm': m}, open(os.path.join(OUT, 'match.json'), 'w'))
print(len(m), sorted(m))
