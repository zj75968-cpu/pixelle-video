"""Smart Scraper - 主题驱动的 AI 内容工厂

流程：
    1. deepsearch(topic)         — Gemini 联网搜索，返回参考素材
    2. reverse_prompt(image)     — Gemini 多模态反推 prompt
    3. regenerate_image(prompt)  — Gemini 图像模型重画
    4. generate_copy(topic, refs)— Gemini 生成标题+正文

所有接口走 chatfire.cn 现有配置（config.yaml: post_model_presets）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


# ─── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class ReferenceItem:
    """搜索返回的单条参考素材。"""
    title: str
    text: str
    source_url: str
    image_urls: list[str] = field(default_factory=list)
    local_images: list[str] = field(default_factory=list)


@dataclass
class GeneratedFrame:
    """重画后的单张图（含原图 + 反推 prompt + 新图）。"""
    ref_image: str          # 参考图本地路径
    image_prompt: str       # 反推得到的 prompt（合成后 full）
    generated_image: str = ""  # 重画后的本地图路径
    error: Optional[str] = None
    prompt_parts: dict = field(default_factory=dict)  # {subject, style, lighting, palette, composition, mood}


@dataclass
class SmartScrapeResult:
    """主题驱动 AI 内容工厂的完整产物。"""
    topic: str
    output_dir: str
    references: list[ReferenceItem] = field(default_factory=list)
    frames: list[GeneratedFrame] = field(default_factory=list)
    title: str = ""
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def final_images(self) -> list[str]:
        """优先返回重画图，没有则降级用参考图。"""
        regen = [f.generated_image for f in self.frames if f.generated_image]
        if regen:
            return regen
        return [img for ref in self.references for img in ref.local_images]


# ─── 配置加载 ─────────────────────────────────────────────────────────────────

def _load_text_llm() -> dict:
    """文本/搜索 LLM 配置（post_content preset，默认走联网模型）。"""
    from pixelle_video.config.manager import ConfigManager
    cm = ConfigManager()
    preset = cm.get_post_model_preset("post_content")
    if not (preset.get("api_key") and preset.get("base_url")):
        # fallback 到主 LLM
        preset = cm.get_llm_config()
    return preset


def _load_image_llm() -> dict:
    """图像生成 LLM 配置（post_image preset）。"""
    from pixelle_video.config.manager import ConfigManager
    cm = ConfigManager()
    preset = cm.get_post_model_preset("post_image")
    return preset


def _load_search_llm() -> dict:
    """联网搜索 LLM 配置：
    - 优先用 post_search preset（如果用户单独配了）
    - 否则用 post_content 如果是 chatfire 域 → 自动切到 gemini-3-flash-deepsearch
    - 否则借用 post_image / post_vision 的 chatfire 凭证 + gemini-3-flash-deepsearch
    （deepseek、openai 等非联网模型会编造图片 URL，必须强制走 chatfire 联网模型）"""
    from pixelle_video.config.manager import ConfigManager
    cm = ConfigManager()
    # 1) post_search
    preset = cm.get_post_model_preset("post_search")
    if preset.get("api_key") and preset.get("base_url") and preset.get("model"):
        return dict(preset)
    # 2) post_content 如果是 chatfire
    content = cm.get_post_model_preset("post_content")
    if content.get("api_key") and "chatfire" in (content.get("base_url") or "").lower():
        return {**content, "model": "gemini-3-flash-deepsearch"}
    # 3) 借 chatfire 凭证（post_image / post_vision）
    for name in ("post_vision", "post_image"):
        cf = cm.get_post_model_preset(name)
        if cf.get("api_key") and "chatfire" in (cf.get("base_url") or "").lower():
            return {**cf, "model": "gemini-3-flash-deepsearch"}
    # 4) 实在没有 → 返回 post_content 原样（调用方会因没联网拿到假 URL，需检测）
    return dict(content) if content else {}


def _load_vision_llm() -> dict:
    """多模态反推 LLM 配置：优先 post_vision，缺省回退 post_image。
    注意：post_image 的模型如果是纯图像生成模型（如 *-image-preview），
    会无法做 reverse-prompt（safety 拒绝）。建议配 post_vision 指向支持
    vision 的 chat 模型，如 gpt-4o-mini / gemini-2.0-flash 等。"""
    from pixelle_video.config.manager import ConfigManager
    cm = ConfigManager()
    preset = cm.get_post_model_preset("post_vision")
    if preset.get("api_key") and preset.get("base_url") and preset.get("model"):
        return preset
    # fallback: 用 post_image（可能失败）
    return cm.get_post_model_preset("post_image")


# ─── HTTP 工具 ────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=120.0)


async def _post_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    temperature: float = 0.7,
    extra_body: Optional[dict] = None,
    timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
) -> dict:
    """统一的 chat/completions 调用。"""
    api_base = base_url.rstrip("/")
    url = (
        f"{api_base}/chat/completions"
        if api_base.endswith("/v1")
        else f"{api_base}/v1/chat/completions"
    )
    body = {"model": model, "messages": messages, "temperature": temperature}
    if extra_body:
        body.update(extra_body)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=timeout) as c:
        r = await c.post(url, json=body, headers=headers)
        return r.json()


def _extract_text(data: dict) -> str:
    """从 chat/completions 响应里提取文本内容。"""
    try:
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            # gemini 风格的 parts
            parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            return "\n".join([p for p in parts if p])
        return content or ""
    except Exception as e:
        logger.warning(f"_extract_text 解析失败: {e}")
        return ""


def _parse_json_block(text: str) -> Optional[dict | list]:
    """从模型输出里抓取 JSON 块（兼容 ```json 围栏 / 裸 JSON，并使用 json_repair 兜底）。"""
    if not text:
        return None

    # 1. 优先尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. 尝试从 markdown 代码块提取
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 3. 尝试匹配最外层括号/大括号
    for opener, closer in (("{", "}"), ("[", "]")):
        i = text.find(opener)
        j = text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                pass

    # 4. 尝试使用 json_repair 修复和解析
    try:
        from json_repair import repair_json
        _block = text
        _fence = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text, re.DOTALL)
        if _fence:
            _block = _fence.group(1)
        else:
            for opener, closer in (("{", "}"), ("[", "]")):
                i = text.find(opener)
                j = text.rfind(closer)
                if i != -1 and j > i:
                    _block = text[i:j + 1]
                    break
        repaired = repair_json(_block, return_objects=True)
        if isinstance(repaired, (dict, list)) and repaired:
            return repaired
    except Exception:
        pass

    return None


# ─── 图片下载 ─────────────────────────────────────────────────────────────────

async def _download_image(url: str, save_path: Path) -> bool:
    """异步下载单张图片。"""
    try:
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=True, timeout=60
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
            save_path.write_bytes(r.content)
            return True
    except Exception as e:
        logger.warning(f"图片下载失败 {url}: {e}")
        return False


async def _save_generated(url_or_data: str, save_path: Path) -> bool:
    """保存生图返回的 URL 或 data: URI。"""
    try:
        if url_or_data.startswith("data:"):
            _, b64 = url_or_data.split(",", 1)
            save_path.write_bytes(base64.b64decode(b64))
            return True
        if url_or_data.startswith("http"):
            return await _download_image(url_or_data, save_path)
        # 本地路径
        p = Path(url_or_data)
        if p.exists():
            save_path.write_bytes(p.read_bytes())
            return True
    except Exception as e:
        logger.error(f"保存生成图失败: {e}")
    return False


# ─── Step 1: Deepsearch 搜索素材 ───────────────────────────────────────────────

_SEARCH_PROMPT = """你是「小红书内容研究员」。请围绕主题「{topic}」给出 {n_refs} 条优质参考素材的**元数据**。
图片我自己会用真实图片搜索引擎去抓，你**不要编造图片 URL**。

每条素材请输出：
- title: 中文标题（≤20字，吸睛、可直接做小红书封面）
- text:  80~200字的中文正文摘要（小红书风格、口语化、可带 emoji）
- query_zh: **中文**搜索词（4~8 个词，名词为主，用于小红书/B站/微博/微信公众号等中文平台）
- query_en: **英文**搜索词（4~10 个词，名词为主，用于 Pinterest/Behance/ArtStation 等国外平台）

两个 query 必须**紧扣主题**，不要扩散到无关概念。

严格用以下 JSON 数组格式返回，不要多余解释，不要 markdown 包裹：

```json
[
  {{
    "title": "...",
    "text":  "...",
    "query_zh": "...",
    "query_en": "..."
  }}
]
```
"""

_SEARCH_PROMPT_TUTORIAL = """你是「绘画教程内容研究员」。请围绕主题「{topic}」给出 {n_refs} 条**绘画教程**参考素材的元数据。
我会用真实图片搜索引擎去抓步骤图，你**不要编造图片 URL**。

内容定位：教程向、步骤拆解、技法讲解类（类似 B 站/小红书上的「XX 画法步骤」「如何画 XX」帖子）。

每条素材请输出：
- title: 中文标题（≤20字，要有"画法""教程""步骤"等教程感关键词）
- text:  80~200字的教程摘要（说清楚这个教程讲什么技法/步骤，可带 emoji，小红书口语风）
- query_zh: **中文**搜索词（必须含「画法 / 教程 / 步骤 / 怎么画」等关键词，紧扣主题，4~8 个词）
- query_en: **英文**搜索词（必须含 "tutorial" 或 "step by step" 或 "how to draw"，紧扣主题，4~10 个词）

两个 query 都必须**紧扣主题**，不要扩散到无关概念。

严格用以下 JSON 数组格式返回，不要多余解释，不要 markdown 包裹：

```json
[
  {{
    "title": "...",
    "text":  "...",
    "query_zh": "...",
    "query_en": "..."
  }}
]
```
"""

_SEARCH_PROMPT_REF = """你是「视觉素材研究员」。请围绕主题「{topic}」给出 {n_refs} 条**参考素材**的元数据。
图片我自己会用真实图片搜索引擎去抓，你**不要编造图片 URL**。

内容定位：宽泛的灵感素材、参考图，不限风格。

每条素材请输出：
- title: 中文标题（≤20字）
- text:  80~200字的素材描述（说明图片内容/风格/用途，口语化）
- query_zh: **中文**搜索词（4~8 个词，名词为主，用于中文平台）
- query_en: **英文**搜索词（4~10 个词，名词为主，用于国外平台）

两个 query 都必须**紧扣主题**，不要扩散到无关概念。

严格用以下 JSON 数组格式返回，不要多余解释，不要 markdown 包裹：

```json
[
  {{
    "title": "...",
    "text":  "...",
    "query_zh": "...",
    "query_en": "..."
  }}
]
```
"""


def _search_images_real(query: str, max_results: int = 4) -> list[str]:
    """用 ddgs(bing 后端) 真实搜索图片，返回图片直链列表。
    chatfire 上的 deepsearch / 各种 *-online 模型在当前账号默认分组下都没有可用渠道；
    而 DeepSeek/OpenAI 这类纯文本 LLM 不联网，会胡编 xhscdn UUID 链接（全部 404）。
    所以这里直接走真实搜索引擎抓图，规避所有 LLM 联网不靠谱的问题。"""
    try:
        from ddgs import DDGS
    except Exception as e:
        logger.error(f"[deepsearch] 缺少 ddgs 包：{e}，请 pip install ddgs")
        return []
    # 后端优先级：bing 在国内环境对中文/英文 query 都最稳；其余作为兜底
    backends = ["bing", "yahoo", "startpage", "google"]
    for backend in backends:
        try:
            with DDGS() as d:
                items = list(d.images(query, max_results=max_results, backend=backend))
                urls = [
                    it.get("image") or it.get("url") or ""
                    for it in items
                    if isinstance(it, dict)
                ]
                urls = [u for u in urls if u and u.startswith("http")]
                if urls:
                    logger.debug(f"[deepsearch] backend={backend} query={query!r} -> {len(urls)} urls")
                    return urls
        except Exception as e:
            logger.warning(f"[deepsearch] backend={backend} 失败：{type(e).__name__}: {str(e)[:80]}")
            continue
    return []


# 多平台 site: 过滤表 —— 通过 ddgs 图片搜索 + site: 限定域名抓不同平台
_SOURCE_SITE_FILTERS: dict[str, str] = {
    "小红书": "site:xiaohongshu.com OR site:xhscdn.com",
    "Twitter/X": "site:twitter.com OR site:x.com OR site:pbs.twimg.com",
    "Reddit": "site:reddit.com OR site:redd.it",
    "微博": "site:weibo.com OR site:weibo.cn OR site:sinaimg.cn",
    "B站": "site:bilibili.com OR site:hdslb.com",
    "Pixiv": "site:pixiv.net OR site:pximg.net",
    "Pinterest": "site:pinterest.com OR site:pinimg.com",
    "Behance": "site:behance.net",
    "ArtStation": "site:artstation.com",
    "DeviantArt": "site:deviantart.com OR site:wixmp.com",
    "站酷": "site:zcool.com.cn",
    "百度贴吧": "site:tieba.baidu.com OR site:hiphotos.baidu.com",
    "知乎": "site:zhihu.com OR site:zhimg.com",
    "微信公众号": "site:mp.weixin.qq.com OR site:mmbiz.qpic.cn",
    "花瓣": "site:huaban.com OR site:hbimg.huabanimg.com",
    "B站文章": "site:bilibili.com/read OR site:bilibili.com/opus",
    "抖音": "site:douyin.com OR site:amemv.com OR site:iesdouyin.com",
    "通用图片": "",  # 不加 site: 限定，全网搜
}

# 中文为主的平台 → 应当用中文 query 搜索
_CN_SOURCES: set[str] = {
    "小红书", "微博", "B站", "B站文章", "站酷", "百度贴吧", "知乎",
    "微信公众号", "花瓣", "抖音",
}


def _search_images_by_source(query: str, source: str, max_results: int = 4) -> list[str]:
    """按指定平台关键词过滤搜索图片。"""
    site_filter = _SOURCE_SITE_FILTERS.get(source, "")
    composed = f"{query} {site_filter}".strip() if site_filter else query
    return _search_images_real(composed, max_results=max_results)


def _search_images_multi_sources(
    query_zh: str,
    query_en: str,
    sources: list[str],
    per_source: int = 3,
    has_foreign: bool = False,
) -> list[str]:
    """对多个平台并行搜图，按平台顺序合并去重。

    - 中文平台（小红书/微博/B站/站酷/...）使用 query_zh
    - 国外平台（Pinterest/Behance/...）使用 query_en
    - "通用图片"：若不含国外平台则仅用中文搜索，否则使用中英文合并取并集
    """
    if not sources:
        sources = ["通用图片"]
    all_urls: list[str] = []
    seen: set[str] = set()

    def _pick_query(src: str) -> list[str]:
        if src == "通用图片":
            if not has_foreign:
                return [query_zh] if query_zh else [query_en]
            qs = [q for q in (query_zh, query_en) if q]
            return qs or [query_zh or query_en]
        if src in _CN_SOURCES:
            return [query_zh] if query_zh else [query_en]
        return [query_en] if query_en else [query_zh]

    for src in sources:
        for q in _pick_query(src):
            try:
                urls = _search_images_by_source(q, src, max_results=per_source)
            except Exception as e:
                logger.warning(f"[deepsearch] source={src} 搜图失败：{e}")
                urls = []
            for u in urls:
                if u and u not in seen:
                    seen.add(u)
                    all_urls.append(u)
    return all_urls


# ─── Agent-Reach 集成：xhs / Exa ──────────────────────────────────────────────

@lru_cache(maxsize=16)
def _have_cli(name: str) -> bool:
    """检查命令行工具是否在 PATH 中可用（结果缓存）。"""
    return shutil.which(name) is not None


def _run_cli(cmd: list[str], timeout: float = 30.0, override_username: str = None) -> tuple[int, str]:
    """运行 CLI，返回 (returncode, stdout_text)。失败时 stdout 为合并后的输出。
    Windows 上 npm-installed 工具（如 mcporter）通常是 .cmd/.ps1 包装器，
    subprocess 直接传 'mcporter' 会 WinError 2，必须用 shutil.which 解析完整路径。"""
    try:
        resolved = shutil.which(cmd[0])
        if not resolved:
            return 127, ""
        
        from pixelle_video.utils.user_context import get_current_username
        username = override_username or get_current_username() or "default"
        
        proj_root = Path(__file__).resolve().parent.parent.parent
        user_home = proj_root / "data" / "users" / username
        user_home.mkdir(parents=True, exist_ok=True)
        
        xhs_config_dir = user_home / ".xiaohongshu-cli"
        active_account_file = xhs_config_dir / "active_account.txt"
        
        # 1. 如果是 xhs 命令且存在激活账号配置，执行前把对应的 cookies_*.json 覆盖到 cookies.json
        if cmd[0] == "xhs" and active_account_file.exists() and xhs_config_dir.exists():
            try:
                active_acc = active_account_file.read_text(encoding="utf-8").strip()
                if active_acc:
                    acc_cookie = xhs_config_dir / f"cookies_{active_acc}.json"
                    if acc_cookie.exists():
                        shutil.copy(acc_cookie, xhs_config_dir / "cookies.json")
            except Exception as e:
                logger.warning(f"Failed to copy active cookie before running xhs command: {e}")
        
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["HOME"] = str(user_home)
        env["USERPROFILE"] = str(user_home)
        
        r = subprocess.run(
            [resolved, *cmd[1:]],
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=str(user_home),
        )
        out = (r.stdout or b"").decode("utf-8", errors="replace")
        err = (r.stderr or b"").decode("utf-8", errors="replace")
        
        # 2. 如果是 xhs 命令且执行完后，主 cookies.json 存在，同步回写至对应的 active 账号文件
        if cmd[0] == "xhs" and active_account_file.exists() and xhs_config_dir.exists():
            try:
                active_acc = active_account_file.read_text(encoding="utf-8").strip()
                if active_acc:
                    main_cookie = xhs_config_dir / "cookies.json"
                    acc_cookie = xhs_config_dir / f"cookies_{active_acc}.json"
                    if main_cookie.exists():
                        shutil.copy(main_cookie, acc_cookie)
            except Exception as e:
                logger.warning(f"Failed to copy cookie back to active account: {e}")
                
        return r.returncode, (out + err) if r.returncode != 0 else out
    except subprocess.TimeoutExpired:
        return 124, ""
    except Exception as e:
        logger.warning(f"[agent-reach] {cmd[0]} 调用异常：{type(e).__name__}: {e}")
        return 1, ""


def _search_via_xhs(query: str, n: int = 4) -> list[dict]:
    """通过 Agent-Reach 的 xhs-cli 搜索小红书笔记。
    未安装 / 未登录 / 任何异常都安静返回 []。
    返回 [{title, text, source_url, image_urls}, ...]
    """
    if not _have_cli("xhs"):
        return []
    rc, out = _run_cli(["xhs", "search", query, "--json", "--type", "image"], timeout=30.0)
    if rc != 0 or not out.strip():
        # 常见原因：未登录（{ok:false, error.code: not_authenticated}）
        return []
    try:
        data = json.loads(out)
    except Exception:
        return []
    if not isinstance(data, dict) or not data.get("ok", True):
        return []
    # xhs-cli v0.6.x 输出结构：{ok, data: {items: [...]}} 或 {ok, items: [...]}
    items = data.get("data", {}).get("items") if isinstance(data.get("data"), dict) else None
    if not items:
        items = data.get("items") or data.get("notes") or []
    results: list[dict] = []
    for it in items[:n]:
        if not isinstance(it, dict):
            continue
        card = it.get("note_card") if isinstance(it.get("note_card"), dict) else None
        src = card or it
        # 兼容多种字段命名
        title = (src.get("title") or src.get("display_title") or "").strip()
        text = (src.get("desc") or src.get("description") or src.get("content") or "").strip()
        url = src.get("url") or src.get("share_url") or src.get("note_url") or ""
        if not url:
            note_id = it.get("id") or src.get("note_id") or src.get("id")
            xsec_token = it.get("xsec_token") or src.get("xsec_token") or ""
            if note_id and xsec_token:
                url = (
                    f"https://www.xiaohongshu.com/explore/{note_id}"
                    f"?xsec_token={xsec_token}&xsec_source=pc_search"
                )
        imgs: list[str] = []
        # 候选字段：images / image_list / images_list / cover
        for key in ("images", "image_list", "images_list", "image_urls"):
            v = src.get(key)
            if isinstance(v, list):
                for img in v:
                    if isinstance(img, str) and img.startswith("http"):
                        imgs.append(img)
                    elif isinstance(img, dict):
                        u = img.get("url") or img.get("url_default") or img.get("info_list", [{}])[0].get("url", "")
                        if u and u.startswith("http"):
                            imgs.append(u)
        cover = src.get("cover")
        if isinstance(cover, str) and cover.startswith("http"):
            imgs.insert(0, cover)
        elif isinstance(cover, dict):
            u = cover.get("url") or cover.get("url_default") or ""
            if u and u.startswith("http"):
                imgs.insert(0, u)
        # 去重
        seen = set()
        imgs = [u for u in imgs if not (u in seen or seen.add(u))]
        results.append({
            "title": title,
            "text": text,
            "source_url": url,
            "image_urls": imgs,
        })
    if results:
        logger.info(f"[deepsearch] xhs 命中 {len(results)} 条笔记 (query={query!r})")
    return results


def _search_via_exa(query: str, n: int = 2) -> str:
    """通过 Agent-Reach 的 mcporter + Exa MCP 做语义搜索，返回拼接后的摘要文本。
    未安装 mcporter / Exa 未配置 / 任何异常都返回 ""。"""
    if not _have_cli("mcporter"):
        return ""
    rc, out = _run_cli(
        [
            "mcporter", "call", "exa.web_search_exa",
            f"query={query}", f"numResults={n}",
            "--output", "json", "--timeout", "30000",
        ],
        timeout=45.0,
    )
    if rc != 0 or not out.strip():
        return ""
    try:
        data = json.loads(out)
    except Exception:
        return ""
    # MCP tool result: {content: [{type:'text', text:'...'}], ...}
    blocks = data.get("content") or []
    full = ""
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            full += b.get("text", "")
    if not full:
        return ""
    # 取每条结果的 Highlights，去掉 [...] 噪音，截到 200 字
    chunks: list[str] = []
    for block in full.split("\n---\n"):
        m = re.search(r"Highlights:\s*\n(.+)", block, flags=re.DOTALL)
        if not m:
            continue
        text = m.group(1)
        text = re.sub(r"\[\.\.\.\]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            chunks.append(text[:220])
    if not chunks:
        return ""
    logger.debug(f"[deepsearch] exa 摘要 {len(chunks)} 段 (query={query!r})")
    return " ".join(chunks[:2])


def get_channel_status() -> dict:
    """返回 deepsearch 三个数据源的可用性，供 UI 展示。
    {
      "xhs":  {"installed": bool, "logged_in": bool, "username": str, "message": str},
      "exa":  {"installed": bool, "configured": bool, "message": str},
      "ddgs": {"installed": bool, "message": str},
    }
    所有探测都是本地秒级操作，不发起任何网络请求。"""
    status: dict = {}

    # ── xhs ──────────────────────────────────────────────────────────────
    xhs: dict = {"installed": _have_cli("xhs"), "logged_in": False, "username": "", "message": ""}
    if xhs["installed"]:
        rc, out = _run_cli(["xhs", "status", "--json"], timeout=10.0)
        try:
            data = json.loads(out) if out.strip() else {}
        except Exception:
            data = {}
        xhs["logged_in"] = bool(data.get("ok"))
        if xhs["logged_in"]:
            user_info = (data.get("data", {}) or {}).get("user") or {}
            xhs["username"] = user_info.get("nickname") or user_info.get("name") or user_info.get("username") or (data.get("data", {}) or {}).get("username") or data.get("username") or ""
            xhs["message"] = "已登录"
        else:
            err = (data.get("error") or {}).get("code") or "not_authenticated"
            xhs["message"] = f"未登录 ({err})"
    else:
        xhs["message"] = "xhs CLI 未安装：`pipx install xiaohongshu-cli`"
    status["xhs"] = xhs

    # ── Exa via mcporter ─────────────────────────────────────────────────
    exa: dict = {"installed": _have_cli("mcporter"), "configured": False, "message": ""}
    if exa["installed"]:
        cfg_path = Path(os.path.expanduser("~")) / "config" / "mcporter.json"
        if cfg_path.exists():
            try:
                cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                exa["configured"] = "exa" in (cfg_data.get("mcpServers") or {})
            except Exception:
                pass
        exa["message"] = "Exa 已就绪" if exa["configured"] else "未配置 exa server：`mcporter config add exa https://mcp.exa.ai/mcp`（需先 cd ~）"
    else:
        exa["message"] = "mcporter 未安装：`npm install -g mcporter`"
    status["exa"] = exa

    # ── ddgs ─────────────────────────────────────────────────────────────
    try:
        import ddgs  # noqa: F401
        status["ddgs"] = {"installed": True, "message": "ddgs 已就绪"}
    except Exception:
        status["ddgs"] = {"installed": False, "message": "ddgs 未安装：`pip install ddgs`"}

    return status


