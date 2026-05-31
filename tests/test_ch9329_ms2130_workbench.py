import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script_module():
    script = REPO_ROOT / "scripts" / "ch9329_visual_debug.py"
    spec = importlib.util.spec_from_file_location("ch9329_visual_debug", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_script_exposes_ms2130_label_text():
    module = load_script_module()

    assert hasattr(module, "OBSERVATION_LABEL")
    assert "MS2130" in module.OBSERVATION_LABEL
    assert "ADB" not in module.OBSERVATION_LABEL


def test_script_imports_ms2130_provider_symbol():
    module = load_script_module()

    assert hasattr(module, "MS2130FrameProvider")
