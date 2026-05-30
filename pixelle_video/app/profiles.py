from __future__ import annotations

from enum import StrEnum


class RunProfile(StrEnum):
    LOCAL_UI = "local_ui"
    API_SERVER = "api_server"
    WORKER = "worker"
    CLI = "cli"
    DEV = "dev"
    TEST = "test"

    @classmethod
    def coerce(cls, value: "RunProfile | str") -> "RunProfile":
        if isinstance(value, cls):
            return value
        return cls(str(value).lower())
