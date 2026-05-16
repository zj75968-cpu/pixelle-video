# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Image-Text Post Generation Page

Generate Xiaohongshu-style image-text posts with AI.
"""

import sys
import json
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.utils.async_helpers import run_async

st.set_page_config(
    page_title="图文创作 - AI Video Generator",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="collapsed",
)


POST_FORM_DEFAULTS = {
    "topic": "",
    "image_count": 6,
    "post_tone": "种草",
    "hashtag_count": 5,
    "template_size": "1080x1080",
    "style": "",
    "aspect_ratio": "（不指定）",
    "image_size": "（不指定）",
    "post_type": "content",
}


def _safe_load_json(file_path: Path) -> dict | None:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_recent_post_param_history(limit: int = 20) -> list[dict]:
    output_dir = _project_root / "output"
    if not output_dir.exists():
        return []

    items: list[dict] = []
    for task_dir in sorted([p for p in output_dir.iterdir() if p.is_dir()], reverse=True):
        params_path = task_dir / "post_params.json"
        if not params_path.exists():
            continue

        params = _safe_load_json(params_path)
        if not isinstance(params, dict):
            continue

        post_data = _safe_load_json(task_dir / "post.json") or {}
        title = str(post_data.get("title", "(无标题)"))
        saved_at = str(params.get("saved_at", ""))
        ts = saved_at[:16].replace("T", " ") if saved_at else task_dir.name
        label = f"{ts} | {title[:24]} | {task_dir.name}"
        items.append({
            "label": label,
            "task_id": task_dir.name,
            "params": params,
        })

        if len(items) >= limit:
            break

    return items


def _init_post_form_defaults():
    for key, value in POST_FORM_DEFAULTS.items():
        st.session_state.setdefault(f"post_form_{key}", value)


def _apply_model_config(prefix: str, cfg: dict | None):
    cfg = cfg or {}
    api_key = str(cfg.get("api_key", ""))
    base_url = str(cfg.get("base_url", ""))
    model = str(cfg.get("model", ""))

    st.session_state[f"{prefix}_api_key"] = api_key
    st.session_state[f"{prefix}_base_url"] = base_url
    st.session_state[f"{prefix}_model"] = model
    st.session_state[f"{prefix}_preset_select"] = "Custom"
    st.session_state[f"{prefix}_api_key_field_Custom"] = api_key
    st.session_state[f"{prefix}_base_url_field_Custom"] = base_url
    st.session_state[f"{prefix}_model_field_Custom"] = model


def _apply_history_params_to_form(params: dict):
    tones = ["种草", "干货", "日常", "搞笑", "情感"]
    template_sizes = ["1080x1080", "1080x1920", "1920x1080"]
    aspect_ratio_options = ["（不指定）", "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "4:5", "5:4", "1:4", "4:1", "1:8", "8:1", "21:9"]
    image_size_options = ["（不指定）", "1K", "2K", "4K", "512px"]

    st.session_state["post_form_topic"] = str(params.get("topic", ""))
    image_count = int(params.get("image_count", 6))
    hashtag_count = int(params.get("hashtag_count", 5))
    post_tone = str(params.get("post_tone", "种草"))
    template_size = str(params.get("template_size", "1080x1080"))
    aspect_ratio = str(params.get("aspect_ratio") or "（不指定）")
    image_size = str(params.get("image_size") or "（不指定）")

    st.session_state["post_form_image_count"] = max(3, min(9, image_count))
    st.session_state["post_form_post_tone"] = post_tone if post_tone in tones else "种草"
    st.session_state["post_form_hashtag_count"] = max(3, min(10, hashtag_count))
    st.session_state["post_form_template_size"] = template_size if template_size in template_sizes else "1080x1080"
    st.session_state["post_form_style"] = str(params.get("style", ""))
    st.session_state["post_form_aspect_ratio"] = aspect_ratio if aspect_ratio in aspect_ratio_options else "（不指定）"
    st.session_state["post_form_image_size"] = image_size if image_size in image_size_options else "（不指定）"
    _post_type = str(params.get("post_type", "content"))
    st.session_state["post_form_post_type"] = _post_type if _post_type in ("content", "traffic") else "content"

    _apply_model_config("post_content", params.get("content_llm"))
    _apply_model_config("post_image", params.get("image_llm"))


def _is_complete_override(cfg: dict | None) -> bool:
    if not cfg:
        return False
    return bool(cfg.get("api_key") and cfg.get("base_url") and cfg.get("model"))


def render_generate_form() -> dict | None:
    """Render the post generation input form. Returns params dict on submit."""
    # Polish button must live OUTSIDE st.form (form bodies only allow form_submit_button).
    from web.components.polish import render_polish_button
    polish_col, _ = st.columns([1, 5])
    with polish_col:
        render_polish_button(
            source_key="post_form_topic",
            kind="topic",
            label="✨ 润色主题",
            help_text="让创作主题更具体、更可执行",
            button_key="polish_post_topic",
        )

    with st.form("post_gen_form"):
        st.subheader("📝 图文帖子生成")

        topic = st.text_area(
            "创作主题",
            placeholder="例：去云南旅行的三天两夜，探索古镇、品尝当地美食。",
            height=80,
            key="post_form_topic",
        )

        # Post-type strategy selector (drives prompt strategy in the agent brain)
        post_type = st.radio(
            "帖子定位",
            options=["content", "traffic"],
            format_func=lambda x: "📚 干货帖（输出真实价值，长期保留）" if x == "content"
                                  else "📢 引流帖（钩子+CTA，引导互动）",
            key="post_form_post_type",
            horizontal=True,
            help="干货帖侧重知识价值；引流帖侧重制造钩子和引导互动",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            image_count = st.slider("图片数量", min_value=3, max_value=9, step=1, key="post_form_image_count")
        with col2:
            post_tone = st.selectbox(
                "文风",
                options=["种草", "干货", "日常", "搞笑", "情感"],
                key="post_form_post_tone",
            )
        with col3:
            hashtag_count = st.slider("话题标签数", min_value=3, max_value=10, key="post_form_hashtag_count")

        col4, col5, col6, col7 = st.columns(4)
        with col4:
            template_size = st.selectbox(
                "图片分辨率",
                options=["1080x1080", "1080x1920", "1920x1080"],
                key="post_form_template_size",
            )
        with col5:
            style = st.text_input(
                "图片风格（可选）",
                placeholder="例如：小清新、复古胶片、极简主义",
                key="post_form_style",
            )
        with col6:
            aspect_ratio_opt = st.selectbox(
                "宽高比 (aspectRatio)",
                options=["（不指定）", "1:1", "3:4", "4:3", "9:16", "16:9",
                         "2:3", "3:2", "4:5", "5:4", "1:4", "4:1", "1:8", "8:1", "21:9"],
                key="post_form_aspect_ratio",
                help="传给图像模型的 aspectRatio 参数（Gemini 等模型支持）",
            )
        with col7:
            image_size_opt = st.selectbox(
                "图片尺寸 (imageSize)",
                options=["（不指定）", "1K", "2K", "4K", "512px"],
                key="post_form_image_size",
                help="仅 Gemini 3 系列支持，其他模型忽略此参数",
            )

        submitted = st.form_submit_button("🚀 开始生成", width="stretch", type="primary")

    if submitted:
        if not topic.strip():
            st.error("请输入创作主题")
            return None
        return {
            "topic": topic.strip(),
            "image_count": image_count,
            "post_tone": post_tone,
            "template_size": template_size,
            "style": style.strip(),
            "hashtag_count": hashtag_count,
            "aspect_ratio": None if aspect_ratio_opt == "（不指定）" else aspect_ratio_opt,
            "image_size": None if image_size_opt == "（不指定）" else image_size_opt,
            "post_type": post_type,
        }
    return None


def render_result(result):
    """Render the generated post result."""
    if result is None:
        return

    content = result.content
    output_dir = Path(result.output_dir)

    st.success("✅ 图文帖子生成完成！")

    # Keep original topic for publish-page device theme matching.
    source_topic = st.session_state.get("last_post_params", {}).get("topic", "")

    col_content, col_images = st.columns([1, 1])

    with col_content:
        st.markdown("### 📋 帖子内容")
        st.markdown(f"**标题：** {content.title}")
        st.markdown("**正文：**")
        st.text_area("", value=content.body, height=200, disabled=True, label_visibility="collapsed")

        if content.hashtags:
            tags_str = "  ".join([f"`#{tag}`" for tag in content.hashtags])
            st.markdown(f"**话题标签：** {tags_str}")

        # Copy-ready combined text
        full_text = f"{content.title}\n\n{content.body}\n\n" + " ".join([f"#{t}" for t in content.hashtags])
        with st.expander("📋 一键复制全文"):
            st.text_area("", value=full_text, height=250, label_visibility="collapsed")

    with col_images:
        st.markdown("### 🖼️ 生成图片")
        images_dir = output_dir / "images"
        if images_dir.exists():
            img_files = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))
            if img_files:
                # Show images in a scrollable column grid
                cols = st.columns(min(3, len(img_files)))
                for i, img_path in enumerate(img_files):
                    with cols[i % len(cols)]:
                        st.image(str(img_path), caption=f"图 {i+1}", width="stretch")
            else:
                st.info("图片生成中或未找到图片文件")
        else:
            st.info("图片目录不存在，可能仍在生成中")

    # Preview HTML
    preview_path = output_dir / "post_preview.html"
    if preview_path.exists():
        with st.expander("🔍 预览 HTML"):
            with open(preview_path, encoding="utf-8") as f:
                st.components.v1.html(f.read(), height=600, scrolling=True)

    # Auto-push to device gallery
    st.markdown("---")
    st.markdown("### 📲 推送到手机相册")

    images_dir = output_dir / "images"
    img_files_to_push = []
    if images_dir.exists():
        img_files_to_push = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))

    from pixelle_video.services.phone_agent_client import push_images_auto
    from pixelle_video.services.device_manager import device_manager as dm

    if not source_topic or not img_files_to_push:
        st.info("无主题或无生成图片，跳过自动推送。")
    else:
        # Suggest devices by topic
        suggested = dm.suggest_devices_by_topic(source_topic, connected_only=True, threshold=0.0)
        
        if not suggested:
            st.info("💡 未找到相关主题的已连接设备，可在 📱 发布管理 里为设备添加主题标签。")
        else:
            col_device, col_auto = st.columns([3, 1])
            
            with col_device:
                # Show suggested devices with scores
                suggestions_text = "\n".join(
                    [f"**{dev.name or dev.serial}** (相似度 {score:.0%}) - {reason}"
                     for dev, score, reason in suggested[:3]]
                )
                st.markdown(f"**推荐设备：**\n{suggestions_text}")
            
            with col_auto:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("📤 推送到最优设备", key="auto_push_best", type="primary"):
                    best_device = suggested[0][0]  # Highest score
                    with st.spinner(f"正在推送 {len(img_files_to_push)} 张图片到 {best_device.name or best_device.serial}..."):
                        try:
                            result = push_images_to_gallery(
                                serial=best_device.serial,
                                local_paths=[str(p) for p in img_files_to_push],
                            )
                            if result["success"] > 0:
                                st.success(
                                    f"成功推送 {result['success']} 张图片到 {best_device.name or best_device.serial} 相册"
                                )
                            if result["failed"]:
                                st.error(f"{len(result['failed'])} 张推送失败")
                        except Exception as e:
                            st.error(f"推送失败：{e}")
            
            # Manual device selection
            with st.expander("🔧 手动选择设备推送"):
                all_devices = [d for d in dm.get_all() if d.connected]
                if all_devices:
                    device_options = {f"{d.name or d.serial} ({d.serial})": d.serial for d in all_devices}
                    selected_label = st.selectbox(
                        "选择设备",
                        options=list(device_options.keys()),
                        key="manual_push_device",
                    )
                    if st.button("💾 推送到此设备", key="manual_push_btn"):
                        selected_serial = device_options[selected_label]
                        with st.spinner(f"正在推送 {len(img_files_to_push)} 张图片..."):
                            try:
                                result = push_images_auto(
                                    serial=selected_serial,
                                    local_paths=[str(p) for p in img_files_to_push],
                                )
                                if result["success"] > 0:
                                    st.success(f"成功推送 {result['success']} 张图片")
                                if result["failed"]:
                                    st.error(f"{len(result['failed'])} 张推送失败")
                            except Exception as e:
                                st.error(f"推送失败：{e}")
                else:
                    st.warning("暂无已连接设备，请先在 📱 发布管理 中连接手机。")

    # Publish button shortcut
    st.markdown("---")
    col_tip, col_btn = st.columns([3, 1])
    with col_tip:
        st.markdown("**发布到小红书？** 点击右侧按钮前往发布管理创建发布任务")
    with col_btn:
        if st.button("📱 前往发布管理", width="stretch"):
            st.switch_page("pages/4_📱_Publish.py")

    # Store result in session for publish page
    st.session_state["last_post_result"] = {
        "task_id": result.task_id,
        "output_dir": str(result.output_dir),
        "topic": source_topic,
        "title": content.title,
        "body": content.body,
        "hashtags": content.hashtags,
        "images": [str(p) for p in sorted((output_dir / "images").glob("*.png"))],
    }


def main():
    init_session_state()
    init_i18n()

    st.title("📝 图文帖子生成")
    st.caption("AI 驱动的小红书图文帖子一键生成")

    _init_post_form_defaults()

    # Apply pending history params before model widgets are instantiated.
    pending_history = st.session_state.pop("_pending_history_params", None)
    if pending_history:
        _apply_history_params_to_form(pending_history)
        st.success("已应用历史参数到表单")

    # Per-post model overrides removed — use global config from admin settings
    content_llm = None
    image_llm = None

    with st.expander("🕘 历史参数复用（避免重复填写）", expanded=False):
        history_items = _list_recent_post_param_history(limit=20)
        if not history_items:
            st.caption("暂无可复用历史。完成一次生成后会自动记录参数。")
        else:
            labels = [item["label"] for item in history_items]
            selected_label = st.selectbox("选择历史参数", options=labels, key="post_history_select")
            chosen = next((item for item in history_items if item["label"] == selected_label), None)
            if chosen and st.button("应用到表单", width="stretch"):
                st.session_state["_pending_history_params"] = chosen["params"]
                st.rerun()
    # �?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?

    # Generation form
    params = render_generate_form()

    pipeline_params = None
    history_snapshot = None
    if params:
        # Build pipeline parameters separately from history payload.
        pipeline_params = dict(params)
        pipeline_params["content_llm"] = content_llm if _is_complete_override(content_llm) else None
        pipeline_params["image_llm"] = image_llm if _is_complete_override(image_llm) else None

        history_snapshot = {
            "topic": params.get("topic", ""),
            "image_count": params.get("image_count", 6),
            "post_tone": params.get("post_tone", "种草"),
            "template_size": params.get("template_size", "1080x1080"),
            "style": params.get("style", ""),
            "hashtag_count": params.get("hashtag_count", 5),
            "aspect_ratio": params.get("aspect_ratio"),
            "image_size": params.get("image_size"),
            "post_type": params.get("post_type", "content"),
            "content_llm": content_llm or {},
            "image_llm": image_llm or {},
            "saved_at": datetime.now().isoformat(),
        }

    if pipeline_params:
        pixelle_video = get_pixelle_video()
        pipeline = pixelle_video.pipelines.get("image_text_post")
        if pipeline is None:
            st.error("图文流水线未初始化，请检查配置")
            return

        with st.spinner(f"正在为「{pipeline_params['topic']}」生成图文帖子..."):
            try:
                st.session_state["last_post_params"] = pipeline_params
                result = run_async(pipeline(**pipeline_params))
                st.session_state["post_result"] = result

                history_params = history_snapshot or {}
                (Path(result.output_dir) / "post_params.json").write_text(
                    json.dumps(history_params, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                st.error(f"生成失败：{e}")
                return

    # Show result (persists after rerun)
    if "post_result" in st.session_state:
        render_result(st.session_state["post_result"])


if __name__ == "__main__":
    main()


