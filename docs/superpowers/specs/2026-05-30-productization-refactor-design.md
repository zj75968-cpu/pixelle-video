# Productization Refactor Design

Date: 2026-05-30

## 1. Context

Pixelle-Video is a Python 3.11 AI short-video and content creation platform. It currently includes a Streamlit UI, FastAPI backend, video/post generation pipelines, external provider integrations, publishing automation, device automation, Docker assets, local startup scripts, and documentation.

The refactor goal is a system-wide productization baseline. The project should eventually support three standard delivery paths:

1. local one-click use for ordinary users;
2. Docker/server deployment for long-running services;
3. CLI/API/package use for developers and automation.

The first implementation stage will not chase visible feature changes. It will establish internal architecture boundaries for configuration, runtime profiles, lifecycle ownership, application factories, and service composition. Existing video generation and publishing flows must remain usable during the migration.

## 2. Goals

- Establish a productized architecture baseline before changing delivery paths.
- Keep the main video generation and publishing flows strongly compatible.
- Make entry points thin and explicit: Streamlit, FastAPI, CLI, scripts, and Docker should bootstrap the application rather than own business orchestration.
- Separate configuration schema, loading, migration, and user-scoped persistence.
- Define explicit runtime profiles for local UI, API server, worker, CLI, and development/test usage.
- Centralize scheduler, device manager, and cleanup lifecycle ownership.
- Reduce `PixelleVideoCore` from an all-purpose service locator into a compatibility facade over clearer factories, context, services, and use cases.
- Prepare the repository for local, Docker, and CLI/API product paths without requiring a large rewrite.

## 3. Non-Goals

- Do not redesign the product UI in the first stage.
- Do not rewrite all pipelines at once.
- Do not remove `PixelleVideoCore` immediately.
- Do not require users to rewrite existing `config.yaml` files during the first stage.
- Do not require real external services or physical devices for default automated tests.
- Do not clean every legacy artifact before compatibility paths are in place.

## 4. Compatibility Policy

### Strong compatibility

These should keep working throughout the first refactor stages:

- primary Streamlit pages;
- video generation flow;
- publishing flow;
- common API endpoints;
- existing `config.yaml` format;
- user data directories and generated assets.

### Medium compatibility

These may change with migration notes or compatibility wrappers:

- startup scripts;
- Docker Compose layout;
- CLI entry points;
- developer scripts;
- internal configuration structure.

### Weak compatibility / cleanup candidates

These may be deprecated, migrated, or removed after inventory:

- old ADB / Phone Agent paths;
- `.old` files;
- runtime debug dumps and screenshots;
- root-level temporary outputs;
- unsupported experimental scripts;
- stale package entry points;
- obsolete binaries not required by supported product flows.

## 5. Target Architecture

The desired architecture separates entry points, application orchestration, domain services, providers, and infrastructure.

```text
Entry points
├─ web/                 Streamlit UI: pages, interactions, display, use-case calls
├─ api/                 FastAPI HTTP boundary: requests, responses, schemas, errors
├─ CLI / scripts        command entry points: argument parsing and use-case calls
└─ deployment           Docker, local startup scripts, env vars, volumes, logging

Application layer
├─ use_cases/           generation, publishing, config, device, task, health flows
├─ lifecycle/           scheduler, device, cleanup startup/shutdown coordination
└─ factories/           create context, services, use cases, compatibility facade

Domain / service layer
├─ pipelines/           video/post/action-transfer generation pipelines
├─ services/            LLM, TTS, media, video, publish, device capabilities
├─ config/              schema, loading, validation, migration, user config service
└─ models/              domain models, task status, configuration objects

Infrastructure layer
├─ providers/           OpenAI, Ollama, ComfyUI, RunningHub, Supabase, XHS, CH9329
├─ storage/             paths, user data, assets, cache, logs
└─ automation/          physical device automation implementations
```

Core principles:

1. Entry points only bootstrap runtime state and call use cases.
2. Application use cases own business orchestration.
3. Lifecycle ownership is explicit and profile-dependent.
4. Configuration reads are separated from filesystem mutation.
5. `PixelleVideoCore` remains as a compatibility facade while new code depends on use cases or explicit services.
6. Legacy cleanup follows the compatibility policy instead of deleting files opportunistically.

## 6. Configuration Design