def run_xhs_login(cookie_source: str = "auto") -> dict:
    """在子进程跑 `xhs login`，从浏览器自动提取 Cookie。返回 {ok, message, username}。
    cookie_source: auto / chrome / edge / firefox / safari。"""
    if not _have_cli("xhs"):
        return {"ok": False, "message": "xhs CLI 未安装", "username": ""}
    rc, out = _run_cli(
        ["xhs", "login", "--cookie-source", cookie_source, "--json"]
        if cookie_source != "auto"
        else ["xhs", "login", "--json"],
        timeout=60.0,
    )
    try:
        data = json.loads(out) if out.strip() else {}
    except Exception:
        data = {}
    if rc == 0 and data.get("ok"):
        return {
            "ok": True,
            "username": (data.get("data", {}) or {}).get("username", ""),
            "message": data.get("message") or "登录成功",
        }
    err = (data.get("error") or {})
    return {
        "ok": False,
        "username": "",
        "message": err.get("message") or err.get("code") or f"登录失败 (rc={rc})",
    }


async def deepsearch(
    topic: str,
    n_refs: int = 4,
    save_dir: Path | None = None,
    content_type: str = "成品展示",
    sources: list[str] | None = None,
) -> list[ReferenceItem]:
    """两步法：
    1) 文本 LLM 生成 N 条 {title, text, query} 元数据（无图片 URL）
    2) 对每条 query，按优先级取真实素材：
         (a) Agent-Reach `xhs search`：已登录时直接拿小红书笔记（带封面 + 真实文案）
         (b) Agent-Reach `mcporter call exa.web_search_exa`：用 Exa 摘要增强 LLM 文案
         (c) ddgs(bing 后端) 兜底搜图（可指定多平台 site: 过滤）
    content_type: "教程步骤图" / "成品展示" / "素材参考"
    sources: 多平台来源列表，如 ["小红书", "Twitter/X", "Reddit", "微博", "通用图片"]
             默认 ["小红书", "通用图片"]
    """
    if sources is None:
        sources = ["小红书", "通用图片"]
    cfg = _load_text_llm()
    if not (cfg.get("api_key") and cfg.get("base_url")):
        raise RuntimeError("文本 LLM 未配置，请到 ⚙️ 设置中填写 post_content preset")

    text_model = cfg.get("model") or ""
    # 根据 content_type 选择对应 prompt 模板
    if content_type == "教程步骤图":
        _prompt_tpl = _SEARCH_PROMPT_TUTORIAL
    elif content_type == "素材参考":
        _prompt_tpl = _SEARCH_PROMPT_REF
    else:
        _prompt_tpl = _SEARCH_PROMPT
    prompt = _prompt_tpl.format(topic=topic, n_refs=n_refs)

    logger.info(f"[deepsearch] topic={topic!r} text_model={text_model} n={n_refs}")
    data = await _post_chat(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=text_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        timeout=httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=120.0),
    )

    text = _extract_text(data)
    parsed = _parse_json_block(text)
    if not parsed:
        logger.error(f"[deepsearch] 无法解析元数据响应：{text[:500]}")
        return []

    if isinstance(parsed, dict):
        parsed = [parsed]

    # 一次性检测 xhs 登录状态，避免对每条 query 都等 30s 超时
    _xhs_logged_in: bool = False
    if "小红书" in sources and _have_cli("xhs"):
        rc_s, out_s = _run_cli(["xhs", "status", "--json"], timeout=8.0)
        try:
            _xhs_logged_in = json.loads(out_s).get("ok", False) if out_s.strip() else False
        except Exception:
            _xhs_logged_in = False
    logger.info(f"[deepsearch] sources={sources} xhs_logged_in={_xhs_logged_in}")

    # 非小红书的多平台来源（走 ddgs site: 过滤）
    other_sources = [s for s in sources if s != "小红书"]
    # 仅当用户没勾任何来源（不太可能，UI 有默认值）才兜底用通用图片
    if not other_sources and not _xhs_logged_in:
        other_sources = ["通用图片"]

    async def _fetch_one(item: dict) -> ReferenceItem:
        """并行执行单条 ref 的外部搜索：小红书 + 其它平台合并取图。"""
        if not isinstance(item, dict):
            return ReferenceItem(title="", text="", source_url="", image_urls=[])
        title = str(item.get("title", "")).strip()
        text_body = str(item.get("text", "")).strip()
        # 兼容旧字段 query / 新字段 query_zh + query_en
        query_zh = str(item.get("query_zh") or "").strip()
        query_en = str(item.get("query_en") or "").strip()
        legacy_q = str(item.get("query") or "").strip()
        if not query_zh and not query_en:
            # 旧版只有 query：当作通用 query 同时给中英
            query_zh = legacy_q or title or topic
            query_en = legacy_q or title or topic
        elif not query_zh:
            query_zh = title or topic
        elif not query_en:
            query_en = legacy_q or title or topic

        # Sanitize query to prevent splitting for "Van" (truck)
        query_zh = sanitize_search_query(query_zh, is_en=False)
        query_en = sanitize_search_query(query_en, is_en=True)

        # xhs CLI 专用 query：中文为主
        xhs_query = query_zh or title or topic

        source_url = ""
        urls: list[str] = []

        # —— 并行启动：xhs（仅当登录且勾选小红书）+ 多平台 ddgs + exa
        xhs_quota = 2 if (_xhs_logged_in and other_sources) else 4  # 有其它平台时只给 xhs 2 张
        per_source = max(1, max(0, 4 - xhs_quota) // max(1, len(other_sources))) if other_sources else 0
        # 至少给每个其它平台 1 张
        per_source = max(per_source, 1) if other_sources else 0

        tasks: dict[str, asyncio.Task] = {}
        if _xhs_logged_in:
            tasks["xhs"] = asyncio.create_task(asyncio.to_thread(_search_via_xhs, xhs_query, xhs_quota))
        has_foreign = any(s not in _CN_SOURCES and s != "通用图片" for s in sources)
        if other_sources:
            tasks["ddgs"] = asyncio.create_task(asyncio.to_thread(
                _search_images_multi_sources, query_zh, query_en, other_sources, per_source, has_foreign
            ))
        # 仅当包含国外平台时才使用 exa 语义抓取，防止中文字段被英文语义污染
        if has_foreign:
            tasks["exa"] = asyncio.create_task(asyncio.to_thread(_search_via_exa, query_en or query_zh, 2))

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        result_map = dict(zip(tasks.keys(), results))

        # —— 处理 xhs 结果（贡献 title/text/source_url + 图）
        xhs_imgs: list[str] = []
        xhs_hits = result_map.get("xhs")
        if isinstance(xhs_hits, list) and xhs_hits:
            head = xhs_hits[0]
            if head.get("title"):
                title = head["title"]
            if head.get("text"):
                text_body = head["text"]
            source_url = head.get("source_url", "")
            for h in xhs_hits:
                xhs_imgs.extend(h.get("image_urls") or [])

        # —— 多平台 ddgs 结果
        ddgs_urls = result_map.get("ddgs")
        ddgs_imgs: list[str] = ddgs_urls if isinstance(ddgs_urls, list) else []

        # —— 交错合并：xhs[0], ddgs[0], xhs[1], ddgs[1], ... 保证多平台都能排进前 4
        from itertools import zip_longest
        interleaved: list[str] = []
        for a, b in zip_longest(xhs_imgs, ddgs_imgs):
            if a:
                interleaved.append(a)
            if b:
                interleaved.append(b)

        # —— 去重 + 截断到 4 张
        seen: set[str] = set()
        urls = [u for u in interleaved if u and not (u in seen or seen.add(u))][:4]

        logger.info(
            f"[deepsearch._fetch_one] zh={query_zh!r} en={query_en!r} "
            f"xhs={len(xhs_imgs)} ddgs={len(ddgs_imgs)} merged={len(urls)} (interleaved)"
        )

        # —— exa 文案增强
        exa_extra = result_map.get("exa")
        if isinstance(exa_extra, str) and exa_extra:
            text_body = (text_body + "\n\n" + exa_extra).strip()

        return ReferenceItem(
            title=title,
            text=text_body,
            source_url=source_url,
            image_urls=urls,
        )

    # 所有 ref 并行发起
    valid_items = [it for it in parsed[:n_refs] if isinstance(it, dict)]
    refs: list[ReferenceItem] = list(await asyncio.gather(*(_fetch_one(it) for it in valid_items)))

    # 下载图片
    if save_dir:
        save_dir = Path(save_dir) / "refs"
        save_dir.mkdir(parents=True, exist_ok=True)
        for i, ref in enumerate(refs):
            for j, img_url in enumerate(ref.image_urls[:3]):
                local = save_dir / f"ref{i + 1:02d}_img{j + 1}.jpg"
                if await _download_image(img_url, local):
                    ref.local_images.append(str(local))

    logger.info(f"[deepsearch] 拿到 {len(refs)} 条参考，共 {sum(len(r.local_images) for r in refs)} 张图")
    return refs


def sanitize_search_query(q: str, is_en: bool) -> str:
    if not q:
        return q
    if is_en:
        # Use full specific names to completely eliminate search engine vehicle (van) confusion
        q = re.sub(r'(?i)[\'"]?\bvan\s+gogh\b[\'"]?', '"Vincent van Gogh"', q)
        q = re.sub(r'(?i)[\'"]?\bvan\s+eyck\b[\'"]?', '"Jan van Eyck"', q)
        q = re.sub(r'(?i)[\'"]?\bvan\s+dyck\b[\'"]?', '"Anthony van Dyck"', q)
    return q


def sanitize_text_overlay(text: str) -> str:
    if not text:
        return ""
    # Remove @ followed by characters up to space or slash
    text = re.sub(r'@[^\s/]+', '', text)
    # Remove ID: / 号: patterns and digits
    text = re.sub(r'(?i)(id|号|账号|uid)\s*[:：]?\s*\d+', '', text)
    # Remove pure numbers (which are often user IDs or dates/timestamps)
    text = re.sub(r'\b\d{5,}\b', '', text)
    
    # Split by / and filter out segments containing platform names
    segments = [s.strip() for s in text.split('/')]
    filtered = []
    forbidden_keywords = {
        "小红书", "xiaohongshu", "xhs", "微博", "weibo", "抖音", "douyin", 
        "快手", "kuaishou", "watermark", "logo", "水印", "标志", "图标", 
        "wechat", "微信", "tiktok", "bilibili", "b站", "贴吧", "tieba"
    }
    for seg in segments:
        seg_lower = seg.lower()
        if any(kw in seg_lower for kw in forbidden_keywords):
            continue
        # If the segment is empty or just special characters, skip it
        cleaned_seg = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', seg).strip()
        if not cleaned_seg:
            continue
        filtered.append(seg)
    return " / ".join(filtered) if filtered else "none"



# ─── Step 2: 反推 Prompt ──────────────────────────────────────────────────────

_REVERSE_PROMPT = """你是「AI 绘画 prompt 反推专家」。
请仔细观察这张图片，输出一段**英文** AI 绘画 prompt，描述：
- 主体物 / 主要元素
- 风格（如：摄影 / 插画 / 极简 / 国风等）
- 构图、视角、光线、色调
- 背景、氛围

要求：
- 60~120 词
- 使用逗号分隔的关键词风格
- 不要包含任何中文
- 不要包含具体可识别的人名、品牌名

只输出英文 prompt 本身，不要其他解释。
"""

_REVERSE_PROMPT_STRUCT = r"""你是「AI 绘画 prompt 反推专家」。请仔细观察图片并把视觉特征拆解为以下维度的关键词。
严格用以下 JSON 格式返回（不要其他解释）：

```json
{
  "subject": "main subject and core elements, ~10-20 words (英文)",
  "style": "art style / medium, e.g. cinematic photo, flat illustration, anime, oil painting (英文)",
  "lighting": "lighting setup, e.g. soft natural daylight, golden hour rim light, studio softbox (英文)",
  "palette": "dominant color palette, e.g. warm pastel beige and cream, cool teal-orange contrast (英文)",
  "composition": "composition / camera angle, e.g. centered eye-level close-up, rule of thirds (英文)",
  "mood": "mood and atmosphere, e.g. serene minimalist, energetic vibrant (英文)",
  "text_overlay": "画面上出现的所有可读文字原文（中文/英文都原样输出）。注意：必须彻底忽略并剔除任何图片来源平台的水印、Logo、用户ID或签名（如“小红书”、“xiaohongshu”、“微博”、“weibo”、“ID:\d+”、“抖音”等）。例：\"头发上色 / 短发教程 / @procreate插画教程 / 自然棕色\"。没有文字填 \"none\"",
  "annotations": "画面中的教学标注元素，如：箭头/数字编号/色卡圈/步骤拆解/辅助线/圈出的区域。用英文描述。没有填 \"none\"",
  "layout": "画面布局：single subject / step-by-step grid / split panels / portrait with color swatches 等，英文一句话"
}
```

要求：
- 前 6 个字段全部英文关键词，逗号分隔，每字段≤ 25 词
- text_overlay 保留原始语言（中英文都不要翻译），并用斜杠 / 分隔各条文本，且绝对不能包含平台水印/Logo文字。
- annotations 、layout 用英文
- 不包含具体人名、品牌名
- 9 个字段都必须填写，没有信息填 "none"
"""


def _compose_prompt(parts: dict) -> str:
    """把结构化 parts 合成一个完整 prompt 字符串。"""
    order = ["subject", "style", "lighting", "palette", "composition", "mood"]
    segs = []
    for k in order:
        v = str(parts.get(k, "") or "").strip().rstrip(".,;")
        if v and v.lower() != "none":
            segs.append(v)
    base = ", ".join(segs)
    # 教学元素：布局 + 标注 + 画面文字
    extras: list[str] = []
    layout = str(parts.get("layout", "") or "").strip().rstrip(".,;")
    if layout and layout.lower() != "none":
        extras.append(f"layout: {layout}")
    annotations = str(parts.get("annotations", "") or "").strip().rstrip(".,;")
    if annotations and annotations.lower() != "none":
        extras.append(f"tutorial annotations: {annotations}")
    text_overlay = str(parts.get("text_overlay", "") or "").strip().rstrip(".,;")
    text_overlay = sanitize_text_overlay(text_overlay)
    if text_overlay and text_overlay.lower() != "none":
        # 明确告诉生图模型在画面上渲染这些文字
        extras.append(
            f'with on-image text overlay reading exactly: "{text_overlay}", '
            f"crisp readable typography, preserve Chinese characters if present"
        )
    if extras:
        base = base + ", " + ", ".join(extras)
    return base


async def reverse_prompt_structured(image_path: str) -> dict:
    """反推结构化 prompt，返回 {subject, style, lighting, palette, composition, mood,
    text_overlay, annotations, layout, full}。"""
    cfg = _load_vision_llm()
    if not (cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")):
        raise RuntimeError("视觉 LLM 未配置，请在 config.yaml 里填 post_vision 或 post_image preset")

    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(f"图片不存在：{image_path}")

    suffix = p.suffix.lower()
    mime = {"png": "image/png", "webp": "image/webp"}.get(
        suffix.lstrip("."), "image/jpeg"
    )
    b64 = base64.b64encode(p.read_bytes()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _REVERSE_PROMPT_STRUCT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }]

    data = await _post_chat(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        messages=messages,
        temperature=0.5,
    )
    text = _extract_text(data).strip()
    if not text:
        raise RuntimeError(
            f"视觉模型返回空响应（可能是模型 {cfg.get('model')} 不支持 vision 或被安全策略拦截）"
        )
    parsed = _parse_json_block(text)

    if not isinstance(parsed, dict):
        # 检查是否是拒绝答复（中文安全策略提示词）
        if re.search(r"(隔离|安全|拒绝|请告诉我你|不能提供|无法生成)", text):
            raise RuntimeError(
                f"视觉模型 {cfg.get('model')} 拒绝输出 prompt（回复前 80 字：{text[:80]}）。"
                f"此模型可能是纯图像生成模型，请改用 vision-chat 模型。"
            )
        logger.warning(f"[reverse_prompt_structured] JSON 解析失败，回退到纯文本：{text[:200]}")
        # 回退：把整段文本塞进 subject
        cleaned = re.sub(r"^prompt\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip('"\'`').strip()
        return {
            "subject": cleaned[:300],
            "style": "", "lighting": "", "palette": "",
            "composition": "", "mood": "",
            "full": cleaned,
        }

    parts = {
        k: str(parsed.get(k, "") or "").strip()
        for k in ("subject", "style", "lighting", "palette", "composition", "mood",
                   "text_overlay", "annotations", "layout")
    }
    parts["full"] = _compose_prompt(parts)
    return parts


async def reverse_prompt(image_path: str) -> str:
    """用 Gemini 多模态反推一张图的英文 prompt（向后兼容：返回字符串）。"""
    parts = await reverse_prompt_structured(image_path)
    return parts.get("full") or parts.get("subject", "")


# ─── Step 3: AI 重画 ──────────────────────────────────────────────────────────

async def regenerate_image(
    prompt: str,
    save_path: str | Path,
    *,
    size: str = "3x4",
    style_hint: str = "",
) -> str:
    """用 chatfire 图像模型重画一张图，返回本地保存路径。"""
    from pixelle_video.services.llm_image_service import LLMImageService

    cfg = _load_image_llm()
    if not (cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")):
        raise RuntimeError("图像 LLM 未配置")

    final_prompt = prompt
    if style_hint:
        final_prompt = f"{prompt}, style: {style_hint}"

    # Append negative prompt criteria to ensure watermarks/logos are avoided
    final_prompt = (
        f"{final_prompt}, clean of any watermarks, logos, signatures, "
        f"website links, username text, platform branding, or UI elements"
    )

    svc = LLMImageService()
    url_or_data = await svc.generate(
        prompt=final_prompt,
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
        size=size,
    )

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    if not await _save_generated(url_or_data, save_path):
        raise RuntimeError(f"无法保存生成图：{url_or_data[:120]}")
    return str(save_path)


# ─── Step 4: AI 文案生成 ──────────────────────────────────────────────────────

_COPY_PROMPT = """你是「小红书爆款文案写手」。请根据主题「{topic}」和下面的参考素材，原创一篇全新的小红书图文笔记。

参考素材（仅供启发，禁止直接照抄）：
{refs_text}

要求：
1. **标题**：≤20字，要有钩子和情绪点，可用 emoji
2. **正文**：200~500 字，自然口语，分段，可用 emoji 增加情绪
3. **标签**：3~6 个热门话题标签，不带 # 符号
4. 严禁敏感词、广告法违禁词、医疗保健功效宣称
5. 全部原创，与参考素材表达不雷同

严格用以下 JSON 格式返回：

```json
{{
  "title": "...",
  "body": "...",
  "hashtags": ["标签1", "标签2"]
}}
```
"""


async def generate_copy(topic: str, refs: list[ReferenceItem]) -> dict:
    """生成新的标题/正文/标签。"""
    cfg = _load_text_llm()
    if not (cfg.get("api_key") and cfg.get("base_url")):
        raise RuntimeError("文本 LLM 未配置")

    refs_blob = "\n\n".join(
        f"【参考{i + 1}】{r.title}\n{r.text[:200]}" for i, r in enumerate(refs[:5])
    ) or "（无参考素材）"

    prompt = _COPY_PROMPT.format(topic=topic, refs_text=refs_blob)

    data = await _post_chat(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,
    )
    text = _extract_text(data)
    parsed = _parse_json_block(text)
    # 递归 unwrap：某些模型返回 "body" 有时会是嵌套 JSON 字符串
    if isinstance(parsed, dict):
        for _ in range(2):
            inner_body = parsed.get("body")
            if isinstance(inner_body, str) and inner_body.lstrip().startswith("{"):
                inner = _parse_json_block(inner_body)
                if isinstance(inner, dict) and (inner.get("title") or inner.get("body")):
                    parsed = inner
                    continue
            break
    if not isinstance(parsed, dict):
        logger.error(f"[generate_copy] 解析失败：{text[:400]}")
        return {"title": topic, "body": text[:500] if text else "", "hashtags": []}

    return {
        "title": str(parsed.get("title", "")).strip(),
        "body": str(parsed.get("body", "")).strip(),
        "hashtags": [
            str(t).strip().lstrip("#")
            for t in (parsed.get("hashtags") or [])
            if isinstance(t, str) and t.strip()
        ][:8],
    }


# ─── 批量并发：重画 / 反推 ────────────────────────────────────────────────────

async def batch_regenerate(
    tasks: list[dict],
    *,
    size: str = "3x4",
    style_hint: str = "",
    concurrency: int = 3,
    progress_cb=None,
) -> list[dict]:
    """并发批量重画。
    tasks: [{"idx": int, "prompt": str, "save_path": str}, ...]
    返回: [{"idx": int, "ok": bool, "path": str|None, "error": str|None}, ...]
    progress_cb(done, total, idx, ok) 可选回调（在子线程，不要触 streamlit）。
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    total = len(tasks)
    done = 0
    lock = asyncio.Lock()
    results: list[dict] = [None] * total  # type: ignore

    async def _one(slot: int, t: dict):
        nonlocal done
        async with sem:
            try:
                p = await regenerate_image(
                    t["prompt"], t["save_path"],
                    size=size, style_hint=style_hint,
                )
                res = {"idx": t["idx"], "ok": True, "path": p, "error": None}
            except Exception as e:
                logger.exception(f"[batch_regenerate] idx={t.get('idx')} 失败")
                res = {"idx": t["idx"], "ok": False, "path": None, "error": str(e)}
            async with lock:
                done += 1
                results[slot] = res
                if progress_cb:
                    try:
                        progress_cb(done, total, t["idx"], res["ok"])
                    except Exception:
                        pass

    await asyncio.gather(*[_one(i, t) for i, t in enumerate(tasks)])
    return results


async def batch_reverse_prompt(
    image_paths: list[str],
    *,
    concurrency: int = 3,
    progress_cb=None,
) -> list[dict]:
    """并发批量反推 prompt（结构化）。
    返回: [{"idx": int, "path": str, "prompt": str|None, "parts": dict|None, "error": str|None}, ...]
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    total = len(image_paths)
    done = 0
    lock = asyncio.Lock()
    results: list[dict] = [None] * total  # type: ignore

    async def _one(slot: int, path: str):
        nonlocal done
        async with sem:
            try:
                parts = await reverse_prompt_structured(path)
                full = parts.get("full") or parts.get("subject", "")
                parts_clean = {k: v for k, v in parts.items() if k != "full"}
                res = {"idx": slot, "path": path, "prompt": full, "parts": parts_clean, "error": None}
            except Exception as e:
                logger.exception(f"[batch_reverse_prompt] slot={slot} 失败")
                res = {"idx": slot, "path": path, "prompt": None, "parts": None, "error": str(e)}
            async with lock:
                done += 1
                results[slot] = res
                if progress_cb:
                    try:
                        progress_cb(done, total, slot, res["error"] is None)
                    except Exception:
                        pass

    await asyncio.gather(*[_one(i, p) for i, p in enumerate(image_paths)])
    return results


# ─── 主入口 ───────────────────────────────────────────────────────────────────

async def smart_scrape(
    topic: str,
    *,
    n_refs: int = 4,
    n_regen: int = 4,
    style_hint: str = "",
    size: str = "3x4",
    output_dir: Optional[str] = None,
    content_type: str = "成品展示",
    sources: list[str] | None = None,
) -> SmartScrapeResult:
    """端到端流程：搜索 → 反推 → 重画 → 写文案。"""
    if not output_dir:
        ts = int(time.time())
        output_dir = str(
            Path("output") / f"smart_{ts}"
        )
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "generated").mkdir(parents=True, exist_ok=True)

    result = SmartScrapeResult(topic=topic, output_dir=str(out_path))

    try:
        # Step 1: 搜索
        refs = await deepsearch(topic, n_refs=n_refs, save_dir=out_path, content_type=content_type, sources=sources)
        if not refs:
            result.error = "搜索未返回结果，请尝试更换主题或检查 API 配置"
            return result
        result.references = refs

        # Step 2/3: 反推 + 重画（并发，每张图独立处理）
        all_local_imgs = [img for r in refs for img in r.local_images]
        if not all_local_imgs:
            result.error = "搜索结果中没有可下载的图片"
            return result

        sample = all_local_imgs[:n_regen]
        semaphore = asyncio.Semaphore(3)  # 限制并发

        # 教程模式：强制让生图模型保留教学元素
        effective_style_hint = style_hint
        if content_type == "教程步骤图":
            tutorial_hint = (
                "instructional tutorial illustration, include step numbers, "
                "color palette swatches, directional arrows and labels, "
                "preserve original Chinese text annotations verbatim, "
                "crisp readable typography, infographic layout"
            )
            effective_style_hint = (
                f"{style_hint}, {tutorial_hint}" if style_hint else tutorial_hint
            )

        async def _process_one(idx: int, ref_img: str) -> GeneratedFrame:
            async with semaphore:
                frame = GeneratedFrame(ref_image=ref_img, image_prompt="")
                try:
                    parts = await reverse_prompt_structured(ref_img)
                    frame.prompt_parts = {k: v for k, v in parts.items() if k != "full"}
                    frame.image_prompt = (parts.get("full") or "").strip()
                    if not frame.image_prompt:
                        frame.error = "反推返回空 prompt，跳过重画"
                        logger.warning(f"[frame {idx + 1}] 反推为空，跳过重画")
                        return frame
                    gen_path = out_path / "generated" / f"img_{idx + 1:02d}.png"
                    frame.generated_image = await regenerate_image(
                        frame.image_prompt,
                        save_path=gen_path,
                        size=size,
                        style_hint=effective_style_hint,
                    )
                except Exception as e:
                    frame.error = str(e)
                    logger.warning(f"[frame {idx + 1}] 处理失败：{e}")
                return frame

        result.frames = await asyncio.gather(
            *[_process_one(i, img) for i, img in enumerate(sample)]
        )

        # Step 4: 文案
        copy = await generate_copy(topic, refs)
        result.title = copy["title"]
        result.body = copy["body"]
        result.hashtags = copy["hashtags"]

        # 落盘
        (out_path / "result.json").write_text(
            json.dumps({
                "topic": topic,
                "title": result.title,
                "body": result.body,
                "hashtags": result.hashtags,
                "frames": [
                    {
                        "ref": Path(f.ref_image).name,
                        "prompt": f.image_prompt,
                        "generated": Path(f.generated_image).name if f.generated_image else "",
                        "error": f.error,
                    } for f in result.frames
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except Exception as e:
        result.error = f"流程异常：{e}"
        logger.exception("[smart_scrape] 总体失败")

    return result


# ─── 多账号矩阵管理及定时保活 ──────────────────────────────────────────────────

import threading

_KEEPALIVE_THREAD = None
_KEEPALIVE_STOP_EVENT = threading.Event()


def get_xhs_accounts(username: str) -> list[dict]:
    """获取指定系统用户下所有的小红书账号及其状态"""
    proj_root = Path(__file__).resolve().parent.parent.parent
    user_home = proj_root / "data" / "users" / username
    xhs_config_dir = user_home / ".xiaohongshu-cli"
    
    if not xhs_config_dir.exists():
        return []
        
    active_account = ""
    active_file = xhs_config_dir / "active_account.txt"
    if active_file.exists():
        try:
            active_account = active_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
            
    accounts = []
    # 查找所有 cookies_*.json
    for p in xhs_config_dir.glob("cookies_*.json"):
        xhs_user = p.stem.replace("cookies_", "")
        saved_at = 0
        try:
            cookie_data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = cookie_data.get("saved_at", 0)
        except Exception:
            pass
            
        accounts.append({
            "xhs_username": xhs_user,
            "saved_at": saved_at,
            "active": (xhs_user == active_account)
        })
        
    return sorted(accounts, key=lambda x: x["xhs_username"])


def switch_xhs_account(username: str, xhs_username: str) -> bool:
    """切换小红书激活账号"""
    proj_root = Path(__file__).resolve().parent.parent.parent
    user_home = proj_root / "data" / "users" / username
    xhs_config_dir = user_home / ".xiaohongshu-cli"
    
    acc_cookie = xhs_config_dir / f"cookies_{xhs_username}.json"
    if not acc_cookie.exists():
        return False
        
    main_cookie = xhs_config_dir / "cookies.json"
    try:
        shutil.copy(acc_cookie, main_cookie)
        (xhs_config_dir / "active_account.txt").write_text(xhs_username, encoding="utf-8")
        logger.info(f"[xhs-matrix] Switched system user {username}'s active account to {xhs_username}")
        return True
    except Exception as e:
        logger.error(f"[xhs-matrix] Failed to switch active account: {e}")
        return False


def delete_xhs_account(username: str, xhs_username: str) -> bool:
    """删除指定小红书账号凭证"""
    proj_root = Path(__file__).resolve().parent.parent.parent
    user_home = proj_root / "data" / "users" / username
    xhs_config_dir = user_home / ".xiaohongshu-cli"
    
    acc_cookie = xhs_config_dir / f"cookies_{xhs_username}.json"
    if acc_cookie.exists():
        try:
            acc_cookie.unlink()
        except Exception:
            pass
            
    active_file = xhs_config_dir / "active_account.txt"
    if active_file.exists():
        try:
            active_acc = active_file.read_text(encoding="utf-8").strip()
            if active_acc == xhs_username:
                active_file.unlink()
                main_cookie = xhs_config_dir / "cookies.json"
                if main_cookie.exists():
                    main_cookie.unlink()
        except Exception:
            pass
    return True


def register_new_xhs_account(username: str) -> str:
    """把最新登录成功的 cookies.json 归档注册为 cookies_{xhs_username}.json"""
    proj_root = Path(__file__).resolve().parent.parent.parent
    user_home = proj_root / "data" / "users" / username
    xhs_config_dir = user_home / ".xiaohongshu-cli"
    main_cookie = xhs_config_dir / "cookies.json"
    
    if not main_cookie.exists():
        return ""
        
    # 运行 xhs status 获取当前登录的用户名
    rc, out = _run_cli(["xhs", "status", "--json"], override_username=username)
    xhs_username = ""
    if rc == 0 and out.strip():
        try:
            data = json.loads(out)
            xhs_username = (data.get("data", {}) or {}).get("username") or data.get("username") or ""
        except Exception:
            pass
            
    if not xhs_username:
        # fallback: 用时间戳
        xhs_username = f"user_{int(time.time())}"
        
    # 清理文件名中可能的不安全字符
    xhs_username = re.sub(r'[\\/*?:"<>| ]', "_", xhs_username)
    
    try:
        acc_cookie = xhs_config_dir / f"cookies_{xhs_username}.json"
        shutil.copy(main_cookie, acc_cookie)
        # 设为 active
        (xhs_config_dir / "active_account.txt").write_text(xhs_username, encoding="utf-8")
        logger.info(f"[xhs-matrix] Registered new xhs account {xhs_username} for user {username}")
        return xhs_username
    except Exception as e:
        logger.error(f"[xhs-matrix] Failed to register account: {e}")
        return ""


def _cookie_keepalive_loop(interval_hours: float):
    interval_seconds = interval_hours * 3600
    # 启动 30 秒后先运行一次保活，确保可以立即对现有 Cookie 触发激活
    time.sleep(30)
    
    while not _KEEPALIVE_STOP_EVENT.is_set():
        try:
            logger.info("[xhs-keepalive] Starting Cookie keepalive loop...")
            proj_root = Path(__file__).resolve().parent.parent.parent
            users_dir = proj_root / "data" / "users"
            if users_dir.exists():
                for user_home in users_dir.iterdir():
                    if _KEEPALIVE_STOP_EVENT.is_set():
                        break
                    if not user_home.is_dir():
                        continue
                        
                    username = user_home.name
                    xhs_config_dir = user_home / ".xiaohongshu-cli"
                    if xhs_config_dir.exists():
                        cookie_files = list(xhs_config_dir.glob("cookies_*.json"))
                        main_cookie = xhs_config_dir / "cookies.json"
                        
                        active_account = ""
                        active_file = xhs_config_dir / "active_account.txt"
                        if active_file.exists():
                            try:
                                active_account = active_file.read_text(encoding="utf-8").strip()
                            except Exception:
                                pass
                                
                        for cookie_file in cookie_files:
                            if _KEEPALIVE_STOP_EVENT.is_set():
                                break
                                
                            xhs_username = cookie_file.stem.replace("cookies_", "")
                            logger.info(f"[xhs-keepalive] Keepalive checking for user={username}, xhs_account={xhs_username}")
                            
                            try:
                                # 临时将此 Cookie 文件覆盖到 cookies.json
                                shutil.copy(cookie_file, main_cookie)
                                
                                # 在该用户上下文下执行 xhs status --json 触发小红书 API 以刷新会话
                                rc, out = _run_cli(["xhs", "status", "--json"], override_username=username)
                                if rc == 0:
                                    logger.info(f"[xhs-keepalive] Keepalive SUCCESS for {username} -> {xhs_username}")
                                    if main_cookie.exists():
                                        shutil.copy(main_cookie, cookie_file)
                                else:
                                    logger.warning(f"[xhs-keepalive] Keepalive FAILED or EXPIRED for {username} -> {xhs_username}")
                            except Exception as e:
                                logger.error(f"[xhs-keepalive] Keepalive error for {username} -> {xhs_username}: {e}")
                                
                        # 恢复原来 active 账号的 cookies.json
                        if active_account:
                            active_cookie = xhs_config_dir / f"cookies_{active_account}.json"
                            if active_cookie.exists():
                                try:
                                    shutil.copy(active_cookie, main_cookie)
                                except Exception:
                                    pass
                                    
            logger.info("[xhs-keepalive] Cookie keepalive loop iteration finished.")
        except Exception as e:
            logger.error(f"[xhs-keepalive] Keepalive loop exception: {e}")
            
        sleep_slept = 0
        while sleep_slept < interval_seconds and not _KEEPALIVE_STOP_EVENT.is_set():
            time.sleep(10)
            sleep_slept += 10


def start_cookie_keepalive(interval_hours: float = 12.0):
    global _KEEPALIVE_THREAD, _KEEPALIVE_STOP_EVENT
    if _KEEPALIVE_THREAD is not None and _KEEPALIVE_THREAD.is_alive():
        logger.info("[xhs-keepalive] Keepalive thread already running.")
        return
        
    _KEEPALIVE_STOP_EVENT.clear()
    _KEEPALIVE_THREAD = threading.Thread(
        target=_cookie_keepalive_loop, 
        args=(interval_hours,), 
        daemon=True,
        name="XHS-KeepAlive-Thread"
    )
    _KEEPALIVE_THREAD.start()
    logger.info("[xhs-keepalive] Keepalive thread started successfully.")


def stop_cookie_keepalive():
    global _KEEPALIVE_THREAD, _KEEPALIVE_STOP_EVENT
    if _KEEPALIVE_THREAD is not None:
        _KEEPALIVE_STOP_EVENT.set()
        _KEEPALIVE_THREAD.join(timeout=5)
        _KEEPALIVE_THREAD = None
        logger.info("[xhs-keepalive] Keepalive thread stopped.")
