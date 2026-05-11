"""Check callability of all RunningHub workflow JSON files using configured key/base.

Outputs a markdown-style table; exits 0 even on per-file failures.
"""
import asyncio
import json
import sys
from pathlib import Path

from pixelle_video.config import config_manager
from comfykit.comfyui.runninghub_client import RunningHubClient


async def check_one(client: RunningHubClient, path: Path) -> tuple[str, str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return (path.name, "-", f"FILE_ERROR: {e}")
    wid = data.get("workflow_id")
    if not wid:
        return (path.name, "-", "NO_WORKFLOW_ID (likely raw-graph local workflow, not for cloud)")
    try:
        wf = await client.get_workflow_json(str(wid))
        return (path.name, str(wid), f"OK ({len(wf)} nodes)")
    except Exception as e:
        msg = str(e)
        # condense
        if "TOKEN_INVALID" in msg:
            msg = "TOKEN_INVALID (412) — key 无权访问该工作流"
        elif "WORKFLOW_NOT_FOUND" in msg or "not found" in msg.lower():
            msg = "WORKFLOW_NOT_FOUND"
        return (path.name, str(wid), f"FAIL: {msg[:120]}")


async def main() -> int:
    key = config_manager.config.comfyui.runninghub_api_key
    base = config_manager.config.comfyui.runninghub_base_url or "https://www.runninghub.ai"
    if not key:
        print("no api key configured")
        return 1

    workflows_dir = Path("workflows")
    rh_files = sorted((workflows_dir / "runninghub").glob("*.json"))
    sh_files = sorted((workflows_dir / "selfhost").glob("*.json"))

    client = RunningHubClient(api_key=key, base_url=base)

    print(f"# RunningHub workflows (base={base}, key={key[:8]}...{key[-6:]})\n")
    print("| file | workflow_id | status |")
    print("|---|---|---|")
    for p in rh_files:
        name, wid, status = await check_one(client, p)
        print(f"| {name} | {wid} | {status} |")

    print("\n# Selfhost workflows (need local ComfyUI; not checked online)\n")
    for p in sh_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            wid = data.get("workflow_id") or "(local graph)"
        except Exception as e:
            wid = f"FILE_ERROR: {e}"
        print(f"- {p.name}: {wid}")

    # Close session if any
    sess = getattr(client, "_session", None) or getattr(client, "session", None)
    if sess and hasattr(sess, "close"):
        try:
            await sess.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
