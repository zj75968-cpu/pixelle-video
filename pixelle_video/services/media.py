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
Media Generation Service - ComfyUI Workflow-based implementation

Supports both image and video generation workflows.
Automatically detects output type based on ExecuteResult.
"""

from typing import Optional

from comfykit import ComfyKit
from loguru import logger

from pixelle_video.services.comfy_base_service import ComfyBaseService
from pixelle_video.models.media import MediaResult


class MediaService(ComfyBaseService):
    """
    Media generation service - Workflow-based
    
    Uses ComfyKit to execute image/video generation workflows.
    Supports both image_ and video_ workflow prefixes.
    
    Usage:
        # Use default workflow (workflows/image_flux.json)
        media = await pixelle_video.media(prompt="a cat")
        if media.is_image:
            print(f"Generated image: {media.url}")
        elif media.is_video:
            print(f"Generated video: {media.url} ({media.duration}s)")
        
        # Use specific workflow
        media = await pixelle_video.media(
            prompt="a cat",
            workflow="image_flux.json"
        )
        
        # List available workflows
        workflows = pixelle_video.media.list_workflows()
    """
    
    WORKFLOW_PREFIX = ""  # Will be overridden by _scan_workflows
    DEFAULT_WORKFLOW = None  # No hardcoded default, must be configured
    WORKFLOWS_DIR = "workflows"
    
    def __init__(self, config: dict, core=None):
        """
        Initialize media service
        
        Args:
            config: Full application config dict
            core: PixelleVideoCore instance (for accessing shared ComfyKit)
        """
        super().__init__(config, service_name="image", core=core)  # Keep "image" for config compatibility

    @staticmethod
    def _to_int_if_numeric(value):
        """Convert numeric-like values to int, keep original when not numeric."""
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return value
            try:
                return int(float(s))
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def _to_float_if_numeric(value):
        """Convert numeric-like values to float, keep original when not numeric."""
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return value
            try:
                return float(s)
            except (TypeError, ValueError):
                return value
        return value
    
    def _scan_workflows(self):
        """
        Scan workflows for both image_ and video_ prefixes
        
        Override parent method to support multiple prefixes
        """
        from pixelle_video.utils.os_util import list_resource_dirs, list_resource_files, get_resource_path
        from pathlib import Path
        
        workflows = []
        
        # Get all workflow source directories
        source_dirs = list_resource_dirs("workflows")
        
        if not source_dirs:
            logger.warning("No workflow source directories found")
            return workflows
        
        # Scan each source directory for workflow files
        for source_name in source_dirs:
            # Get all JSON files for this source
            workflow_files = list_resource_files("workflows", source_name)
            
            # Filter to only files matching image_ or video_ prefix
            # i2v_ 前缀的文件属于图生视频流水线，不在 media service 的扫描范围内
            matching_files = [
                f for f in workflow_files 
                if (f.startswith("image_") or f.startswith("video_")) and f.endswith('.json')
            ]
            
            for filename in matching_files:
                try:
                    # Get actual file path
                    file_path = Path(get_resource_path("workflows", source_name, filename))
                    workflow_info = self._parse_workflow_file(file_path, source_name)
                    workflows.append(workflow_info)
                    logger.debug(f"Found workflow: {workflow_info['key']}")
                except Exception as e:
                    logger.error(f"Failed to parse workflow {source_name}/{filename}: {e}")
        
        # Sort by key (source/name)
        # Add virtual RunningHub Model API workflows from registry
        # （由 registry 驱动；如不希望展示，可设置 comfyui.show_unavailable_workflows=false 并改下面 if）
        try:
            from pixelle_video.config import config_manager
            show_unavailable = bool(getattr(config_manager.config.comfyui, "show_unavailable_workflows", False))
        except Exception:
            show_unavailable = False

        # 默认：始终把 registry 的 RunningHub 低价模型加入（用户已要求接入）。
        # 仍允许通过 show_unavailable_workflows=false 强制隐藏（向后兼容）。
        try:
            from pixelle_video.services import runninghub_registry as _rh_reg
            for _m in _rh_reg.list_models():
                workflows.append({
                    "key": _m["workflow_key"],
                    "source": "runninghub-api",
                    "name": _m["rhEndpoint"].lstrip("/"),
                    "display_name": f"[{_m['category']}] {_m['name']}",
                    "description": (_m.get("modelHighlights") or "")[:120],
                    "path": None,
                    # 额外元数据，供 UI 动态渲染参数表单使用
                    "runninghub_model": _m,
                })
        except Exception as e:
            logger.warning(f"加载 RunningHub registry 失败: {e}")

        if not show_unavailable:
            # 不展示自部署 selfhost/*（默认无本地 ComfyUI）
            workflows = [wf for wf in workflows if wf.get("source") != "selfhost"]
        # 过滤分析类工作流（category: video-analysis / image-analysis 等），不列入生成流水线
        workflows = [wf for wf in workflows if not (wf.get("category") or "").endswith("-analysis")]

        # 动态注入 chatfire.cn 模型条目（读取 post_image preset）
        try:
            from pixelle_video.config import config_manager as _cf_mgr
            _preset = _cf_mgr.get_post_model_preset("post_image")
            if "chatfire" in (_preset.get("base_url") or "").lower() and _preset.get("api_key"):
                # chatfire 已接管图片生成 → 去掉所有 RunningHub/文件型 图片 workflow
                # 只保留视频类（text-to-video / video-tools / image-to-video）和分析类已被过滤掉的
                def _is_image_wf(wf):
                    src = wf.get("source", "")
                    if src == "chatfire":
                        return False   # chatfire 自己不过滤
                    cat = (wf.get("category") or "").lower()
                    if cat in ("text-to-image", "image-to-image"):
                        return True
                    # 文件型工作流按 key 判断（image_*.json）
                    key_low = wf.get("key", "").lower()
                    rh_model = wf.get("runninghub_model")
                    if rh_model:
                        rh_cat = (rh_model.get("category") or "").lower()
                        return rh_cat in ("text-to-image", "image-to-image")
                    # 文件 workflow：key 含 /image_ 且不含 video
                    return "/image_" in key_low or key_low.startswith("runninghub/image_")
                workflows = [wf for wf in workflows if not _is_image_wf(wf)]

                _CHATFIRE_MODELS = [
                    ("nano-banana-pro",              "nano-banana-pro"),
                    ("nano-banana-pro_2k",           "nano-banana-pro 2K"),
                    ("nano-banana-pro_4k",           "nano-banana-pro 4K"),
                    ("nano-banana",                  "nano-banana"),
                    ("gemini-2.5-flash-image",       "Gemini 2.5 Flash Image"),
                    ("gemini-2.5-flash-image-preview",    "Gemini 2.5 Flash Preview"),
                    ("gemini-2.5-flash-image-preview-hd", "Gemini 2.5 Flash Preview HD"),
                ]
                for _mid, _label in _CHATFIRE_MODELS:
                    workflows.append({
                        "key": f"chatfire/{_mid}",
                        "source": "chatfire",
                        "name": _mid,
                        "display_name": f"[chatfire] {_label}",
                        "category": "text-to-image",
                        "path": None,
                    })
        except Exception as _e:
            logger.warning(f"加载 chatfire 模型失败: {_e}")

        return sorted(workflows, key=lambda w: w["key"])
    
    async def __call__(
        self,
        prompt: str,
        workflow: Optional[str] = None,
        # Media type specification (required for proper handling)
        media_type: str = "image",  # "image" or "video"
        # ComfyUI connection (optional overrides)
        comfyui_url: Optional[str] = None,
        runninghub_api_key: Optional[str] = None,
        # Common workflow parameters
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration: Optional[float] = None,  # Video duration in seconds (for video workflows)
        negative_prompt: Optional[str] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        cfg: Optional[float] = None,
        sampler: Optional[str] = None,
        **params
    ) -> MediaResult:
        """
        Generate media (image or video) using workflow
        
        Media type must be specified explicitly via media_type parameter.
        Returns a MediaResult object containing media type and URL.
        
        Args:
            prompt: Media generation prompt
            workflow: Workflow filename (default: from config or "image_flux.json")
            media_type: Type of media to generate - "image" or "video" (default: "image")
            comfyui_url: ComfyUI URL (optional, overrides config)
            runninghub_api_key: RunningHub API key (optional, overrides config)
            width: Media width
            height: Media height
            duration: Target video duration in seconds (only for video workflows, typically from TTS audio duration)
            negative_prompt: Negative prompt
            steps: Sampling steps
            seed: Random seed
            cfg: CFG scale
            sampler: Sampler name
            **params: Additional workflow parameters
        
        Returns:
            MediaResult object with media_type ("image" or "video") and url
        
        Examples:
            # Simplest: use default workflow (workflows/image_flux.json)
            media = await pixelle_video.media(prompt="a beautiful cat")
            if media.is_image:
                print(f"Image: {media.url}")
            
            # Use specific workflow
            media = await pixelle_video.media(
                prompt="a cat",
                workflow="image_flux.json"
            )
            
            # Video workflow
            media = await pixelle_video.media(
                prompt="a cat running",
                workflow="image_video.json"
            )
            if media.is_video:
                print(f"Video: {media.url}, duration: {media.duration}s")
            
            # With additional parameters
            media = await pixelle_video.media(
                prompt="a cat",
                workflow="image_flux.json",
                width=1024,
                height=1024,
                steps=20,
                seed=42
            )
            
            # With absolute path
            media = await pixelle_video.media(
                prompt="a cat",
                workflow="/path/to/custom.json"
            )
            
            # With custom ComfyUI server
            media = await pixelle_video.media(
                prompt="a cat",
                comfyui_url="http://192.168.1.100:8188"
            )
        """
        # 1. Resolve workflow (returns structured info)
        # --- Chatfire.cn 直接路由 (OpenAI-兼容 图片生成 API) ---
        if workflow and workflow.startswith("chatfire/"):
            from pixelle_video.services.llm_image_service import LLMImageService
            from pixelle_video.config import config_manager as _cf_mgr
            _preset = _cf_mgr.get_post_model_preset("post_image")
            _model_id = workflow[len("chatfire/"):]
            _llm_svc = LLMImageService()
            _size = _llm_svc._to_chatfire_size(f"{width or 1080}x{height or 1080}")
            _url = await _llm_svc.generate(
                prompt=prompt,
                api_key=_preset["api_key"],
                base_url=_preset["base_url"],
                model=_model_id,
                size=_size,
            )
            return MediaResult(media_type="image", url=_url)

        # --- RunningHub Model API direct routing (low-cost REST API, registry-driven) ---
        if workflow and workflow.startswith("runninghub-api/"):
            from pixelle_video.services.runninghub_api_service import RunningHubAPIService
            from pixelle_video.services import runninghub_registry as rh_reg

            model = rh_reg.get_model_by_workflow_key(workflow)
            if not model:
                raise ValueError(f"未找到 RunningHub 低价模型: {workflow}")

            # 准备用户参数：把通用 prompt / image_urls 等映射到模型的字段
            user_params = dict(params)  # 复制
            user_params.setdefault("prompt", prompt)

            # 通用宽高 -> aspectRatio 自动映射 / 无效值修正
            field_keys = {i["fieldKey"] for i in model.get("inputs", [])}
            if "aspectRatio" in field_keys:
                import math
                _ar_spec = next(
                    (i for i in model.get("inputs", []) if i.get("fieldKey") == "aspectRatio"),
                    {},
                )
                _options = [o["value"] for o in (_ar_spec.get("options") or []) if o.get("value")]

                def _parse_ratio(v: str) -> float:
                    if "x" in v.lower() and ":" not in v:
                        parts = v.lower().split("x")
                    else:
                        parts = v.split(":")
                    try:
                        return float(parts[0]) / float(parts[1])
                    except Exception:
                        return 1.0

                current_ar = user_params.get("aspectRatio")
                # 若用户没传，或传了但不在允许列表里，则自动选最近邻
                needs_fix = (current_ar is None) or (
                    _options and current_ar not in _options
                )
                if needs_fix and _options:
                    # 以 width/height 为基准；若未提供则解析当前值的比例
                    if width and height:
                        _target = int(width) / int(height)
                    elif current_ar:
                        _target = _parse_ratio(str(current_ar))
                    else:
                        _target = 1.0
                    user_params["aspectRatio"] = min(_options, key=lambda v: abs(_parse_ratio(v) - _target))
                elif needs_fix and not _options:
                    # 模型无选项列表，按宽高生成比例字符串
                    if width and height:
                        g = math.gcd(int(width), int(height))
                        user_params["aspectRatio"] = f"{int(width)//g}:{int(height)//g}"
            # 时长：LIST 模型优先保留字符串枚举；INT 模型再做数值约束
            if "duration" in field_keys and "duration" not in user_params and duration is not None:
                duration_spec = next(
                    (i for i in (model.get("inputs") or []) if i.get("fieldKey") == "duration"),
                    {},
                )
                duration_type = (duration_spec.get("type") or "").upper()
                if duration_type == "LIST":
                    user_params["duration"] = str(duration)
                else:
                    duration_norm = self._to_int_if_numeric(duration)
                    if isinstance(duration_norm, int):
                        user_params["duration"] = max(1, duration_norm)
                    else:
                        user_params["duration"] = duration

            # 常见数值参数做温和归一，避免字符串与数字混用
            for _k in ("seed", "steps", "width", "height"):
                if _k in user_params and user_params[_k] not in (None, ""):
                    user_params[_k] = self._to_int_if_numeric(user_params[_k])
            if "cfg" in user_params and user_params["cfg"] not in (None, ""):
                user_params["cfg"] = self._to_float_if_numeric(user_params["cfg"])

            # image_urls (多图模型) / imageUrl (单图模型) 兼容
            if "imageUrls" in field_keys and "imageUrls" not in user_params:
                imgs = params.get("image_urls") or params.get("imageUrl")
                if imgs:
                    user_params["imageUrls"] = imgs if isinstance(imgs, list) else [imgs]
            if "imageUrl" in field_keys and "imageUrl" not in user_params:
                img = params.get("imageUrl") or params.get("image_url")
                if not img:
                    imgs = params.get("image_urls")
                    if isinstance(imgs, list) and imgs:
                        img = imgs[0]
                if img:
                    user_params["imageUrl"] = img

            # 校验 prompt 长度（提前防护，避免触发 RunningHub 1007）
            prompt_spec = next(
                (i for i in (model.get("inputs") or []) if i.get("fieldKey") == "prompt"),
                {},
            )
            prompt_min_len = prompt_spec.get("minLength") or 5
            if len(str(user_params.get("prompt", "")).strip()) < prompt_min_len:
                raise ValueError(
                    f"提示词 (prompt) 过短：当前 {len(str(user_params.get('prompt', '')).strip())} 字符，"
                    f"最少需要 {prompt_min_len} 字符。请输入更详细的描述。"
                )

            api_svc = RunningHubAPIService()

            # 自动把本地图片路径上传到 RunningHub 云存储，转换成可访问 URL
            import os as _os
            async def _maybe_upload(val):
                if isinstance(val, str) and not val.startswith(("http://", "https://")) and _os.path.exists(val):
                    return await api_svc.upload_image(val)
                return val

            for spec in model.get("inputs", []):
                if spec.get("type") != "IMAGE":
                    continue
                key = spec["fieldKey"]
                if key not in user_params:
                    continue
                v = user_params[key]
                if isinstance(v, list):
                    user_params[key] = [await _maybe_upload(x) for x in v]
                else:
                    user_params[key] = await _maybe_upload(v)

            logger.info(f"[RunningHub低价] 调用 {model['name']} ({model['rhEndpoint']})")
            file_url = await api_svc.call_model(model["rhEndpoint"], user_params)
            media_kind = "video" if "video" in (model.get("category") or "") else "image"
            return MediaResult(media_type=media_kind, url=file_url)
        # --- 正常 ComfyKit 工作流 ---
        workflow_info = self._resolve_workflow(workflow=workflow)

        # 2. Build workflow parameters (ComfyKit config is now managed by core)
        workflow_params = {"prompt": prompt}
        
        # Add optional parameters
        if width is not None:
            workflow_params["width"] = width
        if height is not None:
            workflow_params["height"] = height
        if duration is not None:
            workflow_params["duration"] = duration
            if media_type == "video":
                logger.info(f"📏 Target video duration: {duration:.2f}s (from TTS audio)")
        if negative_prompt is not None:
            workflow_params["negative_prompt"] = negative_prompt
        if steps is not None:
            workflow_params["steps"] = steps
        if seed is not None:
            workflow_params["seed"] = seed
        if cfg is not None:
            workflow_params["cfg"] = cfg
        if sampler is not None:
            workflow_params["sampler"] = sampler
        
        # Add any additional parameters
        workflow_params.update(params)
        
        logger.debug(f"Workflow parameters: {workflow_params}")
        
        # 4. Execute workflow using shared ComfyKit instance from core
        try:
            # Get shared ComfyKit instance (lazy initialization + config hot-reload)
            kit = await self.core._get_or_create_comfykit()
            
            # Determine what to pass to ComfyKit based on source
            if workflow_info["source"] == "runninghub" and "workflow_id" in workflow_info:
                # RunningHub: pass workflow_id (ComfyKit will use runninghub backend)
                workflow_input = workflow_info["workflow_id"]
                logger.info(f"Executing RunningHub workflow: {workflow_input}")
            else:
                # Selfhost: pass file path (ComfyKit will use local ComfyUI)
                workflow_input = workflow_info["path"]
                logger.info(f"Executing selfhost workflow: {workflow_input}")
            
            result = await kit.execute(workflow_input, workflow_params)
            
            # 5. Handle result based on specified media_type
            if result.status != "completed":
                error_msg = result.msg or "Unknown error"
                logger.error(f"Media generation failed: {error_msg}")
                raise Exception(f"Media generation failed: {error_msg}")
            
            # Extract media based on specified type
            if media_type == "video":
                # Video workflow - get video from result
                if not result.videos:
                    logger.error("No video generated (workflow returned no videos)")
                    raise Exception("No video generated")
                
                video_url = result.videos[0]
                logger.info(f"✅ Generated video: {video_url}")
                
                # Try to extract duration from result (if available)
                duration = None
                if hasattr(result, 'duration') and result.duration:
                    duration = result.duration
                
                return MediaResult(
                    media_type="video",
                    url=video_url,
                    duration=duration
                )
            else:  # image
                # Image workflow - get image from result
                if not result.images:
                    logger.error("No image generated (workflow returned no images)")
                    raise Exception("No image generated")
                
                image_url = result.images[0]
                logger.info(f"✅ Generated image: {image_url}")
                
                return MediaResult(
                    media_type="image",
                    url=image_url
                )
        
        except Exception as e:
            logger.error(f"Media generation error: {e}")
            raise
