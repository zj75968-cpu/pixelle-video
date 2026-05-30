from fastapi.testclient import TestClient

from api.config import api_config


def test_create_app_test_profile_exposes_pure_health_endpoints():
    from api.app import create_app

    app = create_app(profile="test")

    with TestClient(app) as client:
        health = client.get("/health")
        version = client.get("/version")

    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "version": "0.1.0",
        "service": "Pixelle-Video API",
    }
    assert version.status_code == 200
    assert version.json() == health.json()


def test_create_app_test_profile_root_metadata_matches_existing_shape():
    from api.app import create_app

    app = create_app(profile="test")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "Pixelle-Video API"
    assert payload["version"] == "0.1.0"
    assert payload["docs"] == api_config.docs_url
    assert payload["health"] == "/health"
    assert payload["api"]["llm"] == f"{api_config.api_prefix}/llm"
    assert payload["api"]["publish"] == f"{api_config.api_prefix}/publish"


def test_create_app_preserves_route_prefixes():
    from api.app import create_app

    app = create_app(profile="test")
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/health" in paths
    assert "/version" in paths
    assert f"{api_config.api_prefix}/tasks" in paths
    assert f"{api_config.api_prefix}/devices" in paths
    assert f"{api_config.api_prefix}/publish/agent/pending" in paths
    assert "/webhooks/runninghub" in paths


def test_create_lifespan_returns_none_for_test_profile():
    from api.app import create_lifespan

    assert create_lifespan("test") is None


def test_create_app_test_profile_disables_lifespan_side_effects(monkeypatch):
    import api.app as app_module
    from api.app import create_app

    calls = []

    async def fake_start(profile):
        calls.append(("start", profile))

    async def fake_stop(profile):
        calls.append(("stop", profile))

    monkeypatch.setattr(app_module, "start_app_lifecycle", fake_start)
    monkeypatch.setattr(app_module, "stop_app_lifecycle", fake_stop)

    app = create_app(profile="test")

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert calls == []
