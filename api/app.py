# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pixelle-Video FastAPI Application

Main FastAPI app with all routers and middleware.

Run this script to start the FastAPI server:
    uv run python api/app.py

Or with custom settings:
    uv run python api/app.py --host 0.0.0.0 --port 8080 --reload
"""

import sys
import os
os.environ["IS_FASTAPI_PROCESS"] = "1"
from pathlib import Path

# Add project root to sys.path for module imports
# This ensures imports work correctly in both development and packaged environments
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import argparse
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from api.config import api_config
from api.lifecycle import RunProfile, start_app_lifecycle, stop_app_lifecycle

# Import routers
from api.routers import (
    health_router,
    llm_router,
    tts_router,
    image_router,
    content_router,
    video_router,
    tasks_router,
    files_router,
    resources_router,
    frame_router,
    post_router,
    devices_router,
    publish_router,
    runninghub_router,
    webhooks_router,
    phone_agent_router,
)


API_DESCRIPTION = """
    ## Pixelle-Video - AI Video Generation Platform API

    ### Features
    - 🤖 **LLM**: Large language model integration
    - 🔊 **TTS**: Text-to-speech synthesis
    - 🎨 **Image**: AI image generation
    - 📝 **Content**: Automated content generation
    - 🎬 **Video**: End-to-end video generation

    ### Video Generation Modes
    - **Sync**: `/api/video/generate/sync` - For small videos (< 30s)
    - **Async**: `/api/video/generate/async` - For large videos with task tracking

    ### Getting Started
    1. Check health: `GET /health`
    2. Generate narrations: `POST /api/content/narration`
    3. Generate video: `POST /api/video/generate/sync` or `/async`
    4. Track task progress: `GET /api/tasks/{task_id}`
    """


def create_lifespan(profile):
    """Create the application lifespan handler for a run profile."""
    coerced_profile = RunProfile.coerce(profile)
    if coerced_profile is RunProfile.TEST:
        return None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Application lifespan manager

        Handles startup and shutdown events.
        """
        logger.info("🚀 Starting Pixelle-Video API...")
        try:
            await start_app_lifecycle(coerced_profile)
        except Exception:
            await stop_app_lifecycle(coerced_profile)
            raise
        logger.info("✅ Pixelle-Video API started successfully\n")

        try:
            yield
        finally:
            logger.info("🛑 Shutting down Pixelle-Video API...")
            await stop_app_lifecycle(coerced_profile)
            logger.info("✅ Pixelle-Video API shutdown complete")

    return lifespan


def create_app(profile=RunProfile.API_SERVER, lifespan_override=None) -> FastAPI:
    """Create and configure the Pixelle-Video FastAPI application."""
    lifespan = lifespan_override if lifespan_override is not None else create_lifespan(profile)

    # Create FastAPI app
    app = FastAPI(
        title="Pixelle-Video API",
        description=API_DESCRIPTION,
        version="0.1.0",
        docs_url=api_config.docs_url,
        redoc_url=api_config.redoc_url,
        openapi_url=api_config.openapi_url,
        lifespan=lifespan,
    )

    # Add CORS middleware
    if api_config.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=api_config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"CORS enabled for origins: {api_config.cors_origins}")

    # Include routers
    # Health check (no prefix)
    app.include_router(health_router)

    # API routers (with /api prefix)
    app.include_router(llm_router, prefix=api_config.api_prefix)
    app.include_router(tts_router, prefix=api_config.api_prefix)
    app.include_router(image_router, prefix=api_config.api_prefix)
    app.include_router(content_router, prefix=api_config.api_prefix)
    app.include_router(video_router, prefix=api_config.api_prefix)
    app.include_router(tasks_router, prefix=api_config.api_prefix)
    app.include_router(files_router, prefix=api_config.api_prefix)
    app.include_router(resources_router, prefix=api_config.api_prefix)
    app.include_router(frame_router, prefix=api_config.api_prefix)
    app.include_router(post_router, prefix=api_config.api_prefix)
    app.include_router(devices_router, prefix=api_config.api_prefix)
    app.include_router(publish_router, prefix=api_config.api_prefix)
    app.include_router(phone_agent_router, prefix=api_config.api_prefix)
    app.include_router(runninghub_router, prefix=api_config.api_prefix)
    # Webhooks have no /api prefix so external services (e.g. RunningHub) can hit a stable URL.
    app.include_router(webhooks_router)

    # Top-level shortcut: /s -> phone-agent setup script
    # Lets the UI advertise an ultra-short command:
    #     curl http://<VPS>/s | bash
    # NOTE: Requires nginx to forward `/s` to this FastAPI service when the
    # Streamlit UI is the default upstream on port 80. See docs/PRD or the
    # Publish page for the nginx snippet.
    from fastapi import Request as _FA_Request  # noqa: E402

    @app.get("/s", include_in_schema=False)
    async def setup_shortcut(request: _FA_Request):
        """短链：等价于 GET /api/phone-agent/setup，方便用户用更短的命令拉取安装脚本。"""
        from api.routers.phone_agent import get_setup_script
        return await get_setup_script(request)

    @app.get("/")
    async def root():
        """Root endpoint with API information"""
        return {
            "service": "Pixelle-Video API",
            "version": "0.1.0",
            "docs": api_config.docs_url,
            "health": "/health",
            "api": {
                "llm": f"{api_config.api_prefix}/llm",
                "tts": f"{api_config.api_prefix}/tts",
                "image": f"{api_config.api_prefix}/image",
                "content": f"{api_config.api_prefix}/content",
                "video": f"{api_config.api_prefix}/video",
                "tasks": f"{api_config.api_prefix}/tasks",
                "files": f"{api_config.api_prefix}/files",
                "resources": f"{api_config.api_prefix}/resources",
                "frame": f"{api_config.api_prefix}/frame",
                "post": f"{api_config.api_prefix}/post",
                "devices": f"{api_config.api_prefix}/devices",
                "publish": f"{api_config.api_prefix}/publish",
            }
        }

    return app


# Create FastAPI app
app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Start Pixelle-Video API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    # Print startup banner
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    Pixelle-Video API Server                      ║
╚══════════════════════════════════════════════════════════════╝

Starting server at http://{args.host}:{args.port}
API Docs: http://{args.host}:{args.port}/docs
ReDoc: http://{args.host}:{args.port}/redoc

Press Ctrl+C to stop the server
""")

    # Start server
    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
