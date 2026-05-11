"""Quick sanity check: can we fetch workflow JSON for given workflow_id using config key."""
import asyncio
import sys
from pixelle_video.config import config_manager
from comfykit.comfyui.runninghub_client import RunningHubClient


async def main(wid: str) -> int:
    key = config_manager.config.comfyui.runninghub_api_key
    base = config_manager.config.comfyui.runninghub_base_url or "https://www.runninghub.ai"
    print(f"[verify] base={base} key={key[:8]}...{key[-6:]}")
    client = RunningHubClient(api_key=key, base_url=base)
    try:
        wf = await client.get_workflow_json(wid)
        print(f"[verify] OK: workflow {wid} has {len(wf)} top-level nodes")
        return 0
    except Exception as e:
        print(f"[verify] FAIL: {type(e).__name__}: {e}")
        return 1
    finally:
        # close client session if exposed
        sess = getattr(client, "_session", None) or getattr(client, "session", None)
        if sess and hasattr(sess, "close"):
            try:
                await sess.close()
            except Exception:
                pass


if __name__ == "__main__":
    wid = sys.argv[1] if len(sys.argv) > 1 else "1991693844100100097"
    sys.exit(asyncio.run(main(wid)))
