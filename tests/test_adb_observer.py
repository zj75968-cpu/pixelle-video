import subprocess
from pathlib import Path

import pytest

from pixelle_video.device_farm.hardware import adb_observer
from pixelle_video.device_farm.hardware.adb_observer import ADBError


def test_resolve_adb_executable_prefers_pixelle_adb_path(monkeypatch, tmp_path):
    adb_path = tmp_path / "adb.exe"
    adb_path.write_text("adb")
    monkeypatch.setenv("PIXELLE_ADB_PATH", str(adb_path))
    monkeypatch.setattr(adb_observer.shutil, "which", lambda _name: None)

    assert adb_observer._resolve_adb_executable() == str(adb_path)


def test_resolve_adb_executable_rejects_missing_pixelle_adb_path(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-adb.exe"
    monkeypatch.setenv("PIXELLE_ADB_PATH", str(missing_path))

    with pytest.raises(ADBError) as excinfo:
        adb_observer._resolve_adb_executable()

    message = str(excinfo.value)
    assert "PIXELLE_ADB_PATH" in message
    assert str(missing_path) in message


def test_resolve_adb_executable_uses_path_from_shutil_which(monkeypatch):
    monkeypatch.delenv("PIXELLE_ADB_PATH", raising=False)
    monkeypatch.setattr(adb_observer.shutil, "which", lambda name: "/usr/bin/adb" if name == "adb" else None)

    assert adb_observer._resolve_adb_executable() == "/usr/bin/adb"


def test_resolve_adb_executable_uses_windows_winget_platformtools_fallback(monkeypatch, tmp_path):
    localappdata = tmp_path / "LocalAppData"
    adb_path = (
        localappdata
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "platform-tools"
        / "adb.exe"
    )
    adb_path.parent.mkdir(parents=True)
    adb_path.write_text("adb")

    monkeypatch.delenv("PIXELLE_ADB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setattr(adb_observer.shutil, "which", lambda _name: None)

    assert adb_observer._resolve_adb_executable() == str(adb_path)


def test_run_adb_command_uses_resolved_executable(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(adb_observer, "_resolve_adb_executable", lambda: "/opt/platform-tools/adb")
    monkeypatch.setattr(adb_observer.subprocess, "run", fake_run)

    assert adb_observer._run_adb_command(["devices", "-l"], timeout=7) == (0, "ok", "")
    assert calls[0][0] == ["/opt/platform-tools/adb", "devices", "-l"]
    assert calls[0][1]["timeout"] == 7
    assert calls[0][1]["text"] is True


def test_capture_screenshot_binary_call_uses_resolved_executable(monkeypatch):
    calls = []
    png_data = b"\x89PNG\r\n\x1a\n" + b"0" * 128

    class TextResult:
        returncode = 0
        stdout = ""
        stderr = ""

    class BinaryResult:
        returncode = 0
        stdout = png_data
        stderr = b""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return TextResult() if kwargs.get("text") else BinaryResult()

    monkeypatch.setattr(adb_observer, "_resolve_adb_executable", lambda: "C:/Android/platform-tools/adb.exe")
    monkeypatch.setattr(adb_observer.subprocess, "run", fake_run)

    assert adb_observer.capture_screenshot("10ACBE28M70044L") == png_data
    assert calls[1][0] == [
        "C:/Android/platform-tools/adb.exe",
        "-s",
        "10ACBE28M70044L",
        "exec-out",
        "screencap",
        "-p",
    ]
    assert calls[1][1]["capture_output"] is True
    assert calls[1][1]["timeout"] == 30
