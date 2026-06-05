# Full-stack task refactor design

Date: 2026-06-01

## Summary

This design defines the first vertical slice for refactoring the Pixelle Video frontend and backend: task execution, task progress querying, and result file display. The goal is not to rewrite the whole project. The goal is to establish a reusable end-to-end pattern that can later be copied into video generation, image/text post generation, publishing, scraping, agent, and monitor flows.

The first slice stabilizes the contract between FastAPI and Streamlit. The backend will expose a consistent public task response, normalize result file URLs, and return structured errors. The frontend will consume that contract through a lightweight API client, store task state through a small state helper, and render progress/errors/files through reusable components.

## Current context

The workflow audit found these issues in the current codebase:

- Backend service ownership is spread across module-level globals in `api/dependencies.py`, `api/lifecycle.py`, and service modules such as device manager and publish scheduler.
- Several routers expose internal task models or loosely typed `dict`/`Any` result objects directly to clients.
- Multiple routers build `/api/files/...` URLs independently, with slightly different behavior.
- Many routes catch broad `Exception` and convert it to `HTTPException(500, detail=str(e))`, which makes errors inconsistent and can leak internal details.
- Streamlit pages combine layout, request calls, session state, polling, and result rendering in the same files.
- Frontend code depends on backend internal response shapes instead of a stable frontend-facing task contract.

## Scope

### Included

- A stable public task response contract.
- A stable progress response contract.
- A stable result file response contract.
- A backend task response mapper from internal task state to public API schema.
- A shared backend file URL helper for task results.
- Structured backend error responses for task-related endpoints.
- A lightweight frontend API client for task submit/query/cancel behavior.
- A frontend task state helper around `st.session_state`.
- Reusable Streamlit task components for progress, errors, controls, and result files.
- End-to-end integration into one representative page: `web/views/1_Create.py`.
- Backend and frontend tests for the new contract and conversion logic.

### Excluded

- Rewriting all FastAPI routers.
- Rewriting all Streamlit pages.
- Replacing Streamlit with another UI framework.
- Introducing Celery, Redis, or a database-backed task queue.
- Guaranteeing task recovery after process restart.
- Deep refactors of device farm, publish scheduler, RunningHub, or scraping internals.
- Full API versioning across the whole application.

## Architecture

The target flow is:

```text
Streamlit page
  -> web API client
  -> frontend task state helper
  -> reusable task components
  -> FastAPI task endpoints
  -> TaskManager / AppState / domain services
  -> generated result files
```

The backend owns task execution, progress, errors, and file URL normalization. The frontend owns user input, local UI state, polling cadence, and rendering.

## Backend design

### Application state

Introduce a typed application state object that is created during FastAPI app creation and stored on `app.state`.

```python
@dataclass
class AppState:
    task_manager: TaskManager
    pixelle: PixelleVideo
```

The first implementation may keep existing module-level singletons as compatibility adapters, but new task-related code should prefer `request.app.state.services` through a typed dependency:

```python
def get_app_state(request: Request) -> AppState:
    return request.app.state.services
```

This reduces hidden global state and makes task endpoints easier to test.

### Public task schema

Create or consolidate public task schemas under the API schema layer. The first slice should support this shape:

```python
class TaskProgressResponse(BaseModel):
    percentage: float
    current: int | None = None
    total: int | None = None
    stage: str | None = None
    message: str | None = None

class TaskFileResponse(BaseModel):
    path: str
    url: str
    kind: Literal["image", "video", "audio", "json", "text", "other"]

class TaskResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    progress: TaskProgressResponse
    result: dict[str, Any] | None = None
    files: list[TaskFileResponse] = []
    error: ErrorResponse | None = None
```

Internal task storage may remain richer and mutable. API routes should return `TaskResponse`, not the internal task object.

### Task mapper

Add a mapper that converts the internal task model into `TaskResponse`.

Responsibilities:

