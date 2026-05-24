import sys
import asyncio
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pixelle_video.services.publish_scheduler import PublishJob
from pixelle_video.services.xhs_publisher import XHSPublisher

def create_beautiful_image(path: Path):
    """绘制一张充满现代磨砂暗光渐变美感的测试封面"""
    # 尺寸 1080x1440 (标准小红书 3:4 比例图)
    img = Image.new("RGB", (1080, 1440), color="#0f0f1a")
    draw = ImageDraw.Draw(img)
    
    # 绘制一个好看的紫色微光渐变背景
    for y in range(1440):
        # 产生由深蓝到暗紫的渐变
        r = int(26 + (y / 1440) * 40)
        g = int(26 - (y / 1440) * 10)
        b = int(46 + (y / 1440) * 30)
        draw.line([(0, y), (1080, y)], fill=(r, g, b))

    # 绘制一个带有磨砂质感和红线的高亮装饰块
    draw.rounded_rectangle([80, 80, 1000, 1360], radius=32, outline="#ff4b4b", width=4)
    
    # 绘制文字
    # 在 Windows 下通常有微软雅黑 (msyh.ttc)
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(font_path):
        font_path = r"C:\Windows\Fonts\arial.ttf" # 兜底
        
    try:
        title_font = ImageFont.truetype(font_path, 64)
        sub_font = ImageFont.truetype(font_path, 40)
    except Exception:
        title_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    draw.text((150, 200), "Pixelle Xiaohongshu", fill="#ff4b4b", font=title_font)
    draw.text((150, 300), "全自动真机发布大捷！", fill="#ffffff", font=title_font)
    
    body_text = (
        "这是一篇由 Pixelle-Video 远程控制\n"
        "并执行全自动发布的测试帖子。\n\n"
        "核心链路测试成果：\n"
        "✓ 远程公网穿透上报 \n"
        "✓ HTTP 媒体文件安全分块推送\n"
        "✓ UI 自动化 Bug 完美修复\n"
        "✓ 多账号真机物理隔离防封大捷\n\n"
        "手机屏幕正在自动执行发帖..."
    )
    draw.text((150, 480), body_text, fill="#c0c0d0", font=sub_font, spacing=15)
    draw.text((150, 1150), "#AI #自动发帖 #流量矩阵", fill="#ff7676", font=sub_font)
    
    img.save(path)

import os

async def main():
    print("[*] 正在准备小红书测试发帖资产...")
    
    test_img = Path(__file__).resolve().parent / "xhs_demo_post.png"
    create_beautiful_image(test_img)
    print(f"[+] 绝美图文封面已绘制完成: {test_img}")

    # 1. 构造发帖任务
    job = PublishJob(
        job_id="xhs_demo_job_001",
        serial="10ACBE28M70044L",
        task_id="xhs_demo_task_001",
        title="真机免插线自动挂机发布大捷！",
        body="恭喜 Pixelle 真机免插线挂机自治发帖模式测试大捷！这是一条由 VPS 远程公网穿透到真机全自动发布的测试帖子，UIAutomator 自动操作成功！",
        hashtags=["AI", "自动发帖", "流量矩阵"],
        images=[str(test_img)],
        kind="image_text"
    )

    # 2. 启动 XHSPublisher 直连控制
    publisher = XHSPublisher(serial=job.serial, job_id=job.job_id)
    print("[-] 正在通过本地 ADB 通道触发 UI 自动化控制机制...")
    print("[提示] 手机屏幕会被自动点亮并启动小红书，请观察你的手机屏幕！")
    
    def _progress_cb(m):
        print(f"  [发帖进度] {m}")

    try:
        # 强制将模式切换为本地发帖以保证这次测试直接在真机上跑通
        success = await publisher.publish(
            images=job.images,
            title=job.title,
            body=job.body,
            hashtags=job.hashtags,
            progress_callback=_progress_cb
        )
        if success:
            print("\n🎉 小红书真机自动发帖大获成功！请在手机小红书里查看你的主页！")
        else:
            print(f"\n❌ 发帖失败: {job.error}")
    except Exception as e:
        import traceback
        print(f"\n❌ 执行时抛出未捕获异常: {e}\n{traceback.format_exc()}")
        
    # 清理产生的临时图片
    if test_img.exists():
        os.remove(test_img)

if __name__ == "__main__":
    asyncio.run(main())
