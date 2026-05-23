import contextvars
from loguru import logger

# 使用 contextvars 管理协程和线程级用户名绑定
_current_user_var = contextvars.ContextVar("current_user", default=None)

def get_current_username() -> str:
    """
    获取当前上下文的用户名。
    1. 优先使用 contextvars 设置的值（适用于后台任务或特定线程环境）
    2. 如果在 Streamlit 会话中且用户已登录，返回已登录用户名
    3. 兜底返回 "default"
    """
    # 1. 优先从 contextvars 获取
    user = _current_user_var.get()
    if user:
        return user

    # 2. 从 Streamlit 会话状态获取
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx is not None:
            import streamlit as st
            if "username" in st.session_state and st.session_state.username:
                return st.session_state.username
    except Exception:
        pass

    return "default"

class set_current_user:
    """
    上下文管理器：临时设置当前线程/协程执行的用户名。
    
    Usage:
        with set_current_user("admin"):
            # 在此 block 内的所有 get_current_username() 均返回 "admin"
            ...
    """
    def __init__(self, username: str):
        self.username = username
        self.token = None

    def __enter__(self):
        self.token = _current_user_var.set(self.username)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            _current_user_var.reset(self.token)

def find_username_by_token(token: str) -> str:
    """
    根据给定的 phone_agent token 寻找匹配的用户名。
    遍历 data/users/{username}/config.yaml 并读取其 phone_agent.token 进行匹配。
    """
    if not token or not token.strip():
        return "default"
        
    from pathlib import Path
    users_dir = Path("data/users")
    if users_dir.exists():
        for u_dir in users_dir.iterdir():
            if u_dir.is_dir():
                cfg_file = u_dir / "config.yaml"
                if cfg_file.exists():
                    try:
                        # 简单用 pyyaml 读取
                        import yaml
                        with open(cfg_file, "r", encoding="utf-8") as f:
                            cfg = yaml.safe_load(f)
                            if cfg and cfg.get("phone_agent", {}).get("token") == token:
                                return u_dir.name
                    except Exception:
                        pass
    return "default"
