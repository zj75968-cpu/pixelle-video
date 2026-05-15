import json
from pathlib import Path
p = Path(r"c:\Users\Administrator\Downloads\LTX2.3高清超自然电商数字人.json")
data = json.loads(p.read_text(encoding="utf-8"))
want = {172,173,179,183,38,106,14,39,153,60}
by = {n["id"]: n for n in data["nodes"]}
for nid in want:
    n = by.get(nid)
    if not n:
        continue
    print("="*20, nid, n.get("type"), n.get("title", ""))
    print(json.dumps(n.get("inputs", []), ensure_ascii=False, indent=2))
