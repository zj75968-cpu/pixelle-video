"""
一次性发布脚本 —— 直接调用 XHSPublisher，不依赖 Streamlit/调度器。
用法：
    .venv\Scripts\python.exe scripts/do_publish_now.py
"""
import asyncio
import os
import sys
from pathlib import Path

# 让 pixelle_video 包可找到
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 把本项目内置的 adb 加入 PATH
_adb_dir = ROOT / "packaging" / "windows" / "platform-tools"
os.environ["PATH"] = str(_adb_dir) + os.pathsep + os.environ.get("PATH", "")

VIDEO_PATH = str(ROOT / "output" / "20260514_223451_e42b" / "final.mp4")
TITLE = "睡前十分钟整理法"
BODY = "每天睡前只需10分钟，把第二天要做的事写下来，清空大脑焦虑，睡得更香！"
HASHTAGS = ["睡眠", "效率提升"]
SERIAL = "KLXDU20611012075"   # 华为手机


async def main():
    from pixelle_video.services.xhs_publisher import XHSPublisher, XHSPublishError

    print(f"[publish] 目标设备: {SERIAL}")
    print(f"[publish] 视频: {VIDEO_PATH}")
    print(f"[publish] 标题: {TITLE}")

    publisher = XHSPublisher(serial=SERIAL, strict_mode=False)
    try:
        ok = await publisher.publish_video(
            video_path=VIDEO_PATH,
            title=TITLE,
            body=BODY,
            hashtags=HASHTAGS,
            dry_run=False,
        )
        if ok:
            print("[publish] ✅ 发布成功！")
        else:
            print("[publish] ❌ 发布返回 False（可能未完成）")
    except XHSPublishError as e:
        print(f"[publish] ❌ 发布错误: {e}")
    except Exception as e:
        import traceback
        print(f"[publish] ❌ 未知错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
