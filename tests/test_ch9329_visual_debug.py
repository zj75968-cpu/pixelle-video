import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path("F:/codex project/小红书/scripts/ch9329_visual_debug.py")


def load_module():
    spec = importlib.util.spec_from_file_location("ch9329_visual_debug_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.config_calls = []
        self.values = None

    def config(self, **kwargs):
        self.config_calls.append(kwargs)

    def __setitem__(self, key, value):
        if key == "values":
            self.values = value
        else:
            setattr(self, key, value)


class FakeCanvas:
    def __init__(self):
        self.deleted = []
        self.lines = []

    def delete(self, item):
        self.deleted.append(item)

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return 123


class FakeImage:
    def __init__(self, width=100, height=200):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class DummyApp:
    def __init__(self):
        self.selected_port = Var("COM9")
        self.selected_serial = Var("")
        self.screen_width = Var(1080)
        self.screen_height = Var(2400)
        self.cb_baud = Var("115200")
        self.controller = None
        self.lbl_fps = Widget()
        self.btn_refresh_ss = Widget()
        self.cb_devices = Widget()
        self.raw_image = object()
        self.tk_image = FakeImage()
        self.img_offset_x = 0
        self.img_offset_y = 0
        self.canvas = FakeCanvas()
        self.selected_x_ratio = 0
        self.selected_y_ratio = 0
        self.selected_x = 0
        self.selected_y = 0
        self.lbl_click_coords = Widget()
        self.point_name = Var("")
        self.point_desc = Var("")
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_line_id = None
        self.auto_refresh_var = Var(False)
        self.after_calls = []
        self.refresh_calls = 0
        self.loaded_profile = False

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def load_calibration_profile(self):
        self.loaded_profile = True

    def manual_refresh_screenshot(self):
        self.refresh_calls += 1

    def draw_target_crosshair(self, *args):
        pass


def bind(app, module, name):
    return getattr(module.VisualDebuggerApp, name).__get__(app, app.__class__)


def test_connect_hardware_does_not_require_adb_serial_and_passes_selected_baud(monkeypatch):
    module = load_module()
    created = []

    class Controller:
        def __init__(self, *, port, baudrate):
            self.port = port
            self.baudrate = baudrate
            self.screen_width = None
            self.screen_height = None
            created.append(self)

        def connect(self):
            return True

        def disconnect(self):
            pass

    errors = []
    infos = []
    monkeypatch.setattr(module, "CH9329Controller", Controller)
    monkeypatch.setattr(module.messagebox, "showerror", lambda *args: errors.append(args))
    monkeypatch.setattr(module.messagebox, "showinfo", lambda *args: infos.append(args))

    app = DummyApp()
    bind(app, module, "connect_hardware")()

    assert errors == []
    assert created[0].port == "COM9"
    assert created[0].baudrate == 115200
    assert app.controller is created[0]
    assert app.loaded_profile is True


def test_failed_connect_clears_controller(monkeypatch):
    module = load_module()

    class Controller:
        def __init__(self, *, port, baudrate):
            pass

        def connect(self):
            return False

        def disconnect(self):
            pass

    monkeypatch.setattr(module, "CH9329Controller", Controller)
    monkeypatch.setattr(module.messagebox, "showerror", lambda *args: None)

    app = DummyApp()
    bind(app, module, "connect_hardware")()

    assert app.controller is None


def test_scan_adb_clears_stale_selected_serial_when_no_online_devices(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "scan_adb_devices", lambda: [SimpleNamespace(serial="offline-1", status="offline")])

    app = DummyApp()
    app.selected_serial.set("stale-serial")
    bind(app, module, "scan_adb")()

    assert app.selected_serial.get() == ""
    assert app.cb_devices.values == []


def test_canvas_drag_does_not_start_physical_click(monkeypatch):
    module = load_module()
    started_threads = []

    class Thread:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))
        def start(self):
            pass

    monkeypatch.setattr(module.threading, "Thread", Thread)
    app = DummyApp()
    app.controller = object()
    app._physical_click_worker = module.VisualDebuggerApp._physical_click_worker.__get__(app, app.__class__)
    app._physical_swipe_worker = module.VisualDebuggerApp._physical_swipe_worker.__get__(app, app.__class__)

    bind(app, module, "on_canvas_click")(SimpleNamespace(x=10, y=10))
    bind(app, module, "on_canvas_drag")(SimpleNamespace(x=80, y=80))
    bind(app, module, "on_canvas_release")(SimpleNamespace(x=90, y=90))

    assert len(started_threads) == 1
    assert started_threads[0][1]["target"].__name__ == "_physical_swipe_worker"


def test_canvas_click_without_drag_sends_one_physical_click(monkeypatch):
    module = load_module()
    started_threads = []

    class Thread:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))
        def start(self):
            pass

    monkeypatch.setattr(module.threading, "Thread", Thread)
    app = DummyApp()
    app.controller = object()
    app._physical_click_worker = module.VisualDebuggerApp._physical_click_worker.__get__(app, app.__class__)
    app._physical_swipe_worker = module.VisualDebuggerApp._physical_swipe_worker.__get__(app, app.__class__)

    bind(app, module, "on_canvas_click")(SimpleNamespace(x=10, y=10))
    bind(app, module, "on_canvas_release")(SimpleNamespace(x=12, y=12))

    assert len(started_threads) == 1
    assert started_threads[0][1]["target"].__name__ == "_physical_click_worker"


def test_swipe_delegates_to_controller_swipe():
    module = load_module()
    calls = []

    class Controller:
        screen_width = 1080
        screen_height = 2400
        def swipe(self, *args, **kwargs):
            calls.append((args, kwargs))
            return True

    app = DummyApp()
    app.controller = Controller()

    result = bind(app, module, "ch9329_swipe_gesture")(0.1, 0.2, 0.8, 0.9, duration=1.2)

    assert result is True
    assert calls == [((0.1, 0.2, 0.8, 0.9), {"duration": 1.2})]


def test_hardware_workers_schedule_refresh_on_tk_thread(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    class Controller:
        def click(self, *args):
            pass

    app = DummyApp()
    app.controller = Controller()

    bind(app, module, "_physical_click_worker")(0.5, 0.5)

    assert app.refresh_calls == 0
    assert len(app.after_calls) == 1
    assert app.after_calls[0][0] == 0
