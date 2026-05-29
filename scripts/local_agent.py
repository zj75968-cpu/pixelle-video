# -*- coding: utf-8 -*-
"""
本地群控 Agent 客户端。
支持方案 B：主动轮询云端发帖任务，并调用本地物理 CH9329 串口控制发布。
"""
import os
import sys
import time
import argparse
import asyncio
import httpx
from pathlib import Path
from loguru import logger

# 将项目根目录添加至 sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pixelle_video.services.xhs_publisher import XHSPublisher


def await_async(coro):
    """同步环境中运行异步协程的辅助工具"""
    return asyncio.run(coro)


def poll_and_execute(
    server_url: str,
    device_serial: str,
    com_port: str,
    token: str,
    poll_interval: float = 5.0
):
    """
    死循环轮询云端任务并执行。
    """
    server_url = server_url.rstrip('/')
    logger.info(f"Agent started. Polling cloud at: {server_url}")
    logger.info(f"Local Serial: {device_serial} | Hardware Serial Port: {com_port}")

    headers = {
        "X-Token": token,
        "Accept": "application/json"
    }

    from pixelle_video.utils.network_util import get_cloud_client

    try:
        with get_cloud_client(timeout=30.0) as client:
            while True:
                try:
                    # 1. 轮询待发布任务
                    # 这里的 serials 参数传给云端，表示这台 Agent 代表的是 device_serial 设备
                    pending_url = f"{server_url}/api/publish/agent/pending?serials={device_serial}"
                    resp = client.get(pending_url, headers=headers)

                    if resp.status_code == 404:
                        # 兼容 API 没有就绪的情况
                        logger.warning(f"Cloud API endpoint not ready (404), retry in 10s...")
                        time.sleep(10)
                        continue

                    if resp.status_code != 200:
                        logger.error(f"Failed to poll cloud: HTTP {resp.status_code}. Retry in 10s...")
                        time.sleep(10)
                        continue

                    data = resp.json()
                    job = data.get("job")

                    if not job:
                        # 没有属于此设备的新任务
                        time.sleep(poll_interval)
                        continue

                    job_id = job["job_id"]
                    title = job["title"]
                    body = job["body"]
                    hashtags = job.get("hashtags", [])
                    images = job.get("images", [])
                    video_path = job.get("video_path")
                    kind = job.get("kind", "image_text")

                    logger.info(f"====== [Task Received] JobID: {job_id[:8]} ======")
                    logger.info(f"Title: {title} | Kind: {kind}")

                    # 2. 定义回调，将本地的每一步日志实时反馈回云端控制台
                    def send_progress_to_cloud(log_msg: str):
                        logger.info(f"[Progress] {log_msg}")
                        try:
                            progress_url = f"{server_url}/api/publish/agent/jobs/{job_id}/progress"
                            client.post(progress_url, headers=headers, json={"log": log_msg})
                        except Exception as ex:
                            logger.warning(f"Failed to report progress to cloud: {ex}")

                    # 3. 本地启动 XHSPublisher 执行发布
                    # 这里的 serial 我们传入本地绑定的 COM 串口
                    try:
                        publisher = XHSPublisher(serial=com_port, job_id=job_id)
                    except Exception as exc:
                        logger.error(f"Failed to initialize XHSPublisher: {exc}")
                        error_msg = f"Publisher initialization failed: {exc}"
                        try:
                            result_url = f"{server_url}/api/publish/agent/jobs/{job_id}/result"
                            client.post(result_url, headers=headers, json={"status": "failed", "error": error_msg})
                        except Exception:
                            pass
                        continue

                    # 云端传过来的图片/视频路径可能是云端服务器的相对路径，
                    # Agent 如果和云端不在同一台电脑，需要下载资源。
                    # 我们的 XHSPublisher 内部已经集成了自动检测 http/https 并下载的功能。
                    # 如果是云端本地生成的相对路径，我们需要拼接成云端提供下载的完整 URL：
                    resolved_images = []
                    for img in images:
                        if img.startswith("http://") or img.startswith("https://"):
                            resolved_images.append(img)
                        else:
                            # 确保路径被正确路由到云端的 api/files 静态下载服务
                            img_clean = img.lstrip("/")
                            if not img_clean.startswith("api/files/"):
                                resolved_images.append(f"{server_url}/api/files/{img_clean}")
                            else:
                                resolved_images.append(f"{server_url}/{img_clean}")

                    resolved_video = None
                    if video_path:
                        if video_path.startswith("http://") or video_path.startswith("https://"):
                            resolved_video = video_path
                        else:
                            video_clean = video_path.lstrip("/")
                            if not video_clean.startswith("api/files/"):
                                resolved_video = f"{server_url}/api/files/{video_clean}"
                            else:
                                resolved_video = f"{server_url}/{video_clean}"

                    send_progress_to_cloud("本地 Agent 开始下载媒体资产并执行发布...")

                    success = False
                    error_msg = ""

                    try:
                        if kind == "video":
                            success = await_async(publisher.publish_video(
                                video_path=resolved_video,
                                title=title,
                                body=body,
                                hashtags=hashtags,
                                progress_callback=send_progress_to_cloud
                            ))
                        else:
                            success = await_async(publisher.publish(
                                images=resolved_images,
                                title=title,
                                body=body,
                                hashtags=hashtags,
                                progress_callback=send_progress_to_cloud
                            ))

                        if not success:
                            error_msg = "XHSPublisher returned failure status"
                    except Exception as exc:
                        success = False
                        error_msg = str(exc)
                        logger.error(f"Execution failed with exception: {exc}")

                    # 4. 向云端提交最终执行结果
                    result_url = f"{server_url}/api/publish/agent/jobs/{job_id}/result"
                    result_data = {
                        "status": "success" if success else "failed",
                        "error": error_msg if not success else ""
                    }

                    # 使用 JSON 提交，与 progress 保持一致
                    try:
                        client.post(result_url, headers=headers, json=result_data)
                        logger.info(f"====== [Task Finished] Status: {'SUCCESS' if success else 'FAILED'} ======\n")
                    except Exception as ex:
                        logger.error(f"Failed to post result to cloud: {ex}")

                except Exception as e:
                    logger.error(f"Exception in polling loop: {e}")
                    time.sleep(10)
    finally:
        logger.info("Agent shutting down")


def await_async(coro):
    """同步环境中运行异步协程的辅助工具 - 已移至文件顶部"""
    pass  # This is now defined at the top of the file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pixelle-Video Local群控 Agent")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="云端 API 地址")
    parser.add_argument("--serial", required=True, help="匹配云端的设备标识，例如 device_A")
    parser.add_argument("--port", required=True, help="本地连接 CH9329 的串口号，例如 COM3")
    parser.add_argument("--token", default="pixelle_secure_agent_token_2026", help="安全 Token")
    parser.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒数")
    
    args = parser.parse_args()
    
    poll_and_execute(
        server_url=args.url,
        device_serial=args.serial,
        com_port=args.port,
        token=args.token,
        poll_interval=args.interval
    )
