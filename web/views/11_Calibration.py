# Copyright (C) 2025 AIDC-AI
"""
Calibration - CH9329 Device Farm Calibration Workbench

Interactive UI for calibrating device coordinate profiles:
- Display device screenshot
- Click to capture coordinates
- Define semantic points (e.g., "publish_button", "title_field")
- Test points via CH9329
- Save calibration profile
"""

from __future__ import annotations

import sys
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any
from io import BytesIO

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from PIL import Image

from pixelle_video.device_farm.registry.device_registry import DeviceRegistry, DeviceStatus
from pixelle_video.device_farm.hardware.ch9329_controller import (
    scan_com_ports,
    connect_ch9329,
    test_tap,
)

st.set_page_config(page_title="设备校准", page_icon="🎯", layout="wide")

# Initialize session state
if "calibration_points" not in st.session_state:
    st.session_state.calibration_points = {}
if "selected_device" not in st.session_state:
    st.session_state.selected_device = None
if "screenshot_data" not in st.session_state:
    st.session_state.screenshot_data = None
if "test_screenshot_data" not in st.session_state:
    st.session_state.test_screenshot_data = None


def get_device_screenshot(adb_serial: str) -> Optional[bytes]:
    """Capture screenshot from device via ADB."""
    try:
        from pixelle_video.services.device_manager import device_manager

        # Get screenshot using device manager
        screenshot_bytes = device_manager.get_screenshot(adb_serial)
        return screenshot_bytes
    except Exception as e:
        st.error(f"截图失败: {e}")
        return None


