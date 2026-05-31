#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Device Health Monitor - Real-time monitoring dashboard for multi-device setup

Features:
- Real-time device status display
- Health metrics tracking
- Auto-reconnection alerts
- Connection history
- Performance statistics

Usage:
    python scripts/04_device_health_monitor.py
    python scripts/04_device_health_monitor.py --devices vivo_v2199a_001,vivo_v2199a_002
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware import ADBManager, DeviceState
from pixelle_video.device_farm.registry import DeviceRegistry


class DeviceHealthMonitor:
    """Real-time health monitoring for device farm."""

    def __init__(self, device_ids: List[str] = None):
        """
        Initialize health monitor.

        Args:
            device_ids: Optional list of device IDs to monitor (monitors all if None)
        """
        self.device_ids = device_ids
        self.registry = DeviceRegistry()
        self.manager = ADBManager(
            retry_attempts=3,
            retry_delay=2.0,
            monitor_interval=15.0,
            auto_restart_adb=True
        )

        # Event tracking
        self.events: List[Dict] = []
        self.max_events = 100

        # Register callbacks
        self.manager.register_callback('connected', self._on_connected)
        self.manager.register_callback('disconnected', self._on_disconnected)
        self.manager.register_callback('reconnected', self._on_reconnected)

    def _on_connected(self, serial: str):
        """Handle device connection."""
        self._log_event('CONNECTED', serial, '🔌 Device connected')

    def _on_disconnected(self, serial: str):
        """Handle device disconnection."""
        self._log_event('DISCONNECTED', serial, '⚠️  Device disconnected')

    def _on_reconnected(self, serial: str):
        """Handle device reconnection."""
        self._log_event('RECONNECTED', serial, '✅ Device reconnected')

    def _log_event(self, event_type: str, serial: str, message: str):
        """Log an event."""
        event = {
            'timestamp': datetime.now(),
            'type': event_type,
            'serial': serial,
            'message': message
        }
        self.events.append(event)

        # Keep only recent events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        logger.info(f"[{event_type}] {serial}: {message}")

    def start(self):
        """Start monitoring."""
        logger.info("=" * 80)
        logger.info("Device Health Monitor")
        logger.info("=" * 80)

        # Initial scan
        logger.info("\nScanning devices...")
        devices = self.manager.scan_devices_with_retry()

        if not devices:
            logger.warning("No devices found!")
            return

        logger.success(f"Found {len(devices)} device(s)")

        # Start background monitoring
        self.manager.start_monitoring()

        try:
            logger.info("\nMonitoring started. Press Ctrl+C to stop.")
            logger.info("Dashboard updates every 10 seconds...\n")

            iteration = 0
            while True:
                time.sleep(10)
                iteration += 1

                self._display_dashboard(iteration)

        except KeyboardInterrupt:
            logger.info("\n\nStopping monitor...")
        finally:
            self.manager.stop_monitoring()
            self._display_summary()

    def _display_dashboard(self, iteration: int):
        """Display real-time dashboard."""
        print("\n" + "=" * 80)
        print(f"Device Health Dashboard - Update #{iteration} - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 80)

        # Get all health status
        health_status = self.manager.get_all_health_status()

        if not health_status:
            print("No devices tracked")
            return

        # Display device status
        print("\n📱 Device Status:")
        print("-" * 80)

        for serial, health in health_status.items():
            # Get device info from registry
            device_name = serial
            try:
                device = self.registry.get_device_by_serial(serial)
                if device:
                    device_name = f"{device.name} ({serial})"
            except:
                pass

            # State indicator
            state_icon = {
                DeviceState.CONNECTED: "✅",
                DeviceState.DISCONNECTED: "❌",
                DeviceState.OFFLINE: "⚠️ ",
                DeviceState.UNAUTHORIZED: "🔒",
                DeviceState.RECONNECTING: "🔄",
                DeviceState.UNKNOWN: "❓"
            }.get(health.state, "❓")

            # Calculate uptime
            uptime_str = "N/A"
            if health.uptime_start and health.state == DeviceState.CONNECTED:
                uptime = datetime.now() - health.uptime_start
                uptime_str = self._format_timedelta(uptime)

            # Time since last seen
            last_seen = datetime.now() - health.last_seen
            last_seen_str = self._format_timedelta(last_seen)

            print(f"\n{state_icon} {device_name}")
            print(f"   State: {health.state.value.upper()}")
            print(f"   Uptime: {uptime_str}")
            print(f"   Last seen: {last_seen_str} ago")
            print(f"   Failures: {health.consecutive_failures}")
            print(f"   Reconnects: {health.total_reconnects}")

            # Health indicator
            if health.is_healthy():
                print(f"   Health: 💚 HEALTHY")
            else:
                print(f"   Health: 💔 UNHEALTHY")

        # Display recent events
        print("\n📋 Recent Events (last 5):")
        print("-" * 80)

        recent_events = self.events[-5:]
        if not recent_events:
            print("No events yet")
        else:
            for event in reversed(recent_events):
                timestamp = event['timestamp'].strftime('%H:%M:%S')
                print(f"[{timestamp}] {event['message']}")

        # Display statistics
        print("\n📊 Statistics:")
        print("-" * 80)

        total_devices = len(health_status)
        connected = sum(1 for h in health_status.values() if h.state == DeviceState.CONNECTED)
        disconnected = sum(1 for h in health_status.values() if h.state == DeviceState.DISCONNECTED)
        total_reconnects = sum(h.total_reconnects for h in health_status.values())

        print(f"Total devices: {total_devices}")
        print(f"Connected: {connected}")
        print(f"Disconnected: {disconnected}")
        print(f"Total reconnections: {total_reconnects}")

    def _display_summary(self):
        """Display final summary."""
        print("\n" + "=" * 80)
        print("Monitoring Summary")
        print("=" * 80)

        health_status = self.manager.get_all_health_status()

        if not health_status:
            print("No devices were monitored")
            return

        print(f"\nMonitored {len(health_status)} device(s):")

        for serial, health in health_status.items():
            print(f"\n{serial}:")
            print(f"  Final state: {health.state.value}")
            print(f"  Total reconnects: {health.total_reconnects}")
            print(f"  Total failures: {health.consecutive_failures}")

        print(f"\nTotal events logged: {len(self.events)}")

    @staticmethod
    def _format_timedelta(td: timedelta) -> str:
        """Format timedelta for display."""
        total_seconds = int(td.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Real-time device health monitor for multi-device setup'
    )
    parser.add_argument(
        '--devices',
        help='Comma-separated list of device IDs to monitor (monitors all if not specified)'
    )

    args = parser.parse_args()

    device_ids = None
    if args.devices:
        device_ids = [d.strip() for d in args.devices.split(',')]

    monitor = DeviceHealthMonitor(device_ids=device_ids)
    monitor.start()

    return 0


if __name__ == "__main__":
    sys.exit(main())
