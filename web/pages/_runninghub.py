# Copyright (C) 2025 AIDC-AI
"""RunningHub 低价模型开通状态检测页面。"""

import asyncio
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n  # noqa: F401

st.set_page_config(page_title="RunningHub 低价模型", page_icon="🟢", layout="wide")
init_session_state()
init_i18n()

st.title("🟢 RunningHub 低价渠道模型状态")

st.warning(
    "⚠️ **限制说明**：这 18 个低价渠道模型属于 **Standard Model API**（`/openapi/v2/<model>`），"
    "服务端强制要求 **企业级-共享 API Key**。个人 Key 调用任意模型都会返回 "
    "`errorCode 1014 ACCESS_DENIED`，与是否「开通」无关。\n\n"
    "**没有企业级 Key 怎么办？** 请改用左侧导航的常规生成入口（文生图 / 文生视频 / 图生视频），"
    "底层走 **ComfyUI Workflow API**，已实测 `image_flux` / `video_wan2.2` / `i2v_LTX2` 等"
    "工作流可用个人 Key 直接出片。"
)

st.caption(
    "对当前 API Key 下的 18 个低价模型逐一探测。"
    "策略：发送只含 apiKey 的极简请求，服务端先校验 token —— "
    "若返回 412 TOKEN_INVALID 即视为未开通，1014 视为受限（需企业 Key），"
    "其它响应（包括缺参数错误）即视为已开通。"
)

# 一键开通入口
st.markdown(
    "👉 未开通的模型请到 "
    "[RunningHub 低价渠道总入口](https://www.runninghub.cn/call-api/search-api/standard-model) "
    "搜索模型名并点击「立即接入」。"
)

col_btn, col_info = st.columns([1, 3])
with col_btn:
    run = st.button("🚀 开始检测", type="primary", use_container_width=True)
with col_info:
    st.caption("耗时约 5~30 秒（并发 4，单模型约 1~2 秒）；不会消耗任何调用余额。")


async def _probe_all():
    from pixelle_video.services import runninghub_registry as reg
    from pixelle_video.services.runninghub_api_service import RunningHubAPIService

    svc = RunningHubAPIService()
    models = reg.list_models()
    sem = asyncio.Semaphore(4)

    async def _p(m):
        async with sem:
            r = await svc.probe_activation(m["rhEndpoint"])
            r["name"] = m["name"]
            r["category"] = m.get("category")
            return r

    return await asyncio.gather(*(_p(m) for m in models))


if run:
    with st.spinner("正在探测…"):
        try:
            results = asyncio.run(_probe_all())
        except RuntimeError:
            # 已有事件循环（streamlit 内部）时退化为新建循环
            loop = asyncio.new_event_loop()
            try:
                results = loop.run_until_complete(_probe_all())
            finally:
                loop.close()

    activated = [r for r in results if r["activated"] is True]
    inactivated = [r for r in results if r["activated"] is False]
    unknown = [r for r in results if r["activated"] is None]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总数", len(results))
    c2.metric("✅ 已开通", len(activated))
    c3.metric("❌ 未开通", len(inactivated))
    c4.metric("❓ 未知/异常", len(unknown))

    import pandas as pd

    df = pd.DataFrame([
        {
            "状态": "✅ 已开通" if r["activated"] is True else ("❌ 未开通" if r["activated"] is False else "❓ 未知"),
            "分类": r["category"],
            "名称": r["name"],
            "endpoint": r["endpoint"],
            "code": r["code"],
            "服务端消息": r["msg"],
        }
        for r in results
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    if inactivated:
        st.warning(f"还有 {len(inactivated)} 个模型未开通，可前往 RunningHub 一键接入。")
        with st.expander("未开通的 endpoint 列表", expanded=False):
            for r in inactivated:
                st.markdown(
                    f"- **{r['name']}**  \n  `{r['endpoint']}`  "
                    f"[去开通 ↗](https://www.runninghub.cn/call-api/search-api/standard-model?search={r['name']})"
                )
