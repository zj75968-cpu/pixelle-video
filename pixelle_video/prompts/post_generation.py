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
Post generation prompt templates.
"""

POST_GENERATION_SYSTEM_PROMPT = """你是小红书图文创作助手。
请基于用户主题，生成结构化图文内容，要求自然、有真实分享感。
输出必须是合法 JSON，且只输出 JSON，不要额外解释。
"""


POST_GENERATION_PROMPT_TEMPLATE = """{system_prompt}

请为以下主题生成小红书图文帖子：
主题：{topic}
图片数量：{image_count}
文案语气：{post_tone}
话题标签数量：{hashtag_count}
视觉风格偏好：{style_hint}

输出 JSON 格式（严格遵守字段名）：
{{
  "title": "20字以内中文标题",
  "body": "150-500字中文正文",
  "hashtags": ["标签1", "标签2"],
  "frames": [
    {{
      "image_prompt": "English image prompt for model",
      "caption": "该图对应的中文短说明"
    }}
  ]
}}

约束：
1. frames 数组长度必须等于 {image_count}
2. hashtags 数组长度必须等于 {hashtag_count}
3. image_prompt 必须为英文，适合 AI 生图
4. caption 必须为中文，简洁自然
5. 不要输出 Markdown 代码块
"""


def build_post_prompt(
    topic: str,
    image_count: int,
    post_tone: str,
    hashtag_count: int,
    style: str = ""
) -> str:
    """Build prompt for image-text post generation."""

    style_hint = style.strip() if style else "无特殊要求"

    return POST_GENERATION_PROMPT_TEMPLATE.format(
        system_prompt=POST_GENERATION_SYSTEM_PROMPT,
        topic=topic.strip(),
        image_count=image_count,
        post_tone=post_tone.strip(),
        hashtag_count=hashtag_count,
        style_hint=style_hint,
    )
