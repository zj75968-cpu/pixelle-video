"""Content Scraper - 从各平台采集图文/视频内容，使用本机 Chrome Cookie 认证。

支持平台: 小红书, 抖音, 快手, 微博, Pinterest, Instagram
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger


# ─── Chrome Cookie 解密 ───────────────────────────────────────────────────────

def _get_chrome_local_state_path() -> Path:
    return (
        Path(os.environ["USERPROFILE"])
        / "AppData" / "Local" / "Google" / "Chrome"
        / "User Data" / "Local State"
    )


def _get_chrome_cookies_path() -> Path:
    return (
        Path(os.environ["USERPROFILE"])
        / "AppData" / "Local" / "Google" / "Chrome"
        / "User Data" / "Default" / "Network" / "Cookies"
    )


def _dpapi_decrypt(encrypted_data: bytes) -> bytes:
    """通过 Windows DPAPI（ctypes）解密数据，无需第三方依赖。"""

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(encrypted_data, len(encrypted_data))
    blob_in = DATA_BLOB(ctypes.sizeof(buf), buf)
    blob_out = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise RuntimeError("DPAPI 解密失败")
    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return result


def _get_chrome_encryption_key() -> bytes:
    """读取并解密 Chrome 的 AES 主密钥。"""
    import base64

    local_state_path = _get_chrome_local_state_path()
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)[5:]  # 去掉 'DPAPI' 前缀
    return _dpapi_decrypt(encrypted_key)


def _decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str:
    """解密单条 Chrome Cookie 值（AES-256-GCM 或旧版 DPAPI）。"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if encrypted_value[:3] in (b"v10", b"v11", b"v20"):
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:]
            return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
        else:
            return _dpapi_decrypt(encrypted_value).decode("utf-8")
    except Exception as e:
        logger.debug(f"Cookie 解密跳过: {e}")
        return ""


def get_chrome_cookies_for_domain(domain: str) -> dict[str, str]:
    """
    读取并解密指定域名的 Chrome Cookie。
    Chrome 运行时 Cookies 文件会被锁定，先复制到临时目录再读取。
    """
    cookies_path = _get_chrome_cookies_path()
    if not cookies_path.exists():
        logger.warning(f"Chrome Cookie 数据库不存在: {cookies_path}")
        return {}

    try:
        key = _get_chrome_encryption_key()
    except Exception as e:
        logger.warning(f"无法获取 Chrome 加密密钥: {e}")
        return {}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp_path = tmp.name
    shutil.copy2(str(cookies_path), tmp_path)

    cookies: dict[str, str] = {}
    try:
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",),
        )
        for row in cursor.fetchall():
            val = _decrypt_cookie_value(bytes(row["encrypted_value"]), key)
            if val:
                cookies[row["name"]] = val
        conn.close()
    except Exception as e:
        logger.error(f"读取 Chrome Cookie 失败: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    logger.debug(f"从 Chrome 读取 {domain} Cookie: {len(cookies)} 条")
    return cookies


# ─── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class ScrapedContent:
    platform: str
    source_url: str
    title: str
    text: str
    image_urls: list[str] = field(default_factory=list)
    video_url: Optional[str] = None
    local_images: list[str] = field(default_factory=list)
    local_video: Optional[str] = None
    raw_data: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def has_video(self) -> bool:
        return bool(self.video_url)

    @property
    def has_images(self) -> bool:
        return bool(self.local_images or self.image_urls)


# ─── 平台检测 ─────────────────────────────────────────────────────────────────

_PLATFORM_PATTERNS: dict[str, list[str]] = {
    "xiaohongshu": [r"xiaohongshu\.com", r"xhslink\.com", r"xhs\.link"],
    "douyin": [r"douyin\.com", r"iesdouyin\.com", r"v\.douyin\.com"],
    "kuaishou": [r"kuaishou\.com", r"gifshow\.com"],
    "weibo": [r"weibo\.com", r"weibo\.cn", r"t\.cn"],
    "pinterest": [r"pinterest\.com", r"pin\.it"],
    "instagram": [r"instagram\.com", r"instagr\.am"],
}


def detect_platform(url: str) -> Optional[str]:
    for platform, patterns in _PLATFORM_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, url, re.IGNORECASE):
                return platform
    return None


# ─── 图片下载 ─────────────────────────────────────────────────────────────────

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def download_images(
    image_urls: list[str],
    save_dir: str,
    referer: str = "",
    cookies: dict | None = None,
) -> list[str]:
    """下载图片到本地目录，返回本地路径列表。"""
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    headers = {**_DEFAULT_HEADERS}
    if referer:
        headers["Referer"] = referer

    local_paths: list[str] = []
    for i, url in enumerate(image_urls):
        try:
            raw_name = url.split("?")[0].split("/")[-1]
            ext = ".jpg"
            if "." in raw_name:
                raw_ext = raw_name.rsplit(".", 1)[-1].lower()
                if raw_ext in ("jpg", "jpeg", "png", "webp", "gif"):
                    ext = f".{raw_ext}"
            local_file = Path(save_dir) / f"img_{i + 1:03d}{ext}"
            with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
                r = client.get(url, headers=headers, cookies=cookies or {})
                r.raise_for_status()
                local_file.write_bytes(r.content)
            local_paths.append(str(local_file))
            logger.debug(f"已下载图片 {i + 1}: {local_file.name}")
        except Exception as e:
            logger.warning(f"图片下载失败 {url}: {e}")
    return local_paths


