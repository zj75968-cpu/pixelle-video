"""Minimal configuration service facade."""


class ConfigService:
    """Small facade that delegates configuration operations to ConfigManager."""

    def __init__(self, manager=None):
        if manager is None:
            from pixelle_video.config import config_manager as manager

        self._manager = manager

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
