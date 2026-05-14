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
from web.utils.runninghub_i2v import discover_workflow_params, run_runninghub_i2v, run_runninghub_i2v_v2
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

    @staticmethod
    def _normalize_named_params(params: dict[str, Any]) -> dict[str, Any]:
        """Normalize numeric-like string values for named kwargs passed to media service."""
        out = dict(params)

        def _to_int_like(v):
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return v
                try:
                    return int(float(s))
                except (TypeError, ValueError):
                    return v
            return v

        def _to_float_like(v):
            if isinstance(v, bool):
                return float(int(v))
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return v
                try:
                    return float(s)
                except (TypeError, ValueError):
                    return v
            return v

        for k in ("duration", "seed", "steps", "width", "height"):
            if k in out and out[k] not in (None, ""):
                out[k] = _to_int_like(out[k])
        if "cfg" in out and out["cfg"] not in (None, ""):
            out["cfg"] = _to_float_like(out["cfg"])
        return out

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
                # 追加 RunningHub 低价渠道 registry 中的图生视频 / 首尾帧模型
                try:
                    from pixelle_video.services import runninghub_registry as _rh_reg
                    for _m in _rh_reg.list_models():
                        cat = _m.get("category") or ""
                        if cat in ("image-to-video", "start-end-to-video"):
                            result.append({
                                "key": _m["workflow_key"],
                                "display_name": f"[{cat}] {_m['name']} - RH低价",
                            })
                except Exception:
                    pass
                return result

            # ── 工作流选择（先选再展示对应图片槽位）─────────────────────
            i2v_workflows = list_i2v_workflows()
            workflow_options = [wf["display_name"] for wf in i2v_workflows]
            workflow_keys = [wf["key"] for wf in i2v_workflows]
            default_workflow_index = 0

            workflow_display = st.selectbox(
                tr("i2v.workflow_select"),
                workflow_options if workflow_options else ["No workflow found"],
                index=default_workflow_index,
                label_visibility="collapsed",
                key=self._k("i2v_workflow_select"),
            )

            if workflow_options:
                workflow_selected_index = workflow_options.index(workflow_display)
                workflow_key = workflow_keys[workflow_selected_index]
            else:
                workflow_key = None

            # ── 读取当前工作流的多图槽位声明 ─────────────────────────────
            import json as _json_i2v
            import uuid as _uuid_i2v
            _image_inputs: list[dict] = []
            _audio_node_id: str | None = None
            _audio_field: str = "audio"
            _wf_cfg: dict = {}
            if workflow_key and workflow_key.startswith("runninghub/"):
                try:
                    _wf_path = Path("workflows") / workflow_key
                    _wf_cfg = _json_i2v.loads(_wf_path.read_text("utf-8"))
                    _image_inputs = _wf_cfg.get("image_inputs") or []
                    _audio_node_id = _wf_cfg.get("audio_node_id")
                    _audio_field = _wf_cfg.get("audio_field") or "audio"
                except Exception:
                    _image_inputs = []

            audio_asset_paths: list[str] = []
            named_image_paths: dict[str, str] = {}  # node_id -> local file path

            def _save_uploaded(uf) -> str:
                td = Path(f"temp/assets_{_uuid_i2v.uuid4().hex[:10]}")
                td.mkdir(parents=True, exist_ok=True)
                fp = td / uf.name
                with open(fp, "wb") as fh:
                    fh.write(uf.getbuffer())
                return str(fp.absolute())

            if _image_inputs:
                # 首尾帧等多槽位工作流：每个槽位独立上传
                for _slot in _image_inputs:
                    _nid = str(_slot["node_id"])
                    _lbl = _slot.get("label", f"图片（节点 {_nid}）")
                    _req = _slot.get("required", True)
                    _up = st.file_uploader(
                        f"{_lbl}{'（必填）' if _req else '（可选）'}",
                        type=["jpg", "jpeg", "png", "webp"],
                        accept_multiple_files=False,
                        key=self._k(f"img_slot_{_nid}"),
                    )
                    if _up:
                        _p = _save_uploaded(_up)
                        named_image_paths[_nid] = _p
                        audio_asset_paths.append(_p)
                        st.image(_up, caption=_lbl, width=160)
                    elif _req:
                        st.caption(f"⬆️ 请上传「{_lbl}」")
            else:
                # 普通 i2v：通用多文件上传
                uploaded_files = st.file_uploader(
                    tr("i2v.assets.upload"),
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    help=tr("i2v.assets.upload_help"),
                    key=self._k("material_files"),
                )

                if uploaded_files:
                    for uploaded_file in uploaded_files:
                        _p = _save_uploaded(uploaded_file)
                        audio_asset_paths.append(_p)
                    st.success(tr("i2v.assets.character_sucess"))

                    with st.expander(tr("i2v.assets.preview"), expanded=True):
                        cols = st.columns(3)
                        for i, (file, path) in enumerate(zip(uploaded_files, audio_asset_paths)):
                            with cols[i % 3]:
                                ext = Path(path).suffix.lower()
                                if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                    st.image(file, caption=file.name, width="stretch")
                else:
                    st.info(tr("i2v.assets.character_empty_hint"))

            # 必填图片完整性校验
            _required_nids = [str(s["node_id"]) for s in _image_inputs if s.get("required", True)]
            image_inputs_ok: bool = (
                all(nid in named_image_paths for nid in _required_nids)
                if _required_nids else True
            )

            # 音频上传（仅当工作流声明了 audio_node_id）
            audio_asset_path: str | None = None
            if _audio_node_id:
                _audio_up = st.file_uploader(
                    "🎵 口播音频（必填）",
                    type=["mp3", "wav", "m4a", "aac"],
                    accept_multiple_files=False,
                    key=self._k("audio_file_upload"),
                )
                if _audio_up:
                    audio_asset_path = _save_uploaded(_audio_up)
                    st.success(f"✅ 已上传音频: {_audio_up.name}")
                else:
                    st.caption("⬆️ 请上传 mp3 / wav / m4a 音频文件")

            prompt_text = st.text_area(
                        tr("i2v.input_text"),
                        placeholder=tr("i2v.input.topic_placeholder"),
                        height=200,
                        help=tr("input.text_help_audio"),
                        key=self._k("audio_box")
                        )

            image_urls = []

            # Check and warn for selfhost workflow (auto popup if not confirmed)
            check_and_warn_selfhost_workflow(workflow_key)

            # ============================================================
            # 工作流参数面板（仅 RunningHub 云端工作流）
            # ============================================================
            param_overrides: list[tuple[str, str, Any]] = []
            task_options: dict[str, Any] = {}
            rh_api_params: dict[str, Any] = {}
            is_rh = bool(workflow_key and workflow_key.startswith("runninghub/"))
            is_rh_api = bool(workflow_key and workflow_key.startswith("runninghub-api/"))
            if is_rh and workflow_key:
                param_overrides = self._render_workflow_params(pixelle_video, workflow_key)
                task_options = self._render_task_options()
            elif is_rh_api and workflow_key:
                rh_api_params = self._render_rh_api_params(workflow_key)

            return {
                "audio_assets": audio_asset_paths,
                "prompt_text": prompt_text,
                "workflow_key": workflow_key,
                "image_urls": image_urls,
                "param_overrides": param_overrides,
                "task_options": task_options,
                "rh_api_params": rh_api_params,
                "is_rh_api": is_rh_api,
                "named_image_paths": named_image_paths,
                "image_inputs_ok": image_inputs_ok,
                "audio_asset_path": audio_asset_path,
                "has_audio_input": bool(_audio_node_id),
                }

    def _render_rh_api_params(self, workflow_key: str) -> dict[str, Any]:
        """渲染 RunningHub 低价渠道 / 标准模型 API 的动态参数面板（registry 驱动）。"""
        from pixelle_video.services import runninghub_registry as rh_reg
        from pixelle_video.config import config_manager as _cfg_mgr

        model = rh_reg.get_model_by_workflow_key(workflow_key)
        if not model:
            st.warning(f"未在 registry 中找到模型: {workflow_key}")
            return {}

        # 鉴权前置校验：「低价渠道版」/rhart-* 端点在 RunningHub 服务端归类为
        # "Standard Model API"，仅接受「企业级-共享 API Key」。若仅配置了
        # consumer key，服务端会返回 errorCode=1014。此处给出明确提示。
        _ent_key = (getattr(_cfg_mgr.config.comfyui, "runninghub_api_key", "") or "").strip()
        _con_key = (getattr(_cfg_mgr.config.comfyui, "runninghub_consumer_api_key", "") or "").strip()
        if not _ent_key:
            st.error(
                "⚠️ 该模型为 RunningHub「标准模型 API」（俗称「低价渠道版」），"
                "**必须配置「企业级-共享 API Key」**（`config.yaml` → `comfyui.runninghub_api_key`）。\n\n"
                "**注意**：名字里的「低价渠道版」只表示套餐内单价较低，鉴权层级仍属标准模型 API；"
                "消费级 key (`runninghub_consumer_api_key`) **不能** 调用 `/rhart-*` 接口，"
                "会返回 `errorCode=1014: Standard Model API is restricted to Enterprise-Shared API Keys only`。\n\n"
                "消费级 key 的用途：仅 ComfyUI workflow_id 形式的工作流（如数字人 digital_image）。"
            )
        elif _con_key and _ent_key == _con_key:
            st.warning(
                "⚠️ 检测到 `runninghub_api_key` 与 `runninghub_consumer_api_key` 相同，"
                "请确认前者是「企业级-共享 API Key」，否则调用本模型时会收到 1014 错误。"
            )

        with st.expander(f"⚙️ 参数 — {model['name']}", expanded=True):
            highlight = model.get("modelHighlights")
            if highlight:
                st.caption(highlight)
            values: dict[str, Any] = {}
            inputs = model.get("inputs", []) or []
            cols = st.columns(2)
            for idx, spec in enumerate(inputs):
                k = spec["fieldKey"]
                # 由 pipeline 自动注入的字段，不在 UI 暴露
                if k in ("prompt", "imageUrls", "imageUrl", "firstFrameUrl", "lastFrameUrl"):
                    continue
                t = spec.get("type")
                label = spec.get("description") or k
                if spec.get("required"):
                    label = f"{label} *"
                default = spec.get("defaultValue")
                wkey = self._k(f"rh_api_{workflow_key}_{k}")
                with cols[idx % 2]:
                    if t == "LIST":
                        options = [o.get("value") for o in (spec.get("options") or [])]
                        if not options:
                            continue
                        try:
                            idx_default = options.index(default) if default in options else 0
                        except ValueError:
                            idx_default = 0
                        values[k] = st.selectbox(label, options, index=idx_default, key=wkey)
                    elif t == "BOOLEAN":
                        values[k] = st.checkbox(label, value=bool(default) if default is not None else False, key=wkey)
                    elif t == "INT":
                        try:
                            min_v = int(spec.get("minValue") or 0)
                            max_v = int(spec.get("maxValue") or 2**31 - 1)
                            cur = int(default) if default not in (None, "") else min_v
                        except Exception:
                            min_v, max_v, cur = 0, 2**31 - 1, 0
                        values[k] = int(st.number_input(label, min_value=min_v, max_value=max_v, value=cur, key=wkey))
                    elif t == "STRING":
                        max_len = int(spec.get("maxLength") or 1000)
                        if max_len > 200:
                            values[k] = st.text_area(label, value=str(default or ""), max_chars=max_len, key=wkey, height=100)
                        else:
                            values[k] = st.text_input(label, value=str(default or ""), max_chars=max_len, key=wkey)
                    elif t in ("IMAGE", "VIDEO"):
                        st.caption(f"{label}（首帧/参考素材请在左侧上传，URL 会自动注入）")
                    else:
                        values[k] = st.text_input(label, value=str(default or ""), key=wkey)
            # 清理空值
            return {kk: vv for kk, vv in values.items() if vv not in (None, "")}

    def _render_task_options(self) -> dict[str, Any]:
        """渲染 RunningHub 任务高级选项（addMetadata / instanceType / usePersonalQueue / retainSeconds）。"""
        with st.expander("🛠️ 任务高级选项", expanded=False):
            st.caption("对应 RunningHub `/task/openapi/create` 接口的可选参数")
            col1, col2 = st.columns(2)
            with col1:
                random_seed = st.checkbox(
                    "randomSeed（随机种子）",
                    value=True,
                    help="开启后每次生成随机；关闭后尽量复用工作流内 seed（结果更可复现）",
                    key=self._k("rh_random_seed"),
                )
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
            "randomSeed": random_seed,
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

        # 消费级 v2 工作流：直接从 JSON 配置渲染参数，无需拉取企业级云端 JSON
        if workflow_config.get("use_consumer_v2"):
            explicit = workflow_config.get("extra_params") or []
            if not explicit:
                return []
            with st.expander("⚙️ 工作流参数", expanded=False):
                return self._render_explicit_params(workflow_id, explicit)

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
                _msg = str(exc)
                if "WORKFLOW_NOT_SAVED_OR_NOT_RUNNING" in _msg:
                    st.error(
                        f"⚠️ RunningHub 工作流 `{workflow_id}` **未发布 API 服务**。\n\n"
                        "请前往 RunningHub 网页 → 我的工作流 → 找到该工作流 → 点击 **"
                        "「发布 API」/「启动 API 服务」**，等状态变为「运行中」后再刷新本页。\n\n"
                        "同时请核对工作流 JSON 中的 `workflow_id` 是否正确。"
                    )
                else:
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
                        disp = meta.get("display_labels")
                        if isinstance(disp, list) and len(disp) == len(options):
                            _fmt = lambda x, _o=options, _d=disp: _d[_o.index(x)] if x in _o else str(x)
                            v = st.selectbox(label, options, index=idx_default, key=wkey, format_func=_fmt)
                        else:
                            v = st.selectbox(label, options, index=idx_default, key=wkey)
                    else:
                        v = st.text_input(label, value=str(cur), key=wkey)
                if v != cur:
                    overrides.append((node_id, field, v))
            return overrides

    def _render_explicit_params(self, workflow_id: str, extra_params: list) -> list[tuple[str, str, Any]]:
        """为 use_consumer_v2 工作流直接从 JSON 配置渲染 extra_params，无需拉取云端 JSON。"""
        overrides: list[tuple[str, str, Any]] = []
        cols = st.columns(2)
        for idx, p in enumerate(extra_params):
            nid = str(p.get("node_id", ""))
            fname = p.get("field_name") or p.get("field") or ""
            if not nid or not fname:
                continue
            label = p.get("label") or f"{fname} (node {nid})"
            ptype = p.get("type", "str")
            default = p.get("default")
            wkey = self._k(f"i2v_param_{workflow_id}_{nid}_{fname}")
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
                else:  # str 及其它
                    cur_str = str(default if default is not None else "")
                    v_str = st.text_input(label, value=cur_str, key=wkey)
                    if v_str != cur_str:
                        overrides.append((nid, fname, v_str))
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
            rh_api_params = video_params.get("rh_api_params", {}) or {}
            is_runninghub_workflow = bool(workflow_key and workflow_key.startswith("runninghub/"))
            is_rh_api_workflow = bool(workflow_key and workflow_key.startswith("runninghub-api/"))
            named_image_paths = video_params.get("named_image_paths", {}) or {}
            image_inputs_ok = video_params.get("image_inputs_ok", True)
            audio_asset_path = video_params.get("audio_asset_path")
            has_audio_input = video_params.get("has_audio_input", False)

            logger.info(f"  - video_params: {video_params}")

            if not is_runninghub_workflow and not audio_assets and not named_image_paths:
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

            if is_runninghub_workflow and not audio_assets and not named_image_paths:
                st.info("RunningHub 工作流需要先上传图片，请在左侧上传本地图片。")
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate_need_urls")
                )
                return

            if is_runninghub_workflow and not image_inputs_ok:
                st.info("请补全所有必填图片（首帧 + 尾帧）后再生成。")
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate_incomplete")
                )
                return

            if is_runninghub_workflow and has_audio_input and not audio_asset_path:
                st.info("该工作流需要上传口播音频，请在左侧上传音频文件。")
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    width="stretch",
                    disabled=True,
                    key=self._k("audio_visual_generate_need_audio")
                )
                return

            # 校验 prompt 最小长度（针对 RunningHub API）
            prompt_min = 5
            if is_rh_api_workflow:
                try:
                    from pixelle_video.services import runninghub_registry as _rh_reg
                    rh_model = _rh_reg.get_model_by_workflow_key(workflow_key)
                    if rh_model:
                        prompt_spec = next(
                            (i for i in (rh_model.get("inputs") or []) if i.get("fieldKey") == "prompt"),
                            {},
                        )
                        prompt_min = prompt_spec.get("minLength", 5)
                except Exception:
                    pass
            
            prompt_too_short = len(prompt_text.strip()) < prompt_min

            # Generate button
            if st.button(
                tr("btn.generate"), 
                type="primary", 
                width="stretch", 
                disabled=prompt_too_short,
                key=self._k("i2v_generate")
            ):
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

                        if is_rh_api_workflow:
                            config_manager.reload()
                            from pixelle_video.services import runninghub_registry as _rh_reg

                            model = _rh_reg.get_model_by_workflow_key(workflow_key)
                            if not model:
                                raise Exception(f"未在 registry 中找到模型: {workflow_key}")

                            # 把上传的图片作为 imageUrl / imageUrls 注入（media.py 会自动上传到 RH CDN）
                            field_keys = {i["fieldKey"] for i in model.get("inputs", [])}
                            params: dict[str, Any] = dict(rh_api_params)
                            if image_path:
                                if "imageUrls" in field_keys:
                                    params.setdefault("imageUrls", [image_path])
                                elif "imageUrl" in field_keys:
                                    params.setdefault("imageUrl", image_path)
                                elif "firstFrameUrl" in field_keys:
                                    params.setdefault("firstFrameUrl", image_path)

                            media_svc = pixelle_video.media
                            status_text.text("正在调用 RunningHub 低价渠道模型...")
                            progress_bar.progress(30)
                            # 把会与 MediaService.__call__ 命名参数冲突的 key 提出来单独传
                            _named = {}
                            for _k in ("duration", "width", "height", "seed", "steps", "cfg", "sampler", "negative_prompt"):
                                if _k in params:
                                    _named[_k] = params.pop(_k)
                            _named = self._normalize_named_params(_named)
                            result = await media_svc(
                                prompt=prompt,
                                workflow=workflow_key,
                                media_type="video",
                                **_named,
                                **params,
                            )
                            generated_video_url = result.url
                        elif is_runninghub_workflow:
                            config_manager.reload()
                            if not image_path and not named_image_paths:
                                raise Exception("RunningHub 工作流需要上传图片。")

                            with open(workflow_path, 'r', encoding='utf-8') as f:
                                workflow_config = json.load(f)
                            workflow_id = workflow_config.get("workflow_id")
                            if not workflow_id:
                                raise Exception(f"工作流配置中没有 workflow_id: {workflow_key}")

                            if workflow_config.get("use_consumer_v2"):
                                # 走「消费级 key + OpenAPI v2」路径（绕开 ComfyKit/企业级 key）
                                status_text.text("使用消费级 API Key (v2) 调用 RunningHub...")
                                generated_video_url = await run_runninghub_i2v_v2(
                                    workflow_id=workflow_id,
                                    image_path=image_path,
                                    prompt=prompt,
                                    workflow_config=workflow_config,
                                    named_image_paths=named_image_paths or None,
                                    audio_path=audio_asset_path,
                                    param_overrides=param_overrides,
                                    task_options=task_options,
                                    status_text=status_text,
                                )
                            else:
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