# ─── 小红书 ───────────────────────────────────────────────────────────────────

class XiaohongshuScraper:
    DOMAIN = "xiaohongshu.com"
    HEADERS = {
        **_DEFAULT_HEADERS,
        "Referer": "https://www.xiaohongshu.com/",
        "Origin": "https://www.xiaohongshu.com",
    }

    def _resolve_url(self, url: str, cookies: dict) -> str:
        """解析短链/跳转链为完整笔记 URL。"""
        if "xhslink.com" in url or "xhs.link" in url:
            try:
                with httpx.Client(trust_env=False, follow_redirects=True, timeout=15) as c:
                    r = c.get(url, headers=self.HEADERS, cookies=cookies)
                    return str(r.url)
            except Exception:
                pass
        return url

    def scrape(self, url: str, save_dir: str) -> ScrapedContent:
        cookies = get_chrome_cookies_for_domain(self.DOMAIN)
        url = self._resolve_url(url, cookies)
        content = ScrapedContent(platform="xiaohongshu", source_url=url, title="", text="")

        try:
            with httpx.Client(trust_env=False, follow_redirects=True, timeout=20) as client:
                r = client.get(url, headers=self.HEADERS, cookies=cookies)
                r.raise_for_status()
                html = r.text

            # 提取 window.__INITIAL_STATE__
            m = re.search(
                r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*(?:;?\s*</script>|;)",
                html,
                re.DOTALL,
            )
            if m:
                try:
                    state = json.loads(m.group(1))
                    note_map = state.get("note", {}).get("noteDetailMap", {})
                    if note_map:
                        first = next(iter(note_map.values()), {})
                        note = first.get("note", first)
                        content.title = note.get("title", "")
                        content.text = note.get("desc", "")
                        for img in note.get("imageList", []):
                            img_url = img.get("urlDefault") or img.get("url") or ""
                            if img_url:
                                content.image_urls.append(img_url)
                        # 视频
                        video = note.get("video", {})
                        if video:
                            streams = video.get("media", {}).get("stream", {})
                            for q in ("h264", "av1", "h265"):
                                qs = streams.get(q, [])
                                if qs:
                                    content.video_url = qs[0].get("masterUrl", "")
                                    break
                        content.raw_data = note
                except json.JSONDecodeError:
                    pass

            # OG 标签兜底
            if not content.title:
                m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
                if m:
                    content.title = m.group(1)
            if not content.image_urls:
                for m in re.finditer(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html):
                    content.image_urls.append(m.group(1))

            if content.image_urls:
                content.local_images = download_images(
                    content.image_urls, save_dir,
                    referer="https://www.xiaohongshu.com/",
                    cookies=cookies,
                )
        except Exception as e:
            content.error = str(e)
            logger.error(f"小红书采集失败 {url}: {e}")

        return content


# ─── 抖音 ─────────────────────────────────────────────────────────────────────

class DouyinScraper:
    DOMAIN = "douyin.com"
    HEADERS = {**_DEFAULT_HEADERS, "Referer": "https://www.douyin.com/"}

    def scrape(self, url: str, save_dir: str) -> ScrapedContent:
        cookies = get_chrome_cookies_for_domain(self.DOMAIN)
        content = ScrapedContent(platform="douyin", source_url=url, title="", text="")

        try:
            with httpx.Client(trust_env=False, follow_redirects=True, timeout=15) as client:
                r = client.get(url, headers=self.HEADERS, cookies=cookies)
                resolved_url = str(r.url)
                html = r.text

            # 提取视频 ID
            m = re.search(r"/video/(\d+)", resolved_url) or re.search(r"/video/(\d+)", url)
            if m:
                vid = m.group(1)
                api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={vid}"
                with httpx.Client(trust_env=False, timeout=15) as client:
                    api_r = client.get(api, headers=self.HEADERS, cookies=cookies)
                    data = api_r.json()
                items = data.get("item_list", [])
                if items:
                    item = items[0]
                    content.title = item.get("desc", "")
                    content.text = item.get("desc", "")
                    cover = item.get("video", {}).get("cover", {}).get("url_list", [])
                    if cover:
                        content.image_urls = [cover[0]]
                    play_urls = item.get("video", {}).get("play_addr", {}).get("url_list", [])
                    if play_urls:
                        content.video_url = play_urls[0]
                    content.raw_data = item

            if not content.title:
                m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
                if m:
                    content.title = m.group(1)

            if content.image_urls:
                content.local_images = download_images(
                    content.image_urls, save_dir,
                    referer="https://www.douyin.com/",
                    cookies=cookies,
                )
        except Exception as e:
            content.error = str(e)
            logger.error(f"抖音采集失败 {url}: {e}")

        return content


