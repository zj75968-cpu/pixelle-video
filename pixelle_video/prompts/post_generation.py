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


# Post-type strategy blocks (injected into prompt)
POST_TYPE_STRATEGY_CONTENT = """【帖子定位：📚 干货帖（content）】
策略要求：
- 以「提供真实价值」为核心，输出可直接执行的知识 / 技巧 / 清单 / 避坑指南。
- 标题倾向于「N 个方法 / N 个技巧 / 一文讲透 / 新手必看」等价值承诺型句式，避免标题党。
- 正文采用结构化分点（1./2./3. 或 ✅/❌），每点先结论后理由，确保读完有收获。
- 不主动出现强引导话术（如「评论扣 1」「私信我」「主页有完整版」）。
- 语气专业、可信、克制；可适度埋伏笔，但落点必须落在「干货」本身。
"""

POST_TYPE_STRATEGY_TRAFFIC = """【帖子定位：📢 引流帖（traffic）】
策略要求：
- 以「制造钩子 + 引导互动」为核心，目的是吸引点击、评论、关注、私信。
- 标题强调情绪 / 悬念 / 反差 / 数字冲击（例：「30 天瘦 10 斤的秘密」「99% 的人都做错了」）。
- 正文前 2 句必须制造好奇或情感共鸣，引导用户「想看下文」；中段可点到为止，关键信息适度留白。
- 正文末尾必须加入一个明确的 CTA：评论关键词、私信领取、点赞收藏、关注主页 等之一。
- 语气更口语化、亲和、带情绪；允许夸张但不虚假。
"""


POST_GENERATION_PROMPT_TEMPLATE = """{system_prompt}

{post_type_strategy}
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
6. 标题与正文必须严格遵循上方「帖子定位」策略要求
"""


def build_post_prompt(
    topic: str,
    image_count: int,
    post_tone: str,
    hashtag_count: int,
    style: str = "",
    post_type: str = "content",
) -> str:
    """Build prompt for image-text post generation.

    Args:
        post_type: "content" (📚 干货帖) or "traffic" (📢 引流帖). Determines
            the strategy block injected into the prompt. Defaults to "content".
    """

    style_hint = style.strip() if style else "无特殊要求"

    if post_type == "traffic":
        post_type_strategy = POST_TYPE_STRATEGY_TRAFFIC
    else:
        post_type_strategy = POST_TYPE_STRATEGY_CONTENT

    return POST_GENERATION_PROMPT_TEMPLATE.format(
        system_prompt=POST_GENERATION_SYSTEM_PROMPT,
        post_type_strategy=post_type_strategy,
        topic=topic.strip(),
        image_count=image_count,
        post_tone=post_tone.strip(),
        hashtag_count=hashtag_count,
        style_hint=style_hint,
    )
