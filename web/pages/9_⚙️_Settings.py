"""
管理员设置页面（URL 参数鉴权）

访问方式：
  /settings?k=<admin_password>  → 验证通过，session 内持续有效
  /settings                     → 静默跳回首页，无任何提示
"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent  # web/pages → web → Pixelle-Video
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
    """带显示/隐藏切换的密钥输入行（默认遮盖）"""
    revealed = st.session_state.reveal_keys.get(field_key, False)
    col1, col2 = st.columns([5, 1])
    with col1:
        new_val = st.text_input(
            label,
            value=current_value if revealed else "",
            placeholder=_mask(current_value),
            type="default" if revealed else "password",
            key=f"input_{field_key}",
        )
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
    new_rh_ent = _key_field("企业级-共享 API Key（兜底）",  "rh_enterprise", cfg.runninghub.api_key)
    new_rh_con = _key_field("消费级会员 API Key（首选）",   "rh_consumer",   cfg.runninghub.consumer_api_key)
    new_rh_url = st.text_input("RunningHub Base URL（留空用默认）",
                               value=cfg.runninghub.base_url or "",
                               key="input_rh_url",
                               placeholder="https://www.runninghub.cn  （国内）")
    new_rh_concurrent = st.number_input("最大并发数", value=cfg.runninghub.concurrent_limit,
                                        min_value=1, max_value=20, key="input_rh_concurrent")

# ── 3. ComfyUI 本地配置 ───────────────────────────────────────────
with st.expander("🖥️ ComfyUI 本地（自托管，可选）"):
    new_comfy_url = st.text_input("ComfyUI URL", value=cfg.comfyui.url or "",
                                  key="input_comfy_url", placeholder="http://127.0.0.1:8188")
    new_comfy_key = _key_field("ComfyUI API Key（可选）", "comfy_key", cfg.comfyui.api_key or "")

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

st.divider()

# ── 保存 ──────────────────────────────────────────────────────────
if st.button("💾 保存配置", type="primary", use_container_width=True):
    updates: dict = {
        "llm": {
            "api_key":  new_llm_key,
            "base_url": new_llm_url.strip(),
            "model":    new_llm_model.strip(),
        },
        "runninghub": {
            "api_key":          new_rh_ent,
            "consumer_api_key": new_rh_con,
            "base_url":         new_rh_url.strip() or None,
            "concurrent_limit": int(new_rh_concurrent),
        },
        "comfyui": {
            "url":     new_comfy_url.strip() or None,
            "api_key": new_comfy_key or None,
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
