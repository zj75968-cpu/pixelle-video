"""
Phone Agent Client
===================
云端 / 本地服务器调用手机 HTTP Agent 的客户端。
用于替换 ADB push 方案，通过 HTTPS（cloudflared 隧道）与手机通信。

配置方式（config.yaml）：
    phone_agent:
        url: "https://xxx-yyy-zzz.trycloudflare.com"   # cloudflared 输出的地址
        token: "your-secret-token"                       # 与 phone_agent.py --token 一致
        chunk_size_mb: 5                                 # 每块大小，默认 5MB
        timeout_push: 120                                # 文件推送超时秒数

使用示例：
    from pixelle_video.services.phone_agent_client import push_images_to_gallery_http

    result = push_images_to_gallery_http(
        local_paths=["/path/to/video.mp4"],
        agent_url="https://xxx.trycloudflare.com",
        token="your-secret-token",
    )
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

# 默认分块大小：5 MB（cloudflared 免费版单请求限制约 100MB，分块更稳定）
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024


def _make_session(token: str) -> requests.Session:
    """创建带认证头的 requests Session。"""
    s = requests.Session()
    if token:
        s.headers.update({"X-Token": token})
    return s


def ping(agent_url: str, token: str = "", timeout: int = 10) -> bool:
    """检查手机 Agent 是否在线。"""
    try:
        s = _make_session(token)
        resp = s.get(f"{agent_url.rstrip('/')}/ping", timeout=timeout)
        return resp.status_code == 200 and resp.json().get("ok") is True
    except Exception as e:
        logger.warning(f"phone_agent ping failed: {e}")
        return False


def push_file_http(
    local_path: str,
    agent_url: str,
    token: str = "",
    push_dir: str = "/sdcard/DCIM/PixelleVideo",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    timeout: int = 120,
) -> dict:
    """
    通过 HTTP 将单个文件推送到手机。
    大文件自动分块传输。

    Returns:
        {"ok": True, "device_path": "...", "size": N}
        {"ok": False, "error": "..."}
    """
    local_path = str(local_path)
    file_size = os.path.getsize(local_path)
    filename = Path(local_path).name
    base_url = agent_url.rstrip("/")
    session = _make_session(token)

    logger.info(f"push_file_http: {local_path} → {push_dir}/{filename} ({file_size/1024/1024:.1f} MB)")

    # 小文件（< chunk_size）直接发送
    if file_size <= chunk_size:
        with open(local_path, "rb") as f:
            content_hex = f.read().hex()
        try:
            resp = session.post(
                f"{base_url}/push-file",
                json={
                    "filename": filename,
                    "content_hex": content_hex,
                    "push_dir": push_dir,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)}

    # 大文件分块传输
    with open(local_path, "rb") as f:
        data = f.read()

    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    total = len(chunks)
    logger.info(f"push_file_http: splitting into {total} chunks")

    for idx, chunk in enumerate(chunks):
        try:
            resp = session.post(
                f"{base_url}/push-file-chunk",
                json={
                    "filename": filename,
                    "chunk_index": idx,
                    "total_chunks": total,
                    "chunk_hex": chunk.hex(),
                    "push_dir": push_dir,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug(f"chunk {idx+1}/{total}: {result}")
            if result.get("completed"):
                return result
        except requests.RequestException as e:
            return {"ok": False, "error": f"chunk {idx} failed: {e}"}

    return {"ok": False, "error": "All chunks sent but no completion response"}


def push_images_to_gallery_http(
    local_paths: list[str],
    agent_url: str,
    token: str = "",
    push_dir: str = "/sdcard/DCIM/PixelleVideo",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    timeout_per_file: int = 120,
) -> dict:
    """
    将多个本地文件批量推送到手机相册。
    接口与 device_manager.push_images_to_gallery 保持一致。

    Args:
        local_paths: 本地文件路径列表
        agent_url:   手机 Agent URL（cloudflared 隧道地址）
        token:       认证 Token
        push_dir:    手机端目标目录
        chunk_size:  分块大小（字节）
        timeout_per_file: 每个文件推送超时（秒）

    Returns:
        {
            "success": int,           # 成功文件数
            "failed": list[str],      # 失败的本地路径
            "device_paths": list[str] # 手机端路径
        }
    """
    if not agent_url:
        raise ValueError("agent_url is required. Set PHONE_AGENT_URL env var or config phone_agent.url")

    device_paths: list[str] = []
    failed: list[str] = []

    for local_path in local_paths:
        result = push_file_http(
            local_path=local_path,
            agent_url=agent_url,
            token=token,
            push_dir=push_dir,
            chunk_size=chunk_size,
            timeout=timeout_per_file,
        )
        if result.get("ok"):
            device_paths.append(result["device_path"])
            logger.info(f"push_images_to_gallery_http: ✓ {local_path}")
        else:
            failed.append(local_path)
            logger.error(f"push_images_to_gallery_http: ✗ {local_path}: {result.get('error')}")

    if device_paths:
        time.sleep(1)  # 给媒体库一点扫描时间

    return {
        "success": len(device_paths),
        "failed": failed,
        "device_paths": device_paths,
    }


def open_app_http(
    package: str,
    agent_url: str,
    token: str = "",
    timeout: int = 15,
) -> bool:
    """
    通过 HTTP Agent 打开手机上的 App。

    Args:
        package: Android 包名，如 "com.xingin.xhs"
        agent_url: 手机 Agent URL
        token: 认证 Token

    Returns:
        True if succeeded, False otherwise
    """
    try:
        session = _make_session(token)
        resp = session.post(
            f"{agent_url.rstrip('/')}/open-app",
            json={"package": package},
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            logger.warning(f"open_app_http: {package} failed: {result.get('error')}")
        return result.get("ok", False)
    except requests.RequestException as e:
        logger.error(f"open_app_http: {e}")
        return False


def push_images_auto(
    local_paths: list[str],
    serial: str = "",
    push_dir: str = "/sdcard/DCIM/PixelleVideo",
) -> dict:
    """
    统一推送入口：优先使用 HTTP Agent，若未配置则降级到 ADB。

    从 config.yaml phone_agent.url 自动读取配置，无需手动传参。

    Args:
        local_paths: 本地文件路径列表
        serial:     ADB serial（降级时使用）
        push_dir:   手机端目标目录

    Returns:
        与 push_images_to_gallery 相同的 dict 格式
    """
    from pixelle_video.config import config_manager

    cfg = config_manager.config
    agent_url = cfg.phone_agent.url.strip()
    agent_token = cfg.phone_agent.token.strip()
    chunk_size = cfg.phone_agent.chunk_size_mb * 1024 * 1024
    timeout = cfg.phone_agent.timeout_push

    if agent_url:
        logger.info("push_images_auto: using HTTP Agent")
        return push_images_to_gallery_http(
            local_paths=local_paths,
            agent_url=agent_url,
            token=agent_token,
            push_dir=push_dir,
            chunk_size=chunk_size,
            timeout_per_file=timeout,
        )
    else:
        logger.info("push_images_auto: falling back to ADB")
        from pixelle_video.services.device_manager import push_images_to_gallery
        return push_images_to_gallery(
            serial=serial,
            local_paths=local_paths,
            push_dir=push_dir,
        )
