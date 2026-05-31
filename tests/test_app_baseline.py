from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import types


def test_run_profile_values_match_design() -> None:
    from pixelle_video.app.profiles import RunProfile

    assert RunProfile.LOCAL_UI == "local_ui"
    assert RunProfile.API_SERVER == "api_server"
    assert RunProfile.WORKER == "worker"
    assert RunProfile.CLI == "cli"
    assert RunProfile.DEV == "dev"
    assert RunProfile.TEST == "test"
    assert [profile.value for profile in RunProfile] == [
        "local_ui",
        "api_server",
        "worker",
        "cli",
        "dev",
        "test",
    ]


def test_run_profile_coerces_strings_and_instances() -> None:
    from pixelle_video.app.profiles import RunProfile

    assert RunProfile.coerce("LOCAL_UI") is RunProfile.LOCAL_UI
    assert RunProfile.coerce("api_server") is RunProfile.API_SERVER
    assert RunProfile.coerce(RunProfile.WORKER) is RunProfile.WORKER


def test_app_context_carries_baseline_fields() -> None:
    from pixelle_video.app.context import AppContext
    from pixelle_video.app.profiles import RunProfile

    project_root = Path("/project")
    data_dir = Path("/project/data")
    output_dir = Path("/project/output")

    context = AppContext(
        profile=RunProfile.LOCAL_UI,
        project_root=project_root,
        data_dir=data_dir,
        output_dir=output_dir,
    )

    assert context.profile is RunProfile.LOCAL_UI
    assert context.project_root == project_root
    assert context.data_dir == data_dir
    assert context.output_dir == output_dir
    assert context.user == "default"


def test_app_package_exports_baseline_types() -> None:
    from pixelle_video.app import AppContext, RunProfile
    from pixelle_video.app.context import AppContext as ContextModuleAppContext
    from pixelle_video.app.profiles import RunProfile as ProfilesModuleRunProfile

    assert AppContext is ContextModuleAppContext
    assert RunProfile is ProfilesModuleRunProfile


