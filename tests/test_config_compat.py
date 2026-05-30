from pathlib import Path

from pixelle_video import PixelleVideoCore, config_manager as package_config_manager, pixelle_video
from pixelle_video.config import (
    ConfigManager,
    PixelleVideoConfig,
    config_manager,
    load_config_dict,
    save_config_dict,
)


def test_public_config_import_surface_is_stable():
    assert ConfigManager.__name__ == "ConfigManager"
    assert PixelleVideoConfig.__name__ == "PixelleVideoConfig"
    assert isinstance(config_manager, ConfigManager)
    assert callable(load_config_dict)
    assert callable(save_config_dict)


def test_config_manager_constructor_returns_global_singleton():
    assert ConfigManager() is config_manager
    assert ConfigManager(config_path="another-config.yaml") is config_manager


def test_missing_config_file_loads_empty_dict(tmp_path):
    missing_config_path = tmp_path / "missing-config.yaml"

    assert load_config_dict(str(missing_config_path)) == {}


def test_save_load_yaml_round_trip(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_data = {
        "project_name": "Compatibility Test",
        "llm": {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
        },
        "nested": {"list": ["a", "b"], "enabled": True},
    }

    save_config_dict(config_data, str(config_path))

    assert load_config_dict(str(config_path)) == config_data


def test_config_manager_config_is_schema_and_get_matches_to_dict():
    config = config_manager.config
    config_dict = config.to_dict()

    assert isinstance(config, PixelleVideoConfig)
    for key, value in config_dict.items():
        assert config_manager.get(key) == value


def test_public_pixelle_video_import_surface_is_stable():
    assert PixelleVideoCore.__name__ == "PixelleVideoCore"
    assert isinstance(pixelle_video, PixelleVideoCore)
    assert package_config_manager is config_manager


def test_core_initial_state_uses_dict_config_snapshot():
    core = PixelleVideoCore()

    assert isinstance(core.config, dict)
    assert core.config is not config_manager.config.to_dict()
    assert isinstance(core.project_name, str)
    assert core.llm is None
    assert core.tts is None
    assert core.media is None
    assert core.generate_video is None


def test_compute_comfykit_config_hash_is_stable_for_sorted_dicts():
    core = PixelleVideoCore()
    first = {
        "comfyui_url": "http://127.0.0.1:8188",
        "api_key": "secret",
        "runninghub_api_key": "runninghub-secret",
    }
    same_values_different_order = {
        "runninghub_api_key": "runninghub-secret",
        "api_key": "secret",
        "comfyui_url": "http://127.0.0.1:8188",
    }

    assert core._compute_comfykit_config_hash(first) == core._compute_comfykit_config_hash(
        same_values_different_order
    )


def test_config_service_delegates_to_existing_manager(monkeypatch):
    from pixelle_video.config import service as service_module

    calls = []

    class FakeManager:
        @property
        def config(self):
            calls.append("config")
            return {"project_name": "unit"}

        def get(self, key, default=None):
            calls.append(("get", key, default))
            return default

        def update(self, updates):
            calls.append(("update", updates))

        def save(self):
            calls.append("save")

        def reload(self):
            calls.append("reload")

        def validate(self):
            calls.append("validate")
            return True

    monkeypatch.setattr(service_module, "config_manager", FakeManager())

    config_service = service_module.ConfigService()

    assert config_service.config == {"project_name": "unit"}
    assert config_service.get("missing", "fallback") == "fallback"
    config_service.update({"llm": {"model": "unit"}})
    config_service.save()
    config_service.reload()
    assert config_service.validate() is True
    assert calls == [
        "config",
        ("get", "missing", "fallback"),
        ("update", {"llm": {"model": "unit"}}),
        "save",
        "reload",
        "validate",
    ]


def test_config_service_is_exported_from_config_package():
    from pixelle_video.config import ConfigService

    assert ConfigService.__name__ == "ConfigService"
