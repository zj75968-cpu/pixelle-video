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
API schemas for publish queue management.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PublishJobRequest(BaseModel):
    serial: Optional[str] = Field(default=None, description="Target device serial")
    serials: List[str] = Field(default_factory=list, description="Target device serial list")
    task_id: str = Field(..., description="Post generation task ID (from /api/post/generate)")
    topic: Optional[str] = Field(default=None, description="Source topic for auto-matching context")
    title: str = Field(..., description="Post title")
    body: str = Field(..., description="Post body text")
    hashtags: List[str] = Field(default_factory=list, description="Hashtag list (without #)")
    images: List[str] = Field(..., description="Absolute paths to generated images")
    scheduled_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 datetime string for scheduled publish. Null = immediate.",
    )
    delete_after_hours: Optional[float] = Field(
        default=None,
        description="Auto-delete TTL in hours (e.g. 0.01 for ~36 seconds)",
    )
    auto_comment_text: Optional[str] = Field(
        default=None,
        description="Text content for auto comment after publish",
    )


class PublishJobResponse(BaseModel):
    job_id: str
    serial: str
    task_id: str
    title: str
    status: str
    scheduled_at: Optional[str]
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    error: Optional[str]
    delete_after_hours: Optional[float] = None
    auto_comment_text: Optional[str] = None


class PublishJobListResponse(BaseModel):
    jobs: List[PublishJobResponse]
    total: int


class PublishBatchCreateResponse(BaseModel):
    created: List[PublishJobResponse]
    created_count: int
    failed: List[str] = Field(default_factory=list)
