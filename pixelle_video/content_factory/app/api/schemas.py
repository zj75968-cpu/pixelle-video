from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from content_factory.domain.topics.states import TopicTaskStatus


class TopicTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    direction: str | None = None
    target_platforms: list[str] = Field(default_factory=lambda: ["xhs"])
    content_type: str = Field(default="image_text")


class TopicBatchCreateRequest(BaseModel):
    topics: list[TopicTaskCreateRequest] = Field(min_length=1, max_length=20)


class TopicTaskTransitionRequest(BaseModel):
    target_status: TopicTaskStatus


class TopicTaskResponse(BaseModel):
    id: str
    title: str
    direction: str | None
    target_platforms: list[str]
    content_type: str
    status: TopicTaskStatus
    created_at: datetime
    updated_at: datetime


class TopicBatchCreateResponse(BaseModel):
    created: list[TopicTaskResponse]
    created_count: int
    failed: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


# --------------------------------------------------------------------- sources
class SourceItemCreateRequest(BaseModel):
    topic_task_id: str
    source_type: str = "manual"
    platform: str | None = None
    url: str | None = None
    title: str | None = None
    text: str | None = None
    comments: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    author_name: str | None = None
    publish_time: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    collect_count: int | None = None
    risk_level: str = "unknown"


class SourceItemResponse(BaseModel):
    id: str
    topic_task_id: str
    source_type: str
    platform: str | None
    url: str | None
    title: str | None
    text: str | None
    comments: list[str]
    images: list[str]
    videos: list[str]
    author_name: str | None
    publish_time: str | None
    like_count: int | None
    comment_count: int | None
    collect_count: int | None
    risk_level: str
    created_at: datetime


class SourceImportRequest(BaseModel):
    topic_task_id: str
    format: str = Field(pattern="^(csv|json)$")
    content: str
    source_type: str = "manual"
    platform: str | None = None


class SourceImportResponse(BaseModel):
    imported: list[SourceItemResponse]
    imported_count: int
    failed: list[str] = Field(default_factory=list)


class SourceCollectPublicRequest(BaseModel):
    topic_task_id: str
    url: str
    platform: str | None = None


class CookieCollectionConfigRequest(BaseModel):
    platform: str
    enabled: bool = False
    low_frequency_seconds: int = Field(default=300, ge=60)


class CookieCollectionConfigResponse(BaseModel):
    platform: str
    enabled: bool
    low_frequency_seconds: int
    warnings: list[str]


class SourceDigestResponse(BaseModel):
    id: str
    source_item_id: str
    topic_task_id: str
    title: str | None
    main_text: str | None
    visible_comments: list[str]
    image_descriptions: list[str]
    video_descriptions: list[str]
    engagement_summary: str | None
    possible_audience: str | None
    possible_intent: str | None
    notable_patterns: str | None
    copied_text_risk: str
    created_at: datetime


# -------------------------------------------------------------------- analysis
class AnalysisGenerateRequest(BaseModel):
    topic_task_id: str


class AnalysisReportResponse(BaseModel):
    id: str
    topic_task_id: str
    source_item_ids: list[str]
    title_patterns: str | None
    hook_patterns: str | None
    content_rhythm: str | None
    visual_elements: str | None
    cover_patterns: str | None
    comment_demands: str | None
    reusable_angles: str | None
    forbidden_copy_points: str | None
    originality_notes: str | None
    created_at: datetime


# ------------------------------------------------------------------ generation
class BriefGenerateRequest(BaseModel):
    topic_task_id: str
    analysis_report_id: str | None = None


class CreativeBriefResponse(BaseModel):
    id: str
    topic_task_id: str
    analysis_report_id: str | None
    target_audience: str | None
    unique_angle: str | None
    key_message: str | None
    title_candidates: list[str]
    outline: list[str]
    visual_direction: str | None
    tone: str | None
    platform_strategy: str | None
    risk_warnings: list[str]
    approved: bool
    created_at: datetime


class ContentGenerateRequest(BaseModel):
    brief_id: str
    platform: str | None = None
    content_type: str | None = None


class ComplianceCheckResponse(BaseModel):
    id: str
    generated_content_id: str
    topic_task_id: str
    originality_score: float
    copied_phrase_warnings: list[str]
    platform_risk_warnings: list[str]
    sensitive_word_warnings: list[str]
    recommended_fixes: list[str]
    passed: bool
    created_at: datetime


class GeneratedContentResponse(BaseModel):
    id: str
    topic_task_id: str
    creative_brief_id: str | None
    platform: str
    content_type: str
    title: str | None
    body: str | None
    cover_text: str | None
    hashtags: list[str]
    image_prompts: list[str]
    video_prompts: list[str]
    storyboard: list[str]
    publish_time_suggestion: str | None
    compliance_notes: str | None
    created_at: datetime
    compliance: ComplianceCheckResponse | None = None


# ---------------------------------------------------------------------- assets
class AssetGenerateRequest(BaseModel):
    generated_content_id: str


