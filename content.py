"""
绠＄悊鍛樿缃〉闈?
- 鏈櫥褰曟椂鏄剧ず瀵嗙爜杈撳叆妗?- 鐧诲綍鍚庢樉绀烘墍鏈夋晱鎰熼厤缃紙API Key 绛夛級锛屾敮鎸佹煡鐪?淇敼/淇濆瓨
"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent  # web/pages 鈫?web 鈫?Pixelle-Video
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from pixelle_video.config import config_manager

# 姣忔娓叉煋鍓嶉噸鏂板姞杞介厤缃紝纭繚 admin_password 绛夊瓧娈垫槸鏈€鏂板€?config_manager.reload()
cfg = config_manager.config
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

# 鈹€鈹€ session state 鍒濆鍖?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "reveal_keys" not in st.session_state:
    st.session_state.reveal_keys = {}


def _mask(value: str) -> str:
    """閬洊鏁忔劅瀛楃涓诧紝鍙樉绀洪灏惧悇 4 瀛楃"""
    if not value:
        return "锛堟湭璁剧疆锛?
    if len(value) <= 10:
        return "鈥⑩€⑩€⑩€⑩€⑩€⑩€⑩€?
    return f"{value[:4]}{'鈥? * min(16, len(value) - 8)}{value[-4:]}"


def _key_field(label: str, field_key: str, current_value: str):
    """娓叉煋涓€涓甫鏄剧ず/闅愯棌鍒囨崲鐨勫瘑閽ヨ緭鍏ヨ"""
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
        btn_label = "闅愯棌" if revealed else "鏄剧ず"
        if st.button(btn_label, key=f"toggle_{field_key}", use_container_width=True):
            st.session_state.reveal_keys[field_key] = not revealed
            st.rerun()
    # 鏈緭鍏ユ柊鍊兼椂淇濈暀鍘熷€?    return new_val.strip() if new_val.strip() else current_value


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
# 鏈櫥褰曪細鏄剧ず瀵嗙爜楠岃瘉
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
if not st.session_state.is_admin:
    st.title("鈿欙笍 绠＄悊鍛樿缃?)
    st.info("姝ら〉闈㈤渶瑕佺鐞嗗憳瀵嗙爜鎵嶈兘璁块棶銆傛櫘閫氱敤鎴锋棤闇€杩涘叆姝ら〉闈€?, icon="馃敀")

    required_pwd = cfg.admin_password.strip()

    if not required_pwd:
        # 鏈缃瘑鐮侊紝鐩存帴杩涘叆
        st.session_state.is_admin = True
        st.rerun()
    else:
        with st.form("admin_login_form"):
            pwd_input = st.text_input("绠＄悊鍛樺瘑鐮?, type="password", placeholder="璇疯緭鍏ュ瘑鐮?)
            submitted = st.form_submit_button("馃敁 鐧诲綍", use_container_width=True)
            if submitted:
                if pwd_input == required_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("瀵嗙爜閿欒锛岃閲嶈瘯銆?)
    st.stop()


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
# 宸茬櫥褰曪細鏄剧ず瀹屾暣璁剧疆
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
col_title, col_logout = st.columns([6, 1])
with col_title:
    st.title("鈿欙笍 绠＄悊鍛樿缃?)
with col_logout:
    st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
    if st.button("閫€鍑虹櫥褰?, use_container_width=True):
        st.session_state.is_admin = False
        st.session_state.reveal_keys = {}
        st.rerun()

st.caption("淇敼瀹屾垚鍚庣偣鍑诲簳閮ㄣ€岎煉?淇濆瓨閰嶇疆銆嶇敓鏁堛€傞噸鍚湇鍔″悗閰嶇疆浼氳嚜鍔ㄥ姞杞姐€?)
st.divider()

# 鈹€鈹€ 1. LLM 閰嶇疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
with st.expander("馃 LLM 璇█妯″瀷锛堟枃妗堢敓鎴愶級", expanded=True):
    new_llm_key    = _key_field("API Key",  "llm_api_key",  cfg.llm.api_key)
    new_llm_url    = st.text_input("Base URL",  value=cfg.llm.base_url,  key="input_llm_url",
                                   placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1")
    new_llm_model  = st.text_input("妯″瀷鍚嶇О",  value=cfg.llm.model,     key="input_llm_model",
                                   placeholder="qwen-max")

# 鈹€鈹€ 2. RunningHub 閰嶇疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
with st.expander("鈽侊笍 RunningHub API锛堝浘鐗?瑙嗛鐢熸垚锛?, expanded=True):
    new_rh_enterprise = _key_field(
        "浼佷笟绾?鍏变韩 API Key锛堝厹搴曪級",
        "rh_enterprise",
        cfg.comfyui.runninghub_api_key or "",
    )
    new_rh_consumer = _key_field(
        "娑堣垂绾т細鍛?API Key锛堥閫夛級",
        "rh_consumer",
        cfg.comfyui.runninghub_consumer_api_key or "",
    )
    new_rh_base_url = st.text_input(
        "RunningHub Base URL锛堢暀绌虹敤榛樿锛?,
        value=cfg.comfyui.runninghub_base_url or "",
        key="input_rh_base_url",
        placeholder="https://www.runninghub.cn  锛堝浗鍐咃級",
    )
    new_rh_concurrent = st.number_input(
        "鏈€澶у苟鍙戞暟",
        min_value=1, max_value=10,
        value=cfg.comfyui.runninghub_concurrent_limit,
        key="input_rh_concurrent",
    )

# 鈹€鈹€ 3. ComfyUI 鏈湴閰嶇疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
with st.expander("馃枼锔?ComfyUI 鏈湴锛堣嚜鎵樼锛屽彲閫夛級"):
    new_comfy_url = st.text_input(
        "ComfyUI URL",
        value=cfg.comfyui.comfyui_url,
        key="input_comfy_url",
        placeholder="http://127.0.0.1:8188",
    )
    new_comfy_key = _key_field("ComfyUI API Key锛堝彲閫夛級", "comfy_key", cfg.comfyui.comfyui_api_key or "")

# 鈹€鈹€ 4. 绠＄悊鍛樺瘑鐮佷慨鏀?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
with st.expander("馃攽 淇敼绠＄悊鍛樺瘑鐮?):
    new_admin_pwd1 = st.text_input("鏂板瘑鐮?, type="password", key="new_pwd1", placeholder="鐣欑┖鍒欎笉淇敼")
    new_admin_pwd2 = st.text_input("纭鏂板瘑鐮?, type="password", key="new_pwd2")
    if new_admin_pwd1 and new_admin_pwd1 != new_admin_pwd2:
        st.warning("涓ゆ杈撳叆鐨勫瘑鐮佷笉涓€鑷淬€?)

# 鈹€鈹€ 5. RunningHub 宸ヤ綔娴?ID 绠＄悊 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
_WF_DIR = _project_root / "workflows" / "runninghub"
_wf_files = sorted(_WF_DIR.glob("*.json"))

with st.expander("馃敆 RunningHub 宸ヤ綔娴?ID", expanded=False):
    st.caption("淇敼鍚庣偣鍑诲簳閮ㄣ€岎煉?淇濆瓨閰嶇疆銆嶄竴骞跺啓鍏ャ€?)
    wf_new_ids: dict[str, str] = {}
    cols = st.columns(2)
    for idx, wf_path in enumerate(_wf_files):
        try:
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        current_wf_id = wf_data.get("workflow_id", "")
        label = wf_path.stem  # 鏂囦欢鍚嶅幓鎺?.json
        with cols[idx % 2]:
            new_id = st.text_input(
                label,
                value=current_wf_id,
                key=f"wf_{wf_path.stem}",
            )
            wf_new_ids[str(wf_path)] = (new_id.strip(), wf_data)

st.divider()

# 鈹€鈹€ 淇濆瓨鎸夐挳 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
if st.button("馃捑 淇濆瓨閰嶇疆", type="primary", use_container_width=True):
    # 鏋勫缓鏇存柊瀛楀吀
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

    # 绠＄悊鍛樺瘑鐮侊紙浠呭綋涓ゆ杈撳叆涓€鑷翠笖闈炵┖鏃舵洿鏂帮級
    if new_admin_pwd1 and new_admin_pwd1 == new_admin_pwd2:
        updates["admin_password"] = new_admin_pwd1

    try:
        config_manager.update(updates)
        config_manager.save()

        # 鍐欏洖宸ヤ綔娴?ID
        wf_errors = []
        for wf_path_str, (new_id, wf_data) in wf_new_ids.items():
            if new_id and new_id != wf_data.get("workflow_id", ""):
                try:
                    wf_data["workflow_id"] = new_id
                    Path(wf_path_str).write_text(
                        json.dumps(wf_data, ensure_ascii=False, indent=4),
                        encoding="utf-8",
                    )
                except Exception as e:
                    wf_errors.append(f"{Path(wf_path_str).stem}: {e}")

        if wf_errors:
            st.warning("閮ㄥ垎宸ヤ綔娴?ID 淇濆瓨澶辫触锛? + "锛?.join(wf_errors))
        else:
            st.success("鉁?閰嶇疆宸蹭繚瀛橈紒鏂伴厤缃珛鍗崇敓鏁堬紙涓嬫鐢熸垚浠诲姟鏃朵娇鐢ㄦ柊 Key锛夈€?)

        # 娓呯┖鏄剧ず鐘舵€侊紝閬垮厤鏄庢枃娈嬬暀
        st.session_state.reveal_keys = {}
        st.rerun()
    except Exception as e:
        st.error(f"淇濆瓨澶辫触锛歿e}")
