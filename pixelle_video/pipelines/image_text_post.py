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
Image-text post generation pipeline.
"""

import asyncio
import base64
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from loguru import logger

from pixelle_video.models.post import PostContent, PostFrame, PostGenerationResult
from pixelle_video.prompts import build_post_prompt
from pixelle_video.utils.os_util import create_task_output_dir


class ImageTextPostPipeline:
    """Generate image-text post from a topic."""

    def __init__(self, core):
        self.core = core

    async def __call__(
        self,
        topic: str,
        image_count: int = 6,
        style: str = "",
        template_size: str = "1080x1080",
        post_tone: str = "种草",
        hashtag_count: int = 5,
        aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        content_llm: Optional[Dict] = None,
        image_llm: Optional[Dict] = None,
        post_type: str = "content",
        ref_image: Optional[str] = None,
    ) -> PostGenerationResult:
        task_dir, task_id = create_task_output_dir()
        output_dir = Path(task_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        width, height = self._parse_size(template_size)

        content = await self.generate_post_content(
            topic=topic,
            image_count=image_count,
            post_tone=post_tone,
            hashtag_count=hashtag_count,
            style=style,
            content_llm=content_llm,
            post_type=post_type,
        )

        await self.generate_images(
            content=content,
            images_dir=images_dir,
            style=style,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            image_llm=image_llm,
            ref_image=ref_image,
        )

        post_json_path = self.save_post_json(output_dir=output_dir, content=content)
        self.render_preview(output_dir=output_dir, content=content)

        logger.info(f"Generated post task {task_id}: {post_json_path}")

        return PostGenerationResult(
            task_id=task_id,
            output_dir=output_dir,
            content=content,
            created_at=datetime.now(),
        )

    async def generate_post_content(
        self,
        topic: str,
        image_count: int,
        post_tone: str,
        hashtag_count: int,
        style: str,
        content_llm: Optional[Dict] = None,
        post_type: str = "content",
    ) -> PostContent:
        prompt = build_post_prompt(
            topic=topic,
            image_count=image_count,
            post_tone=post_tone,
            hashtag_count=hashtag_count,
            style=style,
            post_type=post_type,
        )

        llm_override: Dict = {}
        if content_llm and content_llm.get("api_key"):
            llm_override = {
                "api_key": content_llm["api_key"],
                "base_url": content_llm.get("base_url") or None,
                "model":   content_llm.get("model") or None,
            }
            logger.info(f"[PostPipeline] Using custom content LLM: base_url={llm_override['base_url']} model={llm_override['model']}")

        response = await self.core.llm(
            prompt=prompt,
            temperature=0.8,
            max_tokens=4000,
            **llm_override,
        )

        parsed = self._parse_json(response)

        title = str(parsed.get("title", "")).strip()
        body = str(parsed.get("body", "")).strip()
        hashtags = parsed.get("hashtags", []) or []
        frames = parsed.get("frames", []) or []

        if not title:
            raise ValueError("LLM response missing title")
        if not body:
            raise ValueError("LLM response missing body")
        if len(frames) < image_count:
            raise ValueError(f"LLM returned {len(frames)} frames, expected {image_count}")

        hashtags = [str(tag).strip().lstrip("#") for tag in hashtags if str(tag).strip()]
        if len(hashtags) > hashtag_count:
            hashtags = hashtags[:hashtag_count]
        if len(hashtags) < hashtag_count:
            hashtags.extend([f"主题{idx + 1}" for idx in range(hashtag_count - len(hashtags))])

        post_frames = []
        for index, frame in enumerate(frames[:image_count]):
            image_prompt = str(frame.get("image_prompt", "")).strip()
            caption = str(frame.get("caption", "")).strip()
            if not image_prompt:
                # 兜底：用 caption 或主题生成一个通用 prompt，避免因 LLM 漏字段而整体失败
                if caption:
                    image_prompt = f"An aesthetic photo illustration for: {caption}"
                else:
                    image_prompt = f"A beautiful aesthetic illustration related to {topic}, frame {index + 1}"
                logger.warning(
                    f"Frame {index + 1} missing image_prompt, using fallback: {image_prompt[:60]}..."
                )
            post_frames.append(
                PostFrame(
                    index=index,
                    image_prompt=image_prompt,
                    caption=caption,
                )
            )

        return PostContent(
            title=title,
            body=body,
            hashtags=hashtags,
            frames=post_frames,
        )

    async def generate_images(
        self,
        content: PostContent,
        images_dir: Path,
        style: str,
        width: int,
        height: int,
        aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        image_llm: Optional[Dict] = None,
        ref_image: Optional[str] = None,
    ) -> None:
        semaphore = asyncio.Semaphore(3)

        # Decide whether to use LLM image API or ComfyUI
        use_llm_image = bool(
            image_llm
            and image_llm.get("api_key")
            and image_llm.get("base_url")
            and image_llm.get("model")
        )

        if use_llm_image:
            from pixelle_video.services.llm_image_service import LLMImageService
            llm_image_svc = LLMImageService()
            openai_size = self._map_size_to_openai(width, height)
            logger.info(
                f"[PostPipeline] Using LLM image API: "
                f"model={image_llm['model']} size={openai_size}"
            )
        else:
            extra_params: Dict = {}
            if aspect_ratio:
                extra_params["aspectRatio"] = aspect_ratio
            if image_size:
                extra_params["imageSize"] = image_size
            if ref_image:
                extra_params["imageUrl"] = ref_image

        async def _generate_single(frame: PostFrame):
            async with semaphore:
                prompt = self._build_image_prompt(frame.image_prompt, style)
                output_path = images_dir / f"{frame.index + 1}.png"

                if use_llm_image:
                    image_url = await llm_image_svc.generate(
                        prompt=prompt,
                        api_key=image_llm["api_key"],
                        base_url=image_llm["base_url"],
                        model=image_llm["model"],
                        size=openai_size,
                    )
                    await self._save_image(image_url, output_path)
                else:
                    media = await self.core.media(
                        prompt=prompt,
                        media_type="image",
                        width=width,
                        height=height,
                        **extra_params,
                    )
                    await self._save_image(media.url, output_path)

                frame.image_path = output_path

        await asyncio.gather(*[_generate_single(frame) for frame in content.frames])

    def save_post_json(self, output_dir: Path, content: PostContent) -> Path:
        post_json_path = output_dir / "post.json"

        payload = {
            "title": content.title,
            "body": content.body,
            "hashtags": [f"#{tag}" for tag in content.hashtags],
            "frames": [
                {
                    "index": frame.index + 1,
                    "image_prompt": frame.image_prompt,
                    "caption": frame.caption,
                    "image_file": frame.image_path.name if frame.image_path else None,
                }
                for frame in content.frames
            ],
            "created_at": datetime.now().isoformat(),
        }

        post_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return post_json_path

    def render_preview(self, output_dir: Path, content: PostContent) -> Path:
        preview_path = output_dir / "post_preview.html"

        image_items = "\n".join(
            [
                f'<figure class="card"><img src="{self._preview_image_src(output_dir, frame)}" alt="slide-{frame.index + 1}" /><figcaption>{self._escape_html(frame.caption)}</figcaption></figure>'
                for frame in content.frames
            ]
        )
        tags = " ".join([f"#{self._escape_html(tag)}" for tag in content.hashtags])

        html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{self._escape_html(content.title)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: 'Noto Sans SC', sans-serif; background: linear-gradient(160deg, #fef4ea 0%, #f6fbff 100%); color: #2b2b2b; }}
    .wrap {{ max-width: 760px; margin: 0 auto; }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    .tags {{ color: #d9480f; font-weight: 600; margin-bottom: 16px; }}
    p {{ line-height: 1.8; background: #ffffffcc; border-radius: 12px; padding: 14px; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 14px; margin-top: 18px; }}
    .card {{ margin: 0; background: #fff; border-radius: 14px; overflow: hidden; box-shadow: 0 8px 20px rgba(0,0,0,0.08); }}
    img {{ width: 100%; display: block; }}
    figcaption {{ padding: 10px 12px; font-size: 14px; color: #444; }}
    @media (min-width: 860px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <h1>{self._escape_html(content.title)}</h1>
    <div class=\"tags\">{tags}</div>
    <p>{self._escape_html(content.body).replace(chr(10), '<br/>')}</p>
    <section class=\"grid\">{image_items}</section>
  </main>
</body>
</html>
"""

        preview_path.write_text(html, encoding="utf-8")
        return preview_path

    def _preview_image_src(self, output_dir: Path, frame: PostFrame) -> str:
        """Return an embeddable image src for Streamlit HTML preview."""
        image_path = frame.image_path or (output_dir / "images" / f"{frame.index + 1}.png")
        if not image_path.exists():
            # Fallback keeps previous behaviour for troubleshooting.
            return f"images/{frame.index + 1}.png"

        ext = image_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/png")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _map_size_to_openai(self, width: int, height: int) -> str:
        """Map pixel dimensions to the nearest OpenAI image size string."""
        if width == height:
            return "1024x1024"
        elif height > width:
            return "1024x1792"   # portrait (e.g. 1080x1920)
        else:
            return "1792x1024"   # landscape (e.g. 1920x1080)

    def _parse_size(self, template_size: str) -> Tuple[int, int]:
        if "x" not in template_size:
            return 1080, 1080

        try:
            width_str, height_str = template_size.lower().split("x", 1)
            return int(width_str), int(height_str)
        except Exception:
            return 1080, 1080

    def _build_image_prompt(self, image_prompt: str, style: str) -> str:
        if style and style.strip():
            return f"{image_prompt}, style: {style.strip()}"
        return image_prompt

    async def _save_image(self, url_or_path: str, output_path: Path) -> None:
        # Base64 data URI (e.g. from DALL-E response_format=b64_json)
        if url_or_path.startswith("data:"):
            import base64
            # Format: data:<mime>;base64,<data>
            try:
                header, b64data = url_or_path.split(",", 1)
                output_path.write_bytes(base64.b64decode(b64data))
            except Exception as exc:
                raise ValueError(f"Invalid base64 data URI: {exc}") from exc
            return

        if re.match(r"^https?://", url_or_path):
            timeout = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url_or_path)
                response.raise_for_status()
                output_path.write_bytes(response.content)
            return

        source = Path(url_or_path)
        if not source.exists():
            raise FileNotFoundError(f"Generated image not found: {url_or_path}")
        output_path.write_bytes(source.read_bytes())

    def _parse_json(self, text: str) -> Dict:
        # 1. Try direct parsing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Try extracting from markdown code block
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Try finding any JSON object by matching outermost braces
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start != -1 and brace_end > brace_start:
            try:
                json_str = text[brace_start:brace_end + 1]
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 4. Try using json_repair to fix and parse
        try:
            from json_repair import repair_json
            _block = text
            _fence = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text, re.DOTALL)
            if _fence:
                _block = _fence.group(1)
            else:
                brace_start = text.find('{')
                brace_end = text.rfind('}')
                if brace_start != -1 and brace_end > brace_start:
                    _block = text[brace_start:brace_end + 1]

            repaired = repair_json(_block, return_objects=True)
            if isinstance(repaired, dict) and repaired:
                return repaired
        except Exception as repair_exc:
            logger.debug(f"[PostPipeline] json_repair failed: {repair_exc}")

        # If all else fails, log raw response and raise error
        logger.error(f"[PostPipeline] Failed to parse JSON from LLM response. Raw response:\n{text}")
        raise ValueError("No valid JSON found in LLM response")

    def _escape_html(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
