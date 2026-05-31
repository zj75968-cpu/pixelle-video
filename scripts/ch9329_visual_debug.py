#!/usr/bin/env python3
# ruff: noqa: E402
# -*- coding: utf-8 -*-
"""
CH9329 & ADB Hardware Co-Debugging & Visual Coordinate Calibration Workbench

This is a comprehensive desktop GUI workbench (built with Tkinter + Pillow)
specifically designed for hardware-level device farm operations. It helps 
physical device farm engineers:
1. Real-time capture & display Android screen via high-speed ADB.
2. Crosshair coordinate inspector (hovering gives pixel & ratio coordinates).
3. Click & Swipe physically (clicks on desktop Canvas directly translates to physical mouse action).
4. Full Keyboard injection (physical typing and standard short-keys).
5. Rapid calibration & semantic profiles builder (save points directly to yaml).

Requirements:
- Python 3.11+
- pillow (PIL)
- pyyaml
- pyserial
- loguru

Usage:
    python scripts/ch9329_visual_debug.py
"""

import math
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import tkinter as tk
from tkinter import messagebox, ttk

import yaml
from loguru import logger
from PIL import Image, ImageTk

# Import existing hardware components safely
try:
    from pixelle_video.device_farm.hardware.adb_observer import (
        capture_screenshot,
        get_screen_resolution,
        scan_adb_devices,
    )
    from pixelle_video.device_farm.hardware.ch9329_controller import scan_com_ports
    from pixelle_video.device_farm.verification import ProjectionCalibration
    from pixelle_video.device_farm.verification.frame_provider import MS2130FrameProvider
    from pixelle_video.utils.ch9329 import CH9329Controller
except ImportError as e:
    logger.error(f"Failed to import core framework modules: {e}")
    messagebox.showerror(
        "Framework Error",
        "Could not load hardware components. Make sure you run this script from the project root."
    )
    sys.exit(1)



OBSERVATION_LABEL = "MS2130 设备设置 (眼通道)"
WORKBENCH_TITLE = "CH9329 & MS2130 物理手机可视化校验工作台"
MS2130_PROVIDER_CLASS = MS2130FrameProvider
DEFAULT_PROJECTION = ProjectionCalibration(
    projection_id="workbench_default",
    raw_size=(1920, 1080),
    logical_size=(1080, 2400),
)


class VisualDebuggerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WORKBENCH_TITLE)
        self.geometry("1300x820")
        self.minsize(1200, 750)
        
        # Load custom dark futuristic theme style
        self.configure_styles()
        
        # State variables
        self.controller: Optional[CH9329Controller] = None
        self.selected_port = tk.StringVar(value="")
        self.selected_serial = tk.StringVar(value="")
        
        # Parse CLI arguments safely
        p_id = "vivo_v2199a_001"
        prof = "default"
        for i in range(1, len(sys.argv)):
            if sys.argv[i] == "--phone_id" and i + 1 < len(sys.argv):
                p_id = sys.argv[i+1]
            elif sys.argv[i] == "--profile" and i + 1 < len(sys.argv):
                prof = sys.argv[i+1]
                
        self.phone_id = tk.StringVar(value=p_id)
        self.profile_name = tk.StringVar(value=prof)
        
        self.screen_width = tk.IntVar(value=1080)
        self.screen_height = tk.IntVar(value=2400)
        
        # Image rendering & interaction variables
        self.raw_image: Optional[Image.Image] = None
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self.canvas_scale = 1.0
        self.selected_x = 0
        self.selected_y = 0
        self.selected_x_ratio = 0.5
        self.selected_y_ratio = 0.5
        
        # Mouse Swipe drag state
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_line_id = None
        self.drag_candidate = False
        self.drag_exceeded_threshold = False
        
        # Thread control
        self.auto_refresh_running = False
        self.refresh_thread: Optional[threading.Thread] = None
        self.is_capturing = False
        
        # Semantic point forms
        self.point_name = tk.StringVar(value="xhs.")
        self.point_desc = tk.StringVar(value="")
        self.saved_points: Dict[str, dict] = {}
        
        # UI components layout
        self.setup_ui()
        
        # Load local settings & lists
        self.scan_hardware()
        
        # Auto-bind window close
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def configure_styles(self):
        """Build a dark-cyberpunk high-contrast developer theme."""
        self.configure(bg="#1E1E1E")
        
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Global dark style definition
        self.style.configure(".", bg="#1E1E1E", fg="#FFFFFF", fieldbackground="#2D2D2D")
        
        # TPanedwindow
        self.style.configure("TPanedwindow", background="#1E1E1E")
        
        # Frame
        self.style.configure("TFrame", background="#1E1E1E")
        self.style.configure("DarkCard.TFrame", background="#2D2D2D", borderwidth=1, relief="ridge")
        
        # Label
        self.style.configure("TLabel", background="#1E1E1E", foreground="#CCCCCC", font=("Inter", 10))
        self.style.configure("Title.TLabel", foreground="#FF4B4B", font=("Outfit", 14, "bold"))
        self.style.configure("Section.TLabel", foreground="#00E5FF", font=("Inter", 11, "bold"))
        self.style.configure("Stats.TLabel", background="#2D2D2D", foreground="#00FF66", font=("Consolas", 10, "bold"))
        self.style.configure("Header.TLabel", background="#2D2D2D", foreground="#FFFFFF", font=("Inter", 11, "bold"))
        
        # Button
        self.style.configure(
            "TButton",
            background="#3F3F3F",
            foreground="#FFFFFF",
            font=("Inter", 10, "bold"),
            borderwidth=1,
            focuscolor="#FF4B4B"
        )
        self.style.map("TButton",
            background=[("active", "#FF4B4B"), ("disabled", "#222222")],
            foreground=[("active", "#FFFFFF"), ("disabled", "#666666")]
        )
        
        self.style.configure(
            "Accent.TButton",
            background="#FF4B4B",
            foreground="#FFFFFF",
            font=("Inter", 10, "bold")
        )
        self.style.map("Accent.TButton",
            background=[("active", "#FF7676")]
        )
        
        # Combobox
        self.style.configure("TCombobox", fieldbackground="#3A3A3A", background="#3F3F3F", foreground="#FFFFFF")
        
        # Treeview (points list)
        self.style.configure(
            "Treeview",
            background="#252526",
            foreground="#FFFFFF",
            fieldbackground="#252526",
            rowheight=25,
            font=("Consolas", 9)
        )
        self.style.map("Treeview", background=[("selected", "#FF4B4B")])
        self.style.configure("Treeview.Heading", background="#3F3F3F", foreground="#FFFFFF", font=("Inter", 9, "bold"))

    def setup_ui(self):
        """Build responsive 2-column layout."""
        # Top brand banner
        banner_frame = ttk.Frame(self, padding=(10, 5))
        banner_frame.pack(fill="x", side="top")
        
        brand_lbl = ttk.Label(banner_frame, text="🎬 PIXELLE AUTOMATION", style="Title.TLabel")
        brand_lbl.pack(side="left")
        
        subtitle_lbl = ttk.Label(
            banner_frame,
            text="  |  CH9329 & MS2130 物理手机坐标校验工作台",
            font=("Inter", 10, "italic"),
        )
        subtitle_lbl.pack(side="left", fill="y")
        
        # Main split container
        main_pane = ttk.PanedWindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Left screen layout
        left_frame = ttk.Frame(main_pane, padding=10)
        main_pane.add(left_frame, weight=3)
        
        # Left Screen Header Controls
        screen_ctrl_frame = ttk.Frame(left_frame, padding=(0, 0, 0, 10))
        screen_ctrl_frame.pack(fill="x", side="top")
        
        self.btn_refresh_ss = ttk.Button(screen_ctrl_frame, text="📸 立即刷新手机屏幕", style="Accent.TButton", command=self.manual_refresh_screenshot)
        self.btn_refresh_ss.pack(side="left", padx=(0, 10))
        
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.chk_auto_refresh = ttk.Checkbutton(
            screen_ctrl_frame,
            text="🔄 实时同步投屏 (1.5秒/次)",
            variable=self.auto_refresh_var,
            command=self.toggle_auto_refresh
        )
        self.chk_auto_refresh.pack(side="left", padx=10)
        
        self.lbl_fps = ttk.Label(screen_ctrl_frame, text="状态: 未连接", font=("Inter", 9))
        self.lbl_fps.pack(side="right")
        
        # Screen Canvas (uses Scrollbar for large displays)
        canvas_border = ttk.Frame(left_frame, style="DarkCard.TFrame")
        canvas_border.pack(fill="both", expand=True)
        
        self.canvas = tk.Canvas(canvas_border, bg="#0F0F10", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Bind Canvas Mouse Gestures
        self.canvas.bind("<Motion>", self.on_canvas_hover)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        
        # Canvas Coordinate Inspector Bar
        self.coord_bar = ttk.Frame(left_frame, padding=(0, 5, 0, 0))
        self.coord_bar.pack(fill="x", side="bottom")
        
        self.lbl_hover_coords = ttk.Label(self.coord_bar, text="🖱️ 鼠标坐标: 离屏", font=("Consolas", 10))
        self.lbl_hover_coords.pack(side="left")
        
        self.lbl_click_coords = ttk.Label(self.coord_bar, text="🎯 选中点: X=0, Y=0 [Ratio: 0.00, 0.00]", font=("Consolas", 10), foreground="#00FF66")
        self.lbl_click_coords.pack(side="right")
        
        # Right Control Panel Panel
        right_frame = ttk.Frame(main_pane, padding=10)
        main_pane.add(right_frame, weight=2)
        
        # Setup right tabs
        control_tabs = ttk.Notebook(right_frame)
        control_tabs.pack(fill="both", expand=True)
        
        # Tab 1: Hardware Connection
        tab_conn = ttk.Frame(control_tabs, padding=10)
        control_tabs.add(tab_conn, text="⚙️ 硬件连接")
        self.build_conn_tab(tab_conn)
        
        # Tab 2: Points Calibration
        tab_cal = ttk.Frame(control_tabs, padding=10)
        control_tabs.add(tab_cal, text="🎯 坐标校准")
        self.build_calib_tab(tab_cal)
        
        # Tab 3: CH9329 Debug Console
        tab_debug = ttk.Frame(control_tabs, padding=10)
        control_tabs.add(tab_debug, text="⌨️ 键鼠调试")
        self.build_debug_tab(tab_debug)

    def build_conn_tab(self, parent):
        """Construct hardware selection, resolution, profile configs."""
        # Section 1: CH9329 Serial settings
        lbl_ch9329_sec = ttk.Label(parent, text="CH9329 串口设置 (手通道)", style="Section.TLabel")
        lbl_ch9329_sec.pack(anchor="w", pady=(0, 5))
        
        card1 = ttk.Frame(parent, style="DarkCard.TFrame", padding=10)
        card1.pack(fill="x", pady=(0, 15))
        
        ttk.Label(card1, text="选择串口 COM 口:").grid(row=0, column=0, sticky="w", pady=5)
        self.cb_ports = ttk.Combobox(card1, textvariable=self.selected_port, state="readonly", width=15)
        self.cb_ports.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        btn_rescan_ports = ttk.Button(card1, text="🔄 扫描", width=8, command=self.scan_ports)
        btn_rescan_ports.grid(row=0, column=2, sticky="w", pady=5)
        
        ttk.Label(card1, text="波特率:").grid(row=1, column=0, sticky="w", pady=5)
        self.cb_baud = ttk.Combobox(card1, values=["9600", "115200"], state="readonly", width=15)
        self.cb_baud.set("9600")
        self.cb_baud.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        
        # Section 2: MS2130/legacy ADB settings
        lbl_adb_sec = ttk.Label(parent, text=OBSERVATION_LABEL, style="Section.TLabel")
        lbl_adb_sec.pack(anchor="w", pady=(5, 5))

        card2 = ttk.Frame(parent, style="DarkCard.TFrame", padding=10)
        card2.pack(fill="x", pady=(0, 15))

        ttk.Label(card2, text="ADB 序列号 (可选，旧版截图/规格读取):").grid(row=0, column=0, sticky="w", pady=5)
        self.cb_devices = ttk.Combobox(card2, textvariable=self.selected_serial, state="readonly", width=25)
        self.cb_devices.grid(row=0, column=1, columnspan=2, sticky="w", padx=10, pady=5)
        self.cb_devices.bind("<<ComboboxSelected>>", self.on_adb_device_selected)

        btn_rescan_adb = ttk.Button(card2, text="🔄 刷新可选 ADB", width=14, command=self.scan_adb)
        btn_rescan_adb.grid(row=1, column=0, sticky="w", pady=5)
        
        # Section 3: Screen Parameters
        lbl_screen_sec = ttk.Label(parent, text="屏幕物理尺寸配置", style="Section.TLabel")
        lbl_screen_sec.pack(anchor="w", pady=(5, 5))
        
        card3 = ttk.Frame(parent, style="DarkCard.TFrame", padding=10)
        card3.pack(fill="x", pady=(0, 15))
        
        ttk.Label(card3, text="屏幕宽度(W):").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_w = ttk.Entry(card3, textvariable=self.screen_width, width=12)
        self.ent_w.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        ttk.Label(card3, text="屏幕高度(H):").grid(row=1, column=0, sticky="w", pady=5)
        self.ent_h = ttk.Entry(card3, textvariable=self.screen_height, width=12)
        self.ent_h.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        
        btn_fetch_res = ttk.Button(card3, text="⚡ 从 ADB 自动获取屏幕规格", command=self.auto_fetch_resolution)
        btn_fetch_res.grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)
        
        # Big Action Button
        self.btn_connect = ttk.Button(
            parent,
            text="⚡ 建立物理联调连接并加载语义文件",
            style="Accent.TButton",
            command=self.connect_hardware
        )
        self.btn_connect.pack(fill="x", ipady=10, pady=(10, 0))

    def build_calib_tab(self, parent):
        """Calibration profiles management panel with save forms and points treeview."""
        # Top config info
        info_frame = ttk.Frame(parent, style="DarkCard.TFrame", padding=10)
        info_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(info_frame, text="设备 ID:").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_phone_id = ttk.Entry(info_frame, textvariable=self.phone_id, width=18)
        self.ent_phone_id.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        
        ttk.Label(info_frame, text="配置文件:").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=5)
        self.ent_profile = ttk.Entry(info_frame, textvariable=self.profile_name, width=12)
        self.ent_profile.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        
        # Point edit fields
        point_frame = ttk.LabelFrame(parent, text=" 🎯 语义点编辑与快捷保存 ", padding=10)
        point_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(point_frame, text="语义点命名:").grid(row=0, column=0, sticky="w", pady=3)
        self.ent_pt_name = ttk.Entry(point_frame, textvariable=self.point_name, width=28)
        self.ent_pt_name.grid(row=0, column=1, columnspan=2, sticky="w", padx=5, pady=3)
        
        ttk.Label(point_frame, text="示例: xhs.home.publish_button", font=("Inter", 8, "italic"), foreground="#888888").grid(row=1, column=1, columnspan=2, sticky="w", padx=5)
        
        ttk.Label(point_frame, text="说明描述:").grid(row=2, column=0, sticky="w", pady=5)
        self.ent_pt_desc = ttk.Entry(point_frame, textvariable=self.point_desc, width=28)
        self.ent_pt_desc.grid(row=2, column=1, columnspan=2, sticky="w", padx=5, pady=5)
        
        self.btn_save_point = ttk.Button(point_frame, text="💾 保存/覆盖该语义点", style="Accent.TButton", command=self.save_selected_point)
        self.btn_save_point.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(5, 0), ipady=3)
        
        # Semantic Points List header
        ttk.Label(parent, text="已加载的语义点列表 (双击项目直接在真机测试点击):", font=("Inter", 9, "bold")).pack(anchor="w", pady=(5, 2))
        
        # Treeview points list
        tree_scroll = ttk.Scrollbar(parent)
        tree_scroll.pack(side="right", fill="y")
        
        self.tree_points = ttk.Treeview(
            parent,
            columns=("name", "x_y", "ratio", "desc"),
            show="headings",
            yscrollcommand=tree_scroll.set
        )
        self.tree_points.pack(fill="both", expand=True)
        tree_scroll.config(command=self.tree_points.yview)
        
        self.tree_points.heading("name", text="语义点名称")
        self.tree_points.heading("x_y", text="像素 (X, Y)")
        self.tree_points.heading("ratio", text="比例 (X, Y)")
        self.tree_points.heading("desc", text="描述")
        
        self.tree_points.column("name", width=140, anchor="w")
        self.tree_points.column("x_y", width=80, anchor="center")
        self.tree_points.column("ratio", width=90, anchor="center")
        self.tree_points.column("desc", width=110, anchor="w")
        
        self.tree_points.bind("<Double-1>", self.on_tree_double_click)
        self.tree_points.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        # Point operational buttons
        btn_points_ops = ttk.Frame(parent, padding=(0, 5, 0, 0))
        btn_points_ops.pack(fill="x")
        
        self.btn_delete_point = ttk.Button(btn_points_ops, text="🗑️ 删除选中点", command=self.delete_selected_point)
        self.btn_delete_point.pack(side="left", padx=(0, 10))
        
        self.btn_export_points = ttk.Button(btn_points_ops, text="📂 强制保存配置文件", command=self.force_save_profile)
        self.btn_export_points.pack(side="right")

    def build_debug_tab(self, parent):
        """Keyboard entry interface and quick macro action commands."""
        # Direct keyboard input
        card_kb = ttk.LabelFrame(parent, text=" ⌨️ 键盘物理打字模拟 ", padding=10)
        card_kb.pack(fill="x", pady=(0, 15))
        
        ttk.Label(card_kb, text="输入需要输入的英文/数字/字符(CH9329限制英文布局):").pack(anchor="w", pady=(0, 5))
        
        self.ent_typing = ttk.Entry(card_kb, font=("Consolas", 11))
        self.ent_typing.pack(fill="x", pady=5)
        self.ent_typing.bind("<Return>", lambda e: self.send_typing_input())
        
        btn_type = ttk.Button(card_kb, text="⚡ 物理写入手机文本框", style="Accent.TButton", command=self.send_typing_input)
        btn_type.pack(fill="x", pady=(5, 0))
        
        # Macro actions grid
        card_macro = ttk.LabelFrame(parent, text=" 🛠️ CH9329 快捷键与宏调试 ", padding=10)
        card_macro.pack(fill="both", expand=True)
        
        # Set up a button grid
        grid_frame = ttk.Frame(card_macro)
        grid_frame.pack(fill="x", pady=5)
        
        # Setup Grid Weights for responsiveness
        for c in range(3):
            grid_frame.columnconfigure(c, weight=1)
            
        ttk.Button(grid_frame, text="🏠 Home (桌面)", command=lambda: self.execute_macro("home")).grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        ttk.Button(grid_frame, text="🔙 Back (返回)", command=lambda: self.execute_macro("back")).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(grid_frame, text="↩️ Enter (确认)", command=lambda: self.execute_macro("enter")).grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        
        ttk.Button(grid_frame, text="🌐 全选 (Ctrl+A)", command=lambda: self.execute_macro("ctrl_a")).grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        ttk.Button(grid_frame, text="📋 粘贴 (Ctrl+V)", command=lambda: self.execute_macro("ctrl_v")).grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(grid_frame, text="🧹 退格 (Backspace)", command=lambda: self.execute_macro("backspace")).grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        
        # Backspace times control
        bk_ctrl = ttk.Frame(card_macro)
        bk_ctrl.pack(fill="x", pady=5)
        
        ttk.Label(bk_ctrl, text="连续退格次数:").pack(side="left", padx=5)
        self.bk_times = tk.IntVar(value=1)
        self.ent_bk = ttk.Entry(bk_ctrl, textvariable=self.bk_times, width=5, font=("Consolas", 10))
        self.ent_bk.pack(side="left", padx=5)
        
        ttk.Button(bk_ctrl, text="❌ 连续退格删除", command=lambda: self.execute_macro("multi_backspace")).pack(side="left", padx=10, fill="x", expand=True)
        
        # Advanced interactive instructions info card
        adv_info = ttk.Frame(card_macro, style="DarkCard.TFrame", padding=10)
        adv_info.pack(fill="both", expand=True, pady=10)
        
        ttk.Label(adv_info, text="💡 滑动调试指南:", font=("Inter", 9, "bold"), foreground="#00E5FF").pack(anchor="w")
        ttk.Label(
            adv_info,
            text="• 在左侧手机截图中，鼠标左键按住拖动会绘制蓝色轨迹线，\n"
                 "  松开鼠标后将直接向手机发送顺畅的相对缓动滑动手势！\n"
                 "• 这在物理联调多图翻页、内容上下滑动刷新时非常实用！",
            justify="left",
            font=("Inter", 9)
        ).pack(anchor="w", pady=5)

    # =========================================================================
    # Hardware Scan & Controls
    # =========================================================================
    
    def scan_hardware(self):
        """Trigger scan for COM ports and active ADB connections."""
        self.scan_ports()
        self.scan_adb()

    def scan_ports(self):
        """Scan available system serial ports."""
        ports = scan_com_ports()
        if ports:
            port_list = [p[0] for p in ports]
            self.cb_ports["values"] = port_list
            # Select first or attempt match config
            if "COM5" in port_list:
                self.selected_port.set("COM5")
            elif "COM3" in port_list:
                self.selected_port.set("COM3")
            else:
                self.selected_port.set(port_list[0])
            logger.info(f"Scanned ports: {port_list}")
        else:
            self.cb_ports["values"] = []
            self.selected_port.set("")
            logger.warning("No COM ports found.")

    def scan_adb(self):
        """Scan active adb clients."""
        try:
            devices = scan_adb_devices()
            serial_list = [d.serial for d in devices if d.status == "device"] if devices else []
            self.cb_devices["values"] = serial_list
            if serial_list:
                self.selected_serial.set(serial_list[0])
                self.on_adb_device_selected(None)
                logger.info(f"Active ADB devices: {serial_list}")
            else:
                self.selected_serial.set("")
                logger.warning("No active ADB devices found; legacy ADB observation remains optional.")
        except Exception as e:
            logger.error(f"Error scanning ADB: {e}")
            self.cb_devices["values"] = []
            self.selected_serial.set("")

    def on_adb_device_selected(self, event):
        """Callback when an ADB device is chosen, auto fetch info."""
        serial = self.selected_serial.get()
        if not serial:
            return
        
        # Load from config devices.yaml if exists
        try:
            config_path = project_root / "config" / "devices.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                for dev in cfg.get("devices", []):
                    if dev.get("adb_serial") == serial:
                        self.phone_id.set(dev.get("phone_id", "my_phone"))
                        self.selected_port.set(dev.get("ch9329_port", ""))
                        scr = dev.get("screen", {})
                        if scr.get("width") and scr.get("height"):
                            self.screen_width.set(scr["width"])
                            self.screen_height.set(scr["height"])
                        logger.info(f"Loaded config matching serial: {serial} -> {dev.get('phone_id')}")
                        break
        except Exception as e:
            logger.warning(f"Error loading matched config: {e}")

    def auto_fetch_resolution(self):
        """Query shell directly for physical window metrics."""
        serial = self.selected_serial.get()
        if not serial:
            messagebox.showwarning("Warning", "请先选择一个有效的 ADB 设备！")
            return
        
        try:
            res = get_screen_resolution(serial)
            if res:
                self.screen_width.set(res[0])
                self.screen_height.set(res[1])
                logger.info(f"Successfully queried physical resolution from {serial}: {res[0]}x{res[1]}")
                messagebox.showinfo("Success", f"成功自动读取屏幕物理分辨率：{res[0]} x {res[1]}")
            else:
                messagebox.showerror("Error", "未能从 ADB 获取分辨率，请确认该设备处于在线解锁状态。")
        except Exception as e:
            messagebox.showerror("Error", f"获取分辨率时出错: {e}")

    def connect_hardware(self):
        """Disconnect active, instantiate a fresh CH9329Controller, read configs."""
        port = self.selected_port.get()
        serial = self.selected_serial.get()

        if not port:
            messagebox.showerror("Error", "请先选择并确认 CH9329 的串口端口！")
            return

        # Clean existing
        if self.controller:
            self.controller.disconnect()
        self.controller = None

        try:
            baudrate = int(self.cb_baud.get())
            # Instantiate CH9329 controller
            controller = CH9329Controller(port=port, baudrate=baudrate)
            controller.screen_width = self.screen_width.get()
            controller.screen_height = self.screen_height.get()

            if not controller.connect():
                raise ConnectionError(f"无法在端口 {port} 上与 CH9329 建立连接。请确认波特率和连接。")
            self.controller = controller

            self.lbl_fps.config(text="● 硬件已联调", foreground="#00FF66")
            logger.success(f"CH9329/MS2130 visual debug workbench connected on {port}; optional ADB={serial or 'not selected'}")

            # Load Calibration Profile
            self.load_calibration_profile()

            # Instantly refresh screenshot once when legacy ADB is available.
            self.manual_refresh_screenshot()

            adb_text = serial or "未选择（MS2130/CH9329 连接不依赖 ADB）"
            messagebox.showinfo("Success", f"物理联调连接建立成功！\n- 串口: {port}\n- 波特率: {baudrate}\n- ADB: {adb_text}\n- 屏幕: {self.screen_width.get()}x{self.screen_height.get()}")
        except Exception as e:
            self.controller = None
            logger.error(f"Failed to connect hardware: {e}")
            messagebox.showerror("Connection Failed", f"连接失败: {e}")

    # =========================================================================
    # Calibration Profile Files Manager
    # =========================================================================
    
    def load_calibration_profile(self):
        """Load coordinates structure from project yaml profile."""
        phone_id = self.phone_id.get()
        prof_name = self.profile_name.get()
        
        profile_path = project_root / "config" / "calibration_profiles" / f"{phone_id}_{prof_name}.yaml"
        self.saved_points.clear()
        
        # Clear list UI
        for item in self.tree_points.get_children():
            self.tree_points.delete(item)
            
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                
                points_data = data.get("points", [])
                # If structured as MVP CalibrationProfile
                if isinstance(points_data, list):
                    for pt in points_data:
                        name = pt.get("name")
                        if name:
                            self.saved_points[name] = {
                                "x": pt.get("x", 0),
                                "y": pt.get("y", 0),
                                "x_ratio": pt.get("x_ratio", 0.0),
                                "y_ratio": pt.get("y_ratio", 0.0),
                                "description": pt.get("description", "")
                            }
                elif isinstance(points_data, dict): # if direct dictionary
                    for name, pt in points_data.items():
                        self.saved_points[name] = pt
                
                logger.info(f"Loaded {len(self.saved_points)} points from profile: {profile_path}")
                self.refresh_points_list()
            except Exception as e:
                logger.error(f"Failed to parse calibration profile {profile_path}: {e}")
        else:
            logger.info(f"Profile {profile_path} not found. A new one will be created upon save.")

    def refresh_points_list(self):
        """Repopulate treeview grid."""
        for item in self.tree_points.get_children():
            self.tree_points.delete(item)
            
        for name, pt in sorted(self.saved_points.items()):
            x_y = f"{pt['x']}, {pt['y']}"
            ratio = f"{pt['x_ratio']:.4f}, {pt['y_ratio']:.4f}"
            self.tree_points.insert("", "end", values=(name, x_y, ratio, pt.get("description", "")))

    def save_selected_point(self):
        """Append or override active click point in memory, then serialize."""
        name = self.point_name.get().strip()
        desc = self.point_desc.get().strip()
        
        if not name or name == "xhs.":
            messagebox.showerror("Error", "请输入有效的语义点名称！")
            return
            
        # Register in memory dictionary
        self.saved_points[name] = {
            "x": self.selected_x,
            "y": self.selected_y,
            "x_ratio": round(self.selected_x_ratio, 4),
            "y_ratio": round(self.selected_y_ratio, 4),
            "description": desc
        }
        
        self.refresh_points_list()
        self.serialize_profile()
        logger.success(f"Point '{name}' calibrated & saved.")
        
        # Clear fields slightly
        self.point_name.set("xhs.")
        self.point_desc.set("")

    def delete_selected_point(self):
        """Delete from memory list."""
        selected = self.tree_points.selection()
        if not selected:
            messagebox.showwarning("Warning", "请在列表中选择要删除的语义点！")
            return
            
        name = self.tree_points.item(selected[0], "values")[0]
        if name in self.saved_points:
            del self.saved_points[name]
            self.refresh_points_list()
            self.serialize_profile()
            logger.info(f"Deleted semantic point: {name}")

    def force_save_profile(self):
        """Force serialize profiles to folder."""
        self.serialize_profile()
        messagebox.showinfo("Saved", "配置文件强制保存并写入完成！")

    def serialize_profile(self):
        """Write current coordinates dictionary into target YAML."""
        phone_id = self.phone_id.get()
        prof_name = self.profile_name.get()
        
        profiles_dir = project_root / "config" / "calibration_profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        
        profile_path = profiles_dir / f"{phone_id}_{prof_name}.yaml"
        
        # Format matching MVP calibration schema
        profile_data = {
            "profile_id": f"{phone_id}_{prof_name}",
            "phone_id": phone_id,
            "screen": {
                "width": self.screen_width.get(),
                "height": self.screen_height.get(),
                "safe_top": 100,
                "safe_bottom": 120,
                "navigation_mode": "gesture"
            },
            "points": [],
            "created_at": datetime.now().isoformat(),
            "metadata": {
                "device_name": "Calibrated Phone",
                "calibration_method": "visual_workbench"
            }
        }
        
        for name, pt in sorted(self.saved_points.items()):
            profile_data["points"].append({
                "name": name,
                "type": "absolute",
                "x": pt["x"],
                "y": pt["y"],
                "x_ratio": pt["x_ratio"],
                "y_ratio": pt["y_ratio"],
                "description": pt.get("description", "")
            })
            
        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    profile_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )
            logger.debug(f"Saved calibration profile to {profile_path}")
        except Exception as e:
            logger.error(f"Failed to serialize profile: {e}")

    # =========================================================================
    # Interactive Canvas Coordinates Inspector & Streaming Projector
    # =========================================================================
    
    def manual_refresh_screenshot(self):
        """Trigger screenshot fetch in separate thread to prevent main event blocking."""
        serial = self.selected_serial.get()
        if not serial:
            return
            
        if self.is_capturing:
            return
            
        self.is_capturing = True
        self.btn_refresh_ss.config(state="disabled")
        
        threading.Thread(target=self._screenshot_worker, args=(serial,), daemon=True).start()

    def _screenshot_worker(self, serial: str):
        """Worker thread to fetch binary image and redraw on Canvas."""
        try:
            # Temporary cache path
            temp_path = project_root / "runtime" / f"temp_visual_debug_{serial}.png"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            
            # High speed dump
            capture_screenshot(serial, str(temp_path))
            
            if temp_path.exists():
                self.raw_image = Image.open(temp_path)
                self.after(0, self.update_canvas_image)
        except Exception as e:
            logger.warning(f"Screenshot thread error: {e}")
        finally:
            self.is_capturing = False
            self.after(0, lambda: self.btn_refresh_ss.config(state="normal"))

    def update_canvas_image(self):
        """Scale retrieved image and draw inside canvas bounds."""
        if not self.raw_image:
            return
            
        # Get canvas current dimensions
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        
        if cw < 50 or ch < 50:
            cw, ch = 360, 720  # Fallback initially
            
        # Fit image height with canvas, preserve aspect ratio
        img_w, img_h = self.raw_image.size
        
        scale = ch / img_h
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        
        # Resize Pillow image
        resized_img = self.raw_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        self.canvas_scale = scale
        self.tk_image = ImageTk.PhotoImage(resized_img)
        
        # Redraw
        self.canvas.delete("all")
        
        # Center image in Canvas
        self.img_offset_x = (cw - new_w) // 2
        self.img_offset_y = 0
        
        self.canvas.create_image(
            self.img_offset_x, self.img_offset_y,
            anchor="nw", image=self.tk_image
        )
        
        # Redraw click crosshair if active
        if self.selected_x_ratio > 0:
            cx = self.img_offset_x + int(self.selected_x_ratio * new_w)
            cy = self.img_offset_y + int(self.selected_y_ratio * new_h)
            
            self.draw_target_crosshair(cx, cy)

    def draw_target_crosshair(self, cx, cy):
        """Draw an elegant high-contrast target ring with crosshair lines."""
        # Draw circular targeting ring
        self.canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, outline="#FF4B4B", width=2, tags="crosshair")
        self.canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill="#00FF66", outline="#00FF66", tags="crosshair")
        # Draw dotted crosshair lines
        self.canvas.create_line(cx - 25, cy, cx - 10, cy, fill="#FF4B4B", width=1.5, tags="crosshair")
        self.canvas.create_line(cx + 10, cy, cx + 25, cy, fill="#FF4B4B", width=1.5, tags="crosshair")
        self.canvas.create_line(cx, cy - 25, cx, cy - 10, fill="#FF4B4B", width=1.5, tags="crosshair")
        self.canvas.create_line(cx, cy + 10, cx, cy + 25, fill="#FF4B4B", width=1.5, tags="crosshair")

    def toggle_auto_refresh(self):
        """Enable background loop checking."""
        if self.auto_refresh_var.get():
            self.auto_refresh_running = True
            self.lbl_fps.config(text="● 自动投屏中", foreground="#00E5FF")
            self.refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
            self.refresh_thread.start()
            logger.info("Auto screenshot sync loop enabled.")
        else:
            self.auto_refresh_running = False
            self.lbl_fps.config(text="● 硬件已联调", foreground="#00FF66")

    def _auto_refresh_loop(self):
        """Background continuous stream worker."""
        while self.auto_refresh_running:
            serial = self.selected_serial.get()
            if serial and not self.is_capturing:
                try:
                    temp_path = project_root / "runtime" / f"temp_visual_debug_{serial}.png"
                    capture_screenshot(serial, str(temp_path))
                    if temp_path.exists():
                        self.raw_image = Image.open(temp_path)
                        self.after(0, self.update_canvas_image)
                except Exception as e:
                    logger.debug(f"Auto refresh screenshot sync loop error: {e}")
            time.sleep(1.5)

    # =========================================================================
    # Coordinates Math & Input Handlers
    # =========================================================================
    
    def on_canvas_hover(self, event):
        """Inspector mouse hover coordinates translation."""
        if not self.raw_image or not self.tk_image:
            return
            
        cw = self.tk_image.width()
        ch = self.tk_image.height()
        
        # Relative to image offset
        rx = event.x - self.img_offset_x
        ry = event.y - self.img_offset_y
        
        # Check boundary
        if 0 <= rx <= cw and 0 <= ry <= ch:
            x_ratio = rx / cw
            y_ratio = ry / ch
            
            # Map back to target phone pixels
            p_width = self.screen_width.get()
            p_height = self.screen_height.get()
            px = int(x_ratio * p_width)
            py = int(y_ratio * p_height)
            
            self.lbl_hover_coords.config(
                text=f"🖱️ 物理坐标: ({px}, {py})  |  比例: ({x_ratio:.4f}, {y_ratio:.4f})"
            )
        else:
            self.lbl_hover_coords.config(text="🖱️ 物理坐标: 离屏")

    def on_canvas_click(self, event):
        """Trigger physical click via CH9329 and record point coordinates."""
        if not self.raw_image or not self.tk_image:
            return
            
        cw = self.tk_image.width()
        ch = self.tk_image.height()
        
        # Target image metrics
        rx = event.x - self.img_offset_x
        ry = event.y - self.img_offset_y
        
        # Check boundary
        if 0 <= rx <= cw and 0 <= ry <= ch:
            # Ratios
            self.selected_x_ratio = rx / cw
            self.selected_y_ratio = ry / ch
            
            # Screen pixels
            p_width = self.screen_width.get()
            p_height = self.screen_height.get()
            self.selected_x = int(self.selected_x_ratio * p_width)
            self.selected_y = int(self.selected_y_ratio * p_height)
            
            # Redraw indicator immediately
            self.canvas.delete("crosshair")
            self.draw_target_crosshair(event.x, event.y)
            
            # Update coordinate labels
            self.lbl_click_coords.config(
                text=f"🎯 选中点: X={self.selected_x}, Y={self.selected_y} [Ratio: {self.selected_x_ratio:.4f}, {self.selected_y_ratio:.4f}]"
            )
            
            # Auto-fill calibration inputs
            self.point_name.set("xhs.")
            self.point_desc.set(f"Selected point at ({self.selected_x}, {self.selected_y})")
            
            # Save Drag Start coordinates for possible click/swipe on release
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            self.drag_candidate = True
            self.drag_exceeded_threshold = False
        else:
            self.drag_candidate = False

    def _physical_click_worker(self, xr, yr):
        """Perform hardware click."""
        try:
            self.controller.click(xr, yr)
            # If auto-refresh is OFF, request one screenshot capture on Tk thread to show outcome
            if not self.auto_refresh_var.get():
                time.sleep(0.6)  # wait for UI render
                self.after(0, self.manual_refresh_screenshot)
        except Exception as e:
            logger.error(f"Physical click fail: {e}")

    # =========================================================================
    # Drag Gestures to CH9329 Swipe
    # =========================================================================
    
    def on_canvas_drag(self, event):
        """Draw interactive line trajectory on canvas."""
        if not self.raw_image or not self.tk_image:
            return
            
        distance = math.sqrt((event.x - self.drag_start_x)**2 + (event.y - self.drag_start_y)**2)
        if distance >= 15:
            self.drag_exceeded_threshold = True

        if self.drag_line_id:
            self.canvas.delete(self.drag_line_id)

        # Draw transparent blue dragging vector line
        self.drag_line_id = self.canvas.create_line(
            self.drag_start_x, self.drag_start_y,
            event.x, event.y,
            fill="#00E5FF", width=3, arrow=tk.LAST, tags="drag_line"
        )

    def on_canvas_release(self, event):
        """Release mouse drag gesture to trigger physical swipe."""
        if not self.raw_image or not self.tk_image:
            return
            
        if self.drag_line_id:
            self.canvas.delete(self.drag_line_id)
            self.drag_line_id = None
            
        # Translate to coordinates
        cw = self.tk_image.width()
        ch = self.tk_image.height()
        
        # Start ratio
        x1_r = (self.drag_start_x - self.img_offset_x) / cw
        y1_r = (self.drag_start_y - self.img_offset_y) / ch
        
        # End ratio
        x2_r = (event.x - self.img_offset_x) / cw
        y2_r = (event.y - self.img_offset_y) / ch
        
        # Filter tiny accidental jitter click drags
        distance = math.sqrt((event.x - self.drag_start_x)**2 + (event.y - self.drag_start_y)**2)
        if distance < 15:
            if self.drag_candidate:
                self.drag_candidate = False
                if self.controller:
                    threading.Thread(
                        target=self._physical_click_worker,
                        args=(self.selected_x_ratio, self.selected_y_ratio),
                        daemon=True
                    ).start()
                else:
                    logger.warning("Click triggered, but CH9329 is not initialized.")
            return
            
        # Check start bounds
        if 0 <= x1_r <= 1 and 0 <= y1_r <= 1:
            # Constrain end points inside boundary
            x2_r = max(0.0, min(1.0, x2_r))
            y2_r = max(0.0, min(1.0, y2_r))
            
            logger.info(f"Gesture Drag: Swipe from ({x1_r:.3f}, {y1_r:.3f}) to ({x2_r:.3f}, {y2_r:.3f})")
            self.drag_candidate = False

            # Send physical swipe via CH9329 on thread
            if self.controller:
                threading.Thread(
                    target=self._physical_swipe_worker,
                    args=(x1_r, y1_r, x2_r, y2_r),
                    daemon=True
                ).start()
            else:
                logger.warning("Gesture swipe parsed, but CH9329 is not initialized.")

    def _physical_swipe_worker(self, x1_r, y1_r, x2_r, y2_r):
        """Execute physical high precision cosine easing swipe on phone."""
        try:
            success = self.ch9329_swipe_gesture(x1_r, y1_r, x2_r, y2_r)
            if success:
                logger.success("Swipe executed successfully.")
                if not self.auto_refresh_var.get():
                    time.sleep(0.8)  # wait for swipe UI animation
                    self.after(0, self.manual_refresh_screenshot)
            else:
                logger.error("Swipe gesture execution failed.")
        except Exception as e:
            logger.error(f"Swipe worker failed: {e}")

    def ch9329_swipe_gesture(self, x1_r, y1_r, x2_r, y2_r, duration=0.8) -> bool:
        """
        Execute a physical swipe through CH9329Controller.

        Delegating keeps long-distance movement accounting in the controller, which avoids
        losing clipped residual deltas in this workbench layer.
        """
        if not self.controller:
            return False

        swipe = getattr(self.controller, "swipe", None)
        if not callable(swipe):
            logger.error("CH9329 controller does not expose swipe().")
            return False
        return bool(swipe(x1_r, y1_r, x2_r, y2_r, duration=duration))

    # =========================================================================
    # Keyboard & Macro Action Handlers
    # =========================================================================
    
    def send_typing_input(self):
        """Simulate virtual keyboard keystroke strings."""
        text = self.ent_typing.get()
        if not text:
            return
            
        if not self.controller:
            messagebox.showerror("Error", "请先建立物理连接！")
            return
            
        logger.info(f"Typing text: '{text}'")
        self.btn_refresh_ss.config(state="disabled")
        
        # Trigger on background thread to prevent UI lock
        threading.Thread(target=self._typing_worker, args=(text,), daemon=True).start()

    def _typing_worker(self, text: str):
        """Key injector."""
        try:
            self.controller.write_text(text)
            self.after(0, lambda: self.ent_typing.delete(0, tk.END))
            if not self.auto_refresh_var.get():
                time.sleep(0.5)
                self.after(0, self.manual_refresh_screenshot)
        except Exception as e:
            logger.error(f"Typing input error: {e}")

    def execute_macro(self, command: str):
        """Trigger fast macro clicks directly."""
        if not self.controller:
            messagebox.showerror("Error", "请先建立物理连接！")
            return
            
        threading.Thread(target=self._macro_worker, args=(command,), daemon=True).start()

    def _macro_worker(self, command: str):
        """Macro command worker."""
        try:
            if command == "home":
                self.controller.swipe_up_to_home()
            elif command == "back":
                self.controller._send_keyboard(0x00, 0x29) # Keycode for ESC (standard Android Back key mapped on CH9329)
            elif command == "enter":
                self.controller.press_enter()
            elif command == "ctrl_a":
                self.controller.press_ctrl_a()
            elif command == "ctrl_v":
                self.controller.press_ctrl_v()
            elif command == "backspace":
                self.controller.press_backspace(1)
            elif command == "multi_backspace":
                times = max(1, min(100, self.bk_times.get()))
                self.controller.press_backspace(times)
                
            logger.success(f"Macro action executed: {command}")
            
            if not self.auto_refresh_var.get():
                time.sleep(0.6)
                self.after(0, self.manual_refresh_screenshot)
        except Exception as e:
            logger.error(f"Macro action fail: {e}")

    # =========================================================================
    # Points Treeview Handlers
    # =========================================================================
    
    def on_tree_select(self, event):
        """Load selected tree point information back into edit fields."""
        selected = self.tree_points.selection()
        if not selected:
            return
            
        name = self.tree_points.item(selected[0], "values")[0]
        pt = self.saved_points.get(name)
        if pt:
            self.point_name.set(name)
            self.point_desc.set(pt.get("description", ""))

    def on_tree_double_click(self, event):
        """Double click point list item to run physical click test."""
        selected = self.tree_points.selection()
        if not selected:
            return
            
        name = self.tree_points.item(selected[0], "values")[0]
        pt = self.saved_points.get(name)
        
        if pt and self.controller:
            xr = pt["x_ratio"]
            yr = pt["y_ratio"]
            
            logger.info(f"Double-click test point: {name} at ({xr}, {yr})")
            
            # Draw on canvas if raw image exists
            if self.tk_image:
                cw = self.tk_image.width()
                ch = self.tk_image.height()
                cx = self.img_offset_x + int(xr * cw)
                cy = self.img_offset_y + int(yr * ch)
                self.canvas.delete("crosshair")
                self.draw_target_crosshair(cx, cy)
                self.lbl_click_coords.config(
                    text=f"🎯 选中点: X={pt['x']}, Y={pt['y']} [Ratio: {xr:.4f}, {yr:.4f}]"
                )
            
            threading.Thread(
                target=self._physical_click_worker,
                args=(xr, yr),
                daemon=True
            ).start()

    # =========================================================================
    # Graceful Close Cleanup
    # =========================================================================
    
    def on_close(self):
        """Clean connections and kill loops."""
        self.auto_refresh_running = False
        if self.controller:
            self.controller.disconnect()
            logger.info("CH9329Controller connection closed.")
        self.destroy()


if __name__ == "__main__":
    logger.add(
        project_root / "logs" / "ch9329_visual_debug.log",
        rotation="10 MB",
        encoding="utf-8"
    )
    logger.info("Launching CH9329 Visual Calibration Workbench...")
    app = VisualDebuggerApp()
    app.mainloop()
