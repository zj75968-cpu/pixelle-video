# Productization Phase 0 Inventory

Date: 2026-05-30

## Supported Entry Points

| Entry | File | Current Role | Phase 1 Decision |
|---|---|---|---|
| FastAPI app | `api/app.py` | HTTP API process and current background lifecycle owner | Keep supported. Add `create_app()` and delegate lifecycle to `api/lifecycle.py`. |
| Streamlit app | `web/app.py` | UI process with session/auth/navigation behavior | Keep supported. Do not split in Phase 1. Later phase should make it thin. |
| Windows local launcher | `start_web.bat` | Local Streamlit launcher | Keep supported. Later phase standardizes local one-click path. |
| Unix local launcher | `start_web.sh` | Local Streamlit launcher | Keep supported. Later phase standardizes local one-click path. |
| macOS local launcher | `start_mac.sh` | Local launcher | Keep supported until local launchers are consolidated. |
| Docker image | `Dockerfile` | Defaults to FastAPI process | Keep supported. Later phase should introduce explicit api/web/worker profiles. |
| Docker Compose | `docker-compose.yml` | Runs api and web with shared config/data/output mounts | Keep supported. Phase 1 documents single background owner risk; later phase refactors. |
| Python package CLI | `pyproject.toml` -> `pixelle_video.cli:main` | Declared console script | Verify before delivery-path work; not fixed in Phase 1 unless tests require. |

## Main Flows Protected in Phase 1

- Config load through `pixelle_video.config.config_manager`.
- API health/version/root endpoints.
- Existing router prefixes under `api_config.api_prefix`.
- Webhook route without `/api` prefix.
- FastAPI background lifecycle order.
- Publish scheduler queue import no longer starts polling threads; lifecycle starts polling explicitly.
- `PixelleVideoCore` dict config snapshot and public package exports.

## Known Compatibility Risks

1. `PublishScheduler()` previously started a polling daemon in its constructor.
2. `api/app.py` previously created the app at import time with direct lifespan ownership.
3. `ConfigManager.config_path` creates user config directories and copies config files for non-default users.
4. `ConfigManager` is a singleton; later `ConfigManager(config_path=...)` calls do not replace the initialized path.
5. `PixelleVideoCore(config_path=...)` accepts `config_path` but currently reads from global `config_manager`.
6. API agent progress submission uses JSON, while final result submission uses multipart/form with optional screenshot upload.
7. Docker Compose currently lets API and Web share `data/publish_queue.json`; later phases should make one process the background owner.

## Phase 1 Non-Goals

- No full Streamlit split.
- No publishing business rewrite.
- No global singleton removal.
- No forced config format migration.
- No deletion of old device artifacts.
- No Docker Compose redesign.

## Agent Contract Follow-Up

The local agent result submission path needs a dedicated compatibility decision before Phase 3 publishing refactor:

- `scripts/local_agent.py` reports progress with JSON payloads.
- `scripts/local_agent.py` submits final job results as multipart/form data with optional screenshot upload.
- `api/routers/publish.py` matches those two contracts: the progress endpoint accepts a JSON body, and the result endpoint declares form fields with an optional file upload.

Phase 1 only preserves route presence. A later task should decide whether this mixed payload style needs explicit compatibility documentation or a unified client/server contract before the Phase 3 publishing refactor.
