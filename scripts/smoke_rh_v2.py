"""Smoke test for RunningHubV2Client against the consumer key in config.yaml.

Steps:
  1. Read runninghub_consumer_api_key from config.yaml.
  2. Upload a small local image via /openapi/v2/media/upload/binary.
  3. Call /openapi/v2/run/workflow/{digital_image workflow id} with minimal nodeInfo.
  4. Poll /openapi/v2/query a few times until SUCCESS/FAILED or timeout.

Prints every step's raw response so we can verify parsing.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pixelle_video.config import config_manager  # noqa: E402
from pixelle_video.services.runninghub_v2 import RunningHubV2Client  # noqa: E402


async def main() -> int:
    config_manager.reload()
    cfg = config_manager.get_comfyui_config()
    key = (cfg.get("runninghub_consumer_api_key") or "").strip()
    base_url = (cfg.get("runninghub_base_url") or "").strip() or None
    print(f"[smoke] consumer key present={bool(key)} len={len(key)}  base_url={base_url or 'default'}")
    if not key:
        print("[smoke] FAIL: no consumer key in config.yaml")
        return 2

    # Pick a small existing image as upload sample
    candidates = list((ROOT / "output").rglob("*.png"))[:1] or list((ROOT / "resources").rglob("*.png"))[:1]
    if not candidates:
        print("[smoke] FAIL: no .png available for upload")
        return 3
    sample = candidates[0]
    print(f"[smoke] uploading sample: {sample}")

    client = RunningHubV2Client(api_key=key, base_url=base_url)
    up = await client.upload_file(sample)
    print(f"[smoke] upload response data block: {json.dumps(up, ensure_ascii=False)}")
    ref = up.get("fileName") or up.get("download_url")
    if not ref:
        print("[smoke] FAIL: upload response missing fileName/download_url")
        return 4

    # Use digital_image workflow ID
    workflow_id = "2004120336125861890"
    node_info_list = [
        {"nodeId": "18", "fieldName": "image", "fieldValue": ref},
        {"nodeId": "17", "fieldName": "image", "fieldValue": ref},
        {"nodeId": "19", "fieldName": "text", "fieldValue": "smoke"},
    ]
    print(f"[smoke] run_workflow {workflow_id} nodeInfo={node_info_list}")
    try:
        create = await client.run_workflow(workflow_id=workflow_id, node_info_list=node_info_list)
    except Exception as exc:
        print(f"[smoke] run_workflow EXCEPTION: {exc}")
        return 5
    print(f"[smoke] run_workflow response: {json.dumps(create, ensure_ascii=False)[:800]}")
    task_id = create.get("taskId") or (create.get("data") or {}).get("taskId")
    if not task_id:
        print("[smoke] FAIL: no taskId in response")
        return 6

    print(f"[smoke] polling task {task_id} for up to 60s ...")
    try:
        final = await client.wait_for_task(task_id, poll_interval=5.0, max_wait_seconds=60)
        print(f"[smoke] final: {json.dumps(final, ensure_ascii=False)[:1000]}")
    except Exception as exc:
        print(f"[smoke] poll exception (may just be slow, not necessarily a bug): {exc}")

    print("[smoke] DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
