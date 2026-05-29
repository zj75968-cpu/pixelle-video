# Copyright (C) 2025 AIDC-AI
# Licensed under the Apache License, Version 2.0
"""
小红书引流活动调度服务

一次"引流活动"(Campaign)的概念：
- N 轮 × 每轮 2 篇 = 总 2N 篇贴
- 每篇 post_type="traffic"，delete_after_hours=delete_minutes/60 (默认 25min 自动删)
- 轮与轮之间间隔 = delete_minutes + random(gap_min, gap_max)
- 文案由 LLM 生成 + harmonize 自动谐音化

入口：
    schedule_campaign(serials=[...], image_pool=[...], topic=..., cta=..., rounds=5,
                      delete_minutes=25, gap_min=5, gap_max=10) -> campaign_id

依赖：
    pixelle_video.services.publish_scheduler.publish_scheduler  (单例)
    pixelle_video.utils.harmonize.harmonize_text                (谐音化)
"""
from __future__ import annotations

import json
import random
import re
import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import httpx
from loguru import logger

from pixelle_video.utils.harmonize import harmonize_hashtags, harmonize_text


# ── 文件持久化 ─────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CAMPAIGNS_FILE = _DATA_DIR / "drainage_campaigns.json"


@dataclass
class DrainageCampaign:
    campaign_id: str
    created_at: str
    topic: str
    cta: str
    rounds: int
    delete_minutes: int
    gap_min: int
    gap_max: int
    serials: List[str]
    job_ids: List[str] = field(default_factory=list)
    note: str = ""
    status: str = "active"  # active | stopped | finished

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "DrainageCampaign":
        import dataclasses as _dc
        kwargs = {}
        for k, fld in cls.__dataclass_fields__.items():
            if k in d:
                kwargs[k] = d[k]
            elif fld.default is not _dc.MISSING:
                kwargs[k] = fld.default
            elif fld.default_factory is not _dc.MISSING:  # type: ignore[misc]
                kwargs[k] = fld.default_factory()  # type: ignore[misc]
        return cls(**kwargs)


def _load_all() -> dict[str, DrainageCampaign]:
    if not _CAMPAIGNS_FILE.exists():
        return {}
    try:
        raw = json.loads(_CAMPAIGNS_FILE.read_text(encoding="utf-8"))
        return {cid: DrainageCampaign.from_dict(cd) for cid, cd in raw.items()}
    except Exception as e:
        logger.warning(f"[drainage] load failed: {e}")
        return {}


