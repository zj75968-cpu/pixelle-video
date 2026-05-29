# -*- coding: utf-8 -*-
"""
硬件设备调度器（支持直接控制与 Agent 客户端拉取模式）
"""
import asyncio
from typing import Callable
from loguru import logger
from pixelle_video.services.publish_scheduler import PublishJob
from pixelle_video.services.xhs_publisher import XHSPublisher

class DistributionAdapter:
    """
    发帖分发器。
    支持：
    1. 'hardware' (直接串口控制 CH9329，云端即控制端)
    2. 'agent_pull' (云端挂起，等待本地电脑的多个 Agent 客户端拉取并执行)
    """

    @classmethod
    def get_mode(cls) -> str:
        """获取当前系统的发帖分发模式"""
        from pixelle_video.config import config_manager
        try:
            # 1. 优先读取全局覆盖
            override = getattr(config_manager.config, "distribution_mode", None)
            if override:
                return override
            # 2. 其次读取分发配置
            if hasattr(config_manager.config, "distribution") and config_manager.config.distribution:
                return config_manager.config.distribution.mode or "hardware"
        except Exception:
            pass
        return "hardware"

    async def execute_job(
        self,
        job: PublishJob,
        progress_callback: Callable[[str], None]
    ) -> bool:
        """
        根据分发模式执行任务。
        """
        mode = self.get_mode()
        logger.info(f"Executing job {job.job_id} using mode: {mode}")

        if mode == "agent_pull":
            # 1. 方案 B：等待本地 Agent 拉取（事件驱动，无轮询）
            progress_callback("等待本地 Agent 客户端拉取并执行任务 (agent_pull模式)...")

            # 使用事件驱动等待，而不是轮询
            from pixelle_video.services.publish_scheduler import publish_scheduler
            timeout_seconds = 600  # 10 minutes timeout
            start_time = asyncio.get_event_loop().time()

            # 等待作业状态变化（通过定期检查，但间隔更长）
            check_interval = 10  # 增加到 10 秒，因为 agent 会主动更新状态
            last_log_time = start_time

            while True:
                # 重新从 scheduler 获取最新状态
                fresh_job = publish_scheduler.get_job(job.job_id)
                if not fresh_job:
                    progress_callback("任务已被删除")
                    return False

                # 检查最新状态
                if fresh_job.status in ("success", "comment_success"):
                    progress_callback("发帖执行成功 (本地 Agent 已完成并上报)")
                    return True
                elif fresh_job.status == "deleted":
                    progress_callback("任务已被删除")
                    return False
                elif fresh_job.status in ("failed", "cancelled"):
                    progress_callback(f"发帖执行失败 (本地 Agent 上报错误): {fresh_job.error}")
                    return False

                # 超时检查
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout_seconds:
                    progress_callback(f"等待 Agent 超时 ({timeout_seconds}s)，任务失败")
                    return False

                # 定期日志
                if asyncio.get_event_loop().time() - last_log_time > 30:
                    progress_callback(f"等待 Agent 执行中... (已等待 {int(elapsed)}s)")
                    last_log_time = asyncio.get_event_loop().time()
                    logger.info(f"Job {job.job_id} waiting for agent, elapsed: {int(elapsed)}s, status: {fresh_job.status}")

                # 使用更长的间隔，因为 agent 会主动更新状态
                await asyncio.sleep(check_interval)

        else:
            # 2. 方案 A/本地单机：云端直接通过 COM 串口操作 CH9329
            logger.info(f"Direct hardware publish on COM port: {job.serial}")
            publisher = XHSPublisher(serial=job.serial, job_id=job.job_id)

            if job.kind == "video":
                success = await publisher.publish_video(
                    video_path=job.video_path or "",
                    title=job.title,
                    body=job.body,
                    hashtags=job.hashtags,
                    progress_callback=progress_callback,
                )
            else:
                success = await publisher.publish(
                    images=job.images,
                    title=job.title,
                    body=job.body,
                    hashtags=job.hashtags,
                    progress_callback=progress_callback,
                )

            return success
