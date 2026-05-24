"""
Phone Agent registration endpoint.
Receives the cloudflared tunnel URL from the phone and updates config.yaml.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from loguru import logger
from pathlib import Path

router = APIRouter(prefix="/phone-agent", tags=["Phone Agent"])


@router.get("/setup")
async def get_setup_script():
    """直接返回本地 static/setup_termux.sh 的内容。"""
    script_path = Path(__file__).resolve().parent.parent.parent / "static" / "setup_termux.sh"
    if not script_path.exists():
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "setup_termux.sh"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Setup script not found")
    return FileResponse(script_path, media_type="text/plain")


class RegisterRequest(BaseModel):
    url: str
    token: str = ""


@router.post("/register")
async def register_phone_agent(payload: RegisterRequest, request: Request):
    """
    手机端 phone_agent 启动后自动调用此接口，上报 cloudflared 隧道 URL。
    认证：请求体中的 token 必须与当前 config.phone_agent.token 一致。
    """
    from pixelle_video.config import config_manager

    cfg = config_manager.config
    expected_token = cfg.phone_agent.token.strip()

    # Token 验证：如果已配置 token，必须匹配
    if expected_token:
        import hmac
        if not hmac.compare_digest(payload.token.strip(), expected_token):
            raise HTTPException(status_code=401, detail="Invalid token")

    # 验证 URL 格式
    url = payload.url.strip()
    if not url.startswith("https://") and not url.startswith("http://"):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    # 更新 config
    try:
        config_manager.update({"phone_agent": {"url": url}})
        config_manager.save()
        logger.info(f"phone-agent registered new URL: {url}")
        return {"ok": True, "url": url}
    except Exception as e:
        logger.error(f"phone-agent register failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_phone_agent_status():
    """返回当前配置的 Phone Agent URL 和在线状态。"""
    from pixelle_video.config import config_manager
    from pixelle_video.services.phone_agent_client import ping

    cfg = config_manager.config
    url = cfg.phone_agent.url.strip()
    online = False

    if url:
        online = ping(url, token=cfg.phone_agent.token.strip(), timeout=5)

    return {
        "url": url or None,
        "online": online,
        "chunk_size_mb": cfg.phone_agent.chunk_size_mb,
        "timeout_push": cfg.phone_agent.timeout_push,
    }
