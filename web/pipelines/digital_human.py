import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger
import httpx
from web.i18n import tr, get_language
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.components.content_input import render_version_info
from web.components.digital_tts_config import render_style_config
from web.utils.async_helpers import run_async
from web.utils.streamlit_helpers import check_and_warn_selfhost_workflow
from pixelle_video.config import config_manager
from pixelle_video.utils.os_util import create_task_output_dir


async def _try_runninghub_v2(
    *,
    workflow_id: str,
    node_info_list: list[dict],
    expected: str = "image",
):
    """Helper: run a RunningHub workflow via openapi/v2 using the consumer-tier API key.

    Returns one of:
        - {"url": "<image_url>", "text": "<optional_text>"}  if expected == "image"
        - {"url": "<video_url>"}                              if expected == "video"
    Returns None when:
        - consumer key not configured, or
        - v2 call/upload/poll/extract fails (caller should fall back to v1).
    """
    cfg = config_manager.get_comfyui_config()
    key = (cfg.get("runninghub_consumer_api_key") or "").strip()
    if not key:
        return None
    base_url = (cfg.get("runninghub_base_url") or "").strip() or None
    public_base = (cfg.get("public_base_url") or "").strip()
    webhook_url = f"{public_base.rstrip('/')}/webhooks/runninghub" if public_base else None
    try:
        from pixelle_video.services.runninghub_v2 import RunningHubV2Client
        client = RunningHubV2Client(api_key=key, base_url=base_url)
        create = await client.run_workflow(
            workflow_id=workflow_id,
            node_info_list=node_info_list,
            webhook_url=webhook_url,
        )
        task_id = create.get("taskId") or (create.get("data") or {}).get("taskId")
        if not task_id:
            raise RuntimeError(f"v2 run_workflow returned no taskId: {create}")
        if webhook_url:
            logger.info(
                f"[digital_human] v2 task {task_id} created with webhook={webhook_url}, awaiting callback"
            )
            final = await client.wait_via_webhook(task_id)
        else:
            logger.info(f"[digital_human] v2 task {task_id} created, polling (no public_base_url)")
            final = await client.wait_for_task(task_id)
        if (final.get("status") or "").upper() != "SUCCESS":
            raise RuntimeError(f"v2 task non-success: {final}")
        results = final.get("results") or []
        image_url = None
        video_url = None
        text_val = None
        for r in results:
            otype = (r.get("outputType") or "").lower()
            if otype in ("png", "jpg", "jpeg", "webp") and image_url is None:
                image_url = r.get("url")
            if otype in ("mp4", "webm", "mov") and video_url is None:
                video_url = r.get("url")
            if (otype == "txt" or r.get("text")) and text_val is None:
                text_val = r.get("text")
        if expected == "image":
            if not image_url:
                raise RuntimeError(f"v2 task SUCCESS but no image in results: {results}")
            return {"url": image_url, "text": text_val}
        elif expected == "video":
            if not video_url:
                raise RuntimeError(f"v2 task SUCCESS but no video in results: {results}")
            return {"url": video_url}
        else:
            raise ValueError(f"unknown expected type: {expected}")
    except Exception as exc:
        logger.warning(f"[digital_human] v2 path failed (workflow_id={workflow_id}, expected={expected}): {exc}")
        return None


async def _rh_v2_upload(local_path) -> str | None:
    """Upload a local file via openapi/v2 with consumer key. Returns a fileName/url string,
    or None if consumer key not configured. Raises on actual upload errors."""
    cfg = config_manager.get_comfyui_config()
    key = (cfg.get("runninghub_consumer_api_key") or "").strip()
    if not key:
        return None
    base_url = (cfg.get("runninghub_base_url") or "").strip() or None
    from pixelle_video.services.runninghub_v2 import RunningHubV2Client
    client = RunningHubV2Client(api_key=key, base_url=base_url)
    up = await client.upload_file(local_path)
    return up.get("fileName") or up.get("download_url")


def _list_dh_single_workflows() -> list[dict]:
    """扫描 workflows/runninghub/dh_*.json 单步骤数字人工作流配置。"""
    import json as _json_dh
    result = []
    dir_path = Path("workflows/runninghub")
    if not dir_path.exists():
        return result
    for fpath in sorted(dir_path.glob("dh_*.json")):
        try:
            cfg = _json_dh.loads(fpath.read_text("utf-8"))
            result.append({
                "key": f"runninghub/{fpath.name}",
                "display_name": cfg.get("name") or fpath.stem,
            })
        except Exception:
            pass
    return result