def save_calibration_profile(device_id: str, points: Dict[str, Any]) -> bool:
    """Save calibration profile to YAML file."""
    try:
        profile_dir = _PROJECT_ROOT / "config" / "profiles"
        profile_dir.mkdir(parents=True, exist_ok=True)

        profile_path = profile_dir / f"{device_id}.yaml"

        import yaml
        with open(profile_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(points, f, default_flow_style=False, allow_unicode=True)

        return True
    except Exception as e:
        st.error(f"保存配置文件失败: {e}")
        return False


def load_calibration_profile(device_id: str) -> Optional[Dict[str, Any]]:
    """Load calibration profile from YAML file."""
    try:
        profile_path = _PROJECT_ROOT / "config" / "profiles" / f"{device_id}.yaml"

        if not profile_path.exists():
            return None

        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        st.error(f"加载配置文件失败: {e}")
        return None


def main():
    st.title("🎯 设备校准工作台")
    st.markdown("为 CH9329 设备创建和测试坐标校准配置")

    # Initialize device registry
    registry = DeviceRegistry()
    devices = registry.list_devices(include_disabled=False)

    if not devices:
        st.warning("⚠️ 没有注册的设备。请先在设备管理页面注册设备。")
        return

    # Device selection
    col1, col2 = st.columns([2, 1])

    with col1:
        device_options = {f"{d.name} ({d.phone_id})": d for d in devices}
        selected_name = st.selectbox(
            "选择设备",
            options=list(device_options.keys()),
            key="device_selector"
        )

        if selected_name:
            st.session_state.selected_device = device_options[selected_name]

    with col2:
        if st.button("🔄 刷新设备列表", use_container_width=True):
            registry.reload()
            st.rerun()

    if not st.session_state.selected_device:
        return

    device = st.session_state.selected_device

    # Display device info
    st.markdown("---")
    col_info1, col_info2, col_info3 = st.columns(3)

    with col_info1:
        st.metric("设备名称", device.name)
        st.metric("ADB 序列号", device.adb_serial)

    with col_info2:
        st.metric("CH9329 端口", device.ch9329_port)
        st.metric("屏幕分辨率", f"{device.screen['width']}x{device.screen['height']}")

    with col_info3:
        st.metric("状态", device.status.value)
        if device.calibration_profile:
            st.metric("校准配置", device.calibration_profile)
        else:
            st.warning("未校准")

    # Load existing profile if available
    if device.calibration_profile:
        existing_profile = load_calibration_profile(device.phone_id)
        if existing_profile and not st.session_state.calibration_points:
            st.session_state.calibration_points = existing_profile

    st.markdown("---")

    # Main workflow tabs
    tab1, tab2, tab3 = st.tabs(["📸 截图与标注", "🧪 测试点位", "💾 保存配置"])

    with tab1:
        st.subheader("截图与坐标标注")

        col_capture, col_display = st.columns([1, 3])

        with col_capture:
            if st.button("📸 捕获截图", use_container_width=True):
                with st.spinner("正在截图..."):
                    screenshot_bytes = get_device_screenshot(device.adb_serial)
                    if screenshot_bytes:
                        st.session_state.screenshot_data = screenshot_bytes
                        st.success("截图成功！")

            st.markdown("---")
            st.markdown("**添加标注点**")

            point_name = st.text_input(
                "点位名称",
                placeholder="例如: publish_button",
                key="point_name_input"
            )

            point_desc = st.text_input(
                "点位描述",
                placeholder="例如: 发布按钮",
                key="point_desc_input"
            )

            col_x, col_y = st.columns(2)
            with col_x:
                point_x = st.number_input("X 坐标", min_value=0, max_value=device.screen['width'], value=0, key="point_x")
            with col_y:
                point_y = st.number_input("Y 坐标", min_value=0, max_value=device.screen['height'], value=0, key="point_y")

            if st.button("➕ 添加点位", use_container_width=True):
                if not point_name:
                    st.error("请输入点位名称")
                elif point_name in st.session_state.calibration_points:
                    st.error(f"点位 '{point_name}' 已存在")
                else:
                    st.session_state.calibration_points[point_name] = {
                        "x": int(point_x),
                        "y": int(point_y),
                        "description": point_desc or point_name,
                        "x_ratio": round(point_x / device.screen['width'], 4),
                        "y_ratio": round(point_y / device.screen['height'], 4),
                    }
                    st.success(f"✅ 已添加点位: {point_name}")
                    st.rerun()

        with col_display:
            if st.session_state.screenshot_data:
                try:
                    img = Image.open(BytesIO(st.session_state.screenshot_data))

                    # Display screenshot
                    st.image(img, caption=f"设备截图 - {device.name}", use_container_width=True)

                    # Display image info
                    st.caption(f"图像尺寸: {img.width}x{img.height} | 设备分辨率: {device.screen['width']}x{device.screen['height']}")

                    # Note about clicking
                    st.info("💡 提示: 使用图像查看器或外部工具获取精确坐标，然后在左侧输入框中添加点位。")

                except Exception as e:
                    st.error(f"显示截图失败: {e}")
            else:
                st.info("👈 点击左侧「捕获截图」按钮开始")

        # Display current calibration points
        if st.session_state.calibration_points:
            st.markdown("---")
            st.subheader("当前标注点位")

            for point_name, point_data in st.session_state.calibration_points.items():
                col_point, col_delete = st.columns([5, 1])

                with col_point:
                    st.markdown(
                        f"**{point_name}** - {point_data.get('description', '')}  \n"
                        f"坐标: ({point_data['x']}, {point_data['y']}) | "
                        f"比例: ({point_data['x_ratio']:.4f}, {point_data['y_ratio']:.4f})"
                    )

                with col_delete:
                    if st.button("🗑️", key=f"delete_{point_name}"):
                        del st.session_state.calibration_points[point_name]
                        st.rerun()

    with tab2:
        st.subheader("测试点位")
        st.markdown("通过 CH9329 实际点击测试标注的坐标是否准确")

        if not st.session_state.calibration_points:
            st.warning("⚠️ 请先在「截图与标注」标签页添加点位")
        else:
            col_test1, col_test2 = st.columns([1, 2])

            with col_test1:
                test_point = st.selectbox(
                    "选择要测试的点位",
                    options=list(st.session_state.calibration_points.keys()),
                    key="test_point_selector"
                )

                if test_point:
                    point_data = st.session_state.calibration_points[test_point]
                    st.info(
                        f"**{test_point}**\n\n"
                        f"描述: {point_data.get('description', '')}\n\n"
                        f"坐标: ({point_data['x']}, {point_data['y']})\n\n"
                        f"比例: ({point_data['x_ratio']:.4f}, {point_data['y_ratio']:.4f})"
                    )

                st.markdown("---")

                if st.button("🎯 执行测试点击", use_container_width=True, type="primary"):
                    if test_point:
                        point_data = st.session_state.calibration_points[test_point]

                        with st.spinner(f"正在点击 {test_point}..."):
                            # Connect to CH9329
                            ser = connect_ch9329(device.ch9329_port)

                            if ser:
                                # Execute tap using ratio coordinates
                                success = test_tap(
                                    ser,
                                    x_ratio=point_data['x_ratio'],
                                    y_ratio=point_data['y_ratio']
                                )

                                ser.close()

                                if success:
                                    st.success(f"✅ 点击 {test_point} 成功！")
                                else:
                                    st.error("❌ 点击失败")
                            else:
                                st.error(f"❌ 无法连接到 CH9329 端口: {device.ch9329_port}")

                st.markdown("---")

                if st.button("📸 捕获测试后截图", use_container_width=True):
                    with st.spinner("正在截图..."):
                        screenshot_bytes = get_device_screenshot(device.adb_serial)
                        if screenshot_bytes:
                            st.session_state.test_screenshot_data = screenshot_bytes
                            st.success("截图成功！")

            with col_test2:
                st.markdown("**对比视图**")

                col_before, col_after = st.columns(2)

                with col_before:
                    st.markdown("**点击前**")
                    if st.session_state.screenshot_data:
                        img = Image.open(BytesIO(st.session_state.screenshot_data))
                        st.image(img, use_container_width=True)
                    else:
                        st.info("无截图")

                with col_after:
                    st.markdown("**点击后**")
                    if st.session_state.test_screenshot_data:
                        img = Image.open(BytesIO(st.session_state.test_screenshot_data))
                        st.image(img, use_container_width=True)
                    else:
                        st.info("无截图")

    with tab3:
        st.subheader("保存校准配置")

        if not st.session_state.calibration_points:
            st.warning("⚠️ 没有可保存的点位数据")
        else:
            st.markdown(f"**设备:** {device.name} ({device.phone_id})")
            st.markdown(f"**点位数量:** {len(st.session_state.calibration_points)}")

            # Display profile preview
            with st.expander("📄 查看配置文件预览", expanded=True):
                import yaml
                profile_yaml = yaml.safe_dump(
                    st.session_state.calibration_points,
                    default_flow_style=False,
                    allow_unicode=True
                )
                st.code(profile_yaml, language="yaml")

            col_save1, col_save2 = st.columns(2)

            with col_save1:
                if st.button("💾 保存配置文件", use_container_width=True, type="primary"):
                    if save_calibration_profile(device.phone_id, st.session_state.calibration_points):
                        # Update device registry
                        registry.update_device(
                            device.phone_id,
                            calibration_profile=device.phone_id,
                            status=DeviceStatus.IDLE
                        )
                        st.success(f"✅ 配置已保存到: config/profiles/{device.phone_id}.yaml")
                    else:
                        st.error("❌ 保存失败")

            with col_save2:
                if st.button("🗑️ 清空当前点位", use_container_width=True):
                    st.session_state.calibration_points = {}
                    st.rerun()


if __name__ == "__main__":
    main()
