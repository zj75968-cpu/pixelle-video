import asyncio, sys
from comfykit.comfyui.runninghub_client import RunningHubClient
from pixelle_video.config import config_manager

cfg = config_manager.get_comfyui_config()
rh = cfg.get('runninghub') or {}
api_key = cfg.get('runninghub_api_key') or rh.get('api_key')
c = RunningHubClient(api_key=api_key)
wf = asyncio.run(c.get_workflow_json(sys.argv[1]))
for nid, n in sorted(wf.items(), key=lambda kv: (kv[1].get('class_type', ''), kv[0])):
    title = (n.get('_meta') or {}).get('title')
    print(f"{nid}\t{n.get('class_type')}\ttitle={title}")
