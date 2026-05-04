#!/usr/bin/env python3
"""
ADB Diagnostic Script

Run this script to check if ADB is properly configured and if any Android devices are connected.
Usage: python check_adb.py
"""

import subprocess
import sys
from pathlib import Path


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def check_adb_available():
    """Check if ADB is available in PATH."""
    print_header("1️⃣  Checking ADB Availability")
    try:
        result = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ ADB found and working!\n")
            print(result.stdout)
            return True
        else:
            print("❌ ADB found but returned an error:")
            print(result.stderr)
            return False
    except FileNotFoundError:
        print("❌ ADB not found in PATH")
        print("\n📥 How to fix:")
        print("   1. Download Android SDK Platform-Tools from:")
        print("      https://developer.android.google.cn/studio/releases/platform-tools")
        print("   2. Extract to a local folder")
        print("   3. Add the folder to your system PATH environment variable")
        print("   4. Restart your terminal and this script")
        return False
    except subprocess.TimeoutExpired:
        print("❌ ADB command timed out")
        return False
    except Exception as e:
        print(f"❌ Error checking ADB: {e}")
        return False


def check_connected_devices():
    """Check for connected Android devices."""
    print_header("2️⃣  Checking Connected Devices")
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        print(result.stdout)
        
        # Parse devices
        devices = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                if parts[1] == "device":
                    devices.append((parts[0], "✅ Connected"))
                elif parts[1] == "offline":
                    devices.append((parts[0], "⏸️  Offline"))
                elif parts[1] == "unauthorized":
                    devices.append((parts[0], "🔐 Unauthorized (tap 'Allow' on device)"))
                else:
                    devices.append((parts[0], f"❓ {parts[1]}"))
        
        if devices:
            print("📊 Device Summary:")
            for serial, status in devices:
                print(f"   {status}  {serial}")
        else:
            print("⚠️  No devices detected\n")
            print("📱 Troubleshooting:")
            print("   1. Connect your Android device via USB")
            print("   2. Enable Developer Mode (tap Build Number 7 times in Settings)")
            print("   3. Enable USB Debugging in Developer Options")
            print("   4. Check if a 'Allow USB Debugging?' dialog appears on the device")
            print("   5. If yes, tap 'Always allow from this computer'")
            print("   6. Run this script again\n")
            print("   💡 For WiFi connection:")
            print("      adb connect <device-ip>:5555")
        
        return len(devices) > 0
    except FileNotFoundError:
        print("❌ ADB not found (already checked above)")
        return False
    except Exception as e:
        print(f"❌ Error listing devices: {e}")
        return False


def check_pixelle_video_devices():
    """Check what Pixelle-Video has registered."""
    print_header("3️⃣  Pixelle-Video Device Registry")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from pixelle_video.services.device_manager import device_manager
        
        devices = device_manager.get_all()
        if devices:
            print(f"📋 Registered devices ({len(devices)}):\n")
            for dev in devices:
                status_icon = "🟢" if dev.connected else "🔴"
                print(f"   {status_icon} {dev.serial}")
                print(f"      Name: {dev.name or '(no name)'}")
                print(f"      Theme: {dev.theme or '(no theme)'}")
                print(f"      Last seen: {dev.last_seen or '(never)'}")
                print()
        else:
            print("⚠️  No devices registered yet\n")
            print("ℹ️  You'll need to manually register devices or connect them via USB first.")
    except Exception as e:
        print(f"⚠️  Could not load Pixelle-Video device manager: {e}")


def main():
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*15 + "Pixelle-Video ADB Diagnostic Tool" + " "*10 + "║")
    print("╚" + "="*58 + "╝")
    
    adb_ok = check_adb_available()
    
    if adb_ok:
        devices_ok = check_connected_devices()
    else:
        devices_ok = False
    
    check_pixelle_video_devices()
    
    print_header("Summary")
    print(f"ADB Available:      {'✅ Yes' if adb_ok else '❌ No'}")
    print(f"Devices Connected:  {'✅ Yes' if devices_ok else '⚠️  No'}")
    print("\n💡 Next Steps:")
    if not adb_ok:
        print("   1. Install Android SDK Platform-Tools")
        print("   2. Add it to your system PATH")
        print("   3. Restart this script")
    elif not devices_ok:
        print("   1. Connect your Android device via USB or WiFi")
        print("   2. Ensure Developer Mode and USB Debugging are enabled")
        print("   3. Authorize USB Debugging on the device")
        print("   4. Restart this script")
    else:
        print("   All set! Your devices are ready to use with Pixelle-Video")
    
    print("\n")


if __name__ == "__main__":
    main()
