# Copyright (C) 2025 AIDC-AI
"""RunningHub 低价模型 · API 调试面板.

复刻官方「API 标签页」体验：左侧选模型 + 展示 **全部** 请求参数（含 prompt / aspectRatio / resolution
/ duration / seed / 图片输入...），右侧一键发送 + 显示结果。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from pixelle_video.services import runninghub_registry as reg
from web.state.session import init_session_state, init_i18n


st.set_page_config(page_title="API 调试", page_icon="🧪", layout="wide")
init_session_state()
init_i18n()

st.title("🧪 RunningHub 低价模型 · API 调试")
st.caption(
    "复刻官方「API」标签页：所有参数原样呈现，可一键发送并查看结果。所有字段都来自 registry，"
    "与 runninghub.cn 官方 API 文档保持一致。"
)

st.warning(
    "⚠️ **限制说明**：这 18 个「低价渠道版」属于 RunningHub **Standard Model API**，"
    "官方限制必须使用「**企业级-共享 API Key**」才能调用（个人 Key 会得到 `errorCode=1014 Access Denied`）。\n\n"
    "**没有企业级 Key 怎么办？** 请改用左侧导航的常规生成入口（🎨 i2v / 🖼️ style_config 等），"
    "它们走的是 **ComfyUI Workflow API**（`workflows/runninghub/*.json`），\n"
    "**个人 API Key 完全可调用**，已通过端到端实测 ✅。\n\n"
    "如需开通：到 [RunningHub 控制台](https://www.runninghub.cn/) → API 中心 → 申请「企业级-共享 API Key」。"
)

models = reg.list_models()
if not models:
    st.error("registry 为空，请检查 runninghub_lowprice_registry.json")
    st.stop()


def _label(m: dict) -> str:
    cat = m.get("category") or "other"
    return f"[{cat}] {m['name']}  —  {m['rhEndpoint']}"


# ------------------------------------------------------------
# 左：模型选择 + 信息
# ------------------------------------------------------------
left, right = st.columns([1, 1], gap="large")

with left:
    keys = [m["workflow_key"] for m in models]
    idx = st.selectbox(
        "选择模型",
        options=list(range(len(models))),
        format_func=lambda i: _label(models[i]),
    )
    model = models[idx]

    st.markdown(f"**接口：** `{model['rhEndpoint']}`")
    cols = st.columns(3)
    cols[0].metric("类别", model.get("category") or "-")
    cols[1].metric("priceType", model.get("priceType", "-"))
    cols[2].metric("输入字段数", len(model.get("inputs") or []))

    if model.get("modelHighlights"):
        st.info(f"💡 {model['modelHighlights']}")
    if model.get("description"):
        with st.expander("description", expanded=False):
            st.write(model["description"])

    # ----- 高级选项 -----
    adv_cols = st.columns(2)
    use_plus = adv_cols[0].checkbox(
        "⚡ 使用 plus 独立实例",
        value=False,
        help="走独立 GPU 队列，大幅降低 1011（模型繁忙）概率，单价略高。",
        key="rh_api_dbg_use_plus",
    )
    auto_retry = adv_cols[1].checkbox(
        "🔁 1011 模型繁忙时自动重试",
        value=True,
        help="任务因 1011 失败时按 30s/60s/120s 退避重试，最多 3 次。",
        key="rh_api_dbg_auto_retry",
    )

    # ----- 参数表单：原样还原 -----
    st.markdown("### 📥 请求参数")
    st.caption("`*` 标记 = 必填；类型与 default 来自 registry")

    params: dict = {}
    image_uploads: dict = {}

    for f in model.get("inputs") or []:
        ftype = f.get("type")
        key = f["fieldKey"]
        title = f.get("title") or key
        required = bool(f.get("required"))
        default = f.get("defaultValue")
        desc = f.get("paramDesc") or ""
        label = f"{'*' if required else ''}{title}"

        widget_key = f"rh_api_dbg__{model['workflow_key']}__{key}"

        if ftype == "STRING":
            max_len = f.get("maxLength") or 0
            if max_len and max_len > 200:
                params[key] = st.text_area(
                    label, value=default or "", help=desc, height=120, key=widget_key
                )
            else:
                params[key] = st.text_input(
                    label, value=default or "", help=desc, key=widget_key
                )
        elif ftype == "LIST":
            opts = [o["value"] for o in (f.get("options") or [])]
            default_idx = opts.index(default) if default in opts else 0
            params[key] = st.selectbox(
                label, options=opts, index=default_idx, help=desc, key=widget_key
            )
        elif ftype == "INT":
            mn = f.get("minValue")
            mx = f.get("maxValue")
            params[key] = st.number_input(
                label,
                value=int(default) if default is not None else (mn or 0),
                min_value=mn if mn is not None else None,
                max_value=mx if mx is not None else None,
                step=1,
                help=desc,
                key=widget_key,
            )
        elif ftype == "BOOLEAN":
            params[key] = st.checkbox(
                label, value=bool(default), help=desc, key=widget_key
            )
        elif ftype == "IMAGE":
            multi = bool(f.get("multipleInputs"))
            uploaded = st.file_uploader(
                label,
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=multi,
                help=(desc or "") + ("（可多张）" if multi else ""),
                key=widget_key,
            )
            image_uploads[key] = (uploaded, multi)
        elif ftype == "VIDEO":
            uploaded = st.file_uploader(
                label, type=["mp4", "mov", "webm"], help=desc, key=widget_key
            )
            image_uploads[key] = (uploaded, False)  # 同样的上传逻辑
        else:
            st.warning(f"未知字段类型 {ftype}（{key}），跳过")

    submit = st.button(
        "🚀 发送请求", type="primary", use_container_width=True, key="rh_api_dbg_submit"
    )


# ------------------------------------------------------------
# 右：请求体预览 + 结果
# ------------------------------------------------------------
with right:
    st.markdown("### 📄 请求体预览")
    preview = {k: v for k, v in params.items() if v not in (None, "")}
    for k, (u, multi) in image_uploads.items():
        if u is None:
            continue
        if multi:
            preview[k] = [f.name for f in (u or [])]
        else:
            preview[k] = u.name
    if use_plus:
        preview["instanceType"] = "plus"
    st.code(
        f"POST https://www.runninghub.cn/openapi/v2{model['rhEndpoint']}\n"
        + f"Authorization: Bearer <API_KEY>\n"
        + f"Content-Type: application/json\n\n"
        + json.dumps(preview, ensure_ascii=False, indent=2),
        language="json",
    )
    if auto_retry:
        st.caption("🔁 已启用：1011 自动按 30s/60s/120s 退避重试 3 次。")

    st.markdown("### 🎬 结果")
    result_box = st.empty()


async def _send():
    from pixelle_video.services.runninghub_api_service import RunningHubAPIService

    api_svc = RunningHubAPIService()
    image_params = {}
    for k, (u, multi) in image_uploads.items():
        if u is None:
            continue
        files = u if multi else [u]
        urls = []
        for f in files:
            suffix = Path(f.name).suffix or ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(f.getbuffer())
                tmp_path = tmp.name
            urls.append(await api_svc.upload_image(tmp_path))
        image_params[k] = urls if multi else urls[0]

    full_params = {**params, **image_params}
    full_params = {k: v for k, v in full_params.items() if v not in (None, "")}
    url = await api_svc.call_model(
        endpoint=model["rhEndpoint"],
        params=full_params,
        instance_type="plus" if use_plus else None,
        auto_retry_1011=auto_retry,
    )
    suffix = Path(url.split("?")[0]).suffix.lower()
    mtype = "video" if suffix in (".mp4", ".mov", ".webm") else "image"
    return url, mtype


if submit:
    # 校验必填
    missing = []
    for f in model.get("inputs") or []:
        if not f.get("required"):
            continue
        k = f["fieldKey"]
        if f["type"] in ("IMAGE", "VIDEO"):
            u, _ = image_uploads.get(k, (None, False))
            if not u:
                missing.append(k)
        elif not params.get(k):
            missing.append(k)
    if missing:
        result_box.error(f"以下必填字段为空：{missing}")
    else:
        with st.spinner("发送请求并轮询结果中（最长 600s）..."):
            try:
                try:
                    url, mtype = asyncio.run(_send())
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    try:
                        url, mtype = loop.run_until_complete(_send())
                    finally:
                        loop.close()
            except Exception as e:
                result_box.error(f"调用失败：{e}")
            else:
                with result_box.container():
                    st.success("✅ 调用成功")
                    st.write(f"**media_type:** `{mtype}`")
                    st.write(f"**url:** {url}")
                    if mtype == "video":
                        st.video(url)
                    else:
                        st.image(url)
