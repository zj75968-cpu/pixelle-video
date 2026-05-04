"""
LLM Image Generation Service

Generates images via any OpenAI-compatible images API
(OpenAI DALL-E, Together AI, etc.).

Returns the image as a publicly accessible URL or a base64 data URI.
"""

import os
from typing import Optional

import httpx
from loguru import logger

# Strip SOCKS proxy env vars so httpx never tries to use them
# (avoids "socksio not installed" errors when OS has a SOCKS proxy set).
for _pv in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy"):
    if os.environ.get(_pv, "").lower().startswith("socks"):
        os.environ.pop(_pv, None)


class LLMImageService:
    """Stateless wrapper around the OpenAI images.generate endpoint."""

    async def generate(
        self,
        prompt: str,
        api_key: str,
        base_url: str,
        model: str,
        size: str = "1024x1024",
        quality: Optional[str] = None,
        style: Optional[str] = None,
    ) -> str:
        """
        Generate an image and return its URL or base64 data URI.

        Parameters
        ----------
        prompt    : Image description prompt.
        api_key   : API key for the provider.
        base_url  : OpenAI-compatible base URL (e.g. https://api.openai.com/v1).
        model     : Model name (e.g. "dall-e-3", "black-forest-labs/FLUX.1-schnell").
        size      : Image dimensions string accepted by the provider
                    (e.g. "1024x1024", "1024x1792", "1792x1024").
        quality   : Optional quality hint ("standard" / "hd") — ignored by providers
                    that don't support it.
        style     : Optional style hint ("natural" / "vivid") — ignored by providers
                    that don't support it.

        Returns
        -------
        str
            HTTP(S) URL or ``data:image/png;base64,<...>`` data URI.
        """
        logger.info(f"[LLMImageService] model={model} size={size} prompt[:80]={prompt[:80]!r}")

        # Normalise base_url: strip trailing slash so we can append paths reliably.
        api_base = base_url.rstrip("/")

        return await self._generate_raw(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
        )

    async def _generate_raw(
        self,
        api_base: str,
        api_key: str,
        model: str,
        prompt: str,
        size: str,
        quality: Optional[str],
        style: Optional[str],
    ) -> str:
        """
        Call the images-generation endpoint directly via httpx and handle any
        response format the provider returns.

        Supports:
        - Standard OpenAI ImagesResponse  ``{"data": [{"url": "...", "b64_json": "..."}]}``
        - Plain-string URL / data-URI     ``"https://..."``
        - Top-level url key               ``{"url": "..."}``
        - Top-level b64_json key          ``{"b64_json": "..."}``
        - Nested under data as string     ``{"data": "https://..."}``
        - Chat-completions style fallback ``{"choices": [{"message": {"content": "..."}}]}``
        """
        # Build request body
        body: dict = {"model": model, "prompt": prompt, "size": size, "n": 1}
        if quality:
            body["quality"] = quality
        if style:
            body["style"] = style

        # Determine the URL to post to.
        # Some providers use /v1/ prefix, others expose endpoints at the root.
        # We try /v1/images/generations first; if the base already ends with /v1
        # we don't double-add it.
        if api_base.endswith("/v1"):
            url = f"{api_base}/images/generations"
        else:
            url = f"{api_base}/v1/images/generations"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(proxy=None, follow_redirects=True, timeout=120) as http:
            resp = await http.post(url, json=body, headers=headers)

        logger.debug(f"[LLMImageService] raw response status={resp.status_code} url={resp.url}")

        try:
            data = resp.json()
        except Exception:
            # Non-JSON body — treat as raw text URL / data-URI
            text = resp.text.strip().strip('"')
            if text.startswith("http") or text.startswith("data:"):
                return text
            raise ValueError(
                f"[LLMImageService] non-JSON response (status {resp.status_code}): "
                f"{resp.text[:300]!r}"
            )

        logger.debug(f"[LLMImageService] response JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")

        return self._extract_image(data, model)

    def _extract_image(self, data: object, model: str) -> str:
        """
        Walk any response shape and return the first image URL or base64 data-URI.
        """
        # Plain JSON string (some providers return just the URL)
        if isinstance(data, str):
            if data.startswith("http") or data.startswith("data:"):
                return data
            raise ValueError(f"[LLMImageService] unexpected string response: {data[:200]!r}")

        if not isinstance(data, dict):
            raise ValueError(f"[LLMImageService] unexpected response type {type(data)}: {str(data)[:200]}")

        # Standard OpenAI: {"data": [{"url": ..., "b64_json": ...}]}
        items = data.get("data")
        if isinstance(items, list) and items:
            item = items[0]
            if isinstance(item, dict):
                if item.get("url"):
                    logger.debug(f"[LLMImageService] extracted URL from data[0].url")
                    return item["url"]
                if item.get("b64_json"):
                    logger.debug(f"[LLMImageService] extracted base64 from data[0].b64_json")
                    return f"data:image/png;base64,{item['b64_json']}"

        # data is a string (non-standard)
        if isinstance(items, str):
            if items.startswith("http") or items.startswith("data:"):
                return items

        # Top-level url / b64_json
        if data.get("url"):
            logger.debug(f"[LLMImageService] extracted top-level url")
            return data["url"]
        if data.get("b64_json"):
            logger.debug(f"[LLMImageService] extracted top-level b64_json")
            return f"data:image/png;base64,{data['b64_json']}"

        # Chat-completions style (Gemini via some proxies)
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            # content may be a URL or base64 data-URI
            if isinstance(content, str) and (content.startswith("http") or content.startswith("data:")):
                logger.debug(f"[LLMImageService] extracted image from choices[0].message.content")
                return content
            # content may be a list of parts (Gemini native format)
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        if url:
                            return url
                    if isinstance(part, dict) and part.get("inline_data"):
                        inline = part["inline_data"]
                        b64 = inline.get("data", "")
                        mime = inline.get("mime_type", "image/png")
                        if b64:
                            return f"data:{mime};base64,{b64}"

        raise ValueError(
            f"[LLMImageService] cannot extract image from response for model={model}. "
            f"Keys: {list(data.keys())}"
        )
