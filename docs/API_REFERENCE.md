# API Reference Documentation

## Overview
The Pixelle Video API provides RESTful endpoints for task management, status tracking, and result retrieval.

**Base URL:** `http://localhost:8000`  
**API Version:** v1  
**Content Type:** `application/json`

## Authentication
Currently no authentication required. Future versions will implement API key authentication.

## Endpoints

### Tasks

#### POST /api/tasks
Create a new task.

**Request Body:**
```json
{
  "task_type": "VIDEO_GENERATION",
  "prompt": "A beautiful sunset over the ocean",
  "parameters": {
    "duration": 5,
    "resolution": "1920x1080",
    "fps": 30
  }
}
```

**Parameters:**
- `task_type` (string, required): Type of task. Values: `VIDEO_GENERATION`, `IMAGE_GENERATION`
- `prompt` (string, required): Text prompt describing the desired output
- `parameters` (object, optional): Additional task-specific parameters

**Response (201 Created):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "created_at": "2026-06-01T10:00:00Z"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid task_type or missing required fields
- `500 Internal Server Error`: Server error during task creation

**Example:**
```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "VIDEO_GENERATION",
    "prompt": "A cat playing piano"
  }'
```

---

#### GET /api/tasks/{task_id}
Get task status and details.

**Path Parameters:**
- `task_id` (string, required): UUID of the task

**Response (200 OK):**

**Pending Task:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "task_type": "VIDEO_GENERATION",
  "prompt": "A cat playing piano",
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:00:01Z"
}
```

**Running Task:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "RUNNING",
  "task_type": "VIDEO_GENERATION",
  "prompt": "A cat playing piano",
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:00:30Z",
  "progress": {
    "percentage": 45.5,
    "message": "Generating frame 45/100",
    "current_step": "rendering",
    "total_steps": 3
  }
}
```

**Completed Task:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "COMPLETED",
  "task_type": "VIDEO_GENERATION",
  "prompt": "A cat playing piano",
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:02:00Z",
  "completed_at": "2026-06-01T10:02:00Z",
  "result": {
    "files": [
      {
        "path": "output.mp4",
        "url": "http://localhost:8000/files/550e8400-e29b-41d4-a716-446655440000/output.mp4",
        "size": 10485760,
        "mime_type": "video/mp4",
        "duration": 5.0,
        "resolution": "1920x1080"
      }
    ],
    "metadata": {
      "processing_time": 120.5,
      "frames_generated": 150
    }
  }
}
```

**Failed Task:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "FAILED",
  "task_type": "VIDEO_GENERATION",
  "prompt": "A cat playing piano",
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:01:30Z",
  "failed_at": "2026-06-01T10:01:30Z",
  "error": "Video generation failed: Insufficient GPU memory"
}
```

**Error Responses:**
- `404 Not Found`: Task does not exist
- `500 Internal Server Error`: Server error

**Example:**
```bash
curl http://localhost:8000/api/tasks/550e8400-e29b-41d4-a716-446655440000
```

---

#### DELETE /api/tasks/{task_id}
Cancel a running task.

**Path Parameters:**
- `task_id` (string, required): UUID of the task

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Task cancelled successfully"
}
```

**Error Responses:**
- `404 Not Found`: Task does not exist
- `409 Conflict`: Task already completed or cancelled
- `500 Internal Server Error`: Server error

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/tasks/550e8400-e29b-41d4-a716-446655440000
```

---

#### GET /api/tasks
List all tasks (with optional filtering).

**Query Parameters:**
- `status` (string, optional): Filter by status. Values: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`
- `task_type` (string, optional): Filter by task type
- `limit` (integer, optional): Maximum number of results (default: 50, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

**Response (200 OK):**
```json
{
  "tasks": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "COMPLETED",
      "task_type": "VIDEO_GENERATION",
      "created_at": "2026-06-01T10:00:00Z",
      "updated_at": "2026-06-01T10:02:00Z"
    },
    {
      "task_id": "660e8400-e29b-41d4-a716-446655440001",
      "status": "RUNNING",
      "task_type": "IMAGE_GENERATION",
      "created_at": "2026-06-01T10:05:00Z",
      "updated_at": "2026-06-01T10:05:30Z"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

**Example:**
```bash
# Get all running tasks
curl "http://localhost:8000/api/tasks?status=RUNNING"

# Get first 10 completed tasks
curl "http://localhost:8000/api/tasks?status=COMPLETED&limit=10"
```

---

### Health Check

#### GET /health
Check API health status.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": 3600.5
}
```

**Example:**
```bash
curl http://localhost:8000/health
```

---

## Data Models

### Task Status
Tasks progress through the following states:

```
PENDING → RUNNING → COMPLETED
                 ↘ FAILED
                 ↘ CANCELLED
