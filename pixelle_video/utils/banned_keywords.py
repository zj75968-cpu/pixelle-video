"""
小红书违禁词管理：加载、保存、过滤。

存储位置：<repo>/data/banned_keywords.json
{
  "keywords": ["...", "..."],
  "mode": "mask" | "remove",
  "mask": "***",
  "updated_at": "ISO-8601"
}

约定：
- 关键词按长度倒序匹配（避免被更短的子词先吞掉）。
- 大小写不敏感。
- 哈希标签同样过滤；若整个标签被清空则丢弃该标签。
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_STORE_FILE = _DATA_DIR / "banned_keywords.json"
_DEFAULT_MASK = "***"

_lock = threading.RLock()
_cache: dict | None = None
_compiled: re.Pattern | None = None

# ---- 反规避预处理 -----------------------------------------------------------

# 零宽 / 不可见字符（直接删除）
_ZW_TABLE = str.maketrans(
    "",
    "",
    "".join([
        "\u200b",  # ZERO WIDTH SPACE
        "\u200c",  # ZERO WIDTH NON-JOINER
        "\u200d",  # ZERO WIDTH JOINER
        "\u2060",  # WORD JOINER
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
        "\u180e",  # MONGOLIAN VOWEL SEPARATOR
        "\u00ad",  # SOFT HYPHEN
    ]),
)

# 异形空格 → 普通 ASCII 空格
_FANCY_WS = (
    "\u3000\u00a0\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u202f\u205f"
)
_WS_TABLE = str.maketrans(_FANCY_WS, " " * len(_FANCY_WS))

# 同形字（西里尔 / 希腊字母 → ASCII）
_HOMOGLYPH_TABLE = str.maketrans({
    # Cyrillic lowercase
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    # Cyrillic uppercase
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y",
    # Greek lowercase
    "α": "a", "β": "b", "γ": "g", "ε": "e", "ζ": "z", "ι": "i",
    "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    # Greek uppercase
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Υ": "Y", "Χ": "X",
})


def _sanitize(text: str) -> str:
    """反规避预处理：NFKC 归一化 + 零宽字符剥离 + 异形空格替换 + 同形字替换。"""
    text = unicodedata.normalize("NFKC", text)  # 全角→半角、连字拆开等
    text = text.translate(_ZW_TABLE)            # 去除零宽 / 不可见字符
    text = text.translate(_WS_TABLE)            # 异形空格 → 普通空格
    text = text.translate(_HOMOGLYPH_TABLE)     # 西里尔/希腊同形字 → ASCII
    return text

# ----------------------------------------------------------------------------


def _normalize(keywords: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for raw in keywords:
        if raw is None:
            continue
        word = str(raw).strip()
        if not word:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(word)
    # 长度倒序，确保 "黑神话悟空" 优先于 "悟空"
    result.sort(key=lambda w: (-len(w), w))
    return result


def _compile(keywords: Sequence[str]) -> re.Pattern | None:
    if not keywords:
        return None
    # 编译时也对关键词做反规避处理，确保关键词与预处理后的输入文本对齐
    parts = [re.escape(_sanitize(w)) for w in keywords]
    return re.compile("|".join(parts), re.IGNORECASE)


def _load_locked() -> dict:
    global _cache, _compiled
    if _cache is not None:
        return _cache
    if _STORE_FILE.exists():
        try:
            with open(_STORE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    else:
        raw = {}
    keywords = _normalize(raw.get("keywords") or [])
    mode = raw.get("mode") if raw.get("mode") in ("mask", "remove") else "mask"
    mask = str(raw.get("mask") or _DEFAULT_MASK)
    _cache = {
        "keywords": keywords,
        "mode": mode,
        "mask": mask,
        "updated_at": raw.get("updated_at"),
    }
    _compiled = _compile(keywords)
    return _cache


def _save_locked() -> None:
    global _cache
    assert _cache is not None
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(_cache)
    payload["updated_at"] = datetime.now().isoformat()
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _cache = payload


def get_state() -> dict:
    """返回当前完整状态（拷贝）。"""
    with _lock:
        state = _load_locked()
        return {
            "keywords": list(state["keywords"]),
            "mode": state["mode"],
            "mask": state["mask"],
            "updated_at": state.get("updated_at"),
        }


def list_keywords() -> List[str]:
    with _lock:
        return list(_load_locked()["keywords"])


def replace_all(keywords: Iterable[str], *, mode: str | None = None, mask: str | None = None) -> List[str]:
    """整体替换关键词列表。"""
    global _cache, _compiled
    with _lock:
        state = _load_locked()
        normalized = _normalize(keywords)
        state["keywords"] = normalized
        if mode in ("mask", "remove"):
            state["mode"] = mode
        if mask is not None:
            state["mask"] = str(mask) or _DEFAULT_MASK
        _cache = state
        _compiled = _compile(normalized)
        _save_locked()
        return normalized


def add_keywords(words: Iterable[str]) -> List[str]:
    """追加关键词，返回新的完整列表。"""
    global _cache, _compiled
    with _lock:
        state = _load_locked()
        merged = _normalize(list(state["keywords"]) + list(words))
        state["keywords"] = merged
        _cache = state
        _compiled = _compile(merged)
        _save_locked()
        return merged


def remove_keyword(word: str) -> List[str]:
    global _cache, _compiled
    with _lock:
        state = _load_locked()
        keep = [w for w in state["keywords"] if w.lower() != str(word).strip().lower()]
        state["keywords"] = keep
        _cache = state
        _compiled = _compile(keep)
        _save_locked()
        return keep


def clear_all() -> None:
    global _cache, _compiled
    with _lock:
        state = _load_locked()
        state["keywords"] = []
        _cache = state
        _compiled = None
        _save_locked()


def set_mode(mode: str, mask: str | None = None) -> dict:
    global _cache
    with _lock:
        state = _load_locked()
        if mode not in ("mask", "remove"):
            raise ValueError(f"invalid mode: {mode}")
        state["mode"] = mode
        if mask is not None:
            state["mask"] = str(mask) or _DEFAULT_MASK
        _cache = state
        _save_locked()
        return get_state()


def reload() -> None:
    """丢弃缓存，强制下次访问时重新从磁盘读。"""
    global _cache, _compiled
    with _lock:
        _cache = None
        _compiled = None


# ---- parsing uploaded content ----

def parse_upload(content: str | bytes, filename: str = "") -> List[str]:
    """从用户上传的内容里解析关键词。

    支持：
    - .txt: 一行一个关键词；同一行也可用 [\\s,，;；、|] 分隔。
    - .csv: 同 txt，逗号分隔也兼容。
    - .json: list[str] 或 {"keywords": [...]}。
    """
    if isinstance(content, bytes):
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法解码上传文件（请使用 UTF-8 或 GBK）")
    else:
        text = content

    ext = (filename.rsplit(".", 1)[-1] or "").lower() if filename else ""
    stripped = text.strip()
    if ext == "json" or stripped.startswith(("[", "{")):
        try:
            data = json.loads(stripped or "[]")
        except Exception as exc:
            raise ValueError(f"JSON 解析失败：{exc}") from exc
        if isinstance(data, dict):
            data = data.get("keywords") or []
        if not isinstance(data, list):
            raise ValueError("JSON 必须是数组或包含 keywords 数组的对象")
        return _normalize(str(x) for x in data)

    # 文本：按行 + 行内分隔符
    words: List[str] = []
    for line in text.splitlines():
        for token in re.split(r"[\s,，;；、|]+", line):
            token = token.strip()
            if token:
                words.append(token)
    return _normalize(words)


# ---- filtering ----

def filter_text(text: str | None) -> Tuple[str, List[str]]:
    """对单段文本过滤违禁词。

    匹配前先做反规避预处理（NFKC / 零宽字符 / 异形空格 / 同形字），
    返回 (清洗后的文本, 命中的关键词列表)。命中列表用于上层展示告警。
    """
    if not text:
        return text or "", []
    # 反规避预处理：在归一化后的文本上做匹配并返回
    sanitized = _sanitize(text)
    with _lock:
        state = _load_locked()
        pattern = _compiled
        mode = state["mode"]
        mask = state["mask"] or _DEFAULT_MASK
    if pattern is None:
        return sanitized, []

    hits: List[str] = []

    def _sub(match: re.Match) -> str:
        hits.append(match.group(0))
        return "" if mode == "remove" else mask

    cleaned = pattern.sub(_sub, sanitized)
    if mode == "remove":
        # 去除遗留的连续空白
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, hits


def filter_hashtags(tags: Iterable[str] | None) -> Tuple[List[str], List[str]]:
    """对哈希标签列表逐项过滤；若一个标签被清空，则丢弃该标签。"""
    if not tags:
        return [], []
    cleaned: List[str] = []
    all_hits: List[str] = []
    for tag in tags:
        new_tag, hits = filter_text(tag)
        if hits:
            all_hits.extend(hits)
        new_tag = (new_tag or "").strip()
        if new_tag and new_tag.strip("#").strip():
            cleaned.append(new_tag)
    return cleaned, all_hits


def filter_post(
    *, title: str | None = None, body: str | None = None, hashtags: Iterable[str] | None = None
) -> Tuple[str, str, List[str], List[str]]:
    """对整篇帖子的标题/正文/标签做过滤。

    返回 (title, body, hashtags, hits)。hits 已去重。
    """
    new_title, hits_t = filter_text(title or "")
    new_body, hits_b = filter_text(body or "")
    new_tags, hits_h = filter_hashtags(hashtags or [])
    merged: List[str] = []
    seen = set()
    for h in (*hits_t, *hits_b, *hits_h):
        key = h.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(h)
    return new_title, new_body, new_tags, merged


# ---- LLM prompt injection ----

def build_prompt_block(*, max_words: int = 200, language: str = "auto") -> str:
    """生成可拼接到 LLM prompt 末尾的「禁止词」指令段落。

    - 列表为空时返回空字符串（不污染 prompt）。
    - 默认双语提示，兼容中英文模型/中英文输出场景。
    - 超过 `max_words` 个关键词只展示前 N 个（避免 prompt 过长）。
    """
    words = list_keywords()
    if not words:
        return ""
    shown = words[:max_words]
    overflow = max(0, len(words) - len(shown))
    words_line = "、".join(shown)
    if overflow:
        words_line += f"（另有 {overflow} 个未列出）"

    if language == "en":
        block = (
            "\n\nBANNED TERMS — MUST NOT APPEAR in title, body, hashtags, "
            "captions or any text output (Chinese OR English, case-insensitive). "
            "If the topic forces them, rephrase with a neutral synonym. "
            f"List: {words_line}\n"
        )
    else:
        block = (
            "\n\n【小红书禁止出现的关键词 / Banned terms】\n"
            "下列词语在标题、正文、话题标签、字幕里都不允许出现（中英文均判定，"
            "大小写不敏感）。若主题不得不涉及，请改用中性同义表达，或绕开该词。"
            f"\n禁止词列表：{words_line}\n"
        )
    return block


def append_prompt_block(prompt: str, *, language: str = "auto") -> str:
    """便捷函数：把禁止词段落追加到现有 prompt 末尾。"""
    block = build_prompt_block(language=language)
    if not block:
        return prompt
    return f"{prompt}{block}"


# ---- 审计日志 ---------------------------------------------------------------

_AUDIT_FILE = _DATA_DIR / "banned_audit.log"
_audit_lock = threading.Lock()


def append_audit(
    *,
    task_id: str,
    serial: str,
    job_id: str,
    hits: List[str],
) -> None:
    """向 data/banned_audit.log 追加一条 JSONL 审计记录。"""
    entry = {
        "ts": datetime.now().isoformat(),
        "task_id": task_id,
        "serial": serial,
        "job_id": job_id,
        "hits": list(hits),
    }
    line = json.dumps(entry, ensure_ascii=False)
    with _audit_lock:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_audit(last_n: int = 50) -> List[dict]:
    """读取最近 last_n 条审计记录，按时间升序返回。"""
    with _audit_lock:
        if not _AUDIT_FILE.exists():
            return []
        try:
            lines = _AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
    records: List[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records[-last_n:]


# ---- 审计日志 ---------------------------------------------------------------

def _audit_log_path() -> "Path":
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "data" / "banned_audit.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_audit(*, task_id: str, serial: str, job_id: str, hits: List[str]) -> None:
    """将一条违禁词命中记录追加到 data/banned_audit.log（JSONL 格式）。"""
    import json
    from datetime import datetime, timezone

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "serial": serial,
        "job_id": job_id,
        "hits": hits,
    }
    with open(_audit_log_path(), "a", encoding="utf-8") as _f:
        _f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_audit(last_n: int = 50) -> List[dict]:
    """读取最近 last_n 条违禁词命中记录；日志不存在时返回空列表。"""
    import json

    log_file = _audit_log_path()
    if not log_file.exists():
        return []
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    records: List[dict] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except Exception:
            pass
    return records[-last_n:]
