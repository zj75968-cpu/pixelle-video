import os
import re
import time
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger
import httpx
from web.i18n import tr, get_language
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.components.content_input import render_version_info
from web.utils.async_helpers import run_async
from web.utils.streamlit_helpers import check_and_warn_selfhost_workflow
from web.utils.runninghub_i2v import discover_workflow_params, run_runninghub_i2v
from pixelle_video.config import config_manager
from pixelle_video.utils.os_util import create_task_output_dir

class ImageToVideoPipelineUI(PipelineUI):
    """
    UI for the Image To Video Video Generation Pipeline.
    Generates videos from user-provided assets (images&text).
    """
    name = "image_to_video"
    icon = "🎥"

    def __init__(self, key_prefix: str = ""):
        """key_prefix 用于避免在「快速生成」Tab 复用时与本 Tab widget key 冲突。"""
        self.key_prefix = key_prefix

    def _k(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    @property
    def display_name(self):
        return tr("pipeline.i2v.name")
    
    @property
    def description(self):
        return tr("pipeline.i2v.description")

    @staticmethod
    def _parse_image_urls(raw_text: str) -> list[str]:
        if not raw_text:
            return []
        parts = re.split(r"[\s,，;；、]+", raw_text.strip())
        return [p for p in parts if p.startswith("http://") or p.startswith("https://")]

    def render(self, pixelle_video: Any):
        # Two-column layout
        left_col,right_col = st.columns([1, 1])

        # ====================================================================
        # Left Column: Asset Upload
        # ====================================================================
        with left_col:
            asset_params = self.render_audio_visual_input(pixelle_video)
            render_version_info()

        # ====================================================================
        # Right Column: Output Preview
        # ====================================================================
        with right_col:
            video_params = {
                **asset_params
            }

            self._render_output_preview(pixelle_video, video_params)

    def render_audio_visual_input(self, pixelle_video) -> dict:
        with st.container(border=True):
            st.markdown(f"**{tr('i2v.video_generation')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("i2v.assets.image_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("i2v.assets.how"))

            def list_i2v_workflows():
                result = []
                for source in ("runninghub", "selfhost"):
                    dir_path = os.path.join("workflows", source)
                    if not os.path.isdir(dir_path):
                        continue
                    for fname in os.listdir(dir_path):
                        if fname.startswith("i2v_") and fname.endswith(".json"):
                            display = f"{fname} - {'Runninghub' if source == 'runninghub' else 'Selfhost'}"
                            result.append({
                                "key": f"{source}/{fname}",
                                "display_name": display
                            })
                return result

            # File uploader for multiple files
            uploaded_files = st.file_uploader(
                tr("i2v.assets.upload"),
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help=tr("i2v.assets.upload_help"),
                key=self._k("material_files")
            )

            # Save uploaded files to temp directory with unique session ID
            audio_asset_paths = []
            if uploaded_files:
                import uuid
                session_id = str(uuid.uuid4()).replace('-', '')[:12]
                temp_dir = Path(f"temp/assets_{session_id}")
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                for uploaded_file in uploaded_files:
                    file_path = temp_dir / uploaded_file.name
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    audio_asset_paths.append(str(file_path.absolute()))
                
                st.success(tr("i2v.assets.character_sucess"))
                
                # Preview uploaded assets
                with st.expander(tr("i2v.assets.preview"), expanded=True):
                    # Show in a grid (3 columns)
                    cols = st.columns(3)
                    for i, (file, path) in enumerate(zip(uploaded_files, audio_asset_paths)):
                        with cols[i % 3]:
                            # Check if image
                            ext = Path(path).suffix.lower()
                            if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                st.image(file, caption=file.name, width="stretch")
            else:
                st.info(tr("i2v.assets.character_empty_hint"))
            
            prompt_text = st.text_area(
                        tr("i2v.input_text"),
                        placeholder=tr("i2v.input.topic_placeholder"),
                        height=200,
                        help=tr("input.text_help_audio"),
                        key=self._k("audio_box")
                        )
            
            i2v_workflows = list_i2v_workflows()
            workflow_options = [wf["display_name"] for wf in i2v_workflows] 
            workflow_keys = [wf["key"] for wf in i2v_workflows]               
            default_workflow_index = 0

            workflow_display = st.selectbox(
                tr("i2v.workflow_select"),
                workflow_options if workflow_options else ["No workflow found"],
                index=default_workflow_index,
                label_visibility="collapsed",
                key=self._k("i2v_workflow_select")
            )

            if workflow_options:
                workflow_selected_index = workflow_options.index(workflow_display)
                workflow_key = workflow_keys[workflow_selected_index]
            else:
                workflow_key = None

            image_urls = []
            
            # Check and warn for selfhost workflow (auto popup if not confirmed)
            check_and_warn_selfhost_workflow(workflow_key)

            # ============================================================
            # 工作流参数面板（仅 RunningHub 云端工作流）
            # ============================================================
            param_overrides: list[tuple[str, str, Any]] = []
            task_options: dict[str, Any] = {}
            is_rh = bool(workflow_key and workflow_key.startswith("runninghub/"))
            if is_rh and workflow_key:
                param_overrides = self._render_workflow_params(pixelle_video, workflow_key)
                task_options = self._render_task_options()

            return {
                "audio_assets": audio_asset_paths,
                "prompt_text": prompt_text,
                "workflow_key": workflow_key,
                "image_urls": image_urls,
                "param_overrides": param_overrides,
                "task_options": task_options,
                }

    def _render_task_options(self) -> dict[str, Any]:
        """渲染 RunningHub 任务高级选项（addMetadata / instanceType / usePersonalQueue / retainSeconds）。"""
        with st.expander("🛠️ 任务高级选项", expanded=False):
            st.caption("对应 RunningHub `/task/openapi/create` 接口的可选参数")
            col1, col2 = st.columns(2)
            with col1:
                instance_type = st.selectbox(
                    "instanceType（实例类型）",
                    ["default", "plus"],
                    index=0,
                    help="plus 走 48G 显存机器（仅部分账号支持）",
                    key=self._k("rh_instance_type"),
                )
                add_metadata = st.checkbox(
                    "addMetadata（写入元信息）",
                    value=True,
                    help="是否在输出文件里写入提示词等元信息",
                    key=self._k("rh_add_metadata"),
                )
            with col2:
                use_personal_queue = st.checkbox(
                    "usePersonalQueue（独占排队）",
                    value=False,
                    help="独占 apiKey 时使用，平台自动排队",
                    key=self._k("rh_use_personal_queue"),
                )
                retain_seconds = st.number_input(
                    "retainSeconds（实例保留秒数）",
                    min_value=0,
                    max_value=180,
                    value=0,
                    step=10,
                    help="企业共享 apiKey 生效，0 表示不保留；10~180 之间会产生额外费用",
                    key=self._k("rh_retain_seconds"),
                )
        return {
            "instanceType": instance_type,
            "addMetadata": add_metadata,
            "usePersonalQueue": use_personal_queue,
            "retainSeconds": int(retain_seconds) if retain_seconds else None,
        }

    def _render_workflow_params(self, pixelle_video, workflow_key: str) -> list[tuple[str, str, Any]]:
        """渲染 RunningHub 云端工作流的可调参数面板，返回 [(node_id, field, value), ...]。"""
        import json
        try:
            workflow_path = Path("workflows") / workflow_key
            with open(workflow_path, "r", encoding="utf-8") as f:
                workflow_config = json.load(f)
            workflow_id = workflow_config.get("workflow_id")
            if not workflow_id:
                return []
        except Exception as exc:
            logger.warning(f"[i2v] 读取工作流配置失败: {exc}")
            return []

        @st.cache_data(ttl=600, show_spinner=False)
        def _cached_discover(wid: str, cfg_json: str, _ver: str) -> dict:
            async def _do():
                kit = await pixelle_video._get_or_create_comfykit()
                rh_executor = kit._get_runninghub_executor()
                cfg = json.loads(cfg_json) if cfg_json else None
                return await discover_workflow_params(rh_executor.client, wid, cfg)
            return run_async(_do())

        with st.expander("⚙️ 工作流参数", expanded=False):
            # 刷新按钮：清空缓存重新拉取云端工作流（参数策略变更时使用）
            if st.button("🔄 刷新参数", key=self._k(f"i2v_param_refresh_{workflow_id}")):
                _cached_discover.clear()
                st.rerun()
            try:
                cfg_json = json.dumps(workflow_config, ensure_ascii=False, sort_keys=True)
                discovery = _cached_discover(workflow_id, cfg_json, "v6-explicit-mapping")
            except Exception as exc:
                st.warning(f"加载工作流参数失败：{exc}")
                return []

            params = discovery.get("params", []) or []
            if not params:
                st.caption("未识别到可调参数（节点 title 中无常见字段，或全部为连线输入）。")
                return []

            overrides: list[tuple[str, str, Any]] = []
            cols = st.columns(2)
            for idx, meta in enumerate(params):
                node_id = meta["node_id"]
                field = meta["field_name"]
                cur = meta["current_value"]
                t = meta["inferred_type"]
                label = meta["label"]
                wkey = self._k(f"i2v_param_{workflow_id}_{node_id}_{field}")
                with cols[idx % 2]:
                    if t == "bool":
                        v = st.checkbox(label, value=bool(cur), key=wkey)
                    elif t == "int":
                        v = st.number_input(
                            label,
                            value=int(cur),
                            min_value=int(meta.get("min", 0)),
                            max_value=int(meta.get("max", 2**31 - 1)),
                            step=int(meta.get("step", 1)),
                            key=wkey,
                        )
                        v = int(v)
                    elif t == "float":
                        v = st.number_input(
                            label,
                            value=float(cur),
                            min_value=float(meta.get("min", 0.0)),
                            max_value=float(meta.get("max", 100.0)),
                            step=float(meta.get("step", 0.1)),
                            key=wkey,
                        )
                        v = float(v)
                    elif t == "enum":
                        options = meta.get("options", [cur])
                        try:
                            idx_default = options.index(cur)
                        except ValueError:
                            idx_default = 0
                        v = st.selectbox(label, options, index=idx_default, key=wkey)
                    else:
                        v = st.text_input(label, value=str(cur), key=wkey)
                if v != cur:
                    overrides.append((node_id, field, v))
            return overrides

    def _render_output_preview(self, pixelle_video: Any, video_params: dict):
        """Render output preview section"""
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            # Check configuration
            if not config_manager.validate():
                st.warning(tr("settings.not_configured"))
            
            audio_assets = video_params.get("audio_assets", [])
            prompt_text = video_params.get("prompt_text", "")
            workflow_key = video_params.get("workflow_key")
            image_urls = video_params.get("image_urls", [])
            param_overrides = video_params.get("param_overrides", []) or []
            task_options = video_params.get("task_options", {}) or {}
            is_runninghub_workflow = bool(workflow_key and workflow_key.startswith("runninghub/"))

            logger.info(f"  - video_params: {video_params}")

            if not is_runninghub_workflow and not audio_assets:
                st.info(tr("i2v.assets.image_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate_disabled")
                )
                return

            if not prompt_text:
                st.info(tr("i2v.assets.prompt_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate")
                )
                return

            if is_runninghub_workflow and not audio_assets:
                st.info("RunningHub 工作流需要先上传图片，请在左侧上传本地图片。")
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate_need_urls")
                )
                return

            # Generate button
            if st.button(tr("btn.generate"), type="primary", width="stretch", key=self._k("i2v_generate")):
                if not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    st.stop()
                
                progress_bar = st.progress(0)
                status_text = st.empty()

                start_time = time.time()

                try:
                    async def generate_audio_visual_video():
                        task_dir, task_id = create_task_output_dir()
                        logger.info(f"[Initialization] Task Directory: {task_dir}")
                        kit = await pixelle_video._get_or_create_comfykit()
                        
                        import json
                        from pathlib import Path

                        status_text.text(tr("progress.generation"))
                        progress_bar.progress(10)
                        image_path = audio_assets[0] if audio_assets else None
                        prompt = prompt_text

                        workflow_path = Path("workflows") / workflow_key

                        if is_runninghub_workflow:
                            config_manager.reload()
                            if not image_path:
                                raise Exception("RunningHub 工作流需要上传首帧图片。")

                            with open(workflow_path, 'r', encoding='utf-8') as f:
                                workflow_config = json.load(f)
                            workflow_id = workflow_config.get("workflow_id")
                            if not workflow_id:
                                raise Exception(f"工作流配置中没有 workflow_id: {workflow_key}")

                            generated_video_url = await run_runninghub_i2v(
                                kit=kit,
                                workflow_id=workflow_id,
                                image_path=image_path,
                                prompt=prompt,
                                param_overrides=param_overrides,
                                task_options=task_options,
                                workflow_config=workflow_config,
                                status_text=status_text,
                            )
                        else:
                            if not workflow_path.exists():
                                raise Exception(f"The workflow file does not exist: {workflow_path}")
                            if not image_path:
                                raise Exception("Selfhost 图生视频需要上传本地首帧图片。")

                            with open(workflow_path, 'r', encoding='utf-8') as f:
                                workflow_config = json.load(f)

                            workflow_params = {
                                "image": image_path,
                                "prompt": prompt,
                            }
                            workflow_input = str(workflow_path)
                            if workflow_config.get("source") == "runninghub" and "workflow_id" in workflow_config:
                                workflow_input = workflow_config["workflow_id"]

                            video_result = await kit.execute(workflow_input, workflow_params)

                            generated_video_url = None
                            if hasattr(video_result, 'videos') and video_result.videos:
                                generated_video_url = video_result.videos[0]
                            elif hasattr(video_result, 'outputs') and video_result.outputs:
                                for node_id, node_output in video_result.outputs.items():
                                    if isinstance(node_output, dict) and 'videos' in node_output:
                                        videos = node_output['videos']
                                        if videos and len(videos) > 0:
                                            generated_video_url = videos[0]
                                            break

                        if not generated_video_url:
                            raise Exception("The workflow did not return a video. Please check the workflow configuration.")

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
                    final_video_path = run_async(generate_audio_visual_video())

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
                    logger.exception(e)
                    status_text.text("")
                    progress_bar.empty()
                    st.error(tr("status.error", error=str(e)))
                    st.stop()

register_pipeline_ui(ImageToVideoPipelineUI)