- Normalize status into the public status enum.
- Normalize missing progress into a valid progress object.
- Extract result files from known result fields.
- Convert file paths into `TaskFileResponse` values.
- Convert failed task errors into `ErrorResponse`.
- Avoid mutating the internal task object during serialization.

### File URL helper

Create a single helper for file URL construction. It should replace duplicate logic in task-related paths first, then can later be adopted by video, post, and file upload routers.

Responsibilities:

- Accept absolute paths and project-relative paths.
- Preserve or normalize `output/...` paths consistently.
- Construct `/api/files/...` URLs using either configured public base URL or `Request.base_url`.
- Infer file kind from extension.
- Keep the returned `path` stable and safe for display.

### Error handling

Define a small domain error hierarchy:

```python
class AppError(Exception):
    code: str
    message: str
    status_code: int
    details: dict[str, Any] | None
```

Initial error codes:

- `validation_error`
- `not_found`
- `configuration_error`
- `external_service_error`
- `task_not_found`
- `task_cancelled`
- `task_failed`
- `internal_error`

Register FastAPI exception handlers for:

- `AppError`
- request validation errors
- `HTTPException`
- unexpected `Exception`

Task-related routes should raise known domain errors and let central handlers serialize them. Unexpected exceptions should be logged with stack traces and returned as `internal_error` without exposing raw exception text as the primary message.

### TaskManager minimal hardening

The first slice keeps the existing in-process task model, but improves task semantics:

- Use typed async callables for task execution where possible.
- Store task handles explicitly.
- Mark cancelled tasks as `cancelled`.
- Await cancelled tasks during shutdown with `return_exceptions=True`.
- Return public task responses through the mapper.
- Document that task state remains process-local in this phase.

## Frontend design

### API client

Add a lightweight API client layer:

```text
web/api/__init__.py
web/api/client.py
web/api/tasks.py
```

`web/api/client.py` owns:

- Backend base URL lookup.
- Request timeout defaults.
- JSON request/response handling.
- Structured error parsing.

`web/api/tasks.py` owns:

- Submit task calls for the first Create-page flow.
- `get_task(task_id)`.
- `cancel_task(task_id)` if the backend endpoint exists for the selected flow.
- Normalization from backend response into frontend task objects.
- Compatibility conversion for old task responses where needed.

Streamlit pages should not directly depend on backend internal response shapes.

### Task state

Add a frontend task state helper:

```text
web/state/tasks.py
```

It should wrap `st.session_state` and expose operations such as:

- `init_task_state(key)`
- `update_task_state(key, task_response)`
- `clear_task_state(key)`
- `get_task_state(key)`

The UI-facing state should include:

- task ID
- status
- progress percentage
- current message
- result files
- parsed error

### Task components

Add reusable Streamlit components:

```text
web/components/task_status.py
```

Initial component functions:

- `render_task_progress(task_state)`
- `render_task_error(task_state)`
- `render_task_files(task_state)`
- `render_task_controls(task_state)`

`render_task_files` should display by file kind:

- `image` with `st.image`
- `video` with `st.video`
- `audio` with `st.audio`
- `json`, `text`, and `other` as links, downloads, or expandable previews depending on the available data

### First page integration

Integrate the pattern into `web/views/1_Create.py` only.

The page should keep form/layout responsibilities and delegate task behavior:

```text
form submit
  -> web.api.tasks submit function
  -> web.state.tasks update
  -> task_status components render progress, errors, and files
```

Existing behavior should remain available. If an endpoint still returns the old response shape, the API client should normalize it for this page rather than forcing all endpoints to change at once.

### Polling

Keep polling simple in this phase:

- Poll every 1-2 seconds while status is `pending` or `running`.
- Stop polling on `completed`, `failed`, or `cancelled`.
- Reuse existing Streamlit rerun patterns if present.
- Keep polling logic outside page layout code where practical.

## API contract examples

