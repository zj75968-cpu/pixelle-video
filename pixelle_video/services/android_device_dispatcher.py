# -*- coding: utf-8 -*-
"""
硬件设备调度器（CH9329 串口控制）
"""
import asyncio
from typing import Callable
from loguru import logger
from pixelle_video.services.publish_scheduler import PublishJob
from pixelle_video.services.xhs_publisher import XHSPublisher


class DistributionAdapter:
    """
    发帖分发器（CH9329 物理硬件串口控制）。
    """

    @classmethod
    def get_mode(cls) -> str:
        """获取当前系统的发帖分发模式"""
        return "hardware"

    async def execute_job(
        self,
        job: PublishJob,
        progress_callback: Callable[[str], None]
    ) -> bool:
        """
        使用硬件直控模式执行发帖任务。

        Args:
            job: 待执行的任务实例，其中 job.serial 应为硬件 COM 口名（例如 "COM3"）
            progress_callback: 进度汇报回调

        Returns:
            True 执行成功，False 失败
        """
        logger.info(f"Executing job {job.job_id} using hardware mode. COM port: {job.serial}")

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
