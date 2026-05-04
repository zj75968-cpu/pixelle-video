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
Post generation API schemas.
"""

from typing import Optional

from pydantic import BaseModel, Field

from api.tasks.models import TaskStatus


class PostGenerateRequest(BaseModel):
    """Post generation request."""

    topic: str = Field(..., min_length=1, description="Post topic")
    image_count: int = Field(6, ge=3, le=9, description="Number of images")
    style: Optional[str] = Field("", description="Optional image style hint")
    template_size: str = Field("1080x1080", description="Image size, e.g. 1080x1080")
    post_tone: str = Field("种草", description="Post writing tone")
    hashtag_count: int = Field(5, ge=1, le=15, description="Hashtag count")


class PostGenerateAsyncResponse(BaseModel):
    """Async post generation response."""

    success: bool = True
    message: str = "Task created successfully"
    task_id: str = Field(..., description="Task ID for tracking")


class PostTaskResponse(BaseModel):
    """Post task status response."""

    task_id: str
    status: TaskStatus
    progress: Optional[dict] = None
    error: Optional[str] = None
    result: Optional[dict] = None