The current configuration responsibilities should be separated into focused modules:

```text
pixelle_video/config/
├─ schema.py            configuration structures, defaults, validation rules
├─ loader.py            load and merge config.yaml, env vars, CLI arguments
├─ migrator.py          explicit config version migrations and old-field compatibility
├─ store.py             user-scoped config file read/write/create/save behavior
└─ service.py           business-facing ConfigService facade
```

Rules:

- `schema.py` is pure model and validation logic.
- `loader.py` loads and merges sources but does not persist data or create files.
- `store.py` owns filesystem effects: user directories, config copies, saves, backups, permission checks.
- `migrator.py` runs explicitly during startup or save flows.
- `service.py` provides the stable surface consumed by use cases and compatibility code.
- Existing `config.yaml` remains accepted in the first phase.

This design supports:

- local use: project/user config files;
- Docker/server use: environment variables and mounted config/data volumes;
- CLI/API use: `--config`, `--user-id`, and environment overrides.

## 7. Runtime Profiles

Introduce an explicit `RunProfile` instead of letting behavior emerge from the entry file.

```text
RunProfile
├─ local_ui             Streamlit single-machine use
├─ api_server           FastAPI HTTP service
├─ worker               background publishing, device, and cleanup service
├─ cli                  one-shot command execution
└─ dev                  development/test mode
```

Each profile declares:

- whether it may start the scheduler;
- whether it may connect to physical devices;
- whether it needs web session state;
- where logs go;
- which data/cache directories are used;
- configuration source priority;
- whether diagnostics are enabled.

Default lifecycle expectations:

- `worker` may start publishing scheduler, device manager, and cleanup jobs.
- `api_server` does not start physical device automation unless explicitly enabled.
- `local_ui` may use embedded lifecycle behavior, but protected by single-instance locks to survive Streamlit reloads.
- `cli` does not start long-running background tasks by default.
- `dev` may enable diagnostics and mocks.

## 8. Lifecycle Design

Create a lifecycle coordination layer:

```text
pixelle_video/lifecycle/
├─ app_lifecycle.py       application-level startup/shutdown coordination
├─ scheduler_lifecycle.py publishing scheduler lifecycle
├─ device_lifecycle.py    device manager lifecycle
├─ cleanup_lifecycle.py   TTL/temp cleanup lifecycle
└─ locks.py               process/single-instance locks
```

Requirements:

- Background services start only from profiles that explicitly own them.
- Scheduler, device manager, and cleanup startup/shutdown calls are idempotent.
- Global resources use locks to prevent duplicate workers across Streamlit reloads or multiple processes.
- Entry files delegate lifecycle to this layer instead of directly creating global tasks.
- Lock failures produce clear logs and user-facing diagnostics where appropriate.

## 9. Application Factory and Context

Add an application composition root:

```text
pixelle_video/app/
├─ profiles.py           RunProfile definitions
├─ context.py            AppContext: profile, config, paths, logger, user, flags
├─ factory.py            create_app_context, create_core, create_use_cases
└─ errors.py             startup and configuration error types
```

Example direction:

```python
context = create_app_context(profile=RunProfile.LOCAL_UI)
use_cases = create_use_cases(context)
```

The same factory should gradually replace:

- Streamlit session-specific manual core caching;
- FastAPI dependency-specific manual core creation;
- scripts that instantiate `ConfigManager` or `PixelleVideoCore` directly;
- duplicated `config.yaml` loading logic.

## 10. Use Case Layer

Add `pixelle_video/use_cases/` for application orchestration:

```text
pixelle_video/use_cases/
├─ generate_video.py       create video tasks and run generation pipelines
├─ generate_post.py        image/text/XHS post generation
├─ publish_content.py      publishing tasks, queues, and execution
├─ manage_config.py        read/save/migrate user configuration
├─ manage_devices.py       detect/select/control devices
├─ manage_tasks.py         query/cancel/cleanup tasks
└─ health_check.py         validate config, dependencies, services, devices
```

Rules:

- Web pages call use cases rather than assembling services directly.
- API routers call use cases rather than directly managing pipelines, scheduler, or devices.
- CLI commands call use cases and do not duplicate Web/API logic.
- Use cases may depend on service interfaces and `AppContext`, but not on Streamlit or FastAPI.

Suggested migration order:

