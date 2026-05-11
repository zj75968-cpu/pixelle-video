"""
RunningHub API Pydantic schemas
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


class RunningHubI2VRequest(BaseModel):
    """Request body for POST /api/runninghub/image-to-video"""

    prompt: str = Field(
        ...,
        description="Motion / scene description for the generated video",
        examples=["少女缓缓在废墟中转身，液态金属皮肤随动作流动，丝绸长裙在风中摆动"],
    )
    image_urls: List[str] = Field(
        ...,
        min_length=1,
        max_length=7,
        alias="imageUrls",
        description="Reference image URLs (1-7 items)",
        examples=[["https://example.com/image.jpg"]],
    )
    aspect_ratio: Literal["2:3", "3:2", "9:16", "16:9", "1:1", "4:3", "3:4"] = Field(
        "2:3",
        alias="aspectRatio",
        description="Output video aspect ratio",
    )
    duration: int = Field(
        6,
        ge=1,
        le=30,
        description="Video duration in seconds",
    )
    resolution: Literal["480p", "720p", "1080p"] = Field(
        "480p",
        description="Output resolution",
    )

    model_config = {"populate_by_name": True}


class RunningHubT2VRequest(BaseModel):
    """Request body for POST /api/runninghub/text-to-video"""

    prompt: str = Field(
        ...,
        description="Scene description for the generated video",
        examples=["春日午后，樱花纷飞的乡间小路，一位少女骑着自行车经过稻田"],
    )
    aspect_ratio: Literal["9:16", "16:9", "1:1", "2:3", "3:2"] = Field(
        "9:16",
        alias="aspectRatio",
        description="Output video aspect ratio",
    )
    duration: int = Field(
        8,
        ge=4,
        le=15,
        description="Video duration in seconds (4-15)",
    )
    resolution: Literal["720p", "1080p"] = Field(
        "720p",
        description="Output resolution",
    )

    model_config = {"populate_by_name": True}


class RunningHubVideoResponse(BaseModel):
    """Response returned by both video endpoints."""

    success: bool = Field(..., description="Whether the request succeeded")
    message: str = Field(..., description="Human-readable status message")
    data: Optional[Dict[str, Any]] = Field(
        None, description="Raw response data from RunningHub"
    )
