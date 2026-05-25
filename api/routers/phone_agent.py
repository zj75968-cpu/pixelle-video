"""
Phone Agent registration endpoint.
Receives the cloudflared tunnel URL from the phone and updates config.yaml.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, HttpUrl
from loguru import logger
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import hashlib
import json
import re

router = APIRouter(prefix="/phone-agent", tags=["Phone Agent"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_usernames_by_token(token: str) -> list[str]:
    """Return users whose phone-agent token matches the provided token."""
    token = (token or "").strip()
    if not token:
        return []

    users_dir = _PROJECT_ROOT / "data" / "users"
    if not users_dir.exists():
        return []

    matches: list[str] = []
    for cfg_path in users_dir.glob("*/config.yaml"):
        try:
            import yaml

            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            cfg_token = str((data.get("phone_agent") or {}).get("token") or "").strip()
            if cfg_token == token:
                matches.append(cfg_path.parent.name)
        except Exception as e:
            logger.debug(f"skip user config token check {cfg_path}: {e}")
    return matches


def _upsert_user_phone_agent_device(username: str, agent: dict) -> None:
    """Create/update a visible virtual device for one registered phone agent."""
    devices_path = _PROJECT_ROOT / "data" / "users" / username / "devices.json"
    devices_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(devices_path.read_text(encoding="utf-8")) if devices_path.exists() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    now = str(agent.get("last_seen") or datetime.now().isoformat())
    serial = str(agent.get("serial") or "").strip()
    if not serial:
        return
    physical_serial = str(agent.get("device_serial") or "").strip()
    if physical_serial and physical_serial in data and not physical_serial.startswith("phone_agent:"):
        serial = physical_serial
        data.pop(str(agent.get("serial") or ""), None)

    existing = data.get(serial) or {}
    name = str(agent.get("name") or "").strip() or "手机 HTTP 代理"
    data[serial] = {
        "serial": serial,
        "name": existing.get("name") or name,
        "theme": existing.get("theme") or "默认主题",
        "notes": existing.get("notes") or f"phone_agent_url={agent.get('url', '')}",
        "connected": True,
        "last_seen": now,
        "added_at": existing.get("added_at") or now,
    }
    devices_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_url_to_user_configs(url: str, token: str, agent: dict) -> list[str]:
    """Persist a registered phone-agent URL to every matching user config."""
    users = _find_usernames_by_token(token)
    if not users:
        return []

    updated: list[str] = []
    for username in users:
        cfg_path = _PROJECT_ROOT / "data" / "users" / username / "config.yaml"
        try:
            import yaml

            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            phone_agent = data.setdefault("phone_agent", {})
            phone_agent["url"] = url
            agents = phone_agent.setdefault("agents", {})
            if not isinstance(agents, dict):
                agents = {}
                phone_agent["agents"] = agents
            agents[str(agent["agent_id"])] = agent
            cfg_path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            _upsert_user_phone_agent_device(username, agent)
            updated.append(username)
        except Exception as e:
            logger.warning(f"failed to update phone-agent URL for user {username}: {e}")
    return updated


def _detect_pixelle_url(request: Request) -> str:
    """根据请求头推断当前 Pixelle-Video 服务的公网根 URL。

    优先级：X-Forwarded-* 头（nginx 反代场景）> Host 头 > 兜底 localhost。
    """
    fwd_proto = request.headers.get("x-forwarded-proto", "").strip()
    fwd_host = request.headers.get("x-forwarded-host", "").strip()
    host = request.headers.get("host", "").strip()

    scheme = fwd_proto or request.url.scheme or "http"
    netloc = fwd_host or host or "127.0.0.1:8000"
    return f"{scheme}://{netloc}".rstrip("/")


def _clean_agent_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (value or "").strip()).strip("-")
    return cleaned[:80]


def _fallback_agent_id(url: str) -> str:
    host = urlparse(url).hostname or ""
    label = host.split(".")[0] if host else ""
    return _clean_agent_id(label) or hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _build_agent_record(payload: "RegisterRequest", request: Request, url: str) -> dict:
    raw_id = (
        getattr(payload, "agent_id", "")
        or getattr(payload, "device_serial", "")
        or _fallback_agent_id(url)
    )
    agent_id = _clean_agent_id(raw_id) or _fallback_agent_id(url)
    serial = f"phone_agent:{agent_id}"
    device_serial = (getattr(payload, "device_serial", "") or "").strip()
    device_name = (getattr(payload, "device_name", "") or "").strip()
    name_suffix = device_name or device_serial or agent_id[-8:]
    now = datetime.now().isoformat()

    return {
        "agent_id": agent_id,
        "serial": serial,
        "url": url,
        "device_serial": device_serial,
        "device_name": device_name,
        "name": f"手机 HTTP 代理 - {name_suffix}",
        "last_seen": now,
        "source_ip": request.client.host if request.client else "",
    }


@router.get("/setup", response_class=PlainTextResponse)
async def get_setup_script(request: Request):
    """返回 setup_termux.sh，并将 VPS URL 与 token 注入到脚本占位符中。

    用法（手机 Termux）：
        curl -sSL http://<VPS>/api/phone-agent/setup | bash
    """
    from pixelle_video.config import config_manager

    script_path = _PROJECT_ROOT / "scripts" / "setup_termux.sh"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="setup_termux.sh not found")

    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"read setup script failed: {e}")

    pixelle_url = _detect_pixelle_url(request)
    token = config_manager.config.phone_agent.token.strip()

    rendered = (
        content
        .replace("__PIXELLE_URL__", pixelle_url)
        .replace("__PIXELLE_TOKEN__", token)
    )
    return PlainTextResponse(rendered, media_type="text/x-shellscript; charset=utf-8")


@router.get("/agent-script", response_class=PlainTextResponse)
async def get_agent_script():
    """返回 scripts/phone_agent.py 的原始内容，供手机端 setup 脚本下载。"""
    script_path = _PROJECT_ROOT / "scripts" / "phone_agent.py"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="phone_agent.py not found")
    return FileResponse(script_path, media_type="text/x-python; charset=utf-8")


class RegisterRequest(BaseModel):
    url: str
    token: str = ""
    agent_id: str = ""
    device_serial: str = ""
    device_name: str = ""


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
        agent = _build_agent_record(payload, request, url)
        config_manager.update({
            "phone_agent": {
                "url": url,
                "agents": {agent["agent_id"]: agent},
            }
        })
        config_manager.save()
        updated_users = _save_url_to_user_configs(url, payload.token.strip(), agent)
        logger.info(
            f"phone-agent registered new URL: {url}; "
            f"agent={agent['agent_id']}; users={updated_users}"
        )
        return {
            "ok": True,
            "url": url,
            "agent_id": agent["agent_id"],
            "serial": agent["serial"],
            "users": updated_users,
        }
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
    agents = getattr(cfg.phone_agent, "agents", {}) or {}
    online = False

    if url:
        online = ping(url, token=cfg.phone_agent.token.strip(), timeout=5)

    return {
        "url": url or None,
        "online": online,
        "chunk_size_mb": cfg.phone_agent.chunk_size_mb,
        "timeout_push": cfg.phone_agent.timeout_push,
        "agents": agents,
    }
