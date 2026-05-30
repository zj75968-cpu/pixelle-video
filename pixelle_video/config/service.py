"""Minimal configuration service facade."""

from .manager import ConfigManager


config_manager = ConfigManager()


class ConfigService:
    """Small facade that delegates configuration operations to ConfigManager."""

    def __init__(self, manager=None):
        self._manager = manager or config_manager

    @property
    def config(self):
        return self._manager.config

    def get(self, key, default=None):
        return self._manager.get(key, default)

    def update(self, updates):
        return self._manager.update(updates)

    def save(self):
        return self._manager.save()

    def reload(self):
        return self._manager.reload()

    def validate(self):
        return self._manager.validate()
