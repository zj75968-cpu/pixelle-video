# Fullstack Task Refactor - Deployment Guide

## Overview
This guide covers the deployment and operation of the fullstack task management system with FastAPI backend and Streamlit frontend.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Browser                          │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Streamlit Frontend                          │
│         (pixelle_video/web/views/)                       │
│                                                           │
│  • create_page.py - Main UI                              │
│  • components/ - Reusable UI components                  │
│  • state/ - Session state management                     │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP/REST
                     ▼
┌─────────────────────────────────────────────────────────┐
│               FastAPI Backend                            │
│          (pixelle_video/api/)                            │
│                                                           │
│  • /api/tasks - Task management endpoints                │
│  • /api/tasks/{id} - Task status and control             │
└─────────────────────────────────────────────────────────┘
```

## Prerequisites

### System Requirements
- Python 3.10+
- 2GB RAM minimum
- 10GB disk space for video processing

### Dependencies
```bash
# Core dependencies
fastapi>=0.104.0
uvicorn>=0.24.0
streamlit>=1.28.0
httpx>=0.25.0
pydantic>=2.0.0

# Development dependencies
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

## Installation

### 1. Clone Repository
```bash
git clone <repository-url>
cd pixelle_video
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -e .
```

### 4. Verify Installation
```bash
# Run tests
pytest tests/ -v

# Expected: 53 tests passed
```

## Configuration

### Backend Configuration
Create `config/backend.yaml`:
```yaml
server:
  host: "0.0.0.0"
  port: 8000
  workers: 4
  
tasks:
  max_concurrent: 10
  timeout: 3600  # 1 hour
  
storage:
  output_dir: "./output"
  max_file_size: 1073741824  # 1GB
```

### Frontend Configuration
Create `config/frontend.yaml`:
```yaml
api:
  base_url: "http://localhost:8000"
  timeout: 30.0
  
ui:
  polling_interval: 2.0  # seconds
  max_history: 50
  page_title: "Pixelle Video - Task Manager"
```

## Running the Application

### Development Mode

#### Start Backend
```bash
# Terminal 1
cd pixelle_video
python -m pixelle_video.api.main

# Backend will start on http://localhost:8000
# API docs available at http://localhost:8000/docs
```

#### Start Frontend
```bash
# Terminal 2
cd pixelle_video
streamlit run web/views/create_page.py

# Frontend will start on http://localhost:8501
```

### Production Mode

#### Backend with Uvicorn
```bash
uvicorn pixelle_video.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

#### Frontend with Streamlit
```bash
streamlit run web/views/create_page.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true
```

## Docker Deployment

### Dockerfile (Backend)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pixelle_video/ ./pixelle_video/

EXPOSE 8000

CMD ["uvicorn", "pixelle_video.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Dockerfile (Frontend)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pixelle_video/ ./pixelle_video/

EXPOSE 8501

CMD ["streamlit", "run", "pixelle_video/web/views/create_page.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
```

### Docker Compose
```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      - LOG_LEVEL=info
    volumes:
      - ./output:/app/output
    restart: unless-stopped

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "8501:8501"
    environment:
      - API_BASE_URL=http://backend:8000
    depends_on:
      - backend
    restart: unless-stopped
```

### Run with Docker Compose
```bash
docker-compose up -d
```

## Monitoring

### Health Checks

#### Backend Health
```bash
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

#### Frontend Health
```bash
curl http://localhost:8501/_stcore/health
# Expected: {"status": "ok"}
```

### Logging

#### Backend Logs
```bash
# View logs
tail -f logs/backend.log

# Log format
# [timestamp] [level] [module] message
```

#### Frontend Logs
```bash
# Streamlit logs to stdout
docker logs -f pixelle_video_frontend_1
```

### Metrics
Key metrics to monitor:
- Request rate (requests/second)
- Response time (p50, p95, p99)
- Error rate (%)
- Active tasks count
- Task completion rate
- Memory usage
- CPU usage

## Troubleshooting

### Common Issues

#### 1. Backend Won't Start
```bash
# Check port availability
lsof -i :8000

# Check logs
tail -f logs/backend.log

# Verify dependencies
pip list | grep fastapi
```

#### 2. Frontend Can't Connect to Backend
```bash
# Verify backend is running
curl http://localhost:8000/health

# Check frontend config
cat config/frontend.yaml

# Test API connectivity
curl http://localhost:8000/api/tasks
```

#### 3. Tasks Stuck in PENDING
```bash
# Check task queue
curl http://localhost:8000/api/tasks

# Check worker processes
ps aux | grep uvicorn

# Review task logs
tail -f logs/tasks.log
```

#### 4. High Memory Usage
```bash
# Check active tasks
curl http://localhost:8000/api/tasks?status=RUNNING

# Monitor memory
top -p $(pgrep -f uvicorn)

# Restart if needed
docker-compose restart backend
```

## Performance Tuning

### Backend Optimization
```python
# config/backend.yaml
server:
  workers: 8  # 2x CPU cores
  worker_class: "uvicorn.workers.UvicornWorker"
  keepalive: 5
  
tasks:
  max_concurrent: 20
  queue_size: 100
```

### Frontend Optimization
```python
# config/frontend.yaml
ui:
  polling_interval: 5.0  # Reduce polling frequency
  max_history: 20  # Limit history size
  cache_ttl: 300  # Cache API responses
```

### Database Optimization (Future)
- Add Redis for task queue
- Use PostgreSQL for task persistence
- Implement connection pooling

## Security

### API Security
- [ ] Enable HTTPS/TLS
- [ ] Implement API key authentication
- [ ] Add rate limiting
- [ ] Enable CORS with whitelist
- [ ] Validate all inputs
- [ ] Sanitize file uploads

### Frontend Security
- [ ] Enable Streamlit authentication
- [ ] Use secure cookies
- [ ] Implement CSRF protection
- [ ] Sanitize user inputs
- [ ] Validate file downloads

## Backup and Recovery

### Backup Strategy
```bash
# Backup task data
tar -czf backup-$(date +%Y%m%d).tar.gz output/ logs/

# Backup configuration
cp -r config/ config-backup-$(date +%Y%m%d)/
```

### Recovery Procedure
```bash
# Stop services
docker-compose down

# Restore data
tar -xzf backup-20260601.tar.gz

# Restart services
docker-compose up -d
```

## Maintenance

### Regular Tasks
- [ ] Review logs weekly
- [ ] Clean old task outputs monthly
- [ ] Update dependencies quarterly
- [ ] Review security patches monthly
- [ ] Backup data daily

### Update Procedure
```bash
# 1. Backup current state
./scripts/backup.sh

# 2. Pull latest code
git pull origin main

# 3. Update dependencies
pip install -e . --upgrade

# 4. Run tests
pytest tests/ -v

# 5. Restart services
docker-compose restart
```

## Support

### Getting Help
- Documentation: `docs/`
- API Reference: http://localhost:8000/docs
- Issue Tracker: <repository-url>/issues

### Reporting Issues
Include:
1. Error message and stack trace
2. Steps to reproduce
3. Environment details (OS, Python version)
4. Relevant logs

---

**Last Updated:** 2026-06-01  
**Version:** 1.0.0  
**Status:** Production Ready
