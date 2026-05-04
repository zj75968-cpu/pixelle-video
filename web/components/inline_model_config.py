"""
Inline Model Configuration Component

Renders a compact, self-contained LLM config card (preset + API Key + Base URL + Model).
State is stored in st.session_state under the given key_prefix — completely independent
from the global config_manager so it won't affect system-wide settings.
"""

import streamlit as st
from pixelle_video.llm_presets import get_preset_names, get_preset, find_preset_by_base_url_and_model
from pixelle_video.config import config_manager


def render_inline_model_config(key_prefix: str, label: str) -> dict:
    """
    Render a compact inline model configuration card.

    Parameters
    ----------
    key_prefix : str
        Unique prefix used for all st widget keys (e.g. "post_content", "post_image").
        Must be unique across the page to avoid widget key conflicts.
    label : str
        Header label displayed at the top of the card.

    Returns
    -------
    dict
        {"api_key": str, "base_url": str, "model": str}
        All values may be empty strings when the user has not filled them in.
    """
    preset_names = get_preset_names() + ["Custom"]

    # Retrieve persisted values (config.yaml), fallback to session_state during transition
    persisted = config_manager.get_post_model_preset(key_prefix)
    saved_api_key = st.session_state.get(
        f"{key_prefix}_api_key",
        persisted.get("api_key", ""),
    )
    saved_base_url = st.session_state.get(
        f"{key_prefix}_base_url",
        persisted.get("base_url", ""),
    )
    saved_model = st.session_state.get(
        f"{key_prefix}_model",
        persisted.get("model", ""),
    )

    # Auto-detect which preset matches the saved base_url + model
    current_preset = (
        find_preset_by_base_url_and_model(saved_base_url, saved_model)
        if saved_base_url else None
    )
    default_index = (
        preset_names.index(current_preset) if current_preset else len(preset_names) - 1
    )

    with st.container(border=True):
        st.markdown(f"**{label}**")

        selected_preset = st.selectbox(
            "快速选择",
            options=preset_names,
            index=default_index,
            key=f"{key_prefix}_preset_select",
            label_visibility="collapsed",
        )

        # Determine default field values based on the selected preset
        if selected_preset != "Custom":
            preset_cfg = get_preset(selected_preset)

            # Keep api_key only if this preset was already the saved one
            if selected_preset == current_preset:
                default_api_key = saved_api_key
            else:
                default_api_key = preset_cfg.get("default_api_key", "")

            default_base_url = preset_cfg.get("base_url", "")
            default_model    = preset_cfg.get("model", "")

            if preset_cfg.get("api_key_url"):
                st.caption(f"🔑 [获取 API Key]({preset_cfg['api_key_url']})")
        else:
            default_api_key  = saved_api_key
            default_base_url = saved_base_url
            default_model    = saved_model

        api_key = st.text_input(
            "API Key",
            value=default_api_key,
            type="password",
            placeholder="留空则使用系统全局配置",
            key=f"{key_prefix}_api_key_field_{selected_preset}",
        )

        col_url, col_model = st.columns([3, 2])
        with col_url:
            base_url = st.text_input(
                "Base URL",
                value=default_base_url,
                placeholder="https://api.openai.com/v1",
                key=f"{key_prefix}_base_url_field_{selected_preset}",
            )
        with col_model:
            model = st.text_input(
                "Model",
                value=default_model,
                placeholder="gpt-4o",
                key=f"{key_prefix}_model_field_{selected_preset}",
            )

    # Persist current values in session state and config file
    st.session_state[f"{key_prefix}_api_key"]  = api_key
    st.session_state[f"{key_prefix}_base_url"] = base_url
    st.session_state[f"{key_prefix}_model"]    = model

    current = config_manager.get_post_model_preset(key_prefix)
    if (
        current.get("api_key", "") != api_key
        or current.get("base_url", "") != base_url
        or current.get("model", "") != model
    ):
        config_manager.set_post_model_preset(key_prefix, api_key, base_url, model)
        config_manager.save()

    return {"api_key": api_key, "base_url": base_url, "model": model}
