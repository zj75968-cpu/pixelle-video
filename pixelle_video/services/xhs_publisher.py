# -*- coding: utf-8 -*-
# Copyright (C) 2025 AIDC-AI
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""
Xiaohongshu (小红书) Publisher Service using CH9329 hardware and Lsky Pro.
All ADB and uiautomator2 dependencies are removed.
"""

import os
import time
import httpx
from pathlib import Path
from typing import List, Callable
from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.utils.dedup import pixel_de_duplicate
from pixelle_video.utils.lsky import upload_to_lsky
from pixelle_video.utils.ch9329 import CH9329Controller

class XHSPublishError(Exception):
    """Raised when publishing fails."""

class XHSPublisher:
    """
    Automates Xiaohongshu publishing via physical CH9329 serial interface,
    Lsky Pro image hosting, and PIL image de-duplication.
    """
    def __init__(
        self,
        serial: str,
        push_dir: str | None = None,
        strict_mode: bool | None = None,
        job_id: str | None = None
    ):
        # In hardware mode, the serial parameter represents the COM port name (e.g. "COM3")
        self.serial = serial
        self.job_id = job_id
        self.screenshots: List[str] = []
        
        # Load configurations
        self.cfg = config_manager.config.xhs_publish
        self.com_port = self.serial if self.serial else self.cfg.hardware.com_port
        self.baudrate = self.cfg.hardware.baudrate
        self.unlock_pin = self.cfg.hardware.unlock_pin
        
        logger.info(
            f"XHSPublisher (Hardware Mode) initialized: COM={self.com_port}, "
            f"Baudrate={self.baudrate}"
        )

    def _download_file(self, url: str, dest_path: str) -> bool:
        """Helper to download a remote file."""
        try:
            logger.info(f"Downloading remote file: {url} -> {dest_path}")
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    with open(dest_path, "wb") as f:
                        f.write(resp.content)
                    return True
                else:
                    logger.error(f"Download failed with HTTP {resp.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Exception downloading file: {e}")
            return False

    async def publish(
        self,
        images: List[str],
        title: str,
        body: str,
        hashtags: List[str],
        progress_callback: Callable[[str], None] = None
    ) -> bool:
        """Publish image-text post on Xiaohongshu."""
        def _log(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        if not images:
            raise XHSPublishError("Publish failed: No images provided.")

        _log(f"Starting hardware publish task for job: {self.job_id}")

        # ----------------------------------------------------
        # 步骤 1: 图像下载与 PIL 消重
        # ----------------------------------------------------
        local_temp_paths = []
        temp_dir = Path("runtime/temp_publish")
        temp_dir.mkdir(parents=True, exist_ok=True)

        for idx, img_source in enumerate(images):
            # 区分本地文件和远程 URL
            local_src = img_source
            if img_source.startswith("http://") or img_source.startswith("https://"):
                local_src = str(temp_dir / f"downloaded_{idx}.png")
                if not self._download_file(img_source, local_src):
                    raise XHSPublishError(f"Failed to download image: {img_source}")

            # PIL 像素级消重保存为 temp.jpg
            temp_jpg = str(temp_dir / f"temp_{idx}.jpg")
            _log(f"De-duplicating image: {local_src} -> {temp_jpg}")
            if not pixel_de_duplicate(local_src, temp_jpg):
                raise XHSPublishError(f"Deduplication failed for image {local_src}")
            local_temp_paths.append(temp_jpg)

        # ----------------------------------------------------
        # 步骤 2: 上传图床并获得直链
        # ----------------------------------------------------
        direct_urls = []
        lsky_url = self.cfg.lsky_pro.url
        lsky_token = self.cfg.lsky_pro.token
        lsky_album_id = self.cfg.lsky_pro.album_id

        for temp_jpg in local_temp_paths:
            _log(f"Uploading deduplicated image to Lsky Pro: {temp_jpg}...")
            direct_url = upload_to_lsky(temp_jpg, lsky_url, lsky_token, lsky_album_id)
            if not direct_url:
                raise XHSPublishError(f"Failed to upload {temp_jpg} to Lsky Pro.")
            direct_urls.append(direct_url)

        # ----------------------------------------------------
        # 步骤 3: 硬件键鼠执行
        # ----------------------------------------------------
        controller = CH9329Controller(port=self.com_port, baudrate=self.baudrate)
        if not controller.connect():
            raise XHSPublishError(f"Could not connect to CH9329 serial hardware on {self.com_port}")

        try:
            coords = self.cfg.coordinates
            
            # 1. 唤醒并解锁屏幕
            _log("Waking up screen and unlocking...")
            controller.press_win()  # Win/Home 唤醒屏幕
            time.sleep(1.0)
            controller.press_space()
            time.sleep(1.0)
            if self.unlock_pin:
                _log("Entering unlock PIN...")
                controller.write_text(self.unlock_pin)
                time.sleep(0.5)
                controller.press_enter()
                time.sleep(2.0)
            
            controller.press_home()
            time.sleep(1.5)

            # 2. 唤醒手机浏览器并下载图床直链
            _log("Opening mobile browser...")
            controller.press_win()
            time.sleep(1.0)
            controller.write_text("browser")
            time.sleep(1.0)
            controller.press_enter()
            time.sleep(3.0)  # 等待浏览器彻底打开

            for d_url in direct_urls:
                _log(f"Accessing image URL: {d_url}")
                # 点击浏览器地址栏
                controller.click(coords.browser_address_bar_x, coords.browser_address_bar_y)
                time.sleep(0.5)
                
                # 清理原有 URL (发送多次退格键)
                controller.press_backspace(50)
                time.sleep(0.5)
                
                # 输入图床直链
                controller.write_text(d_url)
                time.sleep(0.5)
                controller.press_enter()
                time.sleep(4.0)  # 等待加载

                # 长按保存图片至相册
                _log("Long pressing image to save...")
                controller.long_press(coords.browser_image_x, coords.browser_image_y, duration=2.5)
                time.sleep(1.0)
                
                # 点击“保存图片”菜单项
                controller.click(coords.browser_save_btn_x, coords.browser_save_btn_y)
                time.sleep(2.0)

            # 3. 打开小红书并发布
            _log("Navigating to Xiaohongshu...")
            controller.press_home()
            time.sleep(1.5)
            
            # 可以通过搜索或点击图标打开
            controller.press_win()
            time.sleep(1.0)
            controller.write_text("xhs")
            time.sleep(1.0)
            controller.press_enter()
            time.sleep(6.0)  # 等待小红书启动

            # 点击加号发布
            _log("Tapping create '+' button...")
            controller.click(coords.xhs_add_btn_x, coords.xhs_add_btn_y)
            time.sleep(3.0)

            # 选中最近一张图片 (即刚刚下载到本地的第一张)
            _log("Selecting the newly downloaded image...")
            controller.click(coords.xhs_first_album_x, coords.xhs_first_album_y)
            time.sleep(1.5)

            # 点击下一步
            _log("Confirming selection (Next)...")
            controller.click(coords.xhs_next_btn_x, coords.xhs_next_btn_y)
            time.sleep(2.0)
            
            # 再点一次下一步（若有编辑步骤）
            controller.click(coords.xhs_next_btn_x, coords.xhs_next_btn_y)
            time.sleep(2.5)

            # 输入标题
            _log("Entering title and description...")
            # 小红书标题坐标，通常可以通过稍微靠上的预留区域定位点击
            title_y = 0.35
            controller.click(0.3, title_y)
            time.sleep(0.8)
            controller.write_text(title)
            time.sleep(1.0)

            # 输入正文和 Hashtags
            body_y = 0.45
            controller.click(0.3, body_y)
            time.sleep(0.8)
            full_body = body
            if hashtags:
                full_body += "\n" + " ".join([f"#{t}" for t in hashtags])
            controller.write_text(full_body)
            time.sleep(1.5)

            # 点击发布
            _log("Tapping final publish button...")
            controller.click(coords.xhs_publish_btn_x, coords.xhs_publish_btn_y)
            time.sleep(6.0)  # 等待上传完成
            
            _log("Publish task completed successfully!")
            return True

        except Exception as e:
            _log(f"Publish execution error: {e}")
            return False
        finally:
            controller.disconnect()
            # 清理临时消重文件
            for temp_jpg in local_temp_paths:
                try:
                    os.remove(temp_jpg)
                except Exception:
                    pass

    async def publish_video(
        self,
        video_path: str,
        title: str,
        body: str,
        hashtags: List[str],
        dry_run: bool = False,
        progress_callback: Callable[[str], None] = None
    ) -> bool:
        """Publish video post on Xiaohongshu (by uploading video to image host)."""
        def _log(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        if not video_path:
            raise XHSPublishError("Publish failed: No video path provided.")

        _log(f"Starting hardware video publish task for job: {self.job_id}")

        temp_dir = Path("runtime/temp_publish")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 视频不做 PIL 像素级消重，如果是远程视频先下载
        local_src = video_path
        if video_path.startswith("http://") or video_path.startswith("https://"):
            local_src = str(temp_dir / f"downloaded_video.mp4")
            if not self._download_file(video_path, local_src):
                raise XHSPublishError(f"Failed to download video: {video_path}")

        # 上传到图床
        lsky_url = self.cfg.lsky_pro.url
        lsky_token = self.cfg.lsky_pro.token
        lsky_album_id = self.cfg.lsky_pro.album_id

        _log(f"Uploading video file to Lsky Pro: {local_src}...")
        direct_url = upload_to_lsky(local_src, lsky_url, lsky_token, lsky_album_id)
        if not direct_url:
            raise XHSPublishError("Failed to upload video to Lsky Pro.")

        # 硬件操作序列与图片类似，通过浏览器长按下载该视频，然后小红书发布
        controller = CH9329Controller(port=self.com_port, baudrate=self.baudrate)
        if not controller.connect():
            raise XHSPublishError(f"Could not connect to CH9329 serial hardware on {self.com_port}")

        try:
            coords = self.cfg.coordinates
            
            # 1. 唤醒并解锁
            _log("Waking up screen...")
            controller.press_win()
            time.sleep(1.0)
            controller.press_space()
            time.sleep(1.0)
            if self.unlock_pin:
                controller.write_text(self.unlock_pin)
                time.sleep(0.5)
                controller.press_enter()
                time.sleep(2.0)
            controller.press_home()
            time.sleep(1.5)

            # 2. 唤醒浏览器输入直链
            _log("Opening browser...")
            controller.press_win()
            time.sleep(1.0)
            controller.write_text("browser")
            time.sleep(1.0)
            controller.press_enter()
            time.sleep(3.0)

            # 点击地址栏，打字并进入
            controller.click(coords.browser_address_bar_x, coords.browser_address_bar_y)
            time.sleep(0.5)
            controller.press_backspace(50)
            time.sleep(0.5)
            controller.write_text(direct_url)
            time.sleep(0.5)
            controller.press_enter()
            time.sleep(5.0)  # 等待视频加载

            # 长按下载视频
            _log("Long pressing video to download...")
            controller.long_press(coords.browser_image_x, coords.browser_image_y, duration=2.5)
            time.sleep(1.0)
            controller.click(coords.browser_save_btn_x, coords.browser_save_btn_y)
            time.sleep(3.0)

            # 3. 唤醒小红书发布
            _log("Opening Xiaohongshu...")
            controller.press_home()
            time.sleep(1.5)
            controller.press_win()
            time.sleep(1.0)
            controller.write_text("xhs")
            time.sleep(1.0)
            controller.press_enter()
            time.sleep(6.0)

            # 点击加号发布
            _log("Tapping create '+' button...")
            controller.click(coords.xhs_add_btn_x, coords.xhs_add_btn_y)
            time.sleep(3.0)

            # 选中最近相册格子的视频 (最新下载的那个)
            _log("Selecting the downloaded video...")
            controller.click(coords.xhs_first_album_x, coords.xhs_first_album_y)
            time.sleep(1.5)

            # 点击下一步
            _log("Confirming selection...")
            controller.click(coords.xhs_next_btn_x, coords.xhs_next_btn_y)
            time.sleep(2.5)
            
            # 若有长视频剪切页再点击一次下一步
            controller.click(coords.xhs_next_btn_x, coords.xhs_next_btn_y)
            time.sleep(2.5)

            # 输入文案
            _log("Entering metadata...")
            # 标题和正文输入
            controller.click(0.3, 0.35)
            time.sleep(0.8)
            controller.write_text(title)
            time.sleep(1.0)

            controller.click(0.3, 0.45)
            time.sleep(0.8)
            full_body = body
            if hashtags:
                full_body += "\n" + " ".join([f"#{t}" for t in hashtags])
            controller.write_text(full_body)
            time.sleep(1.5)

            # 点击发布
            _log("Tapping final publish button...")
            controller.click(coords.xhs_publish_btn_x, coords.xhs_publish_btn_y)
            time.sleep(8.0)  # 视频上传可能稍长，等待 8s
            
            _log("Video publish task completed successfully!")
            return True

        except Exception as e:
            _log(f"Video publish execution error: {e}")
            return False
        finally:
            controller.disconnect()
            # 如果是临时下载的视频则清理
            if video_path.startswith("http://") or video_path.startswith("https://"):
                try:
                    os.remove(local_src)
                except Exception:
                    pass

    async def delete_post(self, post_title: str) -> bool:
        """Hardware mode does not support deleting posts."""
        logger.warning("delete_post is not supported in CH9329 hardware control mode.")
        return False

    async def comment_on_post(self, post_title: str, comment_text: str) -> bool:
        """Hardware mode does not support automatic comments."""
        logger.warning("comment_on_post is not supported in CH9329 hardware control mode.")
        return False