def test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb(monkeypatch) -> None:
    class StreamlitStub(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.session_state = {}
            self.clicked_buttons: set[str] = set()
            self.rendered: dict[str, list[str]] = {
                "error": [],
                "info": [],
                "warning": [],
                "markdown": [],
                "caption": [],
                "text": [],
                "text_input": [],
                "number_input": [],
                "button": [],
                "tabs": [],
            }

        def _record(self, collection: str, rendered_value="", *args, **kwargs):
            text = str(rendered_value or "")
            self.rendered[collection].append(text)
            if collection in {"text_input", "number_input"}:
                placeholder = kwargs.get("placeholder")
                if placeholder:
                    self.rendered[collection].append(str(placeholder))
            if collection == "button":
                key = kwargs.get("key") or text
                return key in self.clicked_buttons
            if collection == "text_input":
                return kwargs.get("value", "")
            if collection == "number_input":
                return kwargs.get("value", 0)
            return None

        def error(self, value="", *args, **kwargs):
            return self._record("error", value, *args, **kwargs)

        def info(self, value="", *args, **kwargs):
            return self._record("info", value, *args, **kwargs)

        def warning(self, value="", *args, **kwargs):
            return self._record("warning", value, *args, **kwargs)

        def markdown(self, value="", *args, **kwargs):
            return self._record("markdown", value, *args, **kwargs)

        def caption(self, value="", *args, **kwargs):
            return self._record("caption", value, *args, **kwargs)

        def subheader(self, value="", *args, **kwargs):
            return self._record("markdown", value, *args, **kwargs)

        def success(self, value="", *args, **kwargs):
            return self._record("markdown", value, *args, **kwargs)

        def toggle(self, label="", *args, **kwargs):
            self.rendered["button"].append(str(label or ""))
            return kwargs.get("value", False)

        def text(self, value="", *args, **kwargs):
            return self._record("text", value, *args, **kwargs)

        def text_input(self, label="", *args, **kwargs):
            return self._record("text_input", label, *args, **kwargs)

        def number_input(self, label="", *args, **kwargs):
            return self._record("number_input", label, *args, **kwargs)

        def button(self, label="", *args, **kwargs):
            return self._record("button", label, *args, **kwargs)

        def download_button(self, label="", *args, **kwargs):
            return self._record("button", label, *args, **kwargs)

        def form_submit_button(self, label="", *args, **kwargs):
            return self._record("button", label, *args, **kwargs)

        def tabs(self, labels):
            self.rendered["tabs"].extend(str(label) for label in labels)
            return [self for _ in labels]

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [self for _ in range(count)]

        def form(self, *args, **kwargs):
            return self

        def expander(self, *args, **kwargs):
            return self

        def container(self, *args, **kwargs):
            return self

        def fragment(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def set_page_config(self, *args, **kwargs):
            return None

        def rerun(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class DeviceManagerStub:
        def check_adb_available(self):
            return False

        def list_connected_serials(self):
            return []

        def get_all(self):
            return []

    st_stub = StreamlitStub()
    monkeypatch.setitem(sys.modules, "streamlit", st_stub)

    module_path = Path(__file__).resolve().parents[1] / "web" / "views" / "4_Publish.py"
    spec = importlib.util.spec_from_file_location("publish_view_for_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.get_device_manager = lambda: DeviceManagerStub()

    module.render_devices_tab()

    rendered_text = "\n".join(
        item
        for values in st_stub.rendered.values()
        for item in values
    )

    for legacy in [
        "ADB 环境问题",
        "ADB environment",
        "ADB Server 设置",
        "USB 调试",
        "adb devices",
        "无线配对",
        "ADB 端口",
        "WiFi",
        "Android 调试工具",
    ]:
        assert legacy not in rendered_text

    assert "CH9329" in rendered_text
    assert "COM" in rendered_text
    assert "CH9329 串口设置" in rendered_text
    assert "波特率" in st_stub.rendered["number_input"]


def test_publish_settings_save_ch9329_serial_config_uses_baudrate_schema(monkeypatch) -> None:
    class StreamlitStub(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.session_state = {}
            self.clicked_buttons = {"save_ch9329_serial_settings"}
            self.rerun_called = False

        def set_page_config(self, *args, **kwargs):
            return None

        def fragment(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def expander(self, *args, **kwargs):
            return self

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [self for _ in range(count)]

        def markdown(self, *args, **kwargs):
            return None

        def caption(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
            return None

        def success(self, *args, **kwargs):
            return None

        def toggle(self, label="", *args, **kwargs):
            return kwargs.get("value", False)

        def text_input(self, label="", *args, **kwargs):
            if kwargs.get("key") == "ch9329_com_port_input":
                return "COM7"
            return kwargs.get("value", "")

        def number_input(self, label="", *args, **kwargs):
            if kwargs.get("key") == "ch9329_baudrate_input":
                return 115200
            return kwargs.get("value", 0)

        def button(self, label="", *args, **kwargs):
            key = kwargs.get("key") or str(label)
            return key in self.clicked_buttons

        def rerun(self):
            self.rerun_called = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class DeviceManagerStub:
        def __init__(self):
            self.added = []

        def add_device(self, **kwargs):
            self.added.append(kwargs)

    class ConfigManagerStub:
        def __init__(self):
            hardware = types.SimpleNamespace(com_port="COM3", baudrate=9600)
            self.config = types.SimpleNamespace(
                xhs_publish=types.SimpleNamespace(
                    strict_mode=True,
                    push_dir="/sdcard/DCIM/PixelleVideo",
                    hardware=hardware,
                )
            )
            self.updated = []
            self.saved = False

        def update(self, data):
            self.updated.append(data)

        def save(self):
            self.saved = True

    st_stub = StreamlitStub()
    monkeypatch.setitem(sys.modules, "streamlit", st_stub)

    config_manager_stub = ConfigManagerStub()
    import pixelle_video.config as config_module

    monkeypatch.setattr(config_module, "config_manager", config_manager_stub)
    device_manager_stub = DeviceManagerStub()

    module_path = Path(__file__).resolve().parents[1] / "web" / "views" / "4_Publish.py"
    spec = importlib.util.spec_from_file_location("publish_view_settings_for_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.get_device_manager = lambda: device_manager_stub

    module.render_publish_settings()

    assert config_manager_stub.updated[-1] == {
        "xhs_publish": {"hardware": {"com_port": "COM7", "baudrate": 115200}}
    }
    assert config_manager_stub.saved is True
    assert device_manager_stub.added[-1]["serial"] == "COM7"
    assert "baudrate=115200" in device_manager_stub.added[-1]["notes"]
    assert st_stub.rerun_called is True


def test_api_lifecycle_uses_canonical_run_profile() -> None:
    from api.lifecycle import RunProfile as LifecycleRunProfile
    from pixelle_video.app.profiles import RunProfile

    assert LifecycleRunProfile is RunProfile
