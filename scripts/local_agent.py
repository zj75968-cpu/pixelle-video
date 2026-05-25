# -*- coding: utf-8 -*-
"""
Pixelle-Video Local Client Agent (本地小助手客户端)
===================================================
此脚本由使用者在插着手机的本地 Windows 电脑上运行。
它会自动获取本地连接的手机列表，定时向云端 VPS 轮询可执行的发布、删除、评论任务。

功能：
1. 智能检测本地 ADB 连接，若发现 unauthorized 设备会输出非常醒目的红牌警示和手把手操作引导。
2. 与云端 VPS 进行心跳和状态注册。
3. 从云端接收任务指令，自动下载视频/图文媒体文件。
4. 调用 XHSPublisher 驱动本地手机进行小红书的自动发布、删帖、评论。
5. 自动捕获手机当前屏幕截图，并向云端报告执行进度与结果。
"""

import os
import sys
import time
import uuid
import shutil
import urllib.parse
import subprocess
import argparse
import re
import json
from pathlib import Path

# 将根目录添加到模块搜索路径，以便在本地可以直接 import
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 尝试引入依赖，若没有则引导安装
try:
    import requests
    import yaml
except ImportError:
    print("❌ 缺少核心依赖，正在为你自动安装...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "requests", "pyyaml", "uiautomator2", "loguru"])
    import requests
    import yaml

from loguru import logger

# 引入 XHSPublisher
# 客户端无需完整的 PixelleVideoCore / comfykit / openai 等服务端依赖，
# 注入 stub 模块 → 然后通过 importlib 直接加载 xhs_publisher.py
import types as _types
import importlib.util as _ilu

# 1. stub comfykit
if "comfykit" not in sys.modules:
    _ck = _types.ModuleType("comfykit")
    _ck.ComfyKit = type("ComfyKit", (), {})
    sys.modules["comfykit"] = _ck

# 2. stub pixelle_video 包（避免 __init__.py 导入 service.py → comfykit）
_pv = _types.ModuleType("pixelle_video")
_pv.__version__ = "0.1.0-agent"
_pv.__all__ = []
_pv.__path__ = [str(_ROOT / "pixelle_video")]
_pv.__package__ = "pixelle_video"
sys.modules["pixelle_video"] = _pv

# 3. stub pixelle_video.services 包（避免 services/__init__.py 导入 llm/comfy/tts 等）
_pvs = _types.ModuleType("pixelle_video.services")
_pvs.__path__ = [str(_ROOT / "pixelle_video" / "services")]
_pvs.__package__ = "pixelle_video.services"
sys.modules["pixelle_video.services"] = _pvs
_pv.services = _pvs

# 3b. stub pixelle_video.utils 包（避免导入 user_context 等工具）
_pvu = _types.ModuleType("pixelle_video.utils")
_pvu.__path__ = [str(_ROOT / "pixelle_video" / "utils")]
_pvu.__package__ = "pixelle_video.utils"
sys.modules["pixelle_video.utils"] = _pvu
_pv.utils = _pvu

# 3c. stub pixelle_video.utils.user_context 包
_pvuc = _types.ModuleType("pixelle_video.utils.user_context")
_pvuc.get_current_username = lambda: "default"
sys.modules["pixelle_video.utils.user_context"] = _pvuc
_pvu.user_context = _pvuc

# 4. 预加载 xhs_publisher 的直接依赖子模块（config、device_manager 等）
#    这些模块体积小且不依赖 comfykit
def _load_submod(dotpath: str, filepath: Path):
    """通过文件路径加载单个子模块并注册到 sys.modules"""
    if dotpath in sys.modules:
        return sys.modules[dotpath]
    spec = _ilu.spec_from_file_location(dotpath, str(filepath))
    mod = _ilu.module_from_spec(spec)
    sys.modules[dotpath] = mod
    spec.loader.exec_module(mod)
    return mod

# config 子包
_cfg_init = _ROOT / "pixelle_video" / "config" / "__init__.py"
_cfg_schema = _ROOT / "pixelle_video" / "config" / "schema.py"
_cfg_pkg = _types.ModuleType("pixelle_video.config")
_cfg_pkg.__path__ = [str(_ROOT / "pixelle_video" / "config")]
_cfg_pkg.__package__ = "pixelle_video.config"
sys.modules["pixelle_video.config"] = _cfg_pkg
_pv.config = _cfg_pkg

# 加载 config schema，支持安全 Stub 兜底
if _cfg_schema.exists():
    _load_submod("pixelle_video.config.schema", _cfg_schema)
else:
    _cfg_sch_stub = _types.ModuleType("pixelle_video.config.schema")
    sys.modules["pixelle_video.config.schema"] = _cfg_sch_stub

# 加载 config __init__ (含 config_manager)，支持安全 Stub 兜底
if _cfg_init.exists():
    _load_submod("pixelle_video.config", _cfg_init)
else:
    _cfg_init_stub = _types.ModuleType("pixelle_video.config")
    _cfg_init_stub.config_manager = type("ConfigManager", (), {
        "config": type("Config", (), {
            "phone_agent": type("PhoneAgent", (), {"url": "", "token": "", "chunk_size_mb": 5, "timeout_push": 120})()
        })()
    })()
    sys.modules["pixelle_video.config"] = _cfg_init_stub

# device_manager
_dm_path = _ROOT / "pixelle_video" / "services" / "device_manager.py"
_load_submod("pixelle_video.services.device_manager", _dm_path)

# xhs_publisher
_xhs_path = _ROOT / "pixelle_video" / "services" / "xhs_publisher.py"
_load_submod("pixelle_video.services.xhs_publisher", _xhs_path)

from pixelle_video.services.xhs_publisher import XHSPublisher

# ── 颜色控制台 ────────────────────────────────────────────────────────────
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

if os.name == 'nt':
    os.system('color') # 开启 Windows 虚拟终端颜色支持
    # 强制 UTF-8 输出，防止 GBK 编码导致 emoji 崩溃
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def print_banner():
    print(f"{BLUE}{BOLD}")
    print("============================================================")
    print("      Pixelle-Video 手机发布助手客户端 (Phone Agent)         ")
    print("============================================================")
    print(f"{RESET}")

def ensure_adb_installed() -> str:
    """确保 adb 可用，如果系统 PATH 中没有，且内置路径也没有，则自动下载绿色精简版 adb 到 runtime/bin 目录下"""
    # 1. 尝试直接找系统 PATH 里的 adb
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path

    # 2. 尝试寻找项目内置的 adb
    project_adb = _ROOT / "packaging" / "windows" / "platform-tools" / "adb.exe"
    if project_adb.exists():
        return str(project_adb)

    # 3. 自动下载绿色精简版 adb (Windows 专享)
    bin_dir = _ROOT / "runtime" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    local_adb = bin_dir / "adb.exe"
    
    if local_adb.exists():
        return str(local_adb)

    if os.name != 'nt':
        logger.error("未找到 adb 执行程序，且非 Windows 系统无法自动下载。请先安装 adb 并加入环境变量 PATH。")
        return "adb"

    logger.warning("⚠️ 未在系统 PATH 中发现 adb，准备自动下载绿色精简版 ADB 运行环境...")
    
    files = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]
    sources = [
        "https://cdn.jsdelivr.net/gh/mzlogin/awesome-adb@master/platform-tools/",
        "https://mirror.ghproxy.com/https://raw.githubusercontent.com/mzlogin/awesome-adb/master/platform-tools/"
    ]
    
    import urllib.request
    download_ok = True
    for f in files:
        target_path = bin_dir / f
        if target_path.exists():
            continue
        
        success = False
        for base_url in sources:
            url = base_url + f
            try:
                logger.info(f"正在从下载源下载 {f} ...")
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req, timeout=15) as response, open(target_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                logger.info(f"成功下载 {f} 到 {target_path}")
                success = True
                break
            except Exception as e:
                logger.warning(f"从源 {url} 下载 {f} 失败: {e}")
                if target_path.exists():
                    try:
                        target_path.unlink()
                    except Exception:
                        pass
        if not success:
            download_ok = False
            break
            
    if download_ok:
        logger.info("🎉 绿色精简版 ADB 环境下载成功！")
        return str(local_adb)
    else:
        logger.error("❌ 自动下载 ADB 环境失败。请确认网络畅通，或者手动安装 platform-tools 并配置 PATH。")
        return "adb"


def get_wifi_devices_config() -> list[str]:
    """获取已保存的无线连接 IP 列表"""
    cfg_path = _ROOT / "runtime" / "wifi_devices.json"
    if not cfg_path.exists():
        return []
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_wifi_device(ip_port: str):
    """保存无线连接到配置文件"""
    cfg_dir = _ROOT / "runtime"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "wifi_devices.json"
    devices = get_wifi_devices_config()
    if ip_port not in devices:
        devices.append(ip_port)
        try:
            cfg_path.write_text(json.dumps(devices, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存无线配置失败: {e}")


def connect_wifi_devices(adb_exec: str):
    """尝试连接已保存的所有无线设备"""
    devices = get_wifi_devices_config()
    if not devices:
        return
    logger.info(f"正在尝试连接无线设备列表: {devices} ...")
    for dev in devices:
        try:
            res = subprocess.run([adb_exec, "connect", dev], capture_output=True, text=True, timeout=5)
            out = res.stdout.strip()
            if "connected" in out.lower():
                logger.info(f"✅ 无线设备 {dev} 连接成功!")
            else:
                logger.debug(f"无线设备 {dev} 连接反馈: {out}")
        except Exception as e:
            logger.warning(f"连接无线设备 {dev} 失败: {e}")


def auto_migrate_usb_to_wifi(adb_exec: str, serial: str):
    """【全自动迁移】若发现是通过 USB 连入的已授权设备，自动提取 IP 地址并开启 5555 无线端口"""
    return
        
    try:
        ip = ""
        # 方法 A
        res = subprocess.run([adb_exec, "-s", serial, "shell", "ip", "addr", "show", "wlan0"], capture_output=True, text=True, timeout=5)
        m = re.search(r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", res.stdout)
        if m:
            ip = m.group(1)
        
        # 方法 B
        if not ip:
            res = subprocess.run([adb_exec, "-s", serial, "shell", "ifconfig", "wlan0"], capture_output=True, text=True, timeout=5)
            m = re.search(r"inet\s+addr:?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", res.stdout)
            if m:
                ip = m.group(1)
                
        # 方法 C
        if not ip:
            res = subprocess.run([adb_exec, "-s", serial, "shell", "getprop", "dhcp.wlan0.ipaddress"], capture_output=True, text=True, timeout=5)
            ip = res.stdout.strip()
            
        if not ip or not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
            return
            
        logger.info(f"✨ 发现物理 USB 设备 {serial}，局域网 IP: {ip}。正在全自动开启无线调试授权...")
        subprocess.run([adb_exec, "-s", serial, "tcpip", "5555"], capture_output=True, text=True, timeout=8)
        
        target_dev = f"{ip}:5555"
        res_conn = subprocess.run([adb_exec, "connect", target_dev], capture_output=True, text=True, timeout=8)
        out_conn = res_conn.stdout.strip()
        
        if "connected" in out_conn.lower():
            logger.info(f"🎉 手机 {serial} 已成功转换为无线连接状态：{target_dev}！现在你可以随时拔掉 USB 数据线了！")
            save_wifi_device(target_dev)
    except Exception as e:
        logger.debug(f"USB 转换为无线连接失败: {e}")


def ensure_device_awake(adb_exec: str, serial: str):
    """检测手机屏幕状态，如果是休眠/黑屏，则自动唤醒亮屏并模拟滑动解锁"""
    try:
        res = subprocess.run([adb_exec, "-s", serial, "shell", "dumpsys", "power"], capture_output=True, text=True, timeout=5)
        out = res.stdout
        
        is_asleep = False
        if "Display Power: state=OFF" in out or "mWakefulness=Asleep" in out or "mScreenOn=false" in out:
            is_asleep = True
            
        if is_asleep:
            logger.info(f"📱 检测到手机 {serial} 屏幕处于锁定/休眠状态，正在自动唤醒亮屏...")
            subprocess.run([adb_exec, "-s", serial, "shell", "input", "keyevent", "224"], timeout=5)
            time.sleep(0.5)
            subprocess.run([adb_exec, "-s", serial, "shell", "input", "swipe", "500", "1500", "500", "500", "200"], timeout=5)
            logger.info("📱 屏幕已亮，并完成上滑解锁模拟。")
    except Exception as e:
        logger.debug(f"尝试唤醒设备屏幕失败: {e}")


def get_connected_serials(adb_exec: str) -> tuple[list[str], list[str]]:
    """扫描本地 adb 设备，返回 (已授权serial列表, 未授权serial列表)"""
    connect_wifi_devices(adb_exec)
    
    try:
        res = subprocess.run([adb_exec, "devices"], capture_output=True, text=True, timeout=15)
        lines = res.stdout.strip().splitlines()
    except Exception as e:
        logger.error(f"执行 adb devices 失败: {e}")
        return [], []

    authorized = []
    unauthorized = []
    
    for line in lines[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            serial, status = parts[0], parts[1]
            if status == "device":
                authorized.append(serial)
                ensure_device_awake(adb_exec, serial)
                auto_migrate_usb_to_wifi(adb_exec, serial)
            elif status == "unauthorized":
                unauthorized.append(serial)
    return authorized, unauthorized

def warn_unauthorized_devices(serials: list[str]):
    """针对未授权设备输出超显目的红牌警告"""
    if not serials:
        return
    print("\n" + f"{RED}{BOLD}╔" + "="*58 + "╗" + RESET)
    print(f"{RED}{BOLD}║         🚨 警告：检测到有手机已插上，但「未授权」！         ║{RESET}")
    print(f"{RED}{BOLD}╚" + "="*58 + "╝" + RESET)
    for s in serials:
        print(f" ⚠️  未授权设备：{YELLOW}{BOLD}{s}{RESET}")
    print(f"\n{BOLD}👉 解决步骤（只需30秒）：{RESET}")
    print(f" 1. 解锁这几台手机的屏幕。")
    print(f" 2. 屏幕上会看到弹窗：{GREEN}【是否允许 USB 调试？】{RESET}")
    print(f" 3. 勾选 {GREEN}【始终允许来自此计算机的调试】{RESET}，然后点击 {GREEN}【确定/允许】{RESET}。")
    print(f" 4. 如果没有弹窗，请拔掉数据线重新插一下，或者在手机「开发者选项」里点击「撤销USB调试授权」再插线。")
    print("-" * 60 + "\n")

class LocalClientAgent:
    def __init__(self, server_url: str, token: str = "default_token"):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.agent_id = f"agent_pc_{uuid.getnode()}"
        self.temp_dir = Path("runtime/agent_temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.adb_exec = ensure_adb_installed()
        
        logger.info(f"客户端代理初始化完成。服务地址: {self.server_url} | 代理ID: {self.agent_id}")

    def report_progress(self, job_id: str, message: str):
        """向云端上报任务进度日志"""
        url = f"{self.server_url}/api/publish/agent/jobs/{job_id}/progress"
        headers = {"X-Token": self.token}
        try:
            requests.post(url, json={"log": message}, headers=headers, timeout=5)
        except Exception as e:
            logger.warning(f"汇报进度失败: {e}")

    def submit_result(self, job_id: str, status: str, error: str = None, screenshot_path: str = None):
        """向云端上报最终任务执行结果，支持上传手机屏幕截图"""
        url = f"{self.server_url}/api/publish/agent/jobs/{job_id}/result"
        headers = {"X-Token": self.token}
        data = {
            "status": status,
            "error": error or ""
        }
        files = {}
        if screenshot_path and os.path.exists(screenshot_path):
            files["screenshot"] = (os.path.basename(screenshot_path), open(screenshot_path, "rb"), "image/png")
        
        try:
            res = requests.post(url, data=data, files=files, headers=headers, timeout=30)
            if res.status_code == 200:
                logger.info(f"✅ 任务 {job_id[:8]} 结果上报成功，状态: {status}")
            else:
                logger.error(f"❌ 上报结果失败，HTTP 状态码: {res.status_code}，内容: {res.text}")
        except Exception as e:
            logger.error(f"❌ 无法建立连接以提交结果: {e}")
        finally:
            if files:
                files["screenshot"][1].close()

    def download_file(self, relative_path: str) -> str:
        """从云端下载媒体文件"""
        # relative_path 类似于 output/xxx/images/1.png 或者是 视频路径
        # 需要拼装成完整的下载地址
        # 流式下载到本地临时目录
        encoded_path = urllib.parse.quote(relative_path.replace("\\", "/"))
        url = f"{self.server_url}/static/{encoded_path}"
        # 兼容 API 的 media 路由，如果 static 不通则走 media
        
        dest_path = self.temp_dir / os.path.basename(relative_path)
        logger.info(f"正在从云端下载媒体文件: {relative_path} -> {dest_path}")
        
        # 尝试下载
        for test_url in [url, f"{self.server_url}/{encoded_path}"]:
            try:
                with requests.get(test_url, stream=True, timeout=120) as r:
                    if r.status_code == 200:
                        with open(dest_path, 'wb') as f:
                            shutil.copyfileobj(r.raw, f)
                        return str(dest_path)
            except Exception as e:
                logger.debug(f"下载尝试失败 ({test_url}): {e}")
                
        raise FileNotFoundError(f"无法从云端下载文件: {relative_path}")

    def execute_job(self, job: dict):
        job_id = job["job_id"]
        serial = job["serial"]
        kind = job.get("kind", "image_text")
        title = job.get("title", "")
        body = job.get("body", "")
        hashtags = job.get("hashtags") or []
        dry_run = job.get("dry_run", False)
        
        logger.info(f"🎬 收到待执行任务：[{kind}] {title[:20]} (job_id: {job_id[:8]})")
        self.report_progress(job_id, "客户端已接收任务，准备执行本地发布自动化流程...")

        publisher = XHSPublisher(serial=serial, strict_mode=False, job_id=job_id)
        screenshot_path = None
        
        try:
            # 1. 自动根据任务 kind 处理不同命令
            if kind == "delete":
                self.report_progress(job_id, f"正在手机上执行删帖操作，删除标题：{title}...")
                success = publisher._delete_post_sync(post_title=title)
                if success:
                    self.report_progress(job_id, "✅ 手机端删除帖子成功！")
                    self.submit_result(job_id, status="deleted")
                else:
                    self.report_progress(job_id, "❌ 手机端删除帖子失败。")
                    self.submit_result(job_id, status="failed", error="UIAutomator 未能找到并删除该帖子")
                return

            if kind == "comment":
                comment_text = body  # 评论文字存在正文 body 字段里
                self.report_progress(job_id, f"正在手机上执行评论操作，评论内容：{comment_text}...")
                success = publisher._comment_on_post_sync(post_title=title, comment_text=comment_text)
                if success:
                    self.report_progress(job_id, "✅ 手机端添加评论成功！")
                    self.submit_result(job_id, status="comment_success")
                else:
                    self.report_progress(job_id, "❌ 手机端自动评论失败。")
                    self.submit_result(job_id, status="failed", error="UIAutomator 无法打开帖子或未能成功发送评论")
                return

            # 2. 正常发布逻辑（图文 / 视频）
            local_media_paths = []
            
            # 下载大文件/图片
            if kind == "video":
                video_rel = job.get("video_path")
                if not video_rel:
                    raise ValueError("视频发布任务缺少 video_path 文件配置")
                self.report_progress(job_id, "正在从云端下载生成的视频文件...")
                local_video = self.download_file(video_rel)
                local_media_paths.append(local_video)
            else:
                # 图文帖子
                images_rel = job.get("images") or []
                if not images_rel:
                    raise ValueError("图文发布任务缺少 images 图片列表")
                for idx, img_rel in enumerate(images_rel):
                    self.report_progress(job_id, f"正在下载第 {idx+1}/{len(images_rel)} 张高清插图...")
                    local_img = self.download_file(img_rel)
                    local_media_paths.append(local_img)

            # 调用手机自动化组件进行真正发布
            if kind == "video":
                self.report_progress(job_id, "正在唤醒并控制手机发布小视频...")
                # 兼容 async wrapper
                import asyncio
                success = asyncio.run(publisher.publish_video(
                    video_path=local_media_paths[0],
                    title=title,
                    body=body,
                    hashtags=hashtags,
                    dry_run=dry_run,
                    progress_callback=lambda m: self.report_progress(job_id, m)
                ))
            else:
                self.report_progress(job_id, f"正在唤醒并控制手机自动发布图文（共 {len(local_media_paths)} 张图）...")
                import asyncio
                success = asyncio.run(publisher.publish(
                    images=local_media_paths,
                    title=title,
                    body=body,
                    hashtags=hashtags,
                    progress_callback=lambda m: self.report_progress(job_id, m)
                ))

            # 截取最终的手机屏幕图像用来回传确认
            try:
                d = publisher._get_device()
                ss_file = self.temp_dir / f"final_ss_{job_id}.png"
                d.screenshot(str(ss_file))
                screenshot_path = str(ss_file)
            except Exception:
                pass

            if success:
                self.report_progress(job_id, "🎉 本地手机发帖已确认成功完成！")
                self.submit_result(job_id, status="success", screenshot_path=screenshot_path)
            else:
                self.report_progress(job_id, "⚠️ 本地手机发帖已完成，但无障碍验证未能检测到成功弹窗。")
                self.submit_result(job_id, status="success", error="Unverified success toast", screenshot_path=screenshot_path)

        except Exception as e:
            logger.exception(f"执行任务发生异常: {e}")
            self.report_progress(job_id, f"❌ 任务运行失败: {e}")
            
            # 崩溃时抓取手机状态截图
            try:
                d = publisher._get_device()
                ss_file = self.temp_dir / f"err_ss_{job_id}.png"
                d.screenshot(str(ss_file))
                screenshot_path = str(ss_file)
            except Exception:
                pass
                
            self.submit_result(job_id, status="failed", error=str(e), screenshot_path=screenshot_path)
        finally:
            # 清理本地临时下载的文件
            for f in self.temp_dir.glob("*"):
                try:
                    if f.is_file():
                        f.unlink()
                except Exception:
                    pass

    def start_loop(self):
        """核心轮询主循环"""
        logger.info("小助手进入守护轮询状态，开始监听任务队列...")
        
        while True:
            # 1. 扫描当前电脑的手机连接状态
            authorized_serials, unauthorized_serials = get_connected_serials(self.adb_exec)
            
            # 红牌警示
            warn_unauthorized_devices(unauthorized_serials)
            
            # 即使没有检测到已授权的物理手机，代理本身也应照常向云端发送心跳以报告在线状态！
            if not authorized_serials:
                logger.info("💤 未发现任何已授权的物理手机，保持客户端代理心跳在线...")
                
            # 2. 向云端发起 pending 任务拉取心跳
            serials_str = ",".join(authorized_serials)
            url = f"{self.server_url}/api/publish/agent/pending"
            headers = {"X-Token": self.token}
            params = {
                "serials": serials_str,
                "agent_id": self.agent_id
            }
            
            try:
                res = requests.get(url, params=params, headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    job = data.get("job")
                    if job:
                        # 发现任务，开始处理
                        self.execute_job(job)
                    else:
                        # 正常心跳，无任务
                        logger.debug(f"心跳正常，在线设备: {authorized_serials} | 当前无任务")
                else:
                    logger.error(f"心跳请求异常，HTTP状态码: {res.status_code}，网页返回: {res.text}")
            except Exception as e:
                logger.error(f"与云端服务通信失败 (请确认 VPS 地址是否正确/端口已放开): {e}")

            time.sleep(4) # 每 4 秒轮询一次

def main():
    print_banner()
    
    parser = argparse.ArgumentParser(description="Pixelle-Video Local Phone Agent Client")
    parser.add_argument("--server", required=True, help="云端 VPS 的 API 服务端地址，如 http://23.238.47.62:8000")
    parser.add_argument("--token", default="default", help="该使用者的认证 Token 密钥")
    args = parser.parse_args()
    
    agent = LocalClientAgent(server_url=args.server, token=args.token)
    try:
        agent.start_loop()
    except KeyboardInterrupt:
        print("\n👋 已安全关闭客户端小助手")

if __name__ == "__main__":
    main()
