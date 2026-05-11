"""
RunningHub 低价渠道模型注册表

从 runninghub_lowprice_registry.json 加载所有低价渠道模型的 endpoint 和参数 schema，
向上层（media.py / web UI / runninghub_api_service.py）提供统一查询接口。

注册表来源：抓取 https://www.runninghub.cn/api/sku/detail (POST {"id": ...})
共 20 个模型，覆盖 text-to-image / image-to-image / text-to-video / image-to-video /
start-end-to-video / video-tools 等类别。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from loguru import logger

_REGISTRY_PATH = Path(__file__).parent / "runninghub_lowprice_registry.json"

# Workflow key 前缀 —— 与 media.py 中 runninghub-api/* 分支保持一致
WORKFLOW_PREFIX = "runninghub-api/"


def _infer_category(model: dict) -> str:
    """根据 endpoint 推断 category 标签（注册表抓取时是 null，需要后填）。"""
    ep = (model.get("rhEndpoint") or "").lower()
    if "text-to-video" in ep:
        return "text-to-video"
    if "image-to-video" in ep:
        return "image-to-video"
    if "start-end-to-video" in ep:
        return "start-end-to-video"
    if "text-to-image" in ep:
        return "text-to-image"
    if "image-to-image" in ep or ep.endswith("/edit"):
        return "image-to-image"
    if "upload-character" in ep:
        return "video-tools"
    return "other"


def _workflow_key_for(model: dict) -> str:
    """endpoint `/rhart-video-g/text-to-video` -> `runninghub-api/rhart-video-g/text-to-video`"""
    ep = (model.get("rhEndpoint") or "").lstrip("/")
    return f"{WORKFLOW_PREFIX}{ep}"


@lru_cache(maxsize=1)
def _load_raw() -> list[dict]:
    if not _REGISTRY_PATH.exists():
        logger.warning(f"[Registry] 注册表文件不存在: {_REGISTRY_PATH}")
        return []
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"[Registry] 已加载 {len(data)} 个 RunningHub 低价渠道模型")
        return data
    except Exception as e:
        logger.error(f"[Registry] 加载失败: {e}")
        return []


@lru_cache(maxsize=1)
def list_models() -> list[dict]:
    """
    返回所有模型的规范化记录，每条包含：
        - id, name, nameEn
        - workflow_key: runninghub-api/<path>
        - rhEndpoint: /<path>
        - category: text-to-video / image-to-video / ...
        - description, modelHighlights
        - inputs: 原始 schema 列表
    """
    out = []
    for m in _load_raw():
        out.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "nameEn": m.get("nameEn"),
            "rhEndpoint": m.get("rhEndpoint"),
            "workflow_key": _workflow_key_for(m),
            "category": _infer_category(m),
            "description": m.get("description", ""),
            "modelHighlights": m.get("modelHighlights", ""),
            "inputs": m.get("inputs", []),
        })
    return out


def get_model_by_workflow_key(workflow_key: str) -> Optional[dict]:
    for m in list_models():
        if m["workflow_key"] == workflow_key:
            return m
    return None


def get_model_by_endpoint(endpoint: str) -> Optional[dict]:
    ep_norm = "/" + endpoint.lstrip("/")
    for m in list_models():
        if m["rhEndpoint"] == ep_norm:
            return m
    return None


def is_runninghub_api_workflow(workflow_key: Optional[str]) -> bool:
    return bool(workflow_key) and workflow_key.startswith(WORKFLOW_PREFIX)


def required_input_keys(model: dict) -> list[str]:
    return [i["fieldKey"] for i in (model.get("inputs") or []) if i.get("required")]


def build_payload(model: dict, user_params: dict, api_key: str) -> dict:
    """
    根据模型 schema + 用户提供的参数构造 RunningHub Model API 请求体。

    - 包含 apiKey 字段
    - 自动按字段类型转换（INT -> int, BOOLEAN -> bool, IMAGE 多图 -> list）
    - 未提供的非必填字段会使用默认值（仅 LIST / BOOLEAN / INT 类型）
    - 必填字段缺失时抛 ValueError
    """
    payload: dict = {"apiKey": api_key}
    for spec in model.get("inputs") or []:
        key = spec["fieldKey"]
        ftype = spec.get("type", "STRING")
        required = bool(spec.get("required"))
        default = spec.get("defaultValue")
        provided = user_params.get(key, None)

        if provided is None or provided == "":
            if required and default in (None, "", []):
                raise ValueError(f"缺少必填参数: {key} (model={model.get('nameEn')})")
            # 非必填可省略；必填且有默认值时使用默认值
            if not required:
                # LIST / BOOLEAN 类带默认值的字段仍发送默认值，避免接口报错
                if ftype in ("LIST", "BOOLEAN", "INT") and default not in (None, ""):
                    payload[key] = _coerce(default, ftype, spec)
                continue
            value = default
        else:
            value = provided

        payload[key] = _coerce(value, ftype, spec)
    return payload


def _coerce(value, ftype: str, spec: dict):
    if value is None:
        return None
    try:
        if ftype == "INT":
            return int(value)
        if ftype == "BOOLEAN":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return bool(value)
        if ftype == "IMAGE":
            if spec.get("multipleInputs") and not isinstance(value, list):
                return [value]
            return value
    except Exception:
        return value
    return value


def display_label(model: dict) -> str:
    """UI 上展示的名字。"""
    cat = model.get("category") or "other"
    return f"[{cat}] {model['name']}"