1. `manage_config`
2. `health_check`
3. `manage_tasks`
4. `publish_content`
5. `manage_devices`
6. `generate_post`
7. `generate_video`

This order starts with lower-risk boundaries before moving the most important generation and device flows.

## 11. `PixelleVideoCore` Compatibility Plan

`PixelleVideoCore` should not be removed in the first stage. It becomes a compatibility facade.

Current direction:

```text
web/api/scripts -> PixelleVideoCore -> services/pipelines/config
```

Target direction:

```text
web/api/scripts -> use_cases -> services/pipelines/config/providers
```

Compatibility period:

```text
PixelleVideoCore -> AppContext + UseCaseRegistry + ServiceRegistry
```

Migration steps:

1. Make `PixelleVideoCore` internally use the new context and factory where possible.
2. Keep public attributes and methods stable for existing callers.
3. Prevent new code from adding fresh `core.xxx` dependencies.
4. Replace old `core.xxx` call sites incrementally with use cases.
5. Later decide whether to keep a thin facade or remove it in a breaking release.

## 12. Service and Provider Split

Gradually distinguish business services from external adapters.

```text
pixelle_video/services/
├─ llm_service.py          business-facing LLM capability
├─ tts_service.py          business-facing TTS capability
├─ media_service.py        media processing capability
├─ video_service.py        video composition capability
├─ publish_service.py      publishing business capability
└─ device_service.py       device business capability

pixelle_video/providers/
├─ llm/openai_provider.py
├─ llm/ollama_provider.py
├─ comfyui/provider.py
├─ runninghub/provider.py
├─ storage/file_provider.py
├─ publish/xhs_provider.py
└─ hardware/ch9329_provider.py
```

Services express what the product needs. Providers express how external systems are called. This enables mock testing, provider replacement, and cleaner Docker/CLI/API boundaries.

## 13. Entry Point Refactor

### Streamlit

Split `web/app.py` into focused modules:

```text
web/
├─ app.py                  thin Streamlit entry
├─ bootstrap.py            page registration and session initialization
├─ auth.py                 login, cookies, user context
├─ navigation.py           page navigation
├─ diagnostics.py          dev-only startup/page diagnostics
├─ state/session.py        Streamlit session adapter
└─ views/
```

Split the publishing view into smaller UI components:

```text
web/views/publish/
├─ page.py                 page skeleton
├─ queue_panel.py          publishing queue
├─ device_panel.py         device status
├─ task_actions.py         publishing actions
├─ scheduler_panel.py      scheduler status
└─ forms.py                forms and shared controls
```

### FastAPI

Keep API modules focused on HTTP boundary concerns:

```text
api/
├─ app.py                  create_api_app(profile=RunProfile.API_SERVER)
├─ dependencies.py         context/use-case providers
├─ error_handlers.py       unified error mapping
├─ routers/
└─ schemas/
```

Routers should not directly own lifecycle, device, scheduler, or pipeline construction.

### CLI / scripts

Repair or remove stale console entry points. The productized CLI should eventually provide at least:

```text
pixelle-video health
pixelle-video init-config
pixelle-video run-worker
pixelle-video create-video
```

Scripts should become thin wrappers around these commands or be moved to documented developer-only locations.

## 14. Phased Migration Plan

### Phase 0: Inventory and protection

- Inventory entry points: Streamlit, FastAPI, startup scripts, Docker Compose, CLI, operational scripts.
- Confirm whether `pixelle_video.cli:main` exists and is supported.
- Inventory main flows: config load, web video creation, API task creation/query, publishing scheduler, device control, Docker startup.
- Add minimal smoke/unit tests before large movement.

Acceptance:

- Entry-point and main-flow inventory exists.
- Initial safety tests exist for config load, API app creation, lifecycle idempotency, and CLI presence or documented absence.

### Phase 1: Architecture baseline

- Add `pixelle_video/app/`, `pixelle_video/lifecycle/`, and supporting config/storage boundaries.
- Define `RunProfile` and `AppContext`.
- Split configuration responsibilities behind compatibility wrappers.
- Add lifecycle coordinator and locks.
- Let old `ConfigManager` and `PixelleVideoCore` delegate to the new implementation where practical.

Acceptance:

