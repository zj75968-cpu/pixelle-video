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
Configuration schema with Pydantic models

Single source of truth for all configuration defaults and validation.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM configuration"""
    api_key: str = Field(default="", description="LLM API Key")
    base_url: str = Field(default="", description="LLM API Base URL")
    model: str = Field(default="", description="LLM Model Name")


class TTSLocalConfig(BaseModel):
    """Local TTS configuration (Edge TTS)"""
    voice: str = Field(default="zh-CN-YunjianNeural", description="Edge TTS voice ID")
    speed: float = Field(default=1.2, ge=0.5, le=2.0, description="Speech speed multiplier (0.5-2.0)")


class TTSComfyUIConfig(BaseModel):
    """ComfyUI TTS configuration"""
    default_workflow: Optional[str] = Field(default=None, description="Default TTS workflow (optional)")


class TTSSubConfig(BaseModel):
    """TTS-specific configuration (under comfyui.tts)"""
    inference_mode: str = Field(default="local", description="TTS inference mode: 'local' or 'comfyui'")
    local: TTSLocalConfig = Field(default_factory=TTSLocalConfig, description="Local TTS (Edge TTS) configuration")
    comfyui: TTSComfyUIConfig = Field(default_factory=TTSComfyUIConfig, description="ComfyUI TTS configuration")
    
    # Backward compatibility: keep default_workflow at top level
    @property
    def default_workflow(self) -> Optional[str]:
        """Get default workflow (for backward compatibility)"""
        return self.comfyui.default_workflow


class ImageSubConfig(BaseModel):
    """Image-specific configuration (under comfyui.image)"""
    default_workflow: Optional[str] = Field(default=None, description="Default image workflow (optional)")
    prompt_prefix: str = Field(
        default="Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style",
        description="Prompt prefix for all image generation"
    )


class VideoSubConfig(BaseModel):
    """Video-specific configuration (under comfyui.video)"""
    default_workflow: Optional[str] = Field(default=None, description="Default video workflow (optional)")
    prompt_prefix: str = Field(
        default="Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style",
        description="Prompt prefix for all video generation"
    )


class ComfyUIConfig(BaseModel):
    """ComfyUI configuration (includes global settings and service-specific configs)"""
    comfyui_url: str = Field(default="http://127.0.0.1:8188", description="ComfyUI Server URL")
    comfyui_api_key: Optional[str] = Field(default=None, description="ComfyUI API Key (optional)")
    runninghub_api_key: Optional[str] = Field(default=None, description="RunningHub 企业级-共享 API Key（兑底）。消费级 key 不可用时自动切换此 key。")
    runninghub_consumer_api_key: Optional[str] = Field(
        default=None,
        description="RunningHub 消费级会员 API Key（首选）。所有模型优先使用此 key；返回 1014 时自动切换 runninghub_api_key 作为兖底。",
    )
    runninghub_base_url: Optional[str] = Field(
        default=None,
        description="RunningHub API base URL. Use https://www.runninghub.cn for China, https://www.runninghub.ai for international (default).",
    )
    runninghub_concurrent_limit: int = Field(default=1, ge=1, le=10, description="RunningHub concurrent execution limit (1-10)")
    runninghub_instance_type: Optional[str] = Field(default=None, description="RunningHub instance type (optional, set to 'plus' for 48GB VRAM)")
    show_unavailable_workflows: bool = Field(
        default=False,
        description="Whether to show selfhost/* and runninghub-api/* workflows in UI dropdowns. Set true only if local ComfyUI is running or the standard RunningHub model APIs are enabled on your account.",
    )
    public_base_url: str = Field(
        default="",
        description="Public base URL for file access (e.g. https://yourdomain.com). Used when serving files to external APIs like RunningHub.",
    )
    tts: TTSSubConfig = Field(default_factory=TTSSubConfig, description="TTS-specific configuration")
    image: ImageSubConfig = Field(default_factory=ImageSubConfig, description="Image-specific configuration")
    video: VideoSubConfig = Field(default_factory=VideoSubConfig, description="Video-specific configuration")


class TemplateConfig(BaseModel):
    """Template configuration"""
    default_template: str = Field(
        default="1080x1920/default.html",
        description="Default frame template path"
    )


class HardwareConfig(BaseModel):
    com_port: str = Field(default="COM3", description="CH9329 serial port name")
    baudrate: int = Field(default=9600, description="CH9329 baudrate")
    unlock_pin: str = Field(default="", description="Unlock pin digits")


class LskyProConfig(BaseModel):
    url: str = Field(default="", description="Lsky Pro upload URL")
    token: str = Field(default="", description="Lsky Pro Bearer token")
    album_id: Optional[int] = Field(default=None, description="Optional album ID")


class CoordinateConfig(BaseModel):
    browser_address_bar_x: float = Field(default=0.5)
    browser_address_bar_y: float = Field(default=0.08)
    browser_image_x: float = Field(default=0.5)
    browser_image_y: float = Field(default=0.5)
    browser_save_btn_x: float = Field(default=0.5)
    browser_save_btn_y: float = Field(default=0.85)
    xhs_icon_x: float = Field(default=0.3)
    xhs_icon_y: float = Field(default=0.5)
    xhs_add_btn_x: float = Field(default=0.5)
    xhs_add_btn_y: float = Field(default=0.95)
    xhs_first_album_x: float = Field(default=0.25)
    xhs_first_album_y: float = Field(default=0.25)
    xhs_next_btn_x: float = Field(default=0.85)
    xhs_next_btn_y: float = Field(default=0.08)
    xhs_publish_btn_x: float = Field(default=0.5)
    xhs_publish_btn_y: float = Field(default=0.92)


class XHSPublishConfig(BaseModel):
    """Xiaohongshu publish automation configuration"""
    strict_mode: bool = Field(
        default=False,
        description="Strict mode setting (deprecated).",
    )
    daily_schedule_times: List[str] = Field(
        default_factory=lambda: ["09:00", "12:00", "18:00"],
        description=(
            "每日固定发布时间段（HH:MM，24小时制）。提交发布任务时若未指定时间，"
            "自动分配到下一个未占用的时间段。留空则禁用自动排期。"
        ),
    )
    push_dir: str = Field(default="/sdcard/DCIM/PixelleVideo", description="Device-side image push directory")
    hardware: HardwareConfig = Field(default_factory=HardwareConfig, description="Hardware CH9329 serial settings")
    lsky_pro: LskyProConfig = Field(default_factory=LskyProConfig, description="Lsky Pro image hosting settings")
    coordinates: CoordinateConfig = Field(default_factory=CoordinateConfig, description="Coordinates ratio configuration")


class DistributionConfig(BaseModel):
    """Distribution mode configuration for multi-device control"""
    mode: str = Field(
        default="hardware",
        description="Distribution mode: 'hardware' (direct COM control) or 'agent_pull' (remote agents poll for jobs)"
    )
    cloud_url: str = Field(
        default="",
        description="Cloud API control center URL for forwarding jobs from local web interface"
    )
    local_bind_ip: str = Field(
        default="",
        description="Local physical IP address to bind for outgoing requests to bypass Clash TUN"
    )
    agent_timeout: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Timeout in seconds for agent_pull mode (60-3600)"
    )
    agent_poll_interval: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Polling interval in seconds for checking agent job status (1-30)"
    )


class PixelleVideoConfig(BaseModel):
    """Pixelle-Video main configuration"""
    project_name: str = Field(default="Pixelle-Video", description="Project name")
    admin_password: str = Field(
        default="",
        description="管理员密码。设置后，访问「⚙️ 设置」页面需要输入此密码才能查看/修改 API Key 等敏感配置。留空则无需密码直接进入。",
    )
    llm: LLMConfig = Field(default_factory=LLMConfig)
    post_model_presets: Dict[str, LLMConfig] = Field(
        default_factory=lambda: {
            "post_content": LLMConfig(),
            "post_image": LLMConfig(),
        },
        description="Per-page post model presets persisted for web form",
    )
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    template: TemplateConfig = Field(default_factory=TemplateConfig)
    xhs_publish: XHSPublishConfig = Field(default_factory=XHSPublishConfig)
    distribution: Optional[DistributionConfig] = Field(default=None, description="Distribution mode configuration (optional)")

    def is_llm_configured(self) -> bool:
        """Check if LLM is properly configured"""
        return bool(
            self.llm.api_key and self.llm.api_key.strip() and
            self.llm.base_url and self.llm.base_url.strip() and
            self.llm.model and self.llm.model.strip()
        )
    
    def validate_required(self) -> bool:
        """Validate required configuration"""
        return self.is_llm_configured()
    
    def to_dict(self) -> dict:
        """Convert to dictionary (for backward compatibility)"""
        return self.model_dump()
