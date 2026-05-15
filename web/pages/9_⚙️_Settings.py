"""
管理员设置页面

- 未登录时显示密码输入框
- 登录后显示所有敏感配置（API Key 等），支持查看/修改/保存
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from pixelle_video.config import config_manager

# ── 样式 ──────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stMainBlockContainer"] {
    max-width: 860px !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}
.secret-box {
    font-family: monospace;
    background: #1e1e1e;
    color: #d4d4d4;
    border-radius: 6px;
    padding: 6px 12px;
    word-break: break-all;
    font-size: 13px;
}
</style>
""", unsafe_allow_html=True)

# ── session state 初始化 ──────────────────────────────────────────
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "reveal_keys" not in st.session_state:
    st.session_state.reveal_keys = {}

cfg = config_manager.config


def _mask(value: str) -> str:
    """遮盖敏感字符串，只显示首尾各 4 字符"""
    if not value:
        return "（未设置）"
    if len(value) <= 10:
        return "••••••••"
    return f"{value[:4]}{'•' * min(16, len(value) - 8)}{value[-4:]}"


def _key_field(label: str, field_key: str, current_value: str):
    """渲染一个带显示/隐藏切换的密钥输入行"""
    revealed = st.session_state.reveal_keys.get(field_key, False)
    col1, col2 = st.columns([5, 1])
    with col1:
        display_val = current_value if revealed else _mask(current_value)
        new_val = st.text_input(
            label,
            value=current_value if revealed else "",
            placeholder=display_val,
            type="default" if revealed else "password",
            key=f"input_{field_key}",
        )
    with col2:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        btn_label = "隐藏" if revealed else "显示"
        if st.button(btn_label, key=f"toggle_{field_key}", use_container_width=True):
            st.session_state.reveal_keys[field_key] = not revealed
            st.rerun()
    # 未输入新值时保留原值
    return new_val.strip() if new_val.strip() else current_value


# ════════════════════════════════════════════════════════════════════
# 未登录：显示密码验证
# ════════════════════════════════════════════════════════════════════
if not st.session_state.is_admin:
    st.title("⚙️ 管理员设置")
    st.info("此页面需要管理员密码才能访问。普通用户无需进入此页面。", icon="🔒")

    required_pwd = cfg.admin_password.strip()

    if not required_pwd:
        # 未设置密码，直接进入
        st.session_state.is_admin = True
        st.rerun()
    else:
        with st.form("admin_login_form"):
            pwd_input = st.text_input("管理员密码", type="password", placeholder="请输入密码")
            submitted = st.form_submit_button("🔓 登录", use_container_width=True)
            if submitted:
                if pwd_input == required_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("密码错误，请重试。")
    st.stop()


# ════════════════════════════════════════════════════════════════════
# 已登录：显示完整设置
# ════════════════════════════════════════════════════════════════════
col_title, col_logout = st.columns([6, 1])
with col_title:
    st.title("⚙️ 管理员设置")
with col_logout:
    st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
    if st.button("退出登录", use_container_width=True):
        st.session_state.is_admin = False
        st.session_state.reveal_keys = {}
        st.rerun()

st.caption("修改完成后点击底部「💾 保存配置」生效。重启服务后配置会自动加载。")
st.divider()

# ── 1. LLM 配置 ───────────────────────────────────────────────────
with st.expander("🤖 LLM 语言模型（文案生成）", expanded=True):
    new_llm_key    = _key_field("API Key",  "llm_api_key",  cfg.llm.api_key)
    new_llm_url    = st.text_input("Base URL",  value=cfg.llm.base_url,  key="input_llm_url",
                                   placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1")
    new_llm_model  = st.text_input("模型名称",  value=cfg.llm.model,     key="input_llm_model",
                                   placeholder="qwen-max")

# ── 2. RunningHub 配置 ────────────────────────────────────────────
with st.expander("☁️ RunningHub API（图片/视频生成）", expanded=True):
    new_rh_enterprise = _key_field(
        "企业级-共享 API Key（兜底）",
        "rh_enterprise",
        cfg.comfyui.runninghub_api_key or "",
    )
    new_rh_consumer = _key_field(
        "消费级会员 API Key（首选）",
        "rh_consumer",
        cfg.comfyui.runninghub_consumer_api_key or "",
    )
    new_rh_base_url = st.text_input(
        "RunningHub Base URL（留空用默认）",
        value=cfg.comfyui.runninghub_base_url or "",
        key="input_rh_base_url",
        placeholder="https://www.runninghub.cn  （国内）",
    )
    new_rh_concurrent = st.number_input(
        "最大并发数",
        min_value=1, max_value=10,
        value=cfg.comfyui.runninghub_concurrent_limit,
        key="input_rh_concurrent",
    )

# ── 3. ComfyUI 本地配置 ───────────────────────────────────────────
with st.expander("🖥️ ComfyUI 本地（自托管，可选）"):
    new_comfy_url = st.text_input(
        "ComfyUI URL",
        value=cfg.comfyui.comfyui_url,
        key="input_comfy_url",
        placeholder="http://127.0.0.1:8188",
    )
    new_comfy_key = _key_field("ComfyUI API Key（可选）", "comfy_key", cfg.comfyui.comfyui_api_key or "")

# ── 4. 管理员密码修改 ─────────────────────────────────────────────
with st.expander("🔑 修改管理员密码"):
    new_admin_pwd1 = st.text_input("新密码", type="password", key="new_pwd1", placeholder="留空则不修改")
    new_admin_pwd2 = st.text_input("确认新密码", type="password", key="new_pwd2")
    if new_admin_pwd1 and new_admin_pwd1 != new_admin_pwd2:
        st.warning("两次输入的密码不一致。")

st.divider()

# ── 保存按钮 ──────────────────────────────────────────────────────
if st.button("💾 保存配置", type="primary", use_container_width=True):
    # 构建更新字典
    updates = {
        "llm": {
            "api_key":  new_llm_key,
            "base_url": new_llm_url.strip(),
            "model":    new_llm_model.strip(),
        },
        "comfyui": {
            "runninghub_api_key":          new_rh_enterprise or None,
            "runninghub_consumer_api_key": new_rh_consumer or None,
            "runninghub_base_url":         new_rh_base_url.strip() or None,
            "runninghub_concurrent_limit": int(new_rh_concurrent),
            "comfyui_url":                 new_comfy_url.strip(),
            "comfyui_api_key":             new_comfy_key or None,
        },
    }

    # 管理员密码（仅当两次输入一致且非空时更新）
    if new_admin_pwd1 and new_admin_pwd1 == new_admin_pwd2:
        updates["admin_password"] = new_admin_pwd1

    try:
        config_manager.update(updates)
        config_manager.save()
        st.success("✅ 配置已保存！新配置立即生效（下次生成任务时使用新 Key）。")
        # 清空显示状态，避免明文残留
        st.session_state.reveal_keys = {}
        st.rerun()
    except Exception as e:
        st.error(f"保存失败：{e}")
