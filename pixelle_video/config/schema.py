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
from typing import Dict, List, Optional
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


class PhoneAgentConfig(BaseModel):
    """HTTP Agent configuration for phone control without USB ADB."""
    url: str = Field(
        default="",
        description="手机 Agent 的访问地址（cloudflared 隧道 URL），如 https://xxx.trycloudflare.com",
    )
    token: str = Field(
        default="",
        description="认证 Token，与手机端 phone_agent.py --token 保持一致",
    )
    chunk_size_mb: int = Field(
        default=5,
        description="文件分块大小（MB），默认 5MB",
    )
    timeout_push: int = Field(
        default=120,
        description="单文件推送超时秒数",
    )


class XHSPublishConfig(BaseModel):
    """Xiaohongshu publish automation configuration"""
    strict_mode: bool = Field(
        default=True,
        description=(
            "Strict mode: raise an error when a UI element cannot be found instead of "
            "falling back to coordinate taps. Set to false to enable compatible/fallback mode."
        ),
    )
    push_dir: str = Field(
        default="/sdcard/DCIM/PixelleVideo",
        description="Device-side directory where images are pushed before publishing",
    )
    lock_pin: str = Field(
        default="",
        description="Device unlock PIN (digits only). If set, auto-unlocks the screen before publishing.",
    )
    daily_schedule_times: List[str] = Field(
        default_factory=lambda: ["09:00", "12:00", "18:00"],
        description=(
            "每日固定发布时间段（HH:MM，24小时制）。提交发布任务时若未指定时间，"
            "自动分配到下一个未占用的时间段。留空则禁用自动排期。"
        ),
    )
    adb_server_host: str = Field(
        default="127.0.0.1",
        description=(
            "ADB Server 地址。默认 127.0.0.1（本机）。"
            "若手机连在同网内其他主机上，填写那台主机的 IP（如 192.168.1.5），"
            "并在那台主机运行 adb -a nodaemon server。"
        ),
    )
    adb_server_port: int = Field(
        default=5037,
        description="ADB Server 端口，默认 5037。",
    )


class RemotePathsConfig(BaseModel):
    """Remote directory paths on target phone"""
    job_dir: str = Field(default="/sdcard/Tasker/jobs", description="Directory for job definition and trigger files")
    image_dir: str = Field(default="/sdcard/Pictures/TaskerUpload", description="Directory for uploading image assets")
    video_dir: str = Field(default="/sdcard/Movies/TaskerUpload", description="Directory for uploading video assets")
    screenshot_dir: str = Field(default="/sdcard/Tasker/jobs/screenshots", description="Directory for screenshots")


class DistributionConfig(BaseModel):
    """Android Tasker SSH distribution configuration"""
    mode: str = Field(default="legacy", description="Distribution mode: 'legacy' or 'mobile_tasker_ssh'")
    result_wait_seconds: int = Field(default=60, description="Timeout waiting for job completion")
    result_poll_interval_seconds: int = Field(default=5, description="Polling interval for result file")
    max_retry: int = Field(default=2, description="Maximum number of retries")
    batch_size: int = Field(default=3, description="Task batch size")
    send_interval_seconds: int = Field(default=2, description="Interval between sending files")
    mobile_devices_config: str = Field(default="config/devices.yaml", description="Path to devices config file")
    remote_paths: RemotePathsConfig = Field(default_factory=RemotePathsConfig, description="Paths on target device")


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
    phone_agent: PhoneAgentConfig = Field(default_factory=PhoneAgentConfig)
    distribution_mode: Optional[str] = Field(default=None, description="Global distribution mode override")
    distribution: DistributionConfig = Field(default_factory=DistributionConfig)

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