class AssetUploadRequest(BaseModel):
    generated_content_id: str
    asset_type: str = "image"
    local_path: str
    remote_url: str | None = None


class AssetItemResponse(BaseModel):
    id: str
    topic_task_id: str
    generated_content_id: str
    asset_type: str
    provider: str | None
    prompt: str | None
    local_path: str | None
    remote_url: str | None
    status: str
    checksum: str | None
    error_message: str | None
    created_at: datetime


class AssetTaskResponse(BaseModel):
    id: str
    topic_task_id: str
    generated_content_id: str
    asset_type: str
    provider: str | None
    prompt: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------- review
class ReviewOpenRequest(BaseModel):
    generated_content_id: str


class ReviewDecisionRequest(BaseModel):
    status: str
    reviewer: str | None = None
    comments: str | None = None


class ReviewRecordResponse(BaseModel):
    id: str
    topic_task_id: str
    generated_content_id: str
    reviewer: str | None
    status: str
    comments: str | None
    approved_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------- publish
class PublishPackageCreateRequest(BaseModel):
    generated_content_id: str
    platform: str = "xhs"
    publish_mode: str = "phone_ch9329_draft"
    account_id: str | None = None
    scheduled_time: str | None = None


class PublishPackageResponse(BaseModel):
    id: str
    topic_task_id: str
    generated_content_id: str
    platform: str
    account_id: str | None
    title: str | None
    body: str | None
    hashtags: list[str]
    cover_asset_id: str | None
    media_asset_ids: list[str]
    scheduled_time: str | None
    publish_mode: str
    status: str
    runtime_path: str | None = None
    created_at: datetime


class PlatformAdapterResponse(BaseModel):
    name: str
    max_title_length: int
    max_body_length: int
    max_hashtags: int
    max_media_count: int
    supported_content_types: list[str]
    supported_publish_modes: list[str]
    default_publish_mode: str
    default_upload_flow: str


# ---------------------------------------------------------------------- devices
class DeviceRegisterRequest(BaseModel):
    name: str
    platform: str = "xhs"
    account_name: str | None = None
    ch9329_port: str | None = None
    phone_ip: str | None = None
    camera_index: int | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    app_version: str | None = None
    os_version: str | None = None


class DeviceProfileResponse(BaseModel):
    id: str
    name: str
    platform: str
    account_name: str | None
    ch9329_port: str | None
    phone_ip: str | None = None
    camera_index: int | None = None
    screen_width: int | None
    screen_height: int | None
    app_version: str | None
    os_version: str | None
    coordinate_profile_id: str | None
    status: str
    created_at: datetime


class CoordinateProfileCreateRequest(BaseModel):
    flow_name: str
    platform: str = "xhs"
    device_id: str | None = None
    app_version: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    steps: list[dict] = Field(default_factory=list)


class CoordinateProfileYamlRequest(BaseModel):
    yaml_text: str
    device_id: str | None = None


class CoordinateProfileResponse(BaseModel):
    id: str
    device_id: str | None
    platform: str
    app_version: str | None
    screen_width: int | None
    screen_height: int | None
    flow_name: str
    steps: list[dict]
    yaml_path: str | None = None
    created_at: datetime


# ----------------------------------------------------------------- publish jobs
class PublishJobCreateRequest(BaseModel):
    publish_package_id: str
    device_id: str | None = None
    simulate: bool = True
    start_step: int = Field(default=0, ge=0)
    end_step: int | None = Field(default=None, ge=0)


class PublishJobResumeRequest(BaseModel):
    start_step: int | None = Field(default=None, ge=0)
    simulate: bool = True


class PublishJobLogResponse(BaseModel):
    id: str
    job_id: str
    device_id: str | None
    step_index: int
    step_name: str | None
    action_type: str | None
    status: str
    screenshot_path: str | None
    error_message: str | None


class PublishJobResponse(BaseModel):
    id: str
    publish_package_id: str
    platform: str
    account_id: str | None
    device_id: str | None
    status: str
    retry_count: int
    max_retries: int
    resume_from_step: int | None = None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    logs: list[PublishJobLogResponse] = Field(default_factory=list)


class TaskEnqueueRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)
    priority: int = 0


class PublishJobEnqueueRequest(BaseModel):
    publish_package_id: str
    device_id: str | None = None
    simulate: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    priority: int = 0
    start_step: int = Field(default=0, ge=0)
    end_step: int | None = Field(default=None, ge=0)


class TaskResponse(BaseModel):
    id: str
    task_type: str
    payload: dict
    status: str
    attempts: int
    max_attempts: int
    priority: int
    available_at: datetime
    last_error: str | None
    result_ref: str | None
    created_at: datetime
    updated_at: datetime


class ErrorRecordResponse(BaseModel):
    id: str
    topic_task_id: str | None
    related_id: str | None
    error_code: str
    error_message: str | None
    stage: str
    retryable: bool
    suggested_action: str | None
    screenshot_path: str | None
    raw_response_path: str | None
    created_at: datetime