# ─── 微博 ─────────────────────────────────────────────────────────────────────

class WeiboScraper:
    DOMAIN = "weibo.com"
    HEADERS = {**_DEFAULT_HEADERS, "Referer": "https://weibo.com/"}

    def scrape(self, url: str, save_dir: str) -> ScrapedContent:
        cookies = get_chrome_cookies_for_domain(self.DOMAIN)
        content = ScrapedContent(platform="weibo", source_url=url, title="", text="")

        try:
            with httpx.Client(trust_env=False, follow_redirects=True, timeout=20) as client:
                r = client.get(url, headers=self.HEADERS, cookies=cookies)
                html = r.text

            m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if m:
                content.title = m.group(1)
            for m in re.finditer(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html):
                content.image_urls.append(m.group(1))
            m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
            if m:
                content.text = m.group(1)

            if content.image_urls:
                content.local_images = download_images(
                    content.image_urls, save_dir,
                    referer="https://weibo.com/",
                    cookies=cookies,
                )
        except Exception as e:
            content.error = str(e)
            logger.error(f"微博采集失败 {url}: {e}")

        return content


# ─── Pinterest ────────────────────────────────────────────────────────────────

class PinterestScraper:
    DOMAIN = "pinterest.com"
    HEADERS = {**_DEFAULT_HEADERS, "Referer": "https://www.pinterest.com/"}

    def scrape(self, url: str, save_dir: str) -> ScrapedContent:
        cookies = get_chrome_cookies_for_domain(self.DOMAIN)
        content = ScrapedContent(platform="pinterest", source_url=url, title="", text="")

        try:
            with httpx.Client(trust_env=False, follow_redirects=True, timeout=20) as client:
                r = client.get(url, headers=self.HEADERS, cookies=cookies)
                html = r.text

            # 提取 __PWS_DATA__
            m = re.search(r'<script[^>]+id="__PWS_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    pws = json.loads(m.group(1))
                    pins = (
                        pws.get("props", {})
                        .get("initialReduxState", {})
                        .get("pins", {})
                    )
                    if pins:
                        pin = next(iter(pins.values()))
                        content.title = pin.get("title") or pin.get("description", "")
                        content.text = pin.get("description", "")
                        orig = pin.get("images", {}).get("orig", {})
                        if orig.get("url"):
                            content.image_urls.append(orig["url"])
                except Exception:
                    pass

            if not content.title:
                m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
                if m:
                    content.title = m.group(1)
            if not content.image_urls:
                m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
                if m:
                    content.image_urls.append(m.group(1))

            if content.image_urls:
                content.local_images = download_images(
                    content.image_urls, save_dir,
                    referer="https://www.pinterest.com/",
                    cookies=cookies,
                )
        except Exception as e:
            content.error = str(e)
            logger.error(f"Pinterest 采集失败 {url}: {e}")

        return content


# ─── 统一入口 ─────────────────────────────────────────────────────────────────

_SCRAPERS: dict[str, type] = {
    "xiaohongshu": XiaohongshuScraper,
    "douyin": DouyinScraper,
    "kuaishou": WeiboScraper,   # 快手用相同 OG 策略，后续可单独实现
    "weibo": WeiboScraper,
    "pinterest": PinterestScraper,
    "instagram": PinterestScraper,  # Instagram 用相同 OG 策略
}

_PLATFORM_NAMES: dict[str, str] = {
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "kuaishou": "快手",
    "weibo": "微博",
    "pinterest": "Pinterest",
    "instagram": "Instagram",
}


def scrape_url(url: str, save_dir: str | None = None) -> ScrapedContent:
    """
    主入口：自动识别平台并采集内容。

    Args:
        url: 原始内容链接
        save_dir: 图片保存目录，None 则自动生成
    """
    platform = detect_platform(url)
    if not platform:
        return ScrapedContent(
            platform="unknown",
            source_url=url,
            title="",
            text="",
            error=f"无法识别平台，请检查 URL: {url}",
        )

    if save_dir is None:
        ts = int(time.time())
        save_dir = str(Path("output") / f"scrape_{platform}_{ts}")

    scraper_cls = _SCRAPERS.get(platform)
    if not scraper_cls:
        return ScrapedContent(
            platform=platform,
            source_url=url,
            title="",
            text="",
            error=f"平台 {platform} 暂未实现采集器",
        )

    return scraper_cls().scrape(url, save_dir)


def get_platform_name(platform: str) -> str:
    return _PLATFORM_NAMES.get(platform, platform)
