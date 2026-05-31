"""
Device Farm Service - API Documentation

## Overview

The Device Farm Service provides a unified orchestration layer for managing physical Android devices, calibration, and automated job execution using CH9329 hardware controllers.

## Architecture

```
DeviceFarmService (farm_service.py)
├── DeviceRegistry (registry/)
├── ProfileManager (calibration/)
├── CalibrationWorkbench (calibration/)
├── ActionExecutor (runtime/)
├── JobLogger (runtime/)
└── ADBObserver (hardware/)
```

## Core Components

### 1. Device Management
- List devices with status filtering
- Get detailed device status (including ADB connectivity)
- Update device state (status, calibration profile, metadata)

### 2. Calibration
- Start calibration session
- Save calibration points (semantic names → pixel coordinates)
- Test calibration points (click and verify)
- Finish/cancel calibration sessions

### 3. Job Execution
- Submit jobs (phone_id + flow_id + job_data)
- Monitor job status and logs
- Query job history with filters

### 4. Screenshot Management
- Get latest screenshot for device
- Capture new screenshots on demand

### 5. Manual Recovery
- Retry failed steps
- Mark jobs as manually handled
- Trigger device recalibration

## Usage Examples

### Python Service API

```python
from pixelle_video.device_farm.farm_service import DeviceFarmService

# Initialize service
service = DeviceFarmService()

# List devices
devices = service.list_devices(status=DeviceStatus.IDLE)

# Get device status
status = service.get_device_status("phone_001")

# Start calibration
session = service.start_calibration_session("phone_001")
service.save_calibration_point("phone_001", "xhs.home.publish", 540, 2100)
service.test_calibration_point("phone_001", "xhs.home.publish")
profile = service.finish_calibration_session("phone_001")

# Submit job
job_id = service.submit_job(
    phone_id="phone_001",
    flow_id="flows/xhs_publish_video.yaml",
    job_data={"video_path": "/sdcard/test.mp4", "title": "Test"}
)

# Monitor job
job_status = service.get_job_status(job_id)

# Manual recovery
service.retry_failed_step(job_id, "step_003")
service.mark_job_handled(job_id, "Manually verified")
service.recalibrate_device("phone_001")
```

### REST API

Start the API server:

```python
from pixelle_video.device_farm.api import create_app

app = create_app()
app.run(host="0.0.0.0", port=5000)
```

Or from command line:

```bash
python -m pixelle_video.device_farm.api.rest_api
```

## REST API Endpoints

### Device Management

**List Devices**
```
GET /api/devices?status=idle&include_disabled=true
Response: {"success": true, "devices": [...], "count": 3}
```

**Get Device Status**
```
GET /api/devices/{phone_id}
Response: {
  "success": true,
  "device": {
    "phone_id": "phone_001",
    "status": "idle",
    "adb_connected": true,
    "calibration_valid": true,
    ...
  }
}
```

**Update Device**
```
PATCH /api/devices/{phone_id}
Body: {"status": "idle", "metadata": {"note": "..."}}
Response: {"success": true, "device": {...}}
```

### Calibration

**Start Calibration**
```
POST /api/calibration/start
Body: {"phone_id": "phone_001", "profile_id": "optional"}
Response: {
  "success": true,
  "session": {
    "phone_id": "phone_001",
    "profile_id": "phone_001_20240101_120000",
    "screenshot_path": "..."
  }
}
```

**Save Calibration Point**
```
POST /api/calibration/{phone_id}/point
Body: {
  "point_name": "xhs.home.publish_button",
  "x": 540,
  "y": 2100,
  "description": "Publish button"
}
Response: {"success": true, "point": {...}}
```

**Test Calibration Point**
```
POST /api/calibration/{phone_id}/test
Body: {"point_name": "xhs.home.publish_button"}
Response: {
  "success": true,
  "result": {
    "point_name": "...",
    "screenshot_before": "...",
    "screenshot_after": "..."
  }
}
```

**Finish Calibration**
```
POST /api/calibration/{phone_id}/finish
Body: {"assign_to_device": true}
Response: {
  "success": true,
  "profile": {
    "profile_id": "...",
    "points_count": 5,
    "assigned_to_device": true
  }
}
```

**Cancel Calibration**
```
POST /api/calibration/{phone_id}/cancel
Response: {"success": true}
```

### Job Execution

**Submit Job**
```
POST /api/jobs
Body: {
  "phone_id": "phone_001",
  "flow_id": "flows/xhs_publish_video.yaml",
  "job_data": {
    "video_path": "/sdcard/test.mp4",
    "title": "Test Video"
  },
  "metadata": {"campaign": "test"}
}
Response: {"success": true, "job_id": "phone_001_20240101_120000_abc123"}
```

**Get Job Status**
```
GET /api/jobs/{job_id}
Response: {
  "success": true,
  "job": {
    "job_id": "...",
    "status": "running",
    "phone_id": "phone_001",
    "flow_id": "...",
    "created_at": "...",
    "action_log": [...]
  }
}
```

**List Jobs**
```
GET /api/jobs?phone_id=phone_001&status=failed&limit=10
Response: {"success": true, "jobs": [...], "count": 5}
```

### Screenshots

**Get Latest Screenshot**
```
GET /api/devices/{phone_id}/screenshot
Response: <PNG image file>
```

**Capture Screenshot**
```
POST /api/devices/{phone_id}/screenshot
Response: {"success": true, "screenshot_path": "..."}
```

### Manual Recovery

**Retry Failed Step**
```
POST /api/jobs/{job_id}/retry
Body: {"step_id": "step_003"}
Response: {"success": true, "result": {...}}
```

**Resolve Job**
```
POST /api/jobs/{job_id}/resolve
Body: {"resolution": "Manually verified and fixed"}
Response: {"success": true}
```

**Recalibrate Device**
```
POST /api/devices/{phone_id}/recalibrate
Response: {
  "success": true,
  "session": {
    "phone_id": "phone_001",
    "profile_id": "...",
    "screenshot_path": "..."
  }
}
```

### Health Check

**Health Check**
```
GET /api/health
Response: {
  "success": true,
  "status": "healthy",
  "service": "Device Farm API"
}
```

## Error Handling

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error message description"
}
```

HTTP Status Codes:
- 200: Success
- 201: Created (job submission)
- 400: Bad Request (validation error, session error)
- 404: Not Found (device/job not found)
- 500: Internal Server Error

## Device Status States

- `offline`: Device not connected
- `idle`: Ready for jobs
- `running`: Executing a job
- `needs_calibration`: Requires calibration
- `blocked`: Needs manual intervention
- `cooldown`: Temporary pause
- `disabled`: Administratively disabled

## Job Status States

- `pending`: Job created, not started
- `running`: Job executing
- `completed`: Job finished successfully
- `failed`: Job failed
- `cancelled`: Job cancelled

## Configuration

Default directories (relative to project root):
- Config: `config/`
- Logs: `logs/jobs/`
- Screenshots: `runtime/screenshots/`
- Calibration profiles: `config/calibration_profiles/`

Custom directories:

```python
service = DeviceFarmService(
    config_dir="/custom/config",
    logs_dir="/custom/logs",
    screenshots_dir="/custom/screenshots"
)
```

## Integration Example

```python
# Initialize service
from pixelle_video.device_farm.farm_service import DeviceFarmService

service = DeviceFarmService()

# Complete workflow
devices = service.list_devices(status=DeviceStatus.IDLE)
phone_id = devices[0]["phone_id"]

# Calibrate if needed
if not service.get_device_status(phone_id)["calibration_valid"]:
    session = service.start_calibration_session(phone_id)
    # ... save points ...
    service.finish_calibration_session(phone_id)

# Submit job
job_id = service.submit_job(
    phone_id=phone_id,
    flow_id="flows/xhs_publish_video.yaml",
    job_data={"video_path": "/sdcard/video.mp4"}
)

# Monitor
import time
while True:
    status = service.get_job_status(job_id)
    if status["status"] in ["completed", "failed"]:
        break
    time.sleep(5)

# Cleanup
service.shutdown()
```

## See Also

- `example_farm_service.py` - Complete usage examples
- `farm_service.py` - Service implementation
- `api/rest_api.py` - REST API implementation
"""
