#!/usr/bin/env python3
"""
直接调用 RunningHub 文生视频 API
使用 API Key 直接生成视频
"""

import json
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    sys.exit(1)

from pixelle_video.config import config_manager
from loguru import logger

def call_runninghub_video_api(prompt=None, aspect_ratio="9:16", duration=8, resolution="720p"):
    """
    直接调用 RunningHub 视频生成 API
    
    Args:
        prompt: 视频描述文本
        aspect_ratio: 宽高比 (9:16, 16:9, 1:1 等)
        duration: 视频时长 (秒)
        resolution: 分辨率 (720p, 1080p)
    """
    
    logger.info("=" * 80)
    logger.info("🎬 RunningHub 文生视频 API 直接调用")
    logger.info("=" * 80)
    logger.info("")
    
    # 获取 API Key
    config = config_manager.config
    api_key = config.comfyui.runninghub_api_key
    
    if not api_key:
        logger.error("❌ API Key 未配置")
        return False
    
    logger.info(f"✅ API Key: {api_key[:8]}...{api_key[-8:]}")
    logger.info("")
    
    # 使用默认提示词
    if not prompt:
        prompt = "春日午后，樱花纷飞的乡间小路，一位少女骑着老旧自行车经过稻田，微风拂过她的发梢，远处传来风铃声，画面温暖柔和，充满宁静与希望。"
    
    # API 配置
    api_url = "https://www.runninghub.cn/api/v1/rhart-video-v3.1-fast/text-to-video"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "duration": duration,
        "resolution": resolution
    }
    
    logger.info("📋 请求配置:")
    logger.info(f"   API 端点: {api_url}")
    logger.info(f"   请求方法: POST")
    logger.info("")
    
    logger.info("📝 请求参数:")
    logger.info(f"   提示词: {prompt[:70]}...")
    logger.info(f"   宽高比: {aspect_ratio}")
    logger.info(f"   时长: {duration} 秒")
    logger.info(f"   分辨率: {resolution}")
    logger.info("")
    
    logger.info("🚀 正在向 RunningHub 发送请求...")
    logger.info("")
    
    try:
        # 发送请求
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=60
        )
        
        logger.info(f"📊 HTTP 状态码: {response.status_code}")
        logger.info("")
        
        # 解析响应
        try:
            result = response.json()
        except json.JSONDecodeError:
            logger.error(f"❌ 无法解析 JSON 响应")
            logger.error(f"   响应内容: {response.text[:300]}")
            return False
        
        # 显示完整响应
        logger.info("📄 完整 API 响应:")
        logger.info("")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("")
        
        # ===== 判断结果 =====
        
        # 检查 RunningHub 的错误代码
        if result.get("code") == 412 or "INVALID" in str(result.get("msg", "")):
            logger.error("=" * 80)
            logger.error("❌ 412 TOKEN_INVALID - API Key 无效")
            logger.error("=" * 80)
            logger.error("")
            logger.error("API Key 可能:")
            logger.error("  • 过期或已被撤销")
            logger.error("  • 输入错误")
            logger.error("  • 无权限调用此 API")
            logger.error("")
            logger.error("请在 RunningHub 官网验证:")
            logger.error("  https://www.runninghub.cn")
            logger.error("")
            return False
        
        if response.status_code == 200 and (result.get("status") == "success" or result.get("code") == 200):
            logger.info("=" * 80)
            logger.info("✅ SUCCESS - API 调用成功!")
            logger.info("=" * 80)
            logger.info("")
            
            # 提取关键信息
            if "video_url" in result:
                logger.info(f"   📹 视频 URL:")
                logger.info(f"      {result['video_url']}")
            
            if "task_id" in result:
                logger.info(f"   🆔 任务 ID: {result['task_id']}")
            
            if "status" in result:
                logger.info(f"   ⚙️  状态: {result['status']}")
            
            if "duration" in result:
                logger.info(f"   ⏱️  时长: {result['duration']} 秒")
            
            logger.info("")
            logger.info("🎉 视频生成任务已提交！")
            logger.info("   请稍候片刻，视频将在 RunningHub 生成")
            
            return True
            
        elif response.status_code == 401 or "401" in str(result):
            logger.error("=" * 80)
            logger.error("❌ 401 Unauthorized - API Key 认证失败")
            logger.error("=" * 80)
            logger.error("")
            logger.error("原因可能是:")
            logger.error("  • API Key 无效或过期")
            logger.error("  • API Key 被撤销")
            logger.error("  • 请求格式不正确")
            logger.error("")
            logger.error("解决方案:")
            logger.error("  1. 登录 https://www.runninghub.cn")
            logger.error("  2. 检查 API Key 是否正确")
            logger.error("  3. 重新生成 API Key（如果过期）")
            logger.error("")
            return False
            
        elif response.status_code == 403:
            logger.error("❌ 403 Forbidden - 无权限")
            logger.error("   账户可能没有权限使用此 API")
            return False
            
        elif response.status_code == 429:
            logger.warning("⚠️  429 Too Many Requests - 请求过于频繁")
            logger.warning("   请稍后再试")
            return False
            
        elif response.status_code >= 500:
            logger.error(f"❌ {response.status_code} 服务器错误")
            logger.error("   RunningHub 服务可能暂时不可用")
            logger.error("   请稍后重试")
            return False
            
        else:
            logger.warning(f"⚠️  API 返回了预期外的状态")
            logger.warning(f"   HTTP 状态码: {response.status_code}")
            
            error_msg = result.get("message") or result.get("error") or result.get("msg")
            if error_msg:
                logger.warning(f"   错误信息: {error_msg}")
            
            return False
            
    except requests.exceptions.Timeout:
        logger.error("❌ 请求超时")
        logger.error("   • 服务器响应缓慢")
        logger.error("   • 网络延迟较大")
        logger.error("   请稍后重试")
        return False
        
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ 网络连接错误: {e}")
        logger.error("   • 检查网络连接")
        logger.error("   • 检查 API 端点是否正确")
        logger.error("   • 检查防火墙设置")
        return False
        
    except Exception as e:
        logger.error(f"❌ 发生未预期的错误: {e}")
        logger.error(f"   错误类型: {type(e).__name__}")
        
        error_str = str(e).lower()
        if "ssl" in error_str or "certificate" in error_str:
            logger.error("   → SSL 证书问题")
        elif "timeout" in error_str:
            logger.error("   → 连接超时")
        
        return False

def main():
    """主函数"""
    
    # 可以在这里自定义参数
    prompt = "春日午后，樱花纷飞的乡间小路，一位少女骑着老旧自行车经过稻田，微风拂过她的发梢，远处传来风铃声，画面温暖柔和，充满宁静与希望。"
    
    success = call_runninghub_video_api(
        prompt=prompt,
        aspect_ratio="9:16",  # 竖屏
        duration=8,           # 8秒
        resolution="720p"     # 720p
    )
    
    logger.info("")
    if success:
        logger.info("✨ 测试成功 - API 可正常使用")
        logger.info("   你现在可以在项目中集成这个 API")
    else:
        logger.info("⚠️  测试失败 - 请查看上面的错误信息")
    
    logger.info("")
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