- All supported entry points declare a profile.
- Configuration reading and writing side effects are separated.
- Scheduler/device/cleanup cannot be started accidentally by multiple owners.
- Existing config files still load.

### Phase 2: Entry slimming

- Make `web/app.py` a thin bootstrap entry.
- Move auth, navigation, diagnostics, and session behavior into focused modules.
- Make `api/app.py` expose `create_api_app`.
- Keep API dependencies responsible for request/application-scoped context and use-case providers.

Acceptance:

- Web still opens.
- API app still creates successfully.
- Background tasks are lifecycle-owned.
- Entry files contain less business and diagnostic logic.

### Phase 3: Core use-case migration

- Add `pixelle_video/use_cases/`.
- Migrate config, health check, task management, publishing, device, post, and video generation orchestration in that order.
- Keep `PixelleVideoCore` as facade for old callers.

Acceptance:

- At least one Web/API/CLI path shares a common use case.
- New code avoids new direct `core.xxx` dependencies.
- Key use cases have unit tests with mocked services/providers.

### Phase 4: Product delivery paths

Local one-click path:

- normalize `start_web.bat` / `start_web.sh`;
- make first-run config initialization explicit;
- stabilize log/cache/output directories;
- show readable missing-dependency/config errors.

Docker/server path:

- split Compose responsibilities into api, web, worker, and optional tunnel/proxy as appropriate;
- prefer env vars and mounted volumes over source-tree mutation;
- send logs to stdout or declared volumes;
- make worker profile own scheduler/device/cleanup by default.

CLI/API/developer path:

- repair or remove the stale package entry point;
- implement basic CLI commands around use cases;
- align API schemas with use-case DTOs;
- document developer invocation paths.

Acceptance:

- Each delivery path has a documented standard entry.
- Docker does not rely on mutating source-tree `config.yaml`.
- Installed CLI can show help and run health checks.

### Phase 5: Legacy cleanup

- Classify old ADB/Phone Agent artifacts, `.old` files, runtime debug assets, temporary outputs, unsupported scripts, and obsolete binaries.
- Migrate or deprecate user-facing scripts before removal.
- Remove only after references in docs, startup scripts, and supported flows are checked.
- Update README, usage guide, and deployment docs.

Acceptance:

- Product structure no longer mixes runtime dumps and unsupported historical paths with supported code.
- Any removals have a clear compatibility note or migration path.

## 15. Verification Plan

Default verification per phase:

```text
ruff check
pytest tests/unit
pytest tests/integration -m "not external"
API app creation smoke
Config load smoke
Lifecycle idempotency tests
```

When delivery paths are touched:

```text
Streamlit bootstrap smoke
Docker Compose config validation
CLI --help / health smoke
```

When publishing or devices are touched:

```text
publish scheduler dry-run
device manager mock test
CH9329 provider mock/contract test
```

Real ComfyUI, RunningHub, XHS, Supabase, and physical-device tests should be marked manual or environment-gated. They should not block default local verification unless explicitly requested.

## 16. Risks and Mitigations

### Risk: hidden behavior changes from moving configuration code

Mitigation: keep `ConfigManager` compatibility wrappers, add config load/save tests, and make migration explicit.

### Risk: duplicate background jobs across Streamlit and API

Mitigation: use profile-based lifecycle ownership, idempotent start/stop, and process locks.

### Risk: breaking existing Web/API flows during entry slimming

Mitigation: thin entries incrementally and keep routers/pages calling existing facade until corresponding use cases are ready.

### Risk: provider split becomes too large

Mitigation: split providers only when touching the relevant service for a use case or product path.

### Risk: cleanup deletes something users depend on

Mitigation: classify first, check docs and entry references, deprecate before deletion when user-facing.

## 17. Success Criteria

The refactor is successful when:

- each supported entry point has an explicit runtime profile;
- configuration source, validation, migration, and persistence responsibilities are separate;
- scheduler, device manager, and cleanup ownership are clear and not duplicated accidentally;
- `web/app.py` and `api/app.py` are thin bootstraps;
- new business orchestration lives in use cases;
- `PixelleVideoCore` remains compatible but is no longer the default dependency for new code;
- local, Docker/server, and CLI/API paths each have a documented standard route;
- tests protect configuration, lifecycle, app creation, and selected use cases;
- legacy artifacts are classified and no longer obscure supported product structure.
