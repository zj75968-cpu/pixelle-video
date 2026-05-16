"""
管理员设置页面（URL 参数鉴权）

访问方式：
  /settings?k=<admin_password>  → 验证通过，session 内持续有效
  /settings                     → 静默跳回首页，无任何提示
"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent  # web/pages/file → web/pages → web → Pixelle-Video
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from pixelle_video.config import config_manager

# 每次渲染前重新加载配置，确保使用最新的 admin_password
config_manager.reload()
cfg = config_manager.config

st.markdown("""
<style>
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stMainBlockContainer"] {
    max-width: 860px !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}
</style>
""", unsafe_allow_html=True)

# ── session state 初始化 ──────────────────────────────────────────
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "reveal_keys" not in st.session_state:
    st.session_state.reveal_keys = {}

# ════════════════════════════════════════════════════════════════════
# 鉴权：URL 参数 ?k=<password>
# ════════════════════════════════════════════════════════════════════
if not st.session_state.is_admin:
    required_key = cfg.admin_password.strip()
    url_key = st.query_params.get("k", "")

    if not required_key:
        # 未设置密码，直接放行
        st.session_state.is_admin = True
        st.rerun()
    elif url_key == required_key:
        # URL 参数正确：清除参数（避免密钥留在地址栏），进入设置
        st.session_state.is_admin = True
        st.query_params.clear()
        st.rerun()
    else:
        # 无效或无参数：静默跳回首页
        st.switch_page("pages/1_🎨_创作.py")
        st.stop()


# ════════════════════════════════════════════════════════════════════
# 以下为管理员可见的完整设置界面
# ════════════════════════════════════════════════════════════════════

def _mask(value: str) -> str:
    if not value:
        return "（未设置）"
    if len(value) <= 10:
        return "••••••••"
    return f"{value[:4]}{'•' * min(16, len(value) - 8)}{value[-4:]}"


def _key_field(label: str, field_key: str, current_value: str):
    """带显示/隐藏切换的密钥输入行。
    隐藏时只读显示遮码；显示时渲染不同 key 的输入框，避免 Streamlit 用旧 session state 覆盖 value。
    """
    revealed = st.session_state.reveal_keys.get(field_key, False)
    col1, col2 = st.columns([5, 1])
    with col1:
        if revealed:
            # 使用 _r 后缀 key，首次渲染时 session state 不存在，value=current_value 生效
            new_val = st.text_input(label, value=current_value, key=f"input_{field_key}_r")
        else:
            # 隐藏态：disabled 只读，仅展示遮码，不参与表单值
            st.text_input(label, value=_mask(current_value), disabled=True, key=f"input_{field_key}_h")
            new_val = current_value  # 未修改，沿用原值
    with col2:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        if st.button("隐藏" if revealed else "显示", key=f"toggle_{field_key}", use_container_width=True):
            st.session_state.reveal_keys[field_key] = not revealed
            st.rerun()
    return new_val.strip() if new_val.strip() else current_value


col_title, col_logout = st.columns([6, 1])
with col_title:
    st.title("⚙️ 管理员设置")
with col_logout:
    st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
    if st.button("退出", use_container_width=True):
        st.session_state.is_admin = False
        st.session_state.reveal_keys = {}
        st.switch_page("pages/1_🎨_创作.py")

st.caption("修改完成后点击底部「💾 保存配置」生效。")

# ════════════════════════════════════════════════════════════════════
# 部署状态仪表盘
# ════════════════════════════════════════════════════════════════════
with st.expander("📊 部署状态总览", expanded=True):
    _do_live_check = st.button("🔍 实时检测", key="btn_live_check")

    def _status_card(label: str, ok: bool, detail: str = ""):
        icon = "✅" if ok else "❌"
        color = "#1a7a1a" if ok else "#a00000"
        bg = "#e8f5e9" if ok else "#ffebee"
        border = "#4caf50" if ok else "#ef9a9a"
        st.markdown(
            f"""<div style="border:1px solid {border};border-radius:8px;padding:10px 14px;
            background:{bg};margin-bottom:6px">
            <span style="font-size:1.1em;font-weight:600;color:{color}">{icon} {label}</span>
            {"<br><span style='font-size:.85em;color:#555'>" + detail + "</span>" if detail else ""}
            </div>""",
            unsafe_allow_html=True,
        )

    # ── LLM ──
    llm_ok = bool(cfg.llm.api_key and cfg.llm.base_url and cfg.llm.model)
    llm_detail = ""
    if _do_live_check and llm_ok:
        try:
            import httpx
            r = httpx.get(cfg.llm.base_url.rstrip("/").rsplit("/v1", 1)[0] + "/v1/models",
                          headers={"Authorization": f"Bearer {cfg.llm.api_key}"},
                          timeout=5)
            llm_detail = f"连接正常，HTTP {r.status_code}" if r.status_code < 400 else f"HTTP {r.status_code}"
        except Exception as e:
            llm_detail = f"连接失败: {e}"
    elif llm_ok:
        llm_detail = f"模型: {cfg.llm.model}"
    else:
        llm_detail = "API Key / Base URL / 模型 未完整配置"

    # ── RunningHub ──
    rh_ok = bool(cfg.comfyui.runninghub_consumer_api_key or cfg.comfyui.runninghub_api_key)
    rh_detail = "消费级 Key 已配置" if cfg.comfyui.runninghub_consumer_api_key else (
        "企业级 Key 已配置" if cfg.comfyui.runninghub_api_key else "API Key 未配置"
    )

    # ── Phone Agent ──
    pa_url = cfg.phone_agent.url.strip()
    pa_ok = False
    pa_detail = "URL 未配置"
    if pa_url:
        if _do_live_check:
            from pixelle_video.services.phone_agent_client import ping
            pa_ok = ping(pa_url, token=cfg.phone_agent.token.strip(), timeout=5)
            pa_detail = f"在线 ({pa_url.split('//')[1][:30]}...)" if pa_ok else f"无法连接: {pa_url[:40]}..."
        else:
            pa_ok = True  # 有 URL 就认为配置完成
            pa_detail = pa_url.split("//")[1][:40] + "..."

    # ── ADB 设备 ──
    try:
        from pixelle_video.services.device_manager import device_manager as _dm
        connected_devices = [d for d in _dm.get_all() if d.connected]
        adb_ok = len(connected_devices) > 0
        adb_detail = f"{len(connected_devices)} 台已连接" if adb_ok else "无已连接设备（可选）"
    except Exception:
        adb_ok = False
        adb_detail = "设备管理器加载失败"

    # ── ComfyUI 本地 ──
    comfy_ok = bool(cfg.comfyui.comfyui_url)
    comfy_detail = cfg.comfyui.comfyui_url or "未配置（使用 RunningHub 则可跳过）"

    # 渲染卡片（2列布局）
    col_a, col_b = st.columns(2)
    with col_a:
        _status_card("LLM 语言模型", llm_ok, llm_detail)
        _status_card("Phone Agent（HTTP）", pa_ok, pa_detail)
        _status_card("ComfyUI 本地（可选）", comfy_ok, comfy_detail)
    with col_b:
        _status_card("RunningHub API", rh_ok, rh_detail)
        _status_card("ADB 已连接设备（可选）", adb_ok, adb_detail)

    # 总体状态
    core_ok = llm_ok and rh_ok
    st.markdown(
        f"**总体状态：{'🟢 核心配置完整，可正常使用' if core_ok else '🔴 请完善核心配置（LLM + RunningHub）'}**"
    )

st.divider()

# ── 1. LLM 配置 ───────────────────────────────────────────────────
with st.expander("🤖 LLM 语言模型（文案生成）", expanded=True):
    new_llm_key   = _key_field("API Key",  "llm_api_key",  cfg.llm.api_key)
    new_llm_url   = st.text_input("Base URL",  value=cfg.llm.base_url,  key="input_llm_url",
                                  placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1")
    new_llm_model = st.text_input("模型名称",  value=cfg.llm.model,     key="input_llm_model",
                                  placeholder="qwen-max")

# ── 2. RunningHub 配置 ────────────────────────────────────────────
with st.expander("☁️ RunningHub API（图片/视频生成）", expanded=True):
    new_rh_ent = _key_field("企业级-共享 API Key（兆底）",  "rh_enterprise", cfg.comfyui.runninghub_api_key or "")
    new_rh_con = _key_field("消费级会员 API Key（首选）",   "rh_consumer",   cfg.comfyui.runninghub_consumer_api_key or "")
    new_rh_url = st.text_input("RunningHub Base URL（留空用默认）",
                               value=cfg.comfyui.runninghub_base_url or "",
                               key="input_rh_url",
                               placeholder="https://www.runninghub.cn  （国内）")
    new_rh_concurrent = st.number_input("最大并发数", value=cfg.comfyui.runninghub_concurrent_limit,
                                        min_value=1, max_value=20, key="input_rh_concurrent")

# ── 3. ComfyUI 本地配置 ───────────────────────────────────────────
with st.expander("🖥️ ComfyUI 本地（自托管，可选）"):
    new_comfy_url = st.text_input("ComfyUI URL", value=cfg.comfyui.comfyui_url or "",
                                  key="input_comfy_url", placeholder="http://127.0.0.1:8188")
    new_comfy_key = _key_field("ComfyUI API Key（可选）", "comfy_key", cfg.comfyui.comfyui_api_key or "")

# ── 4. 修改管理员密钥 ────────────────────────────────────────────
with st.expander("🔑 修改管理员访问密钥"):
    st.caption("修改后，新的访问链接为 /settings?k=新密钥")
    new_admin_key1 = st.text_input("新密钥", type="password", key="input_admin_key1")
    new_admin_key2 = st.text_input("确认新密钥", type="password", key="input_admin_key2")

# ── 5. RunningHub 工作流 ID ───────────────────────────────────────
with st.expander("🔗 RunningHub 工作流 ID"):
    workflow_dir = _project_root / "workflows" / "runninghub"
    wf_items = []
    if workflow_dir.exists():
        wf_files = sorted(workflow_dir.glob("*.json"))
        cols = st.columns(2)
        for i, wf_path in enumerate(wf_files):
            try:
                data = json.loads(wf_path.read_text(encoding="utf-8"))
                old_id = data.get("workflow_id", "")
                with cols[i % 2]:
                    new_id = st.text_input(wf_path.stem, value=old_id, key=f"wf_{wf_path.stem}")
                wf_items.append((wf_path, new_id, data))
            except Exception:
                pass

# ── 6. Phone Agent 配置 ─────────────────────────────────────────
with st.expander("📱 手机 HTTP Agent（替代 USB ADB）"):
    st.caption(
        "配置后，将优先通过 HTTP Agent 推送文件到手机，无需 USB 连接或 ADB。\n"
        "手机端运行：`python scripts/phone_agent.py --token 你的token --port 7777`\n"
        "穿透地址：`cloudflared tunnel --url http://localhost:7777`，复制输出 URL 填入下方"
    )

    # ── 实时心跳状态（自动刷新）────────────────────────────────────
    from pixelle_video.services.phone_agent_client import (
        get_monitor, ensure_monitor_running,
    )
    ensure_monitor_running()

    @st.fragment(run_every="30s")
    def _render_heartbeat_badge():
        m = get_monitor()
        if not cfg.phone_agent.url.strip():
            return
        if m.is_online:
            last = m.last_seen.strftime("%H:%M:%S") if m.last_seen else "—"
            st.markdown(
                f'<span style="background:#e8f5e9;color:#1a7a1a;border:1px solid #4caf50;'
                f'border-radius:4px;padding:3px 10px;font-size:.9em">🟢 在线 · 最近: {last}</span>',
                unsafe_allow_html=True,
            )
        else:
            fails = m.consecutive_failures
            st.markdown(
                f'<span style="background:#ffebee;color:#a00000;border:1px solid #ef9a9a;'
                f'border-radius:4px;padding:3px 10px;font-size:.9em">'
                f'🔴 离线 · 连续失败: {fails} 次</span>',
                unsafe_allow_html=True,
            )

    _render_heartbeat_badge()

    _pa = cfg.phone_agent
    new_pa_url = st.text_input(
        "Agent URL",
        value=_pa.url or "",
        key="input_pa_url",
        placeholder="https://xxx-yyy-zzz.trycloudflare.com",
    )
    new_pa_token = _key_field("Agent Token", "pa_token", _pa.token or "")
    col_pa1, col_pa2 = st.columns(2)
    with col_pa1:
        new_pa_chunk = st.number_input(
            "分块大小（MB）",
            value=int(_pa.chunk_size_mb),
            min_value=1, max_value=50,
            key="input_pa_chunk",
        )
    with col_pa2:
        new_pa_timeout = st.number_input(
            "推送超时（秒）",
            value=int(_pa.timeout_push),
            min_value=30, max_value=600,
            key="input_pa_timeout",
        )
    if new_pa_url.strip():
        if st.button("📶 测试连接", key="btn_pa_ping"):
            from pixelle_video.services.phone_agent_client import ping
            ok = ping(new_pa_url.strip(), token=new_pa_token or "")
            if ok:
                st.success("✅ Agent 在线")
            else:
                st.error("❌ 无法连接，请检查 URL 和 Token")

st.divider()

# ── 保存 ──────────────────────────────────────────────────────────
if st.button("💾 保存配置", type="primary", use_container_width=True):
    updates: dict = {
        "llm": {
            "api_key":  new_llm_key,
            "base_url": new_llm_url.strip(),
            "model":    new_llm_model.strip(),
        },
        "comfyui": {
            "runninghub_api_key":          new_rh_ent or None,
            "runninghub_consumer_api_key": new_rh_con or None,
            "runninghub_base_url":         new_rh_url.strip() or None,
            "runninghub_concurrent_limit": int(new_rh_concurrent),
            "comfyui_url":     new_comfy_url.strip() or "http://127.0.0.1:8188",
            "comfyui_api_key": new_comfy_key or None,
        },
        "phone_agent": {
            "url":           new_pa_url.strip(),
            "token":         new_pa_token or "",
            "chunk_size_mb": int(new_pa_chunk),
            "timeout_push":  int(new_pa_timeout),
        },
    }

    if new_admin_key1:
        if new_admin_key1 == new_admin_key2:
            updates["admin_password"] = new_admin_key1
        else:
            st.error("两次输入的密钥不一致，管理员密钥未保存。")
            st.stop()

    # 写回工作流 JSON
    wf_errors = []
    for wf_path, new_id, data in wf_items:
        if new_id != data.get("workflow_id", ""):
            try:
                data["workflow_id"] = new_id
                wf_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                wf_errors.append(f"{wf_path.stem}: {e}")

    try:
        config_manager.update(updates)
        config_manager.save()
        if wf_errors:
            st.warning("部分工作流 ID 保存失败：" + "、".join(wf_errors))
        else:
            st.success("✅ 配置已保存！")
        st.session_state.reveal_keys = {}
        st.rerun()
    except Exception as e:
        st.error(f"保存失败：{e}")
