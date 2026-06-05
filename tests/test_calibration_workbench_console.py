from pathlib import Path
from types import SimpleNamespace

import pytest

from pixelle_video.device_farm.calibration import workbench as workbench_module
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench


class FakeCH9329:
    def __init__(self):
        self.click_calls = []
        self.swipe_calls = []

    def click(self, x_ratio, y_ratio):
        self.click_calls.append((x_ratio, y_ratio))
        return True

    def swipe(self, x1_ratio, y1_ratio, x2_ratio, y2_ratio):
        self.swipe_calls.append((x1_ratio, y1_ratio, x2_ratio, y2_ratio))
        return True


def make_session():
    return SimpleNamespace(
        profile=SimpleNamespace(screen_width=1080, screen_height=2400),
        ch9329=FakeCH9329(),
    )


def test_console_click_defaults_to_pixels_for_one_one(capsys):
    session = make_session()

    CalibrationWorkbench()._console_click(session, "click 1 1")

    assert session.ch9329.click_calls == [(1 / 1080, 1 / 2400)]


def test_console_clickr_treats_one_one_as_ratios(capsys):
    session = make_session()

    CalibrationWorkbench()._console_click(session, "clickr 1 1")

    assert session.ch9329.click_calls == [(1.0, 1.0)]


def test_console_mixed_click_defaults_to_pixels(capsys):
    session = make_session()

    CalibrationWorkbench()._console_click(session, "click 0.5 100")

    assert session.ch9329.click_calls == [(0 / 1080, 100 / 2400)]


def test_launch_interactive_gui_reports_missing_script(monkeypatch, tmp_path):
    module_file = tmp_path / "pixelle_video" / "device_farm" / "calibration" / "workbench.py"
    monkeypatch.setattr(workbench_module, "Path", lambda _value: module_file)

    with pytest.raises(FileNotFoundError, match="Visual debugger unavailable"):
        CalibrationWorkbench().launch_interactive_gui("phone-1", "default")


def test_launch_interactive_gui_uses_existing_visual_debugger(monkeypatch, tmp_path):
    module_file = tmp_path / "pixelle_video" / "device_farm" / "calibration" / "workbench.py"
    project_root = module_file.parents[4]
    script_path = project_root / "scripts" / "ch9329_visual_debug.py"
    script_path.parent.mkdir()
    script_path.write_text("print('debugger')\n", encoding="utf-8")
    monkeypatch.setattr(workbench_module, "Path", lambda _value: module_file)
    monkeypatch.setattr("sys.executable", "python-test")
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(workbench_module.subprocess, "Popen", fake_popen)

    CalibrationWorkbench().launch_interactive_gui("phone-1", "profile-a")

    assert popen_calls[0][0] == [
        "python-test",
        str(script_path),
        "--phone_id",
        "phone-1",
        "--profile",
        "profile-a",
    ]
    assert popen_calls[0][1]["stdout"] is workbench_module.subprocess.DEVNULL


def test_visual_debugger_command_requires_existing_script(tmp_path):
    from importlib import util

    module_path = Path(__file__).resolve().parents[1] / "web" / "views" / "4_Publish.py"
    spec = util.spec_from_file_location("publish_view_for_test", module_path)
    module = util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.get_ch9329_visual_debug_command(tmp_path) is None

    script_path = tmp_path / "scripts" / "ch9329_visual_debug.py"
    script_path.parent.mkdir()
    script_path.write_text("print('debugger')\n", encoding="utf-8")

    assert module.get_ch9329_visual_debug_command(tmp_path) == "python scripts/ch9329_visual_debug.py"
