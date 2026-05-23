import threading
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

_ACTIVE_THREADS = {}
_THREADS_LOCK = threading.Lock()

class XHSQRLoginThread(threading.Thread):
    def __init__(self, username: str, project_root: Path):
        super().__init__()
        self.username = username
        self.project_root = project_root
        self.qr_code_base64 = None
        self.status = "initializing"  # initializing, waiting_scan, logged_in, expired, failed
        self.cookies = None
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        try:
            with sync_playwright() as p:
                # 启动无头浏览器
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                
                # 访问小红书主页
                page.goto("https://www.xiaohongshu.com", timeout=30000)
                
                # 等待二维码节点加载
                try:
                    qr_el = page.wait_for_selector("img.qrcode-img", timeout=15000)
                    self.qr_code_base64 = qr_el.get_attribute("src")
                    self.status = "waiting_scan"
                except Exception as e:
                    self.status = "failed"
                    browser.close()
                    return
                
                # 轮询登录状态 (超时 180 秒)
                start_time = time.time()
                while time.time() - start_time < 180:
                    if self.stop_event.is_set():
                        break
                    
                    # 读取 cookies
                    cookies = context.cookies()
                    cookie_dict = {
                        c["name"]: c["value"]
                        for c in cookies
                        if "xiaohongshu.com" in c["domain"]
                    }
                    
                    # 检查是否成功登录并包含关键 a1 与 web_session
                    if cookie_dict.get("a1") and cookie_dict.get("web_session"):
                        self.cookies = cookie_dict
                        self.status = "logged_in"
                        break
                    
                    time.sleep(2)
                
                if self.status != "logged_in":
                    self.status = "expired"
                
                browser.close()
        except Exception as e:
            self.status = "failed"

def get_or_create_session(username: str, project_root: Path) -> XHSQRLoginThread:
    with _THREADS_LOCK:
        # 如果已有线程在运行，且不是 logged_in，先停止它
        if username in _ACTIVE_THREADS:
            old_thread = _ACTIVE_THREADS[username]
            if old_thread.status in ["initializing", "waiting_scan"]:
                old_thread.stop_event.set()
        
        # 启动新线程
        thread = XHSQRLoginThread(username, project_root)
        _ACTIVE_THREADS[username] = thread
        thread.start()
        return thread

def get_session(username: str) -> XHSQRLoginThread | None:
    with _THREADS_LOCK:
        return _ACTIVE_THREADS.get(username)

def remove_session(username: str):
    with _THREADS_LOCK:
        if username in _ACTIVE_THREADS:
            _ACTIVE_THREADS[username].stop_event.set()
            _ACTIVE_THREADS.pop(username, None)
