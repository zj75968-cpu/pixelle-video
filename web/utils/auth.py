import os
import json
import hashlib
import binascii
from pathlib import Path
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"

class AuthService:
    """
    提供多用户账号认证与管理服务。
    使用 PBKDF2 哈希存储用户密码。
    """
    
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._users = {}
        self._load()

    def _load(self):
        if USERS_FILE.exists():
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    self._users = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load users registry: {e}")
                self._users = {}

    def _save(self):
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save users registry: {e}")

    def _hash_password(self, password: str, salt: bytes = None) -> tuple[str, str]:
        """使用 PBKDF2-HMAC 对密码进行加盐哈希"""
        if salt is None:
            salt = os.urandom(16)
        pwd_bytes = password.encode('utf-8')
        dk = hashlib.pbkdf2_hmac('sha256', pwd_bytes, salt, 100000)
        return binascii.hexlify(dk).decode('utf-8'), binascii.hexlify(salt).decode('utf-8')

    def authenticate(self, username: str, password: str) -> bool:
        """校验用户名和密码是否正确"""
        username = username.strip().lower()
        if username not in self._users:
            return False
        
        user_data = self._users[username]
        stored_hash = user_data["password_hash"]
        stored_salt = binascii.unhexlify(user_data["salt"].encode('utf-8'))
        
        computed_hash, _ = self._hash_password(password, stored_salt)
        return computed_hash == stored_hash

    def register(self, username: str, password: str) -> tuple[bool, str]:
        """注册新用户"""
        username = username.strip().lower()
        if not username:
            return False, "用户名不能为空"
        if len(username) < 3:
            return False, "用户名长度必须至少为 3 个字符"
        if len(password) < 6:
            return False, "密码长度必须至少为 6 个字符"
        
        # 限制用户名只能包含字母数字或下划线
        import re
        if not re.match(r"^[a-zA-Z0-9_]+$", username):
            return False, "用户名只能包含字母、数字和下划线"

        if username in self._users:
            return False, "该用户名已被注册"

        password_hash, salt_hex = self._hash_password(password)
        self._users[username] = {
            "password_hash": password_hash,
            "salt": salt_hex,
            "created_at": hashlib.datetime.datetime.now().isoformat() if hasattr(hashlib, "datetime") else ""
        }
        # 兼容处理 datetime
        from datetime import datetime
        self._users[username]["created_at"] = datetime.now().isoformat()
        
        self._save()
        logger.info(f"Successfully registered user: {username}")
        return True, "注册成功"

# 单例对象
auth_service = AuthService()
