"""批量探测 RunningHub 低价渠道模型在当前 API Key 下的开通状态。

用法：
    .venv\\Scripts\\python.exe scripts\\check_rh_activation.py

输出 ✅ 已开通 / ❌ 未开通 / ❓ 未知 三色清单，并以"summary"行收尾。
"""
import asyncio
import sys
from pathlib import Path

# Ensure project root on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pixelle_video.services import runninghub_registry as reg
from pixelle_video.services.runninghub_api_service import RunningHubAPIService


async def main() -> int:
    svc = RunningHubAPIService()
    models = reg.list_models()
    if not models:
        print("registry 为空")
        return 1

    print(f"开始探测 {len(models)} 个低价渠道模型（注意：未开通会得到 412，已开通会得到缺参数错误）...\n")

    results = []
    sem = asyncio.Semaphore(4)  # 控制并发，避免触发频控

    async def _probe(m):
        async with sem:
            r = await svc.probe_activation(m["rhEndpoint"])
            r["name"] = m["name"]
            r["category"] = m.get("category")
            return r

    results = await asyncio.gather(*(_probe(m) for m in models))

    activated, inactivated, unknown = [], [], []
    for r in results:
        flag = r["activated"]
        if flag is True:
            activated.append(r)
            sym = "✅"
        elif flag is False:
            inactivated.append(r)
            sym = "❌"
        else:
            unknown.append(r)
            sym = "❓"
        print(f"{sym} [{r['category']}] {r['name']}")
        print(f"    endpoint={r['endpoint']}  code={r['code']}  {r['msg']}")

    print("\n" + "=" * 60)
    print(f"总计 {len(models)}  ✅ 已开通 {len(activated)}  ❌ 未开通 {len(inactivated)}  ❓ 未知 {len(unknown)}")
    if inactivated:
        print("\n👉 请在 https://www.runninghub.cn/call-api/search-api/standard-model 搜索以下模型并点击「立即接入」：")
        for r in inactivated:
            print(f"   - {r['name']}  ({r['endpoint']})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
