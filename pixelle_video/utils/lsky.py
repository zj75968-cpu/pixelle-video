# -*- coding: utf-8 -*-
import os
import httpx
from loguru import logger
from typing import Optional

def upload_to_lsky(
    file_path: str,
    upload_url: str,
    token: str,
    album_id: Optional[int] = None
) -> Optional[str]:
    """
    上传图片至 Lsky Pro 图床，并返回其局域网直链。
    
    Args:
        file_path: 本地图片路径
        upload_url: Lsky Pro 上传接口地址 (如 http://192.168.x.x/api/v1/upload)
        token: Lsky Pro 的授权 Token (例如 'Bearer xxxxx')
        album_id: 相册 ID (可选)
        
    Returns:
        Optional[str]: 成功则返回直链 URL，失败返回 None
    """
    if not os.path.exists(file_path):
        logger.error(f"Lsky upload failed: local file {file_path} not found.")
        return None
        
    if not upload_url or not token:
        logger.error("Lsky upload failed: upload_url or token is not configured.")
        return None

    # 规范化 token 格式，如果配置中没有加 Bearer 前缀，自动补上
    token_str = token.strip()
    if not token_str.startswith("Bearer "):
        token_str = f"Bearer {token_str}"

    headers = {
        "Authorization": token_str,
        "Accept": "application/json"
    }

    data = {}
    if album_id is not None:
        data["album_id"] = str(album_id)

    file_name = os.path.basename(file_path)
    
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (file_name, f, "image/jpeg")
            }
            logger.info(f"Uploading {file_name} to Lsky Pro: {upload_url}...")
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(upload_url, headers=headers, data=data, files=files)
                
            if response.status_code != 200:
                logger.error(f"Lsky upload failed: Server returned HTTP {response.status_code}. Response: {response.text}")
                return None
                
            res_json = response.json()
            if not res_json.get("status"):
                logger.error(f"Lsky upload returned error status: {res_json.get('message', 'Unknown error')}")
                return None
                
            direct_url = res_json.get("data", {}).get("links", {}).get("url")
            if not direct_url:
                logger.error("Lsky upload success, but could not find direct url in response data.")
                return None
                
            logger.info(f"Lsky upload success. Direct URL: {direct_url}")
            return direct_url
            
    except Exception as e:
        logger.error(f"Exception during Lsky Pro upload: {e}")
        return None