class DigitalHumanPipelineUI(PipelineUI):
    """
    UI for the Digital_Human Video Generation Pipeline.
    Generates videos from user-provided assets (images&videos&audio).
    """
    name = "digital_human"
    icon = "�?"
    
    @property
    def display_name(self):
        return tr("pipeline.digital_human.name")
    
    @property
    def description(self):
        return tr("pipeline.digital_human.description")

    def _k(self, key: str) -> str:
        return f"dh_{key}"

    def render(self, pixelle_video: Any):
        # Three-column layout
        left_col, middle_col, right_col = st.columns([1, 1, 1])
        
        # ====================================================================
        # Left Column: Asset Upload
        # ====================================================================
        with left_col:
            asset_params = self.render_digital_human_input()
            style_params = render_style_config(pixelle_video)
            # bgm_params = render_bgm_section(key_prefix="asset_")
            render_version_info()
        
        # ====================================================================
        # Middle Column: Video Configuration
        # ====================================================================
        with middle_col:
            # Style configuration ()
            workflow_path = self.workflow_path_config()
            mode_params = self.render_digital_human_mode(asset_params["character_assets"])
        
        # ====================================================================
        # Right Column: Output Preview
        # ====================================================================
        with right_col:
            # Combine all parameters
            video_params = {
                **mode_params,
                **asset_params,
                **style_params,
                "workflow_path": workflow_path
            }
            
            self._render_output_preview(pixelle_video, video_params)

    def render_digital_human_input(self) -> dict:
        """Render digital human character image upload section"""
        with st.container(border=True):
            st.markdown(f"**{tr('digital_human.section.character_assets')}**")
            
            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("digital_human.assets.character_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("digital_human.assets.how"))
            
            # File uploader for multiple files
            uploaded_files = st.file_uploader(
                tr("digital_human.assets.upload"),
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help=tr("digital_human.assets.upload_help"),
                key="character_files"
            )
            
            # Save uploaded files to temp directory with unique session ID
            character_asset_paths = []
            if uploaded_files:
                import uuid
                session_id = str(uuid.uuid4()).replace('-', '')[:12]
                temp_dir = Path(f"temp/assets_{session_id}")
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                for uploaded_file in uploaded_files:
                    file_path = temp_dir / uploaded_file.name
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    character_asset_paths.append(str(file_path.absolute()))
                
                st.success(tr("digital_human.assets.character_sucess"))
                
                # Preview uploaded assets
                with st.expander(tr("digital_human.assets.preview"), expanded=True):
                    # Show in a grid (3 columns)
                    cols = st.columns(3)
                    for i, (file, path) in enumerate(zip(uploaded_files, character_asset_paths)):
                        with cols[i % 3]:
                            # Check if image
                            ext = Path(path).suffix.lower()
                            if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                st.image(file, caption=file.name, width="stretch")
            else:
                st.info(tr("digital_human.assets.character_empty_hint"))

            return {"character_assets": character_asset_paths}

    def workflow_path_config(self) -> dict:
        # Workflow source selection
        with st.container(border=True):
            st.markdown(f"**{tr('asset_based.section.source')}**")
            
            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("asset_based.source.what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("asset_based.source.how"))
            
            source_options = {
                "runninghub": tr("asset_based.source.runninghub"),
                "selfhost": tr("asset_based.source.selfhost")
            }
            
            # Check if RunningHub API key is configured
            comfyui_config = config_manager.get_comfyui_config()
            has_runninghub = bool(comfyui_config.get("runninghub_api_key"))
            has_selfhost = bool(comfyui_config.get("comfyui_url"))
            
            # Default to runninghub always
            default_source_index = 0
            
            source = st.radio(
                tr("asset_based.source.select"),
                options=list(source_options.keys()),
                format_func=lambda x: source_options[x],
                index=default_source_index,
                horizontal=True,
                key="digital_human_workflow_source",
                label_visibility="collapsed"
            )
            
            # Initialize workflow_config with default value based on source selection
            # This ensures the variable is always defined even if the backend is not configured
            if source == "runninghub":
                workflow_config = {
                    "first_workflow_path": "workflows/runninghub/digital_image.json",
                    "second_workflow_path": "workflows/runninghub/digital_combination.json",
                    "third_workflow_path": "workflows/runninghub/digital_customize.json"
                }
                if not has_runninghub:
                    st.warning(tr("asset_based.source.runninghub_not_configured"))
                else:
                    st.info(tr("asset_based.source.runninghub_hint"))
            else:
                workflow_config = {
                    "first_workflow_path": "workflows/selfhost/digital_image.json",
                    "second_workflow_path": "workflows/selfhost/digital_combination.json",
                    "third_workflow_path": "workflows/selfhost/digital_customize.json"
                }
                if not has_selfhost:
                    st.warning(tr("asset_based.source.selfhost_not_configured"))
                else:
                    st.info(tr("asset_based.source.selfhost_hint"))
                    
                    # Check and warn for selfhost workflows (auto popup if not confirmed)
                    # Warn for the first workflow as representative
                    # TODO: need to check if the workflow is valid
                    # check_and_warn_selfhost_workflow("selfhost/digital_image.json")

            # ── 快捷工作流（单步骤 RunningHub，直接复用人物图 + 本地配音）────────
            _dh_wfs = _list_dh_single_workflows()
            if _dh_wfs:
                _opt_none = "__multi_step__"
                _dh_options = [_opt_none] + [wf["key"] for wf in _dh_wfs]
                _dh_labels: dict = {_opt_none: "—— 多步骤流程 ——"}
                _dh_labels.update({wf["key"]: wf["display_name"] for wf in _dh_wfs})
                _dh_sel = st.selectbox(
                    "快捷工作流",
                    _dh_options,
                    format_func=lambda x: _dh_labels.get(x, x),
                    key=self._k("dh_wf_sel"),
                )
                if _dh_sel != _opt_none:
                    import json as _js_wf
                    try:
                        _dh_wf_cfg = _js_wf.loads((Path("workflows") / _dh_sel).read_text("utf-8"))
                    except Exception:
                        _dh_wf_cfg = {}
                    workflow_config["dh_workflow_key"] = _dh_sel
                    workflow_config["dh_workflow_config"] = _dh_wf_cfg

            return workflow_config

    def render_digital_human_mode(self, character_asset_paths: list) -> dict:
        with st.container(border=True):
            st.markdown(f"**{tr('digital_human.section.select_mode')}**")
            
            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("digital_human.assets.mode_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("digital_human.assets.select_how"))
            
            mode = st.radio(
                "Processing Mode",
                ["digital", "customize"],
                horizontal=True,
                format_func=lambda x: tr(f"mode.{x}"),
                label_visibility="collapsed",
                key="mode_selection"
                )
            
            # Text input (unified for both modes)
            text_placeholder = tr("digital_human.input.topic_placeholder") if mode == "digital" else tr("digital_human.input.content_placeholder")
            text_height = 120 if mode == "digital" else 200
            text_help = tr("input.text_help_digital") if mode == "digital" else tr("input.text_help_fixed")
            
            if mode == "digital":
                # File uploader for multiple files
                uploaded_files = st.file_uploader(
                    tr("digital_human.assets.upload"),
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    help=tr("digital_human.assets.upload_help"),
                    key="digital_files"
                )
                
                # Save uploaded files to temp directory with unique session ID
                goods_asset_paths = []
                if uploaded_files:
                    import uuid
                    session_id = str(uuid.uuid4()).replace('-', '')[:12]
                    temp_dir = Path(f"temp/assets_{session_id}")
                    temp_dir.mkdir(parents=True, exist_ok=True)
                
                    for uploaded_file in uploaded_files:
                        file_path = temp_dir / uploaded_file.name
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                        goods_asset_paths.append(str(file_path.absolute()))
                
                    st.success(tr("digital_human.assets.goods_sucess"))
                
                    # Preview uploaded assets
                    with st.expander(tr("digital_human.assets.preview"), expanded=True):
                        # Show in a grid (3 columns)
                        cols = st.columns(3)
                        for i, (file, path) in enumerate(zip(uploaded_files, goods_asset_paths)):
                            with cols[i % 3]:
                                # Check if image
                                ext = Path(path).suffix.lower()
                                if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                    st.image(file, caption=file.name, width="stretch")
                else:
                    st.info(tr("digital_human.assets.goods_empty_hint"))
                    # Text input
                goods_text = st.text_area(
                    tr("digital_human.input_text"),
                    placeholder=text_placeholder,
                    height=text_height,
                    help=text_help,
                    key="digital_box"
                    )

                goods_title = st.text_input(
                    tr("digital_human.goods_title"),
                    placeholder=tr("digital_human.goods_title_placeholder"),
                    help=tr("digital_human.goods_title_help"),
                    key="goods_title"
                )

                # 商品图合成提示词（注入 RunningHub workflow 节点 14 的 CR Text.text 字段）
                product_prompt_default = (
                    "让这个人物自然地手持产品，保留产品的真实材质、立体感和品牌细节，"
                    "产品广告级布光，高级摄影质感，避免把产品压扁成平面贴图"
                )
                product_prompt = st.text_area(
                    "🎨 商品融合提示词（控制立体感/真实感）",
                    value=st.session_state.get("digital_product_prompt", product_prompt_default),
                    height=80,
                    help="决定 AI 在合成「人物+商品」时如何处理商品。默认强调保留立体感与材质，避免被处理成平面图。",
                    key="digital_product_prompt",
                )
                from web.components.polish import render_polish_button
                render_polish_button(
                    source_key="digital_product_prompt",
                    kind="topic",
                    label="✨ 润色提示词",
                    help_text="让商品融合提示词更具体、更专业",
                    button_key="polish_digital_product_prompt",
                )

                return {
                    "character_assets": character_asset_paths,
                    "goods_title": goods_title,
                    "goods_assets": goods_asset_paths,
                    "goods_text": goods_text,
                    "product_prompt": product_prompt,
                    "mode": mode
                    }

            else:
                goods_text = st.text_area(
                    tr("digital_human.customize_text"),
                    placeholder=text_placeholder,
                    height=text_height,
                    help=text_help,
                    key="customize_box"
                )

                return {
                    "character_assets": character_asset_paths,
                    "goods_text": goods_text,
                    "mode": mode
                    }
                    
    def _render_dh_mode_single_step(self, workflow_key: str, character_asset_paths: list) -> dict:
        """中间列单步骤工作流输入（图片 + 音频 + 提示词 + 参数）。"""
        import json as _js
        import uuid as _uuid_dh

        try:
            wf_cfg = _js.loads((Path("workflows") / workflow_key).read_text("utf-8"))
        except Exception as exc:
            st.error(f"无法加载工作流配置：{exc}")
            return {"mode": "dh_single_step_error", "dh_workflow_key": workflow_key,
                    "character_assets": character_asset_paths}

        def _save_up(uf, prefix: str = "dh") -> str:
            td = Path(f"temp/{prefix}_{_uuid_dh.uuid4().hex[:10]}")
            td.mkdir(parents=True, exist_ok=True)
            fp = td / uf.name
            with open(fp, "wb") as fh:
                fh.write(uf.getbuffer())
            return str(fp.absolute())

        with st.container(border=True):
            st.markdown(f"**{tr('digital_human.section.select_mode')}**")

            image_node_id = wf_cfg.get("image_node_id")
            single_image_path: str | None = None
            image_inputs_ok = True

            if image_node_id:
                up = st.file_uploader(
                    "🖼️ 参考图（必填）",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=False,
                    key=self._k("dh_ref_image"),
                )
                if up:
                    single_image_path = _save_up(up)
                    st.image(up, width=120)
                else:
                    st.caption("⬆️ 请上传参考图")
                    image_inputs_ok = False

            _audio_node_id = wf_cfg.get("audio_node_id")
            audio_asset_path: str | None = None
            if _audio_node_id:
                audio_up = st.file_uploader(
                    "🎵 口播音频（必填）",
                    type=["mp3", "wav", "m4a", "aac"],
                    accept_multiple_files=False,
                    key=self._k("dh_audio"),
                )
                if audio_up:
                    audio_asset_path = _save_up(audio_up, "dh_audio")
                    st.success(f"✅ {audio_up.name}")
                else:
                    st.caption("⬆️ 请上传 mp3 / wav / m4a 音频")

            prompt_text = st.text_area(
                "📝 提示词",
                placeholder="描述视频内容，如：亚洲女性自然地介绍手中商品...",
                height=120,
                key=self._k("dh_prompt"),
            )

            extra_params = wf_cfg.get("extra_params") or []
            workflow_id_str = wf_cfg.get("workflow_id", "")
            param_overrides: list = []
            if extra_params:
                with st.expander("⚙️ 工作流参数", expanded=False):
                    param_overrides = self._render_explicit_params(workflow_id_str, extra_params)

        return {
            "mode": "dh_single_step",
            "dh_workflow_key": workflow_key,
            "dh_workflow_config": wf_cfg,
            "single_image_path": single_image_path,
            "audio_asset_path": audio_asset_path,
            "prompt_text": prompt_text,
            "param_overrides": param_overrides,
            "has_audio_input": bool(_audio_node_id),
            "image_inputs_ok": image_inputs_ok,
            "character_assets": character_asset_paths,
        }

    def _render_output_preview(self, pixelle_video: Any, video_params: dict):
        """Render output preview section"""
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            # Check configuration
            if not config_manager.validate():
                st.warning(tr("settings.not_configured"))

            # Get input data
            character_assets = video_params.get("character_assets", [])
            goods_assets = video_params.get("goods_assets", [])
            goods_title = video_params.get("goods_title", "")
            goods_text = video_params.get("goods_text", "")
            mode = video_params.get("mode")
            tts_voice = video_params.get("tts_voice", "zh-CN-YunjianNeural")
            tts_speed = video_params.get("tts_speed", 1.2)
            # dh_workflow_key/dh_workflow_config 存在 video_params["workflow_path"] 嵌套字典中
            _wp_dict = video_params.get("workflow_path", {})
            dh_workflow_key = _wp_dict.get("dh_workflow_key") if isinstance(_wp_dict, dict) else None

            # ── 单步骤工作流（人物图 + 本地 TTS 音频 → RunningHub v2）────────
            if dh_workflow_key:
                if not character_assets:
                    st.info(tr("digital_human.assets.character_warning"))
                    st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                              key="dh_swf_nochar")
                    return
                if not goods_text:
                    st.info(tr("digital_human.assets.customize_mode"))
                    st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                              key="dh_swf_notext")
                    return

                wf_cfg = _wp_dict.get("dh_workflow_config", {})

                # ── ⚙️ 参数配置区（图片模型 + 工作流参数）─────────────────────
                with st.expander("⚙️ 工作流参数", expanded=True):
                    from web.components.inline_model_config import render_inline_model_config
                    _img_cfg = render_inline_model_config("post_image", "🖼️ 图片生成模型（AI合成图）")
                    st.divider()
                    extra_params = wf_cfg.get("extra_params") or []
                    _param_overrides: list = []
                    if extra_params:
                        _param_overrides = self._render_explicit_params(
                            wf_cfg.get("workflow_id", ""), extra_params
                        )

                _has_img_model = bool(_img_cfg.get("api_key") and _img_cfg.get("base_url"))
                # Session state 键（以工作流 key 为命名空间）
                _wk = dh_workflow_key.replace(".", "_")
                _SK_COMP      = f"dh_{_wk}_composite"    # 本地图片路径
                _SK_COMP_PATH = f"dh_{_wk}_comp_path"    # 传入 Wan2.2 的路径
                _SK_TASK_DIR  = f"dh_{_wk}_task_dir"     # task 目录（两步复用）

                # ── 已有合成图 → 展示预览 + 确认 / 重新生成 ──────────────────
                if _has_img_model and _SK_COMP in st.session_state:
                    st.markdown("**Step 1 — AI 合成图（请确认效果是否符合要求）**")
                    st.image(st.session_state[_SK_COMP])
                    _btn_c1, _btn_c2 = st.columns(2)
                    with _btn_c1:
                        _do_video = st.button(
                            "✅ 确认，生成视频", type="primary",
                            use_container_width=True, key="dh_swf_confirm_video"
                        )
                    with _btn_c2:
                        _do_retry = st.button(
                            "🔄 重新生成合成图",
                            use_container_width=True, key="dh_swf_retry_composite"
                        )
                    if _do_retry:
                        for _k in (_SK_COMP, _SK_COMP_PATH, _SK_TASK_DIR):
                            st.session_state.pop(_k, None)
                        st.rerun()

                    if _do_video:
                        if not config_manager.validate():
                            st.error(tr("settings.not_configured"))
                            st.stop()
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        start_time = time.time()
                        _input_img   = st.session_state.get(_SK_COMP_PATH) or character_assets[0]
                        _task_dir    = st.session_state.get(_SK_TASK_DIR) or create_task_output_dir()[0]
                        _cap_ovr     = list(_param_overrides)
                        try:
                            async def _run_tts_and_video():
                                from web.utils.runninghub_i2v import run_runninghub_i2v_v2
                                workflow_id = wf_cfg.get("workflow_id")
                                if not workflow_id:
                                    raise Exception(
                                        f"工作流配置中没有 workflow_id: {dh_workflow_key}")
                                audio_path = os.path.join(_task_dir, "narration.mp3")
                                status_text.text(tr("progress.step_audio"))
                                progress_bar.progress(10)
                                tts_kw: dict = {
                                    "text": goods_text,
                                    "output_path": audio_path,
                                    "inference_mode": video_params.get("tts_inference_mode", "local"),
                                }
                                if tts_kw["inference_mode"] == "local":
                                    tts_kw["voice"] = tts_voice
                                    tts_kw["speed"] = tts_speed
                                elif tts_kw["inference_mode"] == "comfyui":
                                    if video_params.get("tts_workflow"):
                                        tts_kw["workflow"] = video_params["tts_workflow"]
                                    if video_params.get("ref_audio"):
                                        tts_kw["ref_audio"] = video_params["ref_audio"]
                                await pixelle_video.tts(**tts_kw)
                                progress_bar.progress(45)
                                config_manager.reload()
                                status_text.text("使用消费级 API Key (v2) 调用 RunningHub (Wan2.2)...")
                                progress_bar.progress(50)
                                _prefix = wf_cfg.get("prompt_prefix", "")
                                _final_prompt = (_prefix + goods_text) if _prefix else goods_text
                                _conv = []
                                for _nid, _fn, _fv in _cap_ovr:
                                    if str(_nid) in ("44", "48") and isinstance(_fv, (int, float)):
                                        _s = int(_fv)
                                        _fv = f"{_s // 60}:{_s % 60:02d}"
                                    _conv.append((_nid, _fn, _fv))
                                video_url = await run_runninghub_i2v_v2(
                                    workflow_id=workflow_id,
                                    image_path=_input_img,
                                    prompt=_final_prompt,
                                    workflow_config=wf_cfg,
                                    audio_path=audio_path,
                                    param_overrides=_conv or None,
                                    status_text=status_text,
                                )
                                progress_bar.progress(95)
                                return video_url

                            generated_url = run_async(_run_tts_and_video())
                            elapsed = time.time() - start_time
                            progress_bar.progress(100)
                            status_text.text(tr("status.success"))
                            if generated_url:
                                st.success(f"✅ 生成完成！耗时 {elapsed:.0f}s")
                                st.video(generated_url)
                                st.link_button("⬇️ 下载视频", generated_url)
                            else:
                                st.error("生成失败：未收到视频 URL。")
                        except Exception as exc:
                            status_text.text("")
                            progress_bar.empty()
                            st.error(f"生成出错：{exc}")
                            logger.exception(f"[digital_human] dh_video error: {exc}")

                # ── 有图片模型但尚未生成合成图 → 第一步按钮 ──────────────────
                elif _has_img_model:
                    if st.button("第一步：生成合成图 🖼️", type="primary", width="stretch",
                                 key="dh_swf_gen_composite"):
                        if not config_manager.validate():
                            st.error(tr("settings.not_configured"))
                            st.stop()
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        _cap_img_cfg = dict(_img_cfg)
                        try:
                            async def _gen_composite_step():
                                import base64 as _b64
                                import httpx as _httpx
                                from pixelle_video.services.llm_image_service import LLMImageService
                                task_dir, _ = create_task_output_dir()
                                status_text.text("正在生成 AI 商品合成图...")
                                progress_bar.progress(20)
                                _product_desc = (
                                    goods_title or (goods_text[:30] if goods_text else "商品")
                                )
                                _svc = LLMImageService()
                                # 收集可用的本地图片路径
                                _input_imgs = [
                                    p for p in [
                                        character_assets[0] if character_assets else None,
                                        goods_assets[0] if goods_assets else None,
                                    ] if p
                                ]
                                if len(_input_imgs) >= 2:
                                    # 多模态合成：内联实现，绕开模块缓存
                                    _img_prompt = (
                                        f"图1是人物照，图2是商品照。"
                                        f"请将两张图合成为一张商品带货展示图："
                                        f"保留图1人物的外貌和场景，"
                                        f"人物自然手持展示商品【{_product_desc}】，"
                                        f"商品真实立体感，光影与人物场景自然融合，"
                                        f"电商展示风格，高质量。"
                                        f"直接输出合成后的图片，不要文字说明。"
                                    )
                                    _content_parts: list = [{"type": "text", "text": _img_prompt}]
                                    for _ip in _input_imgs:
                                        _ip_lower = str(_ip).lower()
                                        if _ip_lower.endswith(".png"):
                                            _mime = "image/png"
                                        elif _ip_lower.endswith(".webp"):
                                            _mime = "image/webp"
                                        else:
                                            _mime = "image/jpeg"
                                        with open(_ip, "rb") as _if:
                                            _b64_img = _b64.b64encode(_if.read()).decode()
                                        _content_parts.append({
                                            "type": "image_url",
                                            "image_url": {"url": f"data:{_mime};base64,{_b64_img}"},
                                        })
                                    _api_base = _cap_img_cfg["base_url"].rstrip("/")
                                    _chat_url = (
                                        f"{_api_base}/chat/completions"
                                        if _api_base.endswith("/v1")
                                        else f"{_api_base}/v1/chat/completions"
                                    )
                                    _req_body = {
                                        "model": _cap_img_cfg.get("model", "gemini-2.5-flash-image"),
                                        "messages": [{"role": "user", "content": _content_parts}],
                                    }
                                    _req_headers = {
                                        "Authorization": f"Bearer {_cap_img_cfg['api_key']}",
                                        "Content-Type": "application/json",
                                    }
                                    async with _httpx.AsyncClient(proxy=None, follow_redirects=True, timeout=180) as _hc:
                                        _hresp = await _hc.post(_chat_url, json=_req_body, headers=_req_headers)
                                    _hdata = _hresp.json()
                                    if isinstance(_hdata, dict) and "error" in _hdata:
                                        raise ValueError(f"API错误：{_hdata['error']}")
                                    import re as _re
                                    c_url = None
                                    # 遍历 choices，支持 str / markdown / list 三种内容格式
                                    for _ch in (_hdata.get("choices") or [] if isinstance(_hdata, dict) else []):
                                        _mc = _ch.get("message", {}).get("content", "")
                                        if isinstance(_mc, str):
                                            # 直接 URL
                                            if _mc.startswith("http") or _mc.startswith("data:"):
                                                c_url = _mc; break
                                            # Gemini 返回 Markdown 图片: ![...](data:... 或 http...)
                                            _md = _re.search(r'!\[[^\]]*\]\((data:[^)]+|https?://[^)\s]+)', _mc)
                                            if _md:
                                                c_url = _md.group(1); break
                                        elif isinstance(_mc, list):
                                            for _p in _mc:
                                                if not isinstance(_p, dict):
                                                    continue
                                                if _p.get("type") == "image_url":
                                                    c_url = _p["image_url"]["url"]; break
                                                if _p.get("type") == "image":
                                                    _src = _p.get("source", {})
                                                    if _src.get("type") == "base64":
                                                        c_url = f"data:{_src.get('media_type','image/jpeg')};base64,{_src['data']}"; break
                                            if c_url:
                                                break
                                    # 备用： OpenAI images.generate 格式 { "data": [{"url": ...}] }
                                    if not c_url and isinstance(_hdata, dict):
                                        _items = _hdata.get("data") or []
                                        if _items:
                                            _it0 = _items[0]
                                            c_url = _it0.get("url") or (
                                                f"data:image/jpeg;base64,{_it0['b64_json']}" if "b64_json" in _it0 else None
                                            )
                                    if not c_url:
                                        raise ValueError(f"API未返回图片，响应：{str(_hdata)[:300]}")
                                else:
                                    # fallback: 无参考图，纯文本生图
                                    _img_prompt = (
                                        f"Professional product showcase: person naturally "
                                        f"holding [{_product_desc}], realistic 3D product, "
                                        f"e-commerce style, high quality."
                                    )
                                    c_url = await _svc.generate(
                                        prompt=_img_prompt,
                                        api_key=_cap_img_cfg["api_key"],
                                        base_url=_cap_img_cfg["base_url"],
                                        model=_cap_img_cfg.get("model", "gemini-2.5-flash-image"),
                                        size="1024x1024",
                                    )
                                progress_bar.progress(85)
                                _comp_file = os.path.join(task_dir, "composite.jpg")
                                if c_url.startswith("data:"):
                                    _b64_data = c_url.split(",", 1)[1]
                                    with open(_comp_file, "wb") as _f:
                                        _f.write(_b64.b64decode(_b64_data))
                                else:
                                    _resp = _httpx.get(c_url, timeout=30, follow_redirects=True)
                                    with open(_comp_file, "wb") as _f:
                                        _f.write(_resp.content)
                                logger.info(f"[dh] composite saved → {_comp_file}")
                                progress_bar.progress(100)
                                return _comp_file, task_dir

                            c_path, t_dir = run_async(_gen_composite_step())
                            st.session_state[_SK_COMP]      = c_path
                            st.session_state[_SK_COMP_PATH] = c_path
                            st.session_state[_SK_TASK_DIR]  = t_dir
                            status_text.text("✅ 合成图生成完成，请确认效果后点击生成视频")
                            st.rerun()
                        except Exception as exc:
                            progress_bar.empty()
                            status_text.text("")
                            st.error(f"合成图生成失败：{exc}")
                            logger.exception(f"[digital_human] composite error: {exc}")

                # ── 无图片模型配置 → 直接单键生成视频 ───────────────────────
                else:
                    if st.button(tr("btn.generate"), type="primary", width="stretch",
                                 key="dh_swf_generate"):
                        if not config_manager.validate():
                            st.error(tr("settings.not_configured"))
                            st.stop()
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        start_time = time.time()
                        _cap_ovr = list(_param_overrides)
                        try:
                            async def _gen_direct():
                                from web.utils.runninghub_i2v import run_runninghub_i2v_v2
                                task_dir, _ = create_task_output_dir()
                                workflow_id = wf_cfg.get("workflow_id")
                                if not workflow_id:
                                    raise Exception(
                                        f"工作流配置中没有 workflow_id: {dh_workflow_key}")
                                audio_path = os.path.join(task_dir, "narration.mp3")
                                status_text.text(tr("progress.step_audio"))
                                progress_bar.progress(15)
                                tts_kw: dict = {
                                    "text": goods_text,
                                    "output_path": audio_path,
                                    "inference_mode": video_params.get("tts_inference_mode", "local"),
                                }
                                if tts_kw["inference_mode"] == "local":
                                    tts_kw["voice"] = tts_voice
                                    tts_kw["speed"] = tts_speed
                                elif tts_kw["inference_mode"] == "comfyui":
                                    if video_params.get("tts_workflow"):
                                        tts_kw["workflow"] = video_params["tts_workflow"]
                                    if video_params.get("ref_audio"):
                                        tts_kw["ref_audio"] = video_params["ref_audio"]
                                await pixelle_video.tts(**tts_kw)
                                progress_bar.progress(50)
                                config_manager.reload()
                                status_text.text("使用消费级 API Key (v2) 调用 RunningHub (Wan2.2)...")
                                progress_bar.progress(55)
                                _prefix = wf_cfg.get("prompt_prefix", "")
                                _final_prompt = (_prefix + goods_text) if _prefix else goods_text
                                _conv = []
                                for _nid, _fn, _fv in _cap_ovr:
                                    if str(_nid) in ("44", "48") and isinstance(_fv, (int, float)):
                                        _s = int(_fv)
                                        _fv = f"{_s // 60}:{_s % 60:02d}"
                                    _conv.append((_nid, _fn, _fv))
                                video_url = await run_runninghub_i2v_v2(
                                    workflow_id=workflow_id,
                                    image_path=character_assets[0],
                                    prompt=_final_prompt,
                                    workflow_config=wf_cfg,
                                    audio_path=audio_path,
                                    param_overrides=_conv or None,
                                    status_text=status_text,
                                )
                                progress_bar.progress(90)
                                return video_url, task_dir

                            generated_url, task_dir = run_async(_gen_direct())
                            elapsed = time.time() - start_time
                            progress_bar.progress(100)
                            status_text.text(tr("status.success"))
                            if generated_url:
                                st.success(f"✅ 生成完成！耗时 {elapsed:.0f}s")
                                st.video(generated_url)
                                st.link_button("⬇️ 下载视频", generated_url)
                            else:
                                st.error("生成失败：未收到视频 URL。")
                        except Exception as exc:
                            status_text.text("")
                            progress_bar.empty()
                            st.error(f"生成出错：{exc}")
                            logger.exception(f"[digital_human] dh_direct error: {exc}")
                return

            # ── 以下为原有多步骤验证逻辑 ──────────────────────────────
            
            logger.info(f"🔧 The obtained TTS parameters:")
            logger.info(f"  - tts_voice: {tts_voice}")
            logger.info(f"  - tts_speed: {tts_speed}")
            logger.info(f"  - video_params�?��tts_voice: {video_params.get('tts_voice', 'NOT_FOUND')}")
            logger.info(f"  - video_params: {video_params}")
            
            # Validation
            if not character_assets:
                st.info(tr("digital_human.assets.character_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key="digital_human_generate_disabled"
                )
                return

            if mode == "digital" and not goods_assets:
                st.info(tr("digital_human.assets.goods_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key="digital_human_goods_vaiidation"
                )
                return

            if mode == "digital" and not (goods_text or goods_title):
                st.info(tr("digital_human.assets.digital_mode"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key="digital_human_digital_disable"
                )
                return
            
            if mode == "digital" and (goods_text or goods_title):
                st.warning(tr("digital_human.assets.digital_mode_warning"))
            
            if mode == "customize" and not goods_text:
                st.info(tr("digital_human.assets.customize_mode"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key="digital_human_customize_disable"
                )
                return
            
            # Generate button
            if st.button(tr("btn.generate"), type="primary", width="stretch", key="digital_human_generate"):
                # Validate
                if not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    st.stop()
                
                # Show progress
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                start_time = time.time()
                
                try:
                    # Define async generation function
                    async def generate_digital_human_video():
                        task_dir, task_id = create_task_output_dir()
                        kit = await pixelle_video._get_or_create_comfykit()
                        workflow_path = video_params["workflow_path"]

                        import json
                        from pathlib import Path

                        if mode == "customize":
                            status_text.text(tr("progress.step_audio"))
                            progress_bar.progress(25)
                            generated_image_path = character_assets[0]   
                            generated_text = goods_text                 

                            # TTS
                            audio_path = os.path.join(task_dir, "narration.mp3")
                            tts_inference_mode = video_params.get("tts_inference_mode", "local")
                            tts_voice = video_params.get("tts_voice")
                            tts_speed = video_params.get("tts_speed")
                            tts_workflow = video_params.get("tts_workflow")
                            ref_audio = video_params.get("ref_audio")

                            tts_kwargs = {
                                "text": generated_text,
                                "output_path": audio_path,
                                "inference_mode": tts_inference_mode
                            }
                            if tts_inference_mode == "local":
                                tts_kwargs["voice"] = tts_voice
                                tts_kwargs["speed"] = tts_speed
                            elif tts_inference_mode == "comfyui":
                                if tts_workflow:
                                    tts_kwargs["workflow"] = tts_workflow
                                if ref_audio:
                                    tts_kwargs["ref_audio"] = ref_audio

                            await pixelle_video.tts(**tts_kwargs)
                            progress_bar.progress(65)
                            status_text.text(tr("progress.concatenating"))

                            # Directly call the second workflow
                            second_workflow_path = Path(workflow_path.get("second_workflow_path"))
                            if not second_workflow_path.exists():
                                raise Exception(f"The second step workflow file does not exist:{second_workflow_path}")
                            with open(second_workflow_path, 'r', encoding='utf-8') as f:
                                second_workflow_config = json.load(f)
                            second_workflow_params = {
                                "videoimage": generated_image_path,
                                "audio": audio_path
                            }
                            if second_workflow_config.get("source") == "runninghub" and "workflow_id" in second_workflow_config:
                                workflow_input = second_workflow_config["workflow_id"]
                            else:
                                workflow_input = str(second_workflow_config)

                            # ===== v2 + 消费级 key 路径（优先） =====
                            generated_video_url = None
                            if (
                                second_workflow_config.get("source") == "runninghub"
                                and "workflow_id" in second_workflow_config
                            ):
                                try:
                                    img_ref = await _rh_v2_upload(generated_image_path)
                                    audio_ref = await _rh_v2_upload(audio_path) if img_ref else None
                                except Exception as exc:
                                    logger.warning(f"[digital_human] v2 second-step upload failed: {exc}")
                                    img_ref = audio_ref = None
                                if img_ref and audio_ref:
                                    node_info_list = [
                                        {"nodeId": "133", "fieldName": "image", "fieldValue": img_ref},
                                        {"nodeId": "206", "fieldName": "audio", "fieldValue": audio_ref},
                                    ]
                                    v2_res = await _try_runninghub_v2(
                                        workflow_id=workflow_input,
                                        node_info_list=node_info_list,
                                        expected="video",
                                    )
                                    if v2_res:
                                        generated_video_url = v2_res["url"]
                                        logger.info(
                                            f"[digital_human] v2 second-step OK: video_url={generated_video_url}"
                                        )

                            if generated_video_url is None:
                                second_result = await kit.execute(workflow_input, second_workflow_params)
                                # Video Link Extraction
                                if hasattr(second_result, 'videos') and second_result.videos:
                                    generated_video_url = second_result.videos[0]
                                elif hasattr(second_result, 'outputs') and second_result.outputs:
                                    for node_id, node_output in second_result.outputs.items():
                                        if isinstance(node_output, dict) and 'videos' in node_output:
                                            videos = node_output['videos']
                                            if videos and len(videos) > 0:
                                                generated_video_url = videos[0]
                                                break
                            if not generated_video_url:
                                raise Exception("The second step of the workflow did not return a video. Please check the workflow configuration.")
                                        
                            final_video_path = os.path.join(task_dir, "final.mp4")
                            timeout = httpx.Timeout(300.0)
                            async with httpx.AsyncClient(timeout=timeout) as client:
                                response = await client.get(generated_video_url)
                                response.raise_for_status()
                                with open(final_video_path, 'wb') as f:
                                    f.write(response.content)
                            progress_bar.progress(100)
                            status_text.text(tr("status.success"))
                            return final_video_path
                        
                        else:
                            #Initialization and parameter preparation
                            task_dir, task_id = create_task_output_dir()
                            logger.info(f"[Initialization] Task Directory: {task_dir}")

                            first_workflow_path = Path(workflow_path.get("first_workflow_path"))
                            third_workflow_path = Path(workflow_path.get("third_workflow_path"))
                            second_workflow_path = Path(workflow_path.get("second_workflow_path"))
                            assert first_workflow_path.exists(), "The first_workflow file does not exist."
                            assert third_workflow_path.exists(), "The third_workflow file does not exist."
                            assert second_workflow_path.exists(), "The  second_workflow file does not exist."

                            if goods_text and goods_text.strip():
                                workflow_path = third_workflow_path
                                workflow_params = {"firstimage": character_assets[0], "secondimage": goods_assets[0]}
                                generated_text = goods_text

                                status_text.text(tr("progress.step_image"))
                                kit = await pixelle_video._get_or_create_comfykit()
                                workflow_config = json.load(open(workflow_path, 'r', encoding='utf8'))
                                if workflow_config.get("source") == "runninghub" and "workflow_id" in workflow_config:
                                    workflow_input = workflow_config["workflow_id"]
                                else:
                                    workflow_input = str(workflow_config)

                                # ===== v2 + 消费级 key 路径（优先） =====
                                generated_image_url = None
                                if (
                                    workflow_config.get("source") == "runninghub"
                                    and "workflow_id" in workflow_config
                                ):
                                    try:
                                        first_ref = await _rh_v2_upload(character_assets[0])
                                        second_ref = await _rh_v2_upload(goods_assets[0]) if first_ref else None
                                    except Exception as exc:
                                        logger.warning(f"[digital_human] v2 customize upload failed: {exc}")
                                        first_ref = second_ref = None
                                    if first_ref and second_ref:
                                        node_info_list = [
                                            {"nodeId": "18", "fieldName": "image", "fieldValue": first_ref},
                                            {"nodeId": "17", "fieldName": "image", "fieldValue": second_ref},
                                        ]
                                        v2_res = await _try_runninghub_v2(
                                            workflow_id=workflow_input,
                                            node_info_list=node_info_list,
                                            expected="image",
                                        )
                                        if v2_res:
                                            generated_image_url = v2_res["url"]
                                            logger.info(
                                                f"[digital_human] v2 customize step OK: image_url={generated_image_url}"
                                            )

                                if generated_image_url is None:
                                    combine_image = await kit.execute(workflow_input, workflow_params)
                                    if combine_image.status != "completed":
                                        raise Exception(f"workflow execution failed: {combine_image.msg}")
                                    generated_image_url = getattr(combine_image, "images", [None])[0]
                                status_text.text(tr("progress.step_audio"))
                                audio_path = os.path.join(task_dir, "narration.mp3")
                                tts_inference_mode = video_params.get("tts_inference_mode", "local")
                                tts_voice = video_params.get("tts_voice")
                                tts_speed = video_params.get("tts_speed")
                                tts_workflow = video_params.get("tts_workflow")
                                ref_audio = video_params.get("ref_audio")

                                tts_kwargs = {
                                    "text": generated_text,
                                    "output_path": audio_path,
                                    "inference_mode": tts_inference_mode
                                }
                                if tts_inference_mode == "local":
                                    tts_kwargs["voice"] = tts_voice
                                    tts_kwargs["speed"] = tts_speed
                                elif tts_inference_mode == "comfyui":
                                    if tts_workflow:
                                        tts_kwargs["workflow"] = tts_workflow
                                    if ref_audio:
                                        tts_kwargs["ref_audio"] = ref_audio

                                await pixelle_video.tts(**tts_kwargs)
                                progress_bar.progress(65)
                                status_text.text(tr("progress.concatenating"))

                                if not second_workflow_path.exists():
                                    raise Exception(f"The second step workflow file does not exist:{second_workflow_path}")
                                with open(second_workflow_path, 'r', encoding='utf-8') as f:
                                    second_workflow_config = json.load(f)
                                second_workflow_params = {
                                    "videoimage": generated_image_url,
                                    "audio": audio_path
                                }
                                if second_workflow_config.get("source") == "runninghub" and "workflow_id" in second_workflow_config:
                                    workflow_input = second_workflow_config["workflow_id"]
                                else:
                                    workflow_input = str(second_workflow_config)

                                # ===== v2 + ??? key ?????? =====
                                generated_video_url = None
                                if (
                                    second_workflow_config.get("source") == "runninghub"
                                    and "workflow_id" in second_workflow_config
                                ):
                                    try:
                                        audio_ref = await _rh_v2_upload(audio_path)
                                    except Exception as exc:
                                        logger.warning(f"[digital_human] v2 combination upload failed: {exc}")
                                        audio_ref = None
                                    if audio_ref and generated_image_url:
                                        node_info_list = [
                                            {"nodeId": "133", "fieldName": "image", "fieldValue": generated_image_url},
                                            {"nodeId": "206", "fieldName": "audio", "fieldValue": audio_ref},
                                        ]
                                        v2_res = await _try_runninghub_v2(
                                            workflow_id=workflow_input,
                                            node_info_list=node_info_list,
                                            expected="video",
                                        )
                                        if v2_res:
                                            generated_video_url = v2_res["url"]
                                            logger.info(
                                                f"[digital_human] v2 combination OK: video_url={generated_video_url}"
                                            )

                                if generated_video_url is None:
                                    second_result = await kit.execute(workflow_input, second_workflow_params)
                                    if hasattr(second_result, 'videos') and second_result.videos:
                                        generated_video_url = second_result.videos[0]
                                    elif hasattr(second_result, 'outputs') and second_result.outputs:
                                        for node_id, node_output in second_result.outputs.items():
                                            if isinstance(node_output, dict) and 'videos' in node_output:
                                                videos = node_output['videos']
                                                if videos and len(videos) > 0:
                                                    generated_video_url = videos[0]
                                                    break
                                if not generated_video_url:
                                    raise Exception("The second step of the workflow did not return a video. Please check the workflow configuration.")
                                            
                                final_video_path = os.path.join(task_dir, "final.mp4")
                                timeout = httpx.Timeout(300.0)
                                async with httpx.AsyncClient(timeout=timeout) as client:
                                    response = await client.get(generated_video_url)
                                    response.raise_for_status()
                                    with open(final_video_path, 'wb') as f:
                                        f.write(response.content)
                                progress_bar.progress(100)
                                status_text.text(tr("status.success"))
                                return final_video_path
                                
                            else:
                                workflow_path = first_workflow_path
                                workflow_params = {"firstimage": character_assets[0], "secondimage": goods_assets[0], "goodstype": goods_title}

                                status_text.text(tr("progress.step_image"))
                                kit = await pixelle_video._get_or_create_comfykit()
                                workflow_config = json.load(open(workflow_path, 'r', encoding='utf8'))
                                if workflow_config.get("source") == "runninghub" and "workflow_id" in workflow_config:
                                    workflow_input = workflow_config["workflow_id"]
                                else:
                                    workflow_input = str(workflow_config)

                                product_prompt = (video_params.get("product_prompt") or "").strip()
                                generated_image_url = None
                                generated_text = None

                                # ===== v2 + 消费级 key 路径（优先）=====
                                if (
                                    workflow_config.get("source") == "runninghub"
                                    and "workflow_id" in workflow_config
                                ):
                                    try:
                                        first_ref = await _rh_v2_upload(character_assets[0])
                                        second_ref = await _rh_v2_upload(goods_assets[0]) if first_ref else None
                                    except Exception as exc:
                                        logger.warning(f"[digital_human] v2 upload failed: {exc}")
                                        first_ref = second_ref = None
                                    if first_ref and second_ref:
                                        node_info_list = [
                                            {"nodeId": "18", "fieldName": "image", "fieldValue": first_ref},
                                            {"nodeId": "17", "fieldName": "image", "fieldValue": second_ref},
                                            {"nodeId": "19", "fieldName": "text", "fieldValue": goods_title or ""},
                                        ]
                                        if product_prompt:
                                            node_info_list.append(
                                                {"nodeId": "14", "fieldName": "text", "fieldValue": product_prompt}
                                            )
                                        v2_res = await _try_runninghub_v2(
                                            workflow_id=workflow_input,
                                            node_info_list=node_info_list,
                                            expected="image",
                                        )
                                        if v2_res:
                                            generated_image_url = v2_res["url"]
                                            generated_text = v2_res.get("text")
                                            logger.info(
                                                f"[digital_human] v2 first-step OK: image_url={generated_image_url}"
                                            )

                                # ===== v1 fallback / 默认路径 =====
                                if generated_image_url is None:
                                    if (
                                        product_prompt
                                        and workflow_config.get("source") == "runninghub"
                                        and "workflow_id" in workflow_config
                                    ):
                                        try:
                                            rh_executor = kit._get_runninghub_executor()
                                            rh_client = rh_executor.client
                                            first_filename = await rh_client.upload_file(str(character_assets[0]))
                                            second_filename = await rh_client.upload_file(str(goods_assets[0]))
                                            node_info_list = [
                                                {"nodeId": "18", "fieldName": "image", "fieldValue": first_filename},
                                                {"nodeId": "17", "fieldName": "image", "fieldValue": second_filename},
                                                {"nodeId": "19", "fieldName": "text", "fieldValue": goods_title or ""},
                                                {"nodeId": "14", "fieldName": "text", "fieldValue": product_prompt},
                                            ]
                                            logger.info(
                                                f"[digital_human] v1 nodeInfoList override path, "
                                                f"len(product_prompt)={len(product_prompt)}"
                                            )
                                            task_data = await rh_client.create_task(workflow_input, node_info_list)
                                            task_id = task_data.get("taskId")
                                            if not task_id:
                                                raise Exception(f"RunningHub create_task did not return taskId: {task_data}")
                                            synthesis_result = await rh_executor._wait_for_task_completion(task_id, {})
                                        except Exception as exc:
                                            logger.warning(
                                                f"[digital_human] v1 override path failed, falling back to default kit.execute: {exc}"
                                            )
                                            synthesis_result = await kit.execute(workflow_input, workflow_params)
                                    else:
                                        synthesis_result = await kit.execute(workflow_input, workflow_params)
                                    if synthesis_result.status != "completed":
                                        raise Exception(f"workflow execution failed: {synthesis_result.msg}")
                                    generated_image_url = getattr(synthesis_result, "images", [None])[0]
                                    generated_text = getattr(synthesis_result, "texts", [None])[0]
                                
                                status_text.text(tr("progress.step_audio"))
                                audio_path = os.path.join(task_dir, "narration.mp3")
                                tts_inference_mode = video_params.get("tts_inference_mode", "local")
                                tts_voice = video_params.get("tts_voice")
                                tts_speed = video_params.get("tts_speed")
                                tts_workflow = video_params.get("tts_workflow")
                                ref_audio = video_params.get("ref_audio")

                                tts_kwargs = {
                                    "text": generated_text,
                                    "output_path": audio_path,
                                    "inference_mode": tts_inference_mode
                                }
                                if tts_inference_mode == "local":
                                    tts_kwargs["voice"] = tts_voice
                                    tts_kwargs["speed"] = tts_speed
                                elif tts_inference_mode == "comfyui":
                                    if tts_workflow:
                                        tts_kwargs["workflow"] = tts_workflow
                                    if ref_audio:
                                        tts_kwargs["ref_audio"] = ref_audio

                                await pixelle_video.tts(**tts_kwargs)
                                progress_bar.progress(65)
                                status_text.text(tr("progress.concatenating"))

                                if not second_workflow_path.exists():
                                    raise Exception(f"The second step workflow file does not exist:{second_workflow_path}")
                                with open(second_workflow_path, 'r', encoding='utf-8') as f:
                                    second_workflow_config = json.load(f)
                                second_workflow_params = {
                                    "videoimage": generated_image_url,
                                    "audio": audio_path
                                }
                                if second_workflow_config.get("source") == "runninghub" and "workflow_id" in second_workflow_config:
                                    workflow_input = second_workflow_config["workflow_id"]
                                else:
                                    workflow_input = str(second_workflow_config)

                                # ===== v2 + ??? key ?????? =====
                                generated_video_url = None
                                if (
                                    second_workflow_config.get("source") == "runninghub"
                                    and "workflow_id" in second_workflow_config
                                ):
                                    try:
                                        audio_ref = await _rh_v2_upload(audio_path)
                                    except Exception as exc:
                                        logger.warning(f"[digital_human] v2 combination upload failed: {exc}")
                                        audio_ref = None
                                    if audio_ref and generated_image_url:
                                        node_info_list = [
                                            {"nodeId": "133", "fieldName": "image", "fieldValue": generated_image_url},
                                            {"nodeId": "206", "fieldName": "audio", "fieldValue": audio_ref},
                                        ]
                                        v2_res = await _try_runninghub_v2(
                                            workflow_id=workflow_input,
                                            node_info_list=node_info_list,
                                            expected="video",
                                        )
                                        if v2_res:
                                            generated_video_url = v2_res["url"]
                                            logger.info(
                                                f"[digital_human] v2 combination OK: video_url={generated_video_url}"
                                            )

                                if generated_video_url is None:
                                    second_result = await kit.execute(workflow_input, second_workflow_params)
                                    if hasattr(second_result, 'videos') and second_result.videos:
                                        generated_video_url = second_result.videos[0]
                                    elif hasattr(second_result, 'outputs') and second_result.outputs:
                                        for node_id, node_output in second_result.outputs.items():
                                            if isinstance(node_output, dict) and 'videos' in node_output:
                                                videos = node_output['videos']
                                                if videos and len(videos) > 0:
                                                    generated_video_url = videos[0]
                                                    break
                                if not generated_video_url:
                                    raise Exception("The second step of the workflow did not return a video. Please check the workflow configuration.")
                                            
                                final_video_path = os.path.join(task_dir, "final.mp4")
                                timeout = httpx.Timeout(300.0)
                                async with httpx.AsyncClient(timeout=timeout) as client:
                                    response = await client.get(generated_video_url)
                                    response.raise_for_status()
                                    with open(final_video_path, 'wb') as f:
                                        f.write(response.content)
                                progress_bar.progress(100)
                                status_text.text(tr("status.success"))
                                return final_video_path
                                
                    # Execute async generation
                    final_video_path = run_async(generate_digital_human_video())
                    
                    total_time = time.time() - start_time
                    progress_bar.progress(100)
                    status_text.text(tr("status.success"))
                    
                    # Display result
                    st.success(tr("status.video_generated", path=final_video_path))
                    
                    st.markdown("---")
                    
                    # Video info
                    if os.path.exists(final_video_path):
                        file_size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
                        
                        info_text = (
                            f"⏱️ {tr('info.generation_time')} {total_time:.1f}s   "
                            f"📦 {file_size_mb:.2f}MB"
                        )
                        st.caption(info_text)
                        
                        st.markdown("---")
                        
                        # Video preview
                        st.video(final_video_path)
                        
                        # Download button
                        with open(final_video_path, "rb") as video_file:
                            video_bytes = video_file.read()
                            video_filename = os.path.basename(final_video_path)
                            st.download_button(
                                label="⬇️ 下载视�?" if get_language() == "zh_CN" else "⬇️ Download Video",
                                data=video_bytes,
                                file_name=video_filename,
                                mime="video/mp4",
                                width="stretch"
                            )
                    else:
                        st.error(tr("status.video_not_found", path=final_video_path))
                
                except Exception as e:
                    status_text.text("")
                    progress_bar.empty()
                    st.error(tr("status.error", error=str(e)))
                    logger.exception(e)
                    st.stop()

    # ── 单步骤工作流 UI（dh_*.json）──────────────────────────────────────────

    def _render_dh_single_step(self, pixelle_video: Any, workflow_key: str):
        """单步骤数字人工作流 UI（图片 + 音频 → 视频）。"""
        import json as _js
        import uuid as _uuid_dh

        try:
            wf_cfg = _js.loads((Path("workflows") / workflow_key).read_text("utf-8"))
        except Exception as exc:
            st.error(f"无法加载工作流配置：{exc}")
            return

        def _save_up(uf, prefix: str = "dh") -> str:
            td = Path(f"temp/{prefix}_{_uuid_dh.uuid4().hex[:10]}")
            td.mkdir(parents=True, exist_ok=True)
            fp = td / uf.name
            with open(fp, "wb") as fh:
                fh.write(uf.getbuffer())
            return str(fp.absolute())

        left_col, right_col = st.columns([1, 1])

        # ── 左列：素材上传 + 提示词 + 参数 ───────────────────────────────────
        with left_col:
            with st.container(border=True):
                st.markdown("**📥 素材上传**")

                image_inputs = wf_cfg.get("image_inputs") or []
                image_node_id = wf_cfg.get("image_node_id")
                named_image_paths: dict[str, str] = {}
                single_image_path: str | None = None
                image_inputs_ok = True

                if image_inputs:
                    for slot in image_inputs:
                        nid = str(slot["node_id"])
                        lbl = slot.get("label", f"图片（节点 {nid}）")
                        req = slot.get("required", True)
                        up = st.file_uploader(
                            f"{lbl}{'（必填）' if req else '（可选）'}",
                            type=["jpg", "jpeg", "png", "webp"],
                            accept_multiple_files=False,
                            key=self._k(f"dh_img_{nid}"),
                        )
                        if up:
                            named_image_paths[nid] = _save_up(up)
                            st.image(up, caption=lbl, width=160)
                        elif req:
                            st.caption(f"⬆️ 请上传「{lbl}」")
                            image_inputs_ok = False
                elif image_node_id:
                    up = st.file_uploader(
                        "🖼️ 参考图（必填）",
                        type=["jpg", "jpeg", "png", "webp"],
                        accept_multiple_files=False,
                        key=self._k("dh_ref_image"),
                    )
                    if up:
                        single_image_path = _save_up(up)
                        st.image(up, width=160)
                    else:
                        st.caption("⬆️ 请上传参考图")
                        image_inputs_ok = False

                _audio_node_id = wf_cfg.get("audio_node_id")
                audio_asset_path: str | None = None
                if _audio_node_id:
                    audio_up = st.file_uploader(
                        "🎵 口播音频（必填）",
                        type=["mp3", "wav", "m4a", "aac"],
                        accept_multiple_files=False,
                        key=self._k("dh_audio"),
                    )
                    if audio_up:
                        audio_asset_path = _save_up(audio_up, "dh_audio")
                        st.success(f"✅ 已上传音频: {audio_up.name}")
                    else:
                        st.caption("⬆️ 请上传 mp3 / wav / m4a 音频文件")

                prompt_text = st.text_area(
                    "📝 提示词",
                    placeholder="描述视频内容，如：亚洲女性自然地介绍手中商品...",
                    height=160,
                    key=self._k("dh_prompt"),
                )

                extra_params = wf_cfg.get("extra_params") or []
                workflow_id_str = wf_cfg.get("workflow_id", "")
                param_overrides: list = []
                if extra_params:
                    with st.expander("⚙️ 工作流参数", expanded=False):
                        param_overrides = self._render_explicit_params(workflow_id_str, extra_params)

                render_version_info()

        # ── 右列：输出面板 ────────────────────────────────────────────────────
        with right_col:
            self._render_dh_single_output(pixelle_video, {
                "workflow_key": workflow_key,
                "workflow_config": wf_cfg,
                "prompt_text": prompt_text,
                "named_image_paths": named_image_paths,
                "single_image_path": single_image_path,
                "image_inputs_ok": image_inputs_ok,
                "audio_asset_path": audio_asset_path,
                "has_audio_input": bool(_audio_node_id),
                "param_overrides": param_overrides,
            })

    def _render_explicit_params(self, workflow_id: str, extra_params: list) -> list:
        """从 JSON 配置直接渲染 extra_params 控件，无需拉取云端工作流 JSON。"""
        overrides: list = []
        cols = st.columns(2)
        for idx, p in enumerate(extra_params):
            nid = str(p.get("node_id", ""))
            fname = p.get("field_name") or p.get("field") or ""
            if not nid or not fname:
                continue
            label = p.get("label") or f"{fname} (node {nid})"
            ptype = p.get("type", "str")
            default = p.get("default")
            wkey = self._k(f"dh_param_{workflow_id}_{nid}_{fname}")
            with cols[idx % 2]:
                if ptype == "bool":
                    cur = bool(default) if default is not None else False
                    v_bool = st.checkbox(label, value=cur, key=wkey)
                    if v_bool != cur:
                        overrides.append((nid, fname, str(v_bool).lower()))
                elif ptype == "int":
                    try:
                        cur = int(default) if default is not None else int(p.get("min", 0))
                    except Exception:
                        cur = 0
                    v_int = int(st.number_input(
                        label, value=cur,
                        min_value=int(p.get("min", 0)),
                        max_value=int(p.get("max", 2**31 - 1)),
                        step=int(p.get("step", 1)),
                        key=wkey,
                    ))
                    if v_int != cur:
                        overrides.append((nid, fname, v_int))
                elif ptype in ("enum_str", "enum_int"):
                    opts = list(p.get("options") or [])
                    if ptype == "enum_int":
                        opts = [int(o) for o in opts]
                        try:
                            default = int(default) if default is not None else (opts[0] if opts else 0)
                        except Exception:
                            default = opts[0] if opts else 0
                    try:
                        idx_d = opts.index(default)
                    except (ValueError, TypeError):
                        idx_d = 0
                    disp = p.get("display_labels")
                    if isinstance(disp, list) and len(disp) == len(opts):
                        _fmt = lambda x, _o=opts, _d=disp: _d[_o.index(x)] if x in _o else str(x)
                        v_sel = st.selectbox(label, opts if opts else [""], index=idx_d, key=wkey, format_func=_fmt)
                    else:
                        v_sel = st.selectbox(label, opts if opts else [""], index=idx_d, key=wkey)
                    if v_sel != default:
                        overrides.append((nid, fname, v_sel))
                else:  # str
                    cur_str = str(default if default is not None else "")
                    v_str = st.text_input(label, value=cur_str, key=wkey)
                    if v_str != cur_str:
                        overrides.append((nid, fname, v_str))
        return overrides

    def _render_dh_single_output(self, pixelle_video: Any, params: dict):
        """单步骤工作流输出面板（guard + 生成按钮 + 视频展示）。"""
        from web.utils.runninghub_i2v import run_runninghub_i2v_v2

        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")
            if not config_manager.validate():
                st.warning(tr("settings.not_configured"))

            prompt_text = params.get("prompt_text", "")
            workflow_key = params.get("workflow_key", "")
            workflow_config = params.get("workflow_config", {})
            named_image_paths = params.get("named_image_paths", {}) or {}
            single_image_path = params.get("single_image_path")
            image_inputs_ok = params.get("image_inputs_ok", True)
            audio_asset_path = params.get("audio_asset_path")
            has_audio_input = params.get("has_audio_input", False)
            param_overrides = params.get("param_overrides") or []

            no_image = not named_image_paths and not single_image_path
            if no_image:
                st.info("请先上传参考图。")
                st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                          key=self._k("dh_s_gen_noimg"))
                return
            if not image_inputs_ok:
                st.info("请补全所有必填图片后再生成。")
                st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                          key=self._k("dh_s_gen_incomplete"))
                return
            if has_audio_input and not audio_asset_path:
                st.info("该工作流需要上传口播音频，请在左侧上传音频文件。")
                st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                          key=self._k("dh_s_gen_noaudio"))
                return
            if not prompt_text:
                st.info("请输入提示词后再生成。")
                st.button(tr("btn.generate"), type="primary", width="stretch", disabled=True,
                          key=self._k("dh_s_gen_noprompt"))
                return

            if st.button(tr("btn.generate"), type="primary", width="stretch",
                         key=self._k("dh_s_generate")):
                if not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    st.stop()
                progress_bar = st.progress(0)
                status_text = st.empty()
                start_time = time.time()
                try:
                    async def _gen_single():
                        task_dir, task_id = create_task_output_dir()
                        workflow_id = workflow_config.get("workflow_id")
                        if not workflow_id:
                            raise Exception(f"工作流配置中没有 workflow_id: {workflow_key}")
                        config_manager.reload()
                        status_text.text("使用消费级 API Key (v2) 调用 RunningHub...")
                        progress_bar.progress(15)
                        video_url = await run_runninghub_i2v_v2(
                            workflow_id=workflow_id,
                            image_path=single_image_path,
                            prompt=prompt_text,
                            workflow_config=workflow_config,
                            named_image_paths=named_image_paths or None,
                            audio_path=audio_asset_path,
                            param_overrides=param_overrides,
                            status_text=status_text,
                        )
                        progress_bar.progress(90)
                        return video_url, task_dir

                    generated_url, task_dir = run_async(_gen_single())
                    elapsed = time.time() - start_time
                    progress_bar.progress(100)
                    status_text.text(tr("status.success"))
                    if generated_url:
                        st.success(f"✅ 生成完成！耗时 {elapsed:.0f}s")
                        st.video(generated_url)
                        st.link_button("⬇️ 下载视频", generated_url)
                    else:
                        st.error("生成失败：未收到视频 URL。")
                except Exception as exc:
                    status_text.text("")
                    progress_bar.empty()
                    st.error(f"生成出错：{exc}")
                    logger.exception(f"[digital_human] single-step generation error: {exc}")


# Register self
register_pipeline_ui(DigitalHumanPipelineUI)



