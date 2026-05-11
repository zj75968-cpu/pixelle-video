import asyncio, json, sys
from comfykit.comfyui.runninghub_client import RunningHubClient
from pixelle_video.config import config_manager

cfg = config_manager.get_comfyui_config()
rh = cfg.get('runninghub') or {}
api_key = cfg.get('runninghub_api_key') or rh.get('api_key')
c = RunningHubClient(api_key=api_key)
wf = asyncio.run(c.get_workflow_json(sys.argv[1]))
ids = sys.argv[2:]
for nid in ids:
    n = wf.get(nid)
    if not n:
        print(f"{nid} NOT FOUND")
        continue
    print(f"=== {nid} {n.get('class_type')} title={(n.get('_meta') or {}).get('title')} ===")
    print(json.dumps(n.get('inputs') or {}, ensure_ascii=False, indent=2))