```

- `PENDING`: Task created, waiting to start
- `RUNNING`: Task is currently executing
- `COMPLETED`: Task finished successfully
- `FAILED`: Task encountered an error
- `CANCELLED`: Task was cancelled by user

### Task Types

#### VIDEO_GENERATION
Generate video from text prompt.

**Parameters:**
- `duration` (number): Video duration in seconds (default: 5, max: 60)
- `resolution` (string): Video resolution (default: "1920x1080")
- `fps` (number): Frames per second (default: 30)
- `style` (string): Visual style (optional)

#### IMAGE_GENERATION
Generate image from text prompt.

**Parameters:**
- `width` (number): Image width in pixels (default: 1024)
- `height` (number): Image height in pixels (default: 1024)
- `style` (string): Visual style (optional)
- `num_images` (number): Number of images to generate (default: 1, max: 4)

---

## Error Handling

### Error Response Format
```json
{
  "error": {
    "code": "INVALID_TASK_TYPE",
    "message": "Task type 'INVALID' is not supported",
    "details": {
      "valid_types": ["VIDEO_GENERATION", "IMAGE_GENERATION"]
    }
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_REQUEST` | 400 | Malformed request body |
| `INVALID_TASK_TYPE` | 400 | Unsupported task type |
| `MISSING_REQUIRED_FIELD` | 400 | Required field missing |
| `TASK_NOT_FOUND` | 404 | Task ID does not exist |
| `TASK_ALREADY_COMPLETED` | 409 | Cannot modify completed task |
| `TASK_ALREADY_CANCELLED` | 409 | Cannot modify cancelled task |
| `INTERNAL_ERROR` | 500 | Server error |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

---

## Rate Limiting
Currently no rate limiting. Future versions will implement:
- 100 requests per minute per IP
- 10 concurrent tasks per user

**Rate Limit Headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1622548800
```

---

## Webhooks (Future)
Subscribe to task events:

```json
POST /api/webhooks
{
  "url": "https://your-server.com/webhook",
  "events": ["task.completed", "task.failed"]
}
```

---

## SDK Examples

### Python
```python
from pixelle_video.web.api.client import APIClient
from pixelle_video.web.api.tasks import TaskAPI

# Initialize client
client = APIClient(base_url="http://localhost:8000")
task_api = TaskAPI(client)

# Submit task
response = client.post("/api/tasks", json={
    "task_type": "VIDEO_GENERATION",
    "prompt": "A cat playing piano"
})
task_id = response["task_id"]

# Poll for completion
import time
while True:
    task = task_api.get_task_status(task_id)
    if task["status"] in ["COMPLETED", "FAILED", "CANCELLED"]:
        break
    time.sleep(2)

# Get result
if task["status"] == "COMPLETED":
    files = task["result"]["files"]
    print(f"Generated {len(files)} files")
```

### JavaScript
```javascript
// Submit task
const response = await fetch('http://localhost:8000/api/tasks', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    task_type: 'VIDEO_GENERATION',
    prompt: 'A cat playing piano'
  })
});
const {task_id} = await response.json();

// Poll for completion
while (true) {
  const task = await fetch(`http://localhost:8000/api/tasks/${task_id}`)
    .then(r => r.json());
  
  if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)) {
    break;
  }
  await new Promise(r => setTimeout(r, 2000));
}
```

### cURL
```bash
# Submit task
TASK_ID=$(curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_type":"VIDEO_GENERATION","prompt":"A cat playing piano"}' \
  | jq -r '.task_id')

# Poll for completion
while true; do
  STATUS=$(curl -s http://localhost:8000/api/tasks/$TASK_ID | jq -r '.status')
  echo "Status: $STATUS"
  [[ "$STATUS" =~ ^(COMPLETED|FAILED|CANCELLED)$ ]] && break
  sleep 2
done
```

---

## Changelog

### v1.0.0 (2026-06-01)
- Initial API release
- Task creation and management
- Status polling
- Task cancellation
- Result file retrieval

---

**Last Updated:** 2026-06-01  
**API Version:** 1.0.0  
**Documentation Version:** 1.0.0
