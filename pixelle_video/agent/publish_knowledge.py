"""XHS 发布问题知识库

当发布任务失败时，自动用 LLM 分析根因并写入知识库。
下次 Agent 遇到相同/相似错误时，可查询知识库直接获取解决方案，
无需重新从头 debug。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

KNOWLEDGE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "publish_knowledge.json"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class KnowledgeEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    job_kind: str = ""                   # "video" / "image_text" / ""
    problem: str = ""                    # 一句话描述
    error_pattern: str = ""             # 逗号分隔的匹配关键词
    root_cause: str = ""                 # 根本原因（2-3 句）
    solution: str = ""                   # 解决方案（1-2 句）
    resolution_steps: List[str] = Field(default_factory=list)
    times_seen: int = 1
    resolved: bool = False               # 是否已有确认可行的解决方案


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class PublishKnowledge:
    """Singleton knowledge base backed by data/publish_knowledge.json."""

    def __init__(self) -> None:
        self._entries: List[KnowledgeEntry] = []
        self._load()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not KNOWLEDGE_FILE.exists():
            return
        try:
            raw = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
            self._entries = [KnowledgeEntry(**e) for e in raw.get("entries", [])]
        except Exception as exc:
            logger.warning(f"[知识库] 加载失败，将从空库开始: {exc}")

    def _save(self) -> None:
        KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": [e.model_dump() for e in self._entries]}
        KNOWLEDGE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(self, text: str, top_k: int = 3) -> List[KnowledgeEntry]:
        """Fuzzy keyword search; returns up to top_k most-seen matches."""
        lower = text.lower()
        hits: List[KnowledgeEntry] = []
        for entry in self._entries:
            keywords = [k.strip().lower() for k in entry.error_pattern.split(",") if k.strip()]
            if any(kw and kw in lower for kw in keywords):
                hits.append(entry)
        # Sort: resolved first, then by times_seen desc
        hits.sort(key=lambda e: (not e.resolved, -e.times_seen))
        return hits[:top_k]

    def list_all(self) -> List[KnowledgeEntry]:
        return list(self._entries)

    def get_by_id(self, entry_id: str) -> Optional[KnowledgeEntry]:
        return next((e for e in self._entries if e.id == entry_id), None)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_or_update(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        """Add new entry or increment times_seen if a similar one already exists."""
        existing = self.search(entry.error_pattern, top_k=1)
        if existing:
            found = existing[0]
            found.times_seen += 1
            found.updated_at = datetime.now().isoformat()
            # Upgrade to resolved if new entry brings a confirmed solution
            if entry.resolved and not found.resolved:
                found.resolved = True
                found.solution = entry.solution
                found.resolution_steps = entry.resolution_steps
                found.root_cause = entry.root_cause or found.root_cause
            self._save()
            return found
        self._entries.append(entry)
        self._save()
        return entry

    def mark_resolved(
        self,
        entry_id: str,
        solution: str,
        steps: Optional[List[str]] = None,
    ) -> bool:
        entry = self.get_by_id(entry_id)
        if not entry:
            return False
        entry.resolved = True
        entry.solution = solution
        if steps:
            entry.resolution_steps = steps
        entry.updated_at = datetime.now().isoformat()
        self._save()
        return True


# Singleton
publish_knowledge = PublishKnowledge()


# ---------------------------------------------------------------------------
# LLM-powered auto-analysis
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """\
你是小红书自动发布系统的故障分析专家。
请分析以下发布失败案例，提炼出可复用的知识条目。

发布类型: {job_kind}
错误信息: {error}
发布进度日志:
{progress_log}

**要求**：以纯 JSON 回复，不要加 ```json ``` 包裹，结构如下：
{{
  "problem": "一句话描述这个问题（≤30字）",
  "error_pattern": "用于未来匹配此类错误的关键词，逗号分隔（3-6个词）",
  "root_cause": "根本原因（2-3句话，聚焦于为什么出错）",
  "solution": "解决方案（1-2句话，具体可操作）",
  "resolution_steps": ["具体步骤1", "步骤2", "步骤3"],
  "resolved": false
}}

注意：
- error_pattern 关键词要能区分此类问题与其他问题，不要太宽泛（如"发布"）
- 如果你能从错误信息推断出确定的解决方法，把 resolved 置为 true
- 步骤要具体，包括代码路径或 UI 操作
"""


class FailureAnalysisSchema(BaseModel):
    problem: str = Field(description="一句话描述这个问题（≤30字）")
    error_pattern: str = Field(description="用于未来匹配此类错误的关键词，逗号分隔（3-6个词）")
    root_cause: str = Field(description="根本原因（2-3句话，聚焦于为什么出错）")
    solution: str = Field(description="解决方案（1-2句话，具体可操作）")
    resolution_steps: List[str] = Field(default_factory=list, description="具体步骤，包括代码路径或 UI 操作")
    resolved: bool = Field(description="如果能从错误信息推断出确定的解决方法，置为 true，否则 false")


async def analyze_and_record_failure(
    job_id: str,
    job_kind: str,
    error: str,
    progress_log: List[str],
) -> Optional[KnowledgeEntry]:
    """Call LLM to analyze a publish failure and persist the result.

    Safe to call from a background asyncio task; swallows all exceptions.
    """
    if not error or error.startswith("[手动重置"):
        return None

    try:
        from pixelle_video.service import pixelle_video as core  # late import

        if not getattr(core, "_initialized", False) or not core.llm:
            logger.debug("[知识库] LLM 未就绪，跳过自动分析")
            return None

        log_text = "\n".join(progress_log[-20:]) if progress_log else "（无日志）"
        prompt = _ANALYSIS_PROMPT.format(
            job_kind=job_kind or "unknown",
            error=error[:500],
            progress_log=log_text,
        )

        logger.info(f"[知识库] 分析任务 {job_id} 失败原因…")
        data = await core.llm(
            prompt=prompt,
            response_type=FailureAnalysisSchema,
            temperature=0.1,
            max_tokens=600,
        )

        entry = KnowledgeEntry(
            job_kind=job_kind or "",
            problem=data.problem or error[:60],
            error_pattern=data.error_pattern or "",
            root_cause=data.root_cause or "",
            solution=data.solution or "",
            resolution_steps=data.resolution_steps or [],
            resolved=bool(data.resolved),
        )
        saved = publish_knowledge.add_or_update(entry)
        logger.info(f"[知识库] 已记录条目 {saved.id}: {saved.problem}")
        return saved

    except Exception as exc:
        logger.warning(f"[知识库] 自动分析失败（不影响主流程）: {exc}")
        return None
