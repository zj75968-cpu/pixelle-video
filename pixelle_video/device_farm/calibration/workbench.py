# -*- coding: utf-8 -*-
"""
Calibration Workbench API/Service for interactive device calibration.

Provides orchestration for:
- Loading devices by phone_id
- Capturing screenshots via ADB
- Accepting click coordinates on screenshots
- Saving semantic points with name and description
- Testing points immediately via CH9329
- Capturing after-click screenshots for verification
- Comparing before/after screenshots (basic change detection)
"""

import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from loguru import logger

from pixelle_video.device_farm.registry.device_registry import DeviceRegistry, Device
from pixelle_video.device_farm.hardware.adb_observer import capture_screenshot, check_device_connectivity, ADBError
from pixelle_video.utils.ch9329 import CH9329Controller


class CalibrationError(Exception):
    """Base exception for calibration-related errors."""
    pass


@dataclass
class SemanticPoint:
    """Represents a calibrated semantic point on the device screen."""
    name: str
    x: int  # Pixel coordinates
    y: int
    x_ratio: float  # Normalized ratio (0.0-1.0)
    y_ratio: float
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_tested: Optional[str] = None
    test_success: Optional[bool] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SemanticPoint':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CalibrationProfile:
    """Calibration profile containing semantic points for a device."""
    phone_id: str
    profile_name: str
    screen_width: int
    screen_height: int
    points: Dict[str, SemanticPoint] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_point(self, point: SemanticPoint) -> None:
        """Add or update a semantic point."""
        self.points[point.name] = point
        self.last_modified = datetime.now().isoformat()

    def get_point(self, name: str) -> Optional[SemanticPoint]:
        """Get a semantic point by name."""
        return self.points.get(name)

    def remove_point(self, name: str) -> bool:
        """Remove a semantic point by name."""
        if name in self.points:
            del self.points[name]
            self.last_modified = datetime.now().isoformat()
            return True
        return False

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['points'] = {name: point.to_dict() for name, point in self.points.items()}
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'CalibrationProfile':
        """Create from dictionary."""
        data = data.copy()
        points_data = data.pop('points', {})
        profile = cls(**data)
        profile.points = {name: SemanticPoint.from_dict(point_data)
                         for name, point_data in points_data.items()}
        return profile


@dataclass
class CalibrationSession:
    """Active calibration session state."""
    phone_id: str
    device: Device
    profile: CalibrationProfile
    ch9329: CH9329Controller
    screenshots_dir: Path
    current_screenshot: Optional[bytes] = None
    current_screenshot_path: Optional[str] = None
    last_action_screenshot: Optional[bytes] = None
    last_action_screenshot_path: Optional[str] = None
    session_start: str = field(default_factory=lambda: datetime.now().isoformat())


