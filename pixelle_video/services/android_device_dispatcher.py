import asyncio
import time
from typing import Callable, Optional
from loguru import logger
from pixelle_video.services.publish_scheduler import PublishJob

class DistributionAdapter:
    """
    发帖分发器，用于多端/云端发帖执行适配。
    """
    
    @classmethod
    def get_mode(cls) -> str:
        """获取当前系统的发帖分发模式"""
        from pixelle_video.config import config_manager
        
        # 1. 优先智能判断：如果用户配置了 phone_agent.url 且未指定为 agent_pull，则智能识别为 phone_agent 模式
        g_mode = getattr(config_manager.config, "distribution_mode", None)
        d_mode = "legacy"
        if hasattr(config_manager.config, "distribution") and config_manager.config.distribution:
            d_mode = config_manager.config.distribution.mode or "legacy"
        
        final_configured_mode = g_mode or d_mode
        if final_configured_mode != "agent_pull" and hasattr(config_manager.config, "phone_agent") and config_manager.config.phone_agent.url:
            return "phone_agent"
            
        # 2. 其次使用全局覆盖模式
        if hasattr(config_manager.config, "distribution_mode") and config_manager.config.distribution_mode:
            return config_manager.config.distribution_mode
            
        # 3. 最后看 distribution 下的 mode 设定
        return d_mode

    async def execute_job(
        self,
        job: PublishJob,
        progress_callback: Callable[[str], None]
    ) -> bool:
        """
        根据当前发帖分发模式执行任务。
        
        Args:
            job: 待执行的任务实例
            progress_callback: 进度汇报回调
            
        Returns:
            True 执行成功，False 失败
        """
        mode = self.get_mode()
        logger.info(f"Executing job {job.job_id} using mode: {mode}")
        
        if mode == "agent_pull":
            # 1. 客户端拉取模式
            progress_callback("等待客户端拉取并执行发帖 (agent_pull模式)...")
            while True:
                # 重新从内存/全局实例获取当前 job 的最新状态
                # 客户端在完成任务后，会请求 /agent/jobs/{job_id}/result 路由，更改 job.status
                if job.status in ("success", "comment_success", "deleted"):
                    progress_callback("发帖执行成功 (客户端已上报)")
                    return True
                elif job.status in ("failed", "cancelled"):
                    progress_callback(f"发帖执行失败 (客户端已上报): {job.error}")
                    return False
                await asyncio.sleep(3)
                
        elif mode == "phone_agent":
            # 2. 主动向用户的手机 Agent HTTP 代理端推送媒体并发送指令
            from pixelle_video.services.phone_agent_client import (
                push_images_to_gallery_http,
                publish_http,
                wait_for_publish,
                resolve_agent_url,
            )
            from pixelle_video.config import config_manager
            
            cfg = config_manager.config
            agent_url = resolve_agent_url(getattr(job, "serial", ""))
            token = cfg.phone_agent.token.strip()
            
            if not agent_url:
                job.error = "未配置 phone_agent.url，无法使用主动 HTTP 推送"
                logger.error(job.error)
                return False
                
            progress_callback("正在推送媒体资产至手机端...")
            files_to_push = job.images if job.kind == "image_text" else [job.video_path]
            files_to_push = [f for f in files_to_push if f]
            
            if not files_to_push:
                job.error = "发帖资产为空，跳过执行"
                return False
                
            chunk_size = cfg.phone_agent.chunk_size_mb * 1024 * 1024
            timeout_push = cfg.phone_agent.timeout_push
            
            # 使用 HTTP 接口把图片/视频推送给手机端相册
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: push_images_to_gallery_http(
                    local_paths=files_to_push,
                    agent_url=agent_url,
                    token=token,
                    push_dir=cfg.xhs_publish.push_dir,
                    chunk_size=chunk_size,
                    timeout_per_file=timeout_push,
                )
            )
            
            if not res.get("device_paths"):
                job.error = f"文件推送至手机端失败: {res.get('failed', '未知错误')}"
                progress_callback(job.error)
                return False
                
            device_media_path = res["device_paths"][0] if res["device_paths"] else ""
            progress_callback("媒体资产推送成功，正在触发手机端自动发帖...")
            
            # 调用 publish_http 发起发布
            pub_res = await loop.run_in_executor(
                None,
                lambda: publish_http(
                    title=job.title,
                    agent_url=agent_url,
                    token=token,
                    body=job.body,
                    hashtags=job.hashtags,
                    media_path=device_media_path,
                    platform="xhs",
                )
            )
            
            if not pub_res.get("ok"):
                job.error = f"触发手机端发帖错误: {pub_res.get('error', '未知错误')}"
                progress_callback(job.error)
                return False
                
            remote_task_id = pub_res["task_id"]
            progress_callback(f"手机端发帖已成功触发，开始轮询执行结果 (TaskID: {remote_task_id[:8]})...")
            
            # 轮询状态直到执行完毕
            wait_res = await loop.run_in_executor(
                None,
                lambda: wait_for_publish(
                    task_id=remote_task_id,
                    agent_url=agent_url,
                    token=token,
                    poll_interval=3.0,
                    max_wait=300.0,
                )
            )
            
            if wait_res.get("status") == "success":
                progress_callback("发帖成功 (手机端已反馈完成)！")
                return True
            else:
                job.error = wait_res.get("message", "发帖失败（手机端运行异常）")
                progress_callback(job.error)
                return False
                
        else:
            # 3. 降级为 legacy 模式（本地 PC ADB 直接调用 uiautomator2 控制手机）
            from pixelle_video.services.xhs_publisher import XHSPublisher
            publisher = XHSPublisher(serial=job.serial, job_id=job.job_id)
            
            if job.kind == "video":
                success = await publisher.publish_video(
                    video_path=job.video_path or "",
                    title=job.title,
                    body=job.body,
                    hashtags=job.hashtags,
                    dry_run=job.dry_run,
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
                
            if hasattr(publisher, "screenshots") and publisher.screenshots:
                job.screenshots = list(publisher.screenshots)
                
            return success