### Running task

```json
{
  "task_id": "task_123",
  "status": "running",
  "progress": {
    "percentage": 42.5,
    "current": 3,
    "total": 7,
    "stage": "generating_video",
    "message": "正在生成第 3 个片段"
  },
  "result": null,
  "files": [],
  "error": null
}
```

### Completed task

```json
{
  "task_id": "task_123",
  "status": "completed",
  "progress": {
    "percentage": 100,
    "current": 7,
    "total": 7,
    "stage": "completed",
    "message": "生成完成"
  },
  "result": {
    "title": "生成结果",
    "summary": "共生成 1 个视频"
  },
  "files": [
    {
      "path": "output/videos/demo.mp4",
      "url": "http://localhost:8000/api/files/output/videos/demo.mp4",
      "kind": "video"
    }
  ],
  "error": null
}
```

### Failed task

```json
{
  "task_id": "task_123",
  "status": "failed",
  "progress": {
    "percentage": 42.5,
    "current": 3,
    "total": 7,
    "stage": "generating_video",
    "message": "生成失败"
  },
  "result": null,
  "files": [],
  "error": {
    "code": "external_service_error",
    "message": "RunningHub 暂时不可用",
    "details": {
      "provider": "runninghub"
    }
  }
}
```

## Implementation order

1. Add backend task response schemas and error schema updates if needed.
2. Add backend file URL helper.
3. Add backend task response mapper.
4. Harden TaskManager cancellation/status behavior minimally.
5. Update task-related query endpoints to return the public schema.
6. Add structured error handlers for task-related routes.
7. Add `web/api/client.py` and `web/api/tasks.py`.
8. Add `web/state/tasks.py`.
9. Add `web/components/task_status.py`.
10. Integrate the new flow into `web/views/1_Create.py`.
11. Add backend tests for mapper, file URL helper, errors, and cancellation status.
12. Add frontend tests for task response normalization and error parsing.
13. Manually verify the Create-page flow.

## Verification plan

Backend tests should cover:

- Internal task state to public `TaskResponse` mapping.
- Result path to `TaskFileResponse` URL conversion.
- File kind inference.
- `AppError` serialization.
- Task-not-found response.
- Cancelled task status.

Frontend tests should cover:

- New task response to UI task state normalization.
- Legacy response compatibility conversion.
- Structured error parsing.
- File kind rendering decision logic.

Manual verification should cover:

1. Start the backend.
2. Start the Streamlit app.
3. Open the Create page.
4. Submit one generation task.
5. Confirm progress updates while the task runs.
6. Confirm result files display correctly when the task completes.
7. Trigger a configuration or external-service error and confirm a structured error appears.
8. Cancel a task if the selected flow exposes cancellation, and confirm it displays as `cancelled` rather than `failed`.

## Risks and mitigations

### Risk: Old and new task contracts coexist

Mitigation: Keep compatibility normalization in `web/api/tasks.py` and migrate one page first.

### Risk: File URL normalization changes existing links

Mitigation: Use the new helper first for task result files only, add tests for current expected output paths, and do not replace every existing router helper in the first change.

### Risk: TaskManager hardening expands into queue redesign

Mitigation: Explicitly keep task state process-local in this phase and avoid Celery/Redis/database persistence.

### Risk: Create page has hidden coupling to old response shape

Mitigation: Move compatibility code into the frontend API client, not into reusable task components.

## Success criteria

The first phase is successful when:

- `web/views/1_Create.py` uses the new task API/state/component pattern for one generation flow.
- Task query responses for the selected flow use `TaskResponse`.
- Result files are returned as `TaskFileResponse` with stable URLs and file kinds.
- Structured task errors are displayed consistently in the frontend.
- Existing Create-page functionality remains usable.
- Automated tests cover the mapper, URL helper, error parsing, and frontend response normalization.
- Manual verification confirms progress, completion, result display, and failure behavior.