class CalibrationWorkbench:
    """
    Orchestration service for interactive device calibration.

    Manages calibration sessions, coordinates between device registry,
    ADB observer, CH9329 controller, and profile persistence.
    """

    def __init__(
        self,
        device_registry: Optional[DeviceRegistry] = None,
        profiles_dir: Optional[str] = None,
        screenshots_dir: Optional[str] = None
    ):
        """
        Initialize calibration workbench.

        Args:
            device_registry: Device registry instance (creates default if None)
            profiles_dir: Directory for calibration profiles (default: config/calibration_profiles)
            screenshots_dir: Directory for calibration screenshots (default: runtime/calibration_screenshots)
        """
        self.device_registry = device_registry or DeviceRegistry()

        # Set up profiles directory
        if profiles_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            profiles_dir = project_root / "config" / "calibration_profiles"
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Set up screenshots directory
        if screenshots_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            screenshots_dir = project_root / "runtime" / "calibration_screenshots"
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Active sessions
        self._sessions: Dict[str, CalibrationSession] = {}

        logger.info(f"CalibrationWorkbench initialized: profiles={self.profiles_dir}, screenshots={self.screenshots_dir}")

    def start_calibration(self, phone_id: str, profile_name: Optional[str] = None) -> CalibrationSession:
        """
        Start a calibration session for a device.

        Args:
            phone_id: Device identifier
            profile_name: Optional profile name (defaults to phone_id)

        Returns:
            CalibrationSession object

        Raises:
            CalibrationError: If device not found or not ready
        """
        # Load device from registry
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise CalibrationError(f"Device not found: {phone_id}")

        # Check ADB connectivity
        if not check_device_connectivity(device.adb_serial):
            raise CalibrationError(f"Device not connected or not ready: {phone_id} (serial: {device.adb_serial})")

        # Initialize CH9329 controller
        ch9329 = CH9329Controller(port=device.ch9329_port)
        ch9329.screen_width = device.screen['width']
        ch9329.screen_height = device.screen['height']

        if not ch9329.connect():
            raise CalibrationError(f"Failed to connect to CH9329 on port {device.ch9329_port}")

        # Load or create calibration profile
        if profile_name is None:
            profile_name = phone_id

        profile = self._load_profile(phone_id, profile_name)
        if profile is None:
            profile = CalibrationProfile(
                phone_id=phone_id,
                profile_name=profile_name,
                screen_width=device.screen['width'],
                screen_height=device.screen['height']
            )
            logger.info(f"Created new calibration profile: {profile_name}")
        else:
            logger.info(f"Loaded existing calibration profile: {profile_name}")

        # Create session-specific screenshots directory
        session_screenshots_dir = self.screenshots_dir / phone_id / datetime.now().strftime("%Y%m%d_%H%M%S")
        session_screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Create session
        session = CalibrationSession(
            phone_id=phone_id,
            device=device,
            profile=profile,
            ch9329=ch9329,
            screenshots_dir=session_screenshots_dir
        )

        self._sessions[phone_id] = session
        logger.info(f"Started calibration session for {phone_id}")

        return session

    def stop_calibration(self, phone_id: str, save_profile: bool = True) -> None:
        """
        Stop a calibration session.

        Args:
            phone_id: Device identifier
            save_profile: Whether to save the profile before stopping

        Raises:
            CalibrationError: If no active session found
        """
        session = self._get_session(phone_id)

        if save_profile:
            self._save_profile(session.profile)

        # Disconnect CH9329
        session.ch9329.disconnect()

        # Remove session
        del self._sessions[phone_id]
        logger.info(f"Stopped calibration session for {phone_id}")

    def capture_screen(self, phone_id: str) -> Tuple[bytes, str]:
        """
        Capture current screenshot from device.

        Args:
            phone_id: Device identifier

        Returns:
            Tuple of (image_data, screenshot_path)

        Raises:
            CalibrationError: If capture fails
        """
        session = self._get_session(phone_id)

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            screenshot_path = session.screenshots_dir / f"screen_{timestamp}.png"

            img_data = capture_screenshot(session.device.adb_serial, str(screenshot_path))

            session.current_screenshot = img_data
            session.current_screenshot_path = str(screenshot_path)

            logger.info(f"Captured screenshot for {phone_id}: {screenshot_path}")
            return img_data, str(screenshot_path)

        except ADBError as e:
            raise CalibrationError(f"Failed to capture screenshot: {e}")

    def save_point(
        self,
        phone_id: str,
        name: str,
        x: int,
        y: int,
        description: str = ""
    ) -> SemanticPoint:
        """
        Save a semantic point with name and description.

        Args:
            phone_id: Device identifier
            name: Semantic name for the point (e.g., "home_button", "search_icon")
            x: X coordinate in pixels
            y: Y coordinate in pixels
            description: Optional description of the point

        Returns:
            SemanticPoint object

        Raises:
            CalibrationError: If coordinates are invalid
        """
        session = self._get_session(phone_id)

        # Validate coordinates
        if x < 0 or x >= session.profile.screen_width:
            raise CalibrationError(f"Invalid x coordinate: {x} (screen width: {session.profile.screen_width})")
        if y < 0 or y >= session.profile.screen_height:
            raise CalibrationError(f"Invalid y coordinate: {y} (screen height: {session.profile.screen_height})")

        # Calculate normalized ratios
        x_ratio = x / session.profile.screen_width
        y_ratio = y / session.profile.screen_height

        # Create semantic point
        point = SemanticPoint(
            name=name,
            x=x,
            y=y,
            x_ratio=x_ratio,
            y_ratio=y_ratio,
            description=description
        )

        # Add to profile
        session.profile.add_point(point)
        logger.info(f"Saved point '{name}' at ({x}, {y}) -> ratio ({x_ratio:.4f}, {y_ratio:.4f})")

        return point

    def test_point(self, phone_id: str, name: str, capture_after: bool = True) -> Dict:
        """
        Test a semantic point by clicking it via CH9329.

        Args:
            phone_id: Device identifier
            name: Name of the point to test
            capture_after: Whether to capture screenshot after clicking

        Returns:
            Dict with test results including success status and screenshot paths

        Raises:
            CalibrationError: If point not found or test fails
        """
        session = self._get_session(phone_id)

        # Get point from profile
        point = session.profile.get_point(name)
        if point is None:
            raise CalibrationError(f"Point not found: {name}")

        logger.info(f"Testing point '{name}' at ratio ({point.x_ratio:.4f}, {point.y_ratio:.4f})")

        # Capture before screenshot
        before_path = None
        if session.current_screenshot is None:
            _, before_path = self.capture_screen(phone_id)
        else:
            before_path = session.current_screenshot_path

        # Click the point via CH9329
        try:
            success = session.ch9329.click(point.x_ratio, point.y_ratio)

            # Update point test status
            point.last_tested = datetime.now().isoformat()
            point.test_success = success

            if not success:
                logger.warning(f"CH9329 click failed for point '{name}'")
                return {
                    'success': False,
                    'point': point.to_dict(),
                    'before_screenshot': before_path,
                    'after_screenshot': None,
                    'error': 'CH9329 click command failed'
                }

            logger.info(f"Successfully clicked point '{name}'")

        except Exception as e:
            logger.error(f"Error testing point '{name}': {e}")
            point.test_success = False
            raise CalibrationError(f"Failed to test point '{name}': {e}")

        # Capture after screenshot
        after_screenshot = None
        after_path = None
        if capture_after:
            time.sleep(0.5)  # Wait for UI to update
            try:
                after_screenshot, after_path = self.capture_screen(phone_id)
                session.last_action_screenshot = after_screenshot
                session.last_action_screenshot_path = after_path
            except CalibrationError as e:
                logger.warning(f"Failed to capture after-click screenshot: {e}")

        return {
            'success': True,
            'point': point.to_dict(),
            'before_screenshot': before_path,
            'after_screenshot': after_path,
            'timestamp': datetime.now().isoformat()
        }

    def compare_screenshots(
        self,
        phone_id: str,
        before_path: Optional[str] = None,
        after_path: Optional[str] = None
    ) -> Dict:
        """
        Compare before/after screenshots for basic change detection.

        Args:
            phone_id: Device identifier
            before_path: Path to before screenshot (uses session current if None)
            after_path: Path to after screenshot (uses session last_action if None)

        Returns:
            Dict with comparison results including change percentage

        Raises:
            CalibrationError: If screenshots not available or comparison fails
        """
        session = self._get_session(phone_id)

        # Determine screenshot paths
        if before_path is None:
            before_path = session.current_screenshot_path
        if after_path is None:
            after_path = session.last_action_screenshot_path

        if before_path is None or after_path is None:
            raise CalibrationError("Both before and after screenshots are required for comparison")

        try:
            # Read screenshots
            before_data = Path(before_path).read_bytes()
            after_data = Path(after_path).read_bytes()

            # Basic comparison: check if files are identical
            identical = before_data == after_data

            # Calculate simple change metric (byte-level difference)
            if identical:
                change_percentage = 0.0
            else:
                # Count differing bytes
                min_len = min(len(before_data), len(after_data))
                diff_count = sum(1 for i in range(min_len) if before_data[i] != after_data[i])
                diff_count += abs(len(before_data) - len(after_data))
                change_percentage = (diff_count / max(len(before_data), len(after_data))) * 100

            result = {
                'identical': identical,
                'change_percentage': round(change_percentage, 2),
                'before_screenshot': before_path,
                'after_screenshot': after_path,
                'before_size': len(before_data),
                'after_size': len(after_data)
            }

            logger.info(f"Screenshot comparison: {change_percentage:.2f}% change")
            return result

        except Exception as e:
            raise CalibrationError(f"Failed to compare screenshots: {e}")

    def get_profile(self, phone_id: str) -> CalibrationProfile:
        """
        Get the calibration profile for an active session.

        Args:
            phone_id: Device identifier

        Returns:
            CalibrationProfile object

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        return session.profile

    def list_points(self, phone_id: str) -> List[Dict]:
        """
        List all semantic points in the current profile.

        Args:
            phone_id: Device identifier

        Returns:
            List of point dictionaries

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        return [point.to_dict() for point in session.profile.points.values()]

    def remove_point(self, phone_id: str, name: str) -> bool:
        """
        Remove a semantic point from the profile.

        Args:
            phone_id: Device identifier
            name: Name of the point to remove

        Returns:
            True if removed, False if not found

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        removed = session.profile.remove_point(name)
        if removed:
            logger.info(f"Removed point '{name}' from profile")
        return removed

    def quick_pick_coordinates(self, phone_id: str, auto_screenshot: bool = True) -> Optional[Tuple[int, int, float, float]]:
        """
        快速坐标拾取 - 截图后点击图片获取坐标

        Args:
            phone_id: 设备ID
            auto_screenshot: 是否自动截图（False则使用当前截图）

        Returns:
            (x, y, x_ratio, y_ratio) 或 None
        """
        session = self._get_session(phone_id)

        # 截图
        if auto_screenshot or session.current_screenshot is None:
            try:
                self.capture_screen(phone_id)
            except CalibrationError as e:
                logger.error(f"截图失败: {e}")
                return None

        if session.current_screenshot_path is None:
            logger.error("没有可用的截图")
            return None

        # 显示图片选择器
        try:
            result = self._show_coordinate_picker(
                session.current_screenshot_path,
                session.profile.screen_width,
                session.profile.screen_height
            )

            return result

        except ImportError:
            logger.error("需要安装 tkinter 和 Pillow")
            return None
        except Exception as e:
            logger.error(f"坐标拾取失败: {e}")
            return None

    def _show_coordinate_picker(self, image_path: str, screen_width: int, screen_height: int) -> Optional[Tuple[int, int, float, float]]:
        """显示坐标拾取窗口"""
        import tkinter as tk
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.title("快速坐标拾取")

        # 加载图片
        img = Image.open(image_path)

        # 计算缩放
        max_height = 900
        img_w, img_h = img.size
        if img_h > max_height:
            scale = max_height / img_h
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            scale = 1.0

        tk_img = ImageTk.PhotoImage(img)

        result = {'coords': None}

        canvas = tk.Canvas(root, width=img.width, height=img.height, bg='black')
        canvas.pack()
        canvas.create_image(0, 0, anchor='nw', image=tk_img)

        coord_label = tk.Label(root, text="请点击图片上的目标位置",
                              font=("Consolas", 12), bg='#2D2D2D', fg='#00FF66', padx=10, pady=5)
        coord_label.pack(fill='x')

        crosshair_h = None
        crosshair_v = None

        def on_mouse_move(event):
            nonlocal crosshair_h, crosshair_v
            if crosshair_h:
                canvas.delete(crosshair_h)
            if crosshair_v:
                canvas.delete(crosshair_v)

            crosshair_h = canvas.create_line(0, event.y, img.width, event.y, fill='#FF4B4B', width=1, dash=(4, 4))
            crosshair_v = canvas.create_line(event.x, 0, event.x, img.height, fill='#FF4B4B', width=1, dash=(4, 4))

            actual_x = int(event.x / scale)
            actual_y = int(event.y / scale)
            x_ratio = actual_x / screen_width
            y_ratio = actual_y / screen_height

            coord_label.config(text=f"鼠标位置: ({actual_x}, {actual_y}) | 比例: ({x_ratio:.4f}, {y_ratio:.4f})")

        def on_click(event):
            actual_x = int(event.x / scale)
            actual_y = int(event.y / scale)
            x_ratio = actual_x / screen_width
            y_ratio = actual_y / screen_height

            r = 8
            canvas.create_oval(event.x - r, event.y - r, event.x + r, event.y + r, outline='#00FF66', width=3)
            canvas.create_oval(event.x - 2, event.y - 2, event.x + 2, event.y + 2, fill='#FF4B4B', outline='#FF4B4B')

            coord_label.config(text=f"✓ 已选择: ({actual_x}, {actual_y}) | 比例: ({x_ratio:.4f}, {y_ratio:.4f})", fg='#00FF66')

            result['coords'] = (actual_x, actual_y, x_ratio, y_ratio)
            root.after(500, root.destroy)

        canvas.bind('<Motion>', on_mouse_move)
        canvas.bind('<Button-1>', on_click)
        root.bind('<Escape>', lambda e: root.destroy())

        root.mainloop()

        return result['coords']

    def interactive_debug_console(self, phone_id: str) -> None:
        """
        启动交互式CH9329调试控制台

        Args:
            phone_id: 设备ID
        """
        session = self._get_session(phone_id)

        print("\n" + "=" * 70)
        print("  🎮 CH9329 调试控制台")
        print(f"  设备: {phone_id}")
        print(f"  屏幕: {session.profile.screen_width}x{session.profile.screen_height}")
        print("=" * 70)

        self._print_console_help()

        while True:
            try:
                cmd = input("\n[CH9329]> ").strip()

                if not cmd:
                    continue

                if cmd in ['exit', 'quit', 'q']:
                    break
                elif cmd in ['help', 'h', '?']:
                    self._print_console_help()
                elif cmd.startswith(('click ', 'c ', 'clickr ', 'cr ')):
                    self._console_click(session, cmd)
                elif cmd.startswith(('swipe ', 's ', 'swiper ', 'sr ')):
                    self._console_swipe(session, cmd)
                elif cmd.startswith('type ') or cmd.startswith('t '):
                    self._console_type(session, cmd)
                elif cmd == 'home':
                    session.ch9329.swipe_up_to_home()
                    print("✓ 已返回桌面")
                elif cmd == 'back':
                    session.ch9329._send_keyboard(0x00, 0x29)
                    print("✓ 返回键已发送")
                elif cmd == 'enter':
                    session.ch9329.press_enter()
                    print("✓ 回车键已发送")
                elif cmd.startswith('backspace'):
                    parts = cmd.split()
                    times = int(parts[1]) if len(parts) > 1 else 1
                    session.ch9329.press_backspace(times)
                    print(f"✓ 退格键已发送 {times} 次")
                elif cmd in ['screenshot', 'ss']:
                    self.capture_screen(phone_id)
                    print(f"✓ 截图已保存: {session.current_screenshot_path}")
                elif cmd == 'pick':
                    coords = self.quick_pick_coordinates(phone_id, auto_screenshot=False)
                    if coords:
                        print(f"✓ 坐标: ({coords[0]}, {coords[1]}) | 比例: ({coords[2]:.4f}, {coords[3]:.4f})")
                elif cmd == 'list':
                    self._console_list_points(session)
                elif cmd.startswith('test '):
                    point_name = cmd.split(maxsplit=1)[1]
                    self.test_point(phone_id, point_name)
                else:
                    print(f"❌ 未知命令: {cmd}")

            except KeyboardInterrupt:
                print("\n使用 'exit' 退出")
            except Exception as e:
                logger.error(f"命令执行错误: {e}")

    def _print_console_help(self):
        """打印控制台帮助"""
        print("""