def _save_all(items: dict[str, DrainageCampaign]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CAMPAIGNS_FILE.write_text(
        json.dumps({cid: c.to_dict() for cid, c in items.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_campaigns() -> List[DrainageCampaign]:
    return sorted(_load_all().values(), key=lambda c: c.created_at, reverse=True)


# ── LLM 文案生成 ──────────────────────────────────────────────────────────

_PERSONAS = [
    ("emo小白", "刚踏入这个领域的萌新，语气委婉求助，多用 emoji"),
    ("热血干货", "已上岸/有成果的过来人，分享干货吸引同好"),
    ("好物种草", "把主题包装成隐性好物分享，结尾才透露 CTA"),
    ("姐妹日常", "闺蜜聊天式碎碎念，结尾顺嘴提一句加群"),
    ("学习打卡", "立人设：今天 day N 打卡，鼓励同伴加入"),
    ("避坑预警", "踩坑预警体，前面铺垫问题，结尾导流到群里求救"),
]


def _build_prompt(topic: str, cta: str, persona_label: str, persona_brief: str) -> str:
    return f"""你是一个小红书引流文案专家，请按下面要求生成 1 篇小红书图文笔记：

【主题】{topic}
【人设】{persona_label} —— {persona_brief}
【引流目标 CTA】{cta}

要求：
1. **标题**：≤20 字，自带钩子（数字 / 反差 / 提问 / emoji 任选一）。
2. **正文**：120-220 字，分 3-5 个短段，每段 1-2 句，多用 emoji 和换行。
3. **CTA**：必须在正文最后 2 行内自然提到 CTA（评论扣 1 进群 / 私信 / 加群之类），
   但**不要使用任何敏感词原文**（不能直接写"加群""微信""扫码""二维码""V信"等）；
   可用谐音字、表情、近义词暗示，例如"扣1️⃣进🐏圈" "踢我一脚" "戳我"。
4. **hashtag**：给 4-6 个紧扣主题的小红书标签，不带井号，不能含敏感词。
5. 输出必须是合法 JSON：
   {{"title":"...","body":"...","hashtags":["...","..."]}}
   不要任何额外解释，不要 markdown 围栏。
"""


async def _chat(base_url: str, api_key: str, model: str, prompt: str) -> str:
    api_base = base_url.rstrip("/")
    url = (f"{api_base}/chat/completions"
           if api_base.endswith("/v1")
           else f"{api_base}/v1/chat/completions")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.0,
    }
    timeout = httpx.Timeout(connect=15.0, read=90.0, write=90.0, pool=90.0)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=timeout) as c:
        r = await c.post(url, json=body, headers=headers)
        data = r.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        logger.warning(f"[drainage] LLM bad response: {data}")
        return ""


def _parse_json(text: str) -> dict:
    """从模型输出抓 JSON。"""
    if not text:
        return {}
    # 1. Try direct parsing
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # 3. Try finding outermost braces
    brace_start = text.find('{')
    brace_end = text.rfind('}')
    if brace_start != -1 and brace_end > brace_start:
        json_str = text[brace_start:brace_end + 1]
        try:
            return json.loads(json_str)
        except Exception:
            # Try cleaning trailing commas
            cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
            try:
                return json.loads(cleaned)
            except Exception:
                pass

    # 4. Try json_repair
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
    except Exception:
        pass

    return {}


async def generate_drainage_pair(
    topic: str, cta: str, *, seed: int | None = None
) -> List[dict]:
    """生成 2 篇不同人设的引流帖（已谐音化）。返回 [{title, body, hashtags}, ...]"""
    from pixelle_video.config.manager import ConfigManager
    cm = ConfigManager()
    preset = cm.get_post_model_preset("post_content")
    if not (preset.get("api_key") and preset.get("base_url")):
        preset = cm.get_llm_config()
    base_url = preset.get("base_url", "")
    api_key = preset.get("api_key", "")
    model = preset.get("model", "deepseek-chat")
    if not (base_url and api_key):
        raise RuntimeError("post_content / llm 未配置，请到 ⚙️ Settings 填写。")

    rng = random.Random(seed)
    personas = rng.sample(_PERSONAS, k=2)

    results: List[dict] = []
    for idx, (label, brief) in enumerate(personas):
        prompt = _build_prompt(topic, cta, label, brief)
        raw = await _chat(base_url, api_key, model, prompt)
        parsed = _parse_json(raw)
        title = (parsed.get("title") or f"{topic} · 笔记 {idx+1}").strip()
        body = (parsed.get("body") or raw or "").strip()
        tags = parsed.get("hashtags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[、,，#]+", tags) if t.strip()]
        tags = [str(t).lstrip("#").strip() for t in tags if t]

        # 二次谐音化兜底（即使 LLM 不小心写了敏感词，这一步也会替换掉）
        ssed = (seed or 0) ^ (idx * 17 + 11)
        title = harmonize_text(title, seed=ssed)
        body = harmonize_text(body, seed=ssed)
        tags = harmonize_hashtags(tags, seed=ssed)

        # AI 自动生成海报图片
        poster_dir = Path(__file__).resolve().parent.parent.parent / "output" / "drainage_posters"
        poster_dir.mkdir(parents=True, exist_ok=True)
        poster_filename = f"poster_{uuid.uuid4().hex[:12]}.png"
        poster_path = poster_dir / poster_filename
        
        try:
            from pixelle_video.services.poster_generator import generate_drainage_poster
            # 谐音化后完美字眼，直接用来生成引流图（在线程池中执行）
            await asyncio.to_thread(generate_drainage_poster, title, str(poster_path.resolve()))
            image_path_str = str(poster_path.resolve())
        except Exception as e:
            logger.error(f"[drainage] Failed to generate AI poster: {e}")
            image_path_str = ""

        results.append({
            "title": title[:30],
            "body": body,
            "hashtags": tags[:8],
            "persona": label,
            "image_path": image_path_str,
        })
    return results


# ── 排期 ───────────────────────────────────────────────────────────────────

def schedule_campaign(
    *,
    serials: List[str],
    image_pool: List[str],
    posts: List[dict],         # [{title, body, hashtags, image_path}, ...] for round 1
    rounds: int,
    delete_minutes: int = 25,
    gap_min: int = 5,
    gap_max: int = 10,
    topic: str = "",
    cta: str = "",
    note: str = "",
    images_per_post: int = 1,
) -> DrainageCampaign:
    """把 N 轮 × 2 篇排进 publish_scheduler 队列。

    posts 长度必须为 2（同一对文案会在每轮被复用，
    每轮内部仍各发 2 篇 = 一对，确保每篇都有谐音差异）。
    """
    from pixelle_video.services.publish_scheduler import publish_scheduler

    if len(posts) != 2:
        raise ValueError("posts 必须正好是 2 篇文案（每轮 2 篇引流帖）")
    if rounds < 1:
        raise ValueError("rounds 至少为 1")
    if not serials:
        raise ValueError("serials 不能为空")

    campaign = DrainageCampaign(
        campaign_id=str(uuid.uuid4())[:8],
        created_at=datetime.now().isoformat(),
        topic=topic, cta=cta,
        rounds=rounds, delete_minutes=delete_minutes,
        gap_min=gap_min, gap_max=gap_max,
        serials=list(serials),
        note=note,
    )

    rng = random.Random()
    cursor = datetime.now() + timedelta(seconds=10)   # 第 1 轮立刻发

    for r in range(rounds):
        for idx, post in enumerate(posts):
            # 每篇之间留 30s 缓冲，避免同时打 xhs CLI
            scheduled_at = (cursor + timedelta(seconds=idx * 30)).isoformat()
            
            # 检查是否有专属 AI 自动生成海报
            post_poster = post.get("image_path")
            
            if not image_pool and post_poster and Path(post_poster).exists():
                imgs = [post_poster]
            else:
                # 否则，从全局图片池里随机抽
                k = min(images_per_post, len(image_pool))
                imgs = rng.sample(image_pool, k=k) if k > 0 else []
            # 不同轮次/不同篇 → 不同 seed，让谐音字也有差异
            seed = hash((campaign.campaign_id, r, idx)) & 0xFFFFFFFF
            title = harmonize_text(post["title"], seed=seed)[:30]
            body = harmonize_text(post["body"], seed=seed)
            tags = harmonize_hashtags(post.get("hashtags") or [], seed=seed)

            for serial in serials:
                job = publish_scheduler.add_job(
                    serial=serial,
                    task_id=f"drainage:{campaign.campaign_id}:r{r+1}:p{idx+1}",
                    title=title,
                    body=body,
                    hashtags=tags,
                    images=imgs,
                    scheduled_at=scheduled_at,
                    post_type="traffic",
                    delete_after_hours=delete_minutes / 60.0,  # 发出后自动删（默认 25min）
                )
                campaign.job_ids.append(job.job_id)
        # 下一轮起点 = 本轮起点 + delete_minutes + random(gap_min, gap_max)
        cursor += timedelta(minutes=delete_minutes + rng.uniform(gap_min, gap_max))

    # 持久化
    all_campaigns = _load_all()
    all_campaigns[campaign.campaign_id] = campaign
    _save_all(all_campaigns)
    logger.info(
        f"[drainage] campaign {campaign.campaign_id} scheduled: "
        f"{rounds} rounds × 2 posts × {len(serials)} devices "
        f"= {len(campaign.job_ids)} jobs"
    )
    return campaign


def stop_campaign(campaign_id: str, *, delete_published: bool = True) -> dict:
    """手动停止活动。

    - 取消尚未发布的 scheduled/pending job
    - delete_published=True（默认）：异步删除该活动里所有已发布成功的笔记（按标题）

    返回 {cancelled, delete_attempted, delete_succeeded, delete_failed}
    """
    import asyncio as _asyncio
    from pixelle_video.services.publish_scheduler import publish_scheduler
    from pixelle_video.services.xhs_publisher import XHSPublisher

    all_campaigns = _load_all()
    c = all_campaigns.get(campaign_id)
    if not c:
        return {"cancelled": 0, "delete_attempted": 0, "delete_succeeded": 0, "delete_failed": 0}

    cancelled = 0
    to_delete: list[tuple[str, str]] = []  # (serial, title)
    for jid in c.job_ids:
        job = publish_scheduler.get_job(jid)
        if not job:
            continue
        if job.status in ("scheduled", "pending"):
            if publish_scheduler.cancel_job(jid):
                cancelled += 1
        elif delete_published and job.status in ("success", "completed", "published"):
            to_delete.append((job.serial, job.title))

    succ = fail = 0
    if to_delete:
        async def _del_one(serial: str, title: str) -> bool:
            try:
                pub = XHSPublisher(serial=serial, strict_mode=False)
                return bool(await pub.delete_post(post_title=title))
            except Exception as exc:
                logger.warning(f"[drainage] stop-delete fail serial={serial} title={title!r}: {exc}")
                return False

        async def _del_all():
            return await _asyncio.gather(*[_del_one(s, t) for s, t in to_delete])

        try:
            results = _asyncio.run(_del_all())
            succ = sum(1 for r in results if r)
            fail = len(results) - succ
            # 已删除的 job 标 status
            di = 0
            for jid in c.job_ids:
                job = publish_scheduler.get_job(jid)
                if job and job.status in ("success", "completed", "published"):
                    if di < len(results) and results[di]:
                        job.status = "deleted"
                    di += 1
            publish_scheduler._save()
        except Exception as exc:
            logger.error(f"[drainage] stop_campaign delete loop crashed: {exc}")
            fail = len(to_delete)

    c.status = "stopped"
    _save_all(all_campaigns)
    logger.info(
        f"[drainage] campaign {campaign_id} stopped, cancelled={cancelled}, "
        f"deleted={succ}/{len(to_delete)} (fail={fail})"
    )
    return {
        "cancelled": cancelled,
        "delete_attempted": len(to_delete),
        "delete_succeeded": succ,
        "delete_failed": fail,
    }


def get_campaign(campaign_id: str) -> Optional[DrainageCampaign]:
    return _load_all().get(campaign_id)


# ── 进度 / ETA ─────────────────────────────────────────────────────────────

def campaign_progress(campaign: DrainageCampaign) -> dict:
    """统计该活动的 job 状态分布 + 下一篇 ETA。

    返回：{
      total, done, pending, failed,
      next_at: datetime | None,    # 下一个待发 job 计划时间（UTC-naive 或 local-naive，看 scheduler 写入格式）
      next_eta_seconds: int | None,
    }
    """
    from pixelle_video.services.publish_scheduler import publish_scheduler

    total = len(campaign.job_ids)
    done = pending = failed = 0
    next_at: Optional[datetime] = None
    for jid in campaign.job_ids:
        job = publish_scheduler.get_job(jid)
        if not job:
            continue
        s = job.status
        if s in ("success", "completed", "published"):
            done += 1
        elif s in ("failed", "error", "cancelled", "canceled"):
            failed += 1
        elif s in ("scheduled", "pending"):
            pending += 1
            sa = getattr(job, "scheduled_at", None)
            if sa:
                try:
                    dt = sa if isinstance(sa, datetime) else datetime.fromisoformat(str(sa))
                    if next_at is None or dt < next_at:
                        next_at = dt
                except Exception:
                    pass

    next_eta_seconds: Optional[int] = None
    if next_at is not None:
        # next_at 由本服务自己写入时是 datetime.now().isoformat()（local naive）
        delta = (next_at - datetime.now()).total_seconds()
        next_eta_seconds = max(0, int(delta))

    return {
        "total": total,
        "done": done,
        "pending": pending,
        "failed": failed,
        "next_at": next_at,
        "next_eta_seconds": next_eta_seconds,
    }