📖 命令列表:
  click/c <x> <y>        点击像素坐标
  clickr/cr <x> <y>      点击比例坐标 (0.0-1.0)
  swipe/s <x1> <y1> <x2> <y2>  像素坐标滑动
  swiper/sr <x1> <y1> <x2> <y2>  比例坐标滑动
  type/t <text>          输入文本
  home                   返回桌面
  back                   返回键
  enter                  回车键
  backspace [n]          退格键
  screenshot/ss          截图
  pick                   快速拾取坐标
  list                   列出已保存的坐标点
  test <name>            测试指定坐标点
  help/h/?               显示帮助
  exit/quit/q            退出
""")

    def _console_click(self, session: CalibrationSession, cmd: str):
        """控制台点击命令"""
        parts = cmd.split()
        if len(parts) < 3:
            print("❌ 用法: click <x> <y> 或 clickr <x_ratio> <y_ratio>")
            return

        mode = parts[0].lower()
        x, y = float(parts[1]), float(parts[2])

        if mode in ['clickr', 'cr']:
            x_ratio, y_ratio = x, y
            x_px = int(x_ratio * session.profile.screen_width)
            y_px = int(y_ratio * session.profile.screen_height)
            print(f"🎯 点击比例: ({x_ratio:.4f}, {y_ratio:.4f}) -> 像素: ({x_px}, {y_px})")
        else:
            x_px, y_px = int(x), int(y)
            x_ratio = x_px / session.profile.screen_width
            y_ratio = y_px / session.profile.screen_height
            print(f"🎯 点击像素: ({x_px}, {y_px}) -> 比例: ({x_ratio:.4f}, {y_ratio:.4f})")

        if session.ch9329.click(x_ratio, y_ratio):
            print("✓ 点击成功")
        else:
            print("❌ 点击失败")

    def _console_swipe(self, session: CalibrationSession, cmd: str):
        """控制台滑动命令"""
        parts = cmd.split()
        if len(parts) < 5:
            print("❌ 用法: swipe <x1> <y1> <x2> <y2> 或 swiper <x1_ratio> <y1_ratio> <x2_ratio> <y2_ratio>")
            return

        mode = parts[0].lower()
        x1, y1, x2, y2 = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])

        if mode in ['swiper', 'sr']:
            print(f"📱 比例滑动: ({x1:.4f}, {y1:.4f}) -> ({x2:.4f}, {y2:.4f})")
            success = session.ch9329.swipe(x1, y1, x2, y2)
        else:
            x1_r = int(x1) / session.profile.screen_width
            y1_r = int(y1) / session.profile.screen_height
            x2_r = int(x2) / session.profile.screen_width
            y2_r = int(y2) / session.profile.screen_height
            print(f"📱 像素滑动: ({int(x1)}, {int(y1)}) -> ({int(x2)}, {int(y2)})")
            success = session.ch9329.swipe(x1_r, y1_r, x2_r, y2_r)

        if success:
            print("✓ 滑动成功")
        else:
            print("❌ 滑动失败")

    def _console_type(self, session: CalibrationSession, cmd: str):
        """控制台输入命令"""
        text = cmd.split(maxsplit=1)
        if len(text) < 2:
            print("❌ 用法: type <text>")
            return

        text = text[1]
        print(f"⌨️  输入文本: {text}")
        session.ch9329.write_text(text)
        print("✓ 输入成功")

    def _console_list_points(self, session: CalibrationSession):
        """列出所有坐标点"""
        points = list(session.profile.points.values())
        if not points:
            print("暂无保存的坐标点")
            return

        print(f"\n已保存的坐标点 (共 {len(points)} 个):")
        print("-" * 80)
        print(f"{'名称':<30} {'坐标':<15} {'比例':<20} {'描述':<20}")
        print("-" * 80)

        for point in points:
            coords = f"({point.x}, {point.y})"
            ratio = f"({point.x_ratio:.4f}, {point.y_ratio:.4f})"
            desc = point.description[:20] if point.description else ""
            print(f"{point.name:<30} {coords:<15} {ratio:<20} {desc:<20}")

    def launch_interactive_gui(self, phone_id: str, profile_name: str = "default") -> None:
        """
        拉起可视化的物理手机投屏与 CH9329 联调校准工作台 GUI。
        通过独立子进程异步拉起，绝不阻塞当前 Python 主控制流。

        Args:
            phone_id: 物理手机的 ID 标识 (例如 vivo_v2199a_001)
            profile_name: 语义配置文件名称 (默认为 'default')
        """
        project_root = Path(__file__).resolve().parents[4]
        script_path = project_root / "scripts" / "ch9329_visual_debug.py"

        if not script_path.exists():
            message = f"Visual debugger unavailable: expected script at {script_path}"
            logger.error(message)
            raise FileNotFoundError(message)

        logger.info(f"Launching CH9329 Visual Calibration Workbench for {phone_id} (profile: {profile_name})...")

        # 组装 CLI 启动命令并附带设备和配置绑定
        cmd = [
            sys.executable,
            str(script_path),
            "--phone_id", phone_id,
            "--profile", profile_name
        ]

        # 使用 subprocess.Popen 异步拉起子进程，独立运行，绝不阻塞当前线程
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True
        )
        logger.success("CH9329 Visual Calibration Workbench GUI launched successfully as a background subprocess.")

    def _get_session(self, phone_id: str) -> CalibrationSession:
        """Get active session or raise error."""
        session = self._sessions.get(phone_id)
        if session is None:
            raise CalibrationError(f"No active calibration session for {phone_id}. Call start_calibration() first.")
        return session

    def _load_profile(self, phone_id: str, profile_name: str) -> Optional[CalibrationProfile]:
        """Load calibration profile from disk."""
        profile_path = self.profiles_dir / f"{phone_id}_{profile_name}.yaml"

        if not profile_path.exists():
            return None

        try:
            import yaml
            with open(profile_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            profile = CalibrationProfile.from_dict(data)
            logger.info(f"Loaded profile from {profile_path}")
            return profile

        except Exception as e:
            logger.error(f"Failed to load profile from {profile_path}: {e}")
            return None

    def _save_profile(self, profile: CalibrationProfile) -> None:
        """Save calibration profile to disk."""
        profile_path = self.profiles_dir / f"{profile.phone_id}_{profile.profile_name}.yaml"

        try:
            import yaml
            profile.last_modified = datetime.now().isoformat()

            with open(profile_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(
                    profile.to_dict(),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )

            logger.info(f"Saved profile to {profile_path}")

        except Exception as e:
            logger.error(f"Failed to save profile to {profile_path}: {e}")
            raise CalibrationError(f"Failed to save profile: {e}")
