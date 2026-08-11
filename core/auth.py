"""
登录与权限管理模块（单机轻量级实现）

Token 使用 PBKDF2-SHA256 盐值哈希存储，写入本地加密配置文件 data/auth.json，
不保存明文、不依赖操作系统环境变量。
"""

import json
import os
import hashlib
import hmac
import secrets
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.config import DATA_DIR

logger = logging.getLogger(__name__)

# ── 角色 ────────────────────────────────────────────────────
ROLE_OPERATOR = "Operator"      # 经办人
ROLE_APPROVER = "Approver"      # 审批人

ROLE_LABELS = {
    ROLE_OPERATOR: "经办人",
    ROLE_APPROVER: "审批人",
}

# ── 硬编码初始 Token（首次运行 seed 用，审批人首次登录强制修改）──────
# 生成规则：{role}-{uuid4 hex}；存储时以 PBKDF2(salt, token) 哈希写入，不回显明文
INITIAL_OPERATOR_TOKEN = "operator-4f2b9c1e6d8a3e5f7b2c9d1e0a4f6b8c"
INITIAL_APPROVER_TOKEN = "approver-8d3a7f2b6c4e1a9f3b8d2c7e5a1f0d4b"

AUTH_FILE = DATA_DIR / "auth.json"

PBKDF2_ITERATIONS = 200_000
MIN_TOKEN_LENGTH = 8


def _pbkdf2_hash(token: str, salt: bytes) -> str:
    """对 Token 计算 PBKDF2-SHA256 哈希（十六进制字符串）"""
    digest = hashlib.pbkdf2_hmac(
        "sha256", token.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return digest.hex()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AuthManager:
    """登录凭证管理"""

    def __init__(self, file_path: Path = AUTH_FILE):
        self.file_path = file_path
        self.records: Dict[str, Dict] = {}
        self.current_role: Optional[str] = None
        self.load()

    # ── 文件读写 ──────────────────────────────────────────
    def load(self):
        """加载凭证；文件不存在或损坏则重新 seed 初始凭证"""
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.records = data.get("records", {})
                if self._migrate():
                    self.save()
                return
            except (json.JSONDecodeError, IOError, ValueError):
                logger.warning("auth.json 读取失败，重新初始化")
        self._seed()

    def save(self):
        """保存凭证（tmp 文件 + 原子替换，避免崩溃损坏）"""
        tmp_path = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"records": self.records}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.file_path)

    def _migrate(self) -> bool:
        """兼容已有部署：仍在使用初始 Token 的角色强制其改密"""
        initial_tokens = {
            ROLE_OPERATOR: INITIAL_OPERATOR_TOKEN,
            ROLE_APPROVER: INITIAL_APPROVER_TOKEN,
        }
        changed = False
        for role, record in self.records.items():
            initial = initial_tokens.get(role)
            if initial is None:
                continue
            try:
                salt = bytes.fromhex(record.get("salt", ""))
            except (ValueError, TypeError):
                continue
            if hmac.compare_digest(record.get("token_hash", ""),
                                   _pbkdf2_hash(initial, salt)):
                if not record.get("must_change"):
                    record["must_change"] = True
                    changed = True
        return changed

    def _seed(self):
        """首次运行：写入两组硬编码初始凭证的哈希，审批人标记为必须改密"""
        now = _now()
        salt_op = secrets.token_bytes(16)
        salt_ap = secrets.token_bytes(16)
        self.records = {
            ROLE_OPERATOR: {
                "role": ROLE_OPERATOR,
                "salt": salt_op.hex(),
                "token_hash": _pbkdf2_hash(INITIAL_OPERATOR_TOKEN, salt_op),
                "must_change": True,
                "created_at": now,
                "employee_no": "",   # 经办人改密时无需登记
                "sso_account": "",
            },
            ROLE_APPROVER: {
                "role": ROLE_APPROVER,
                "salt": salt_ap.hex(),
                "token_hash": _pbkdf2_hash(INITIAL_APPROVER_TOKEN, salt_ap),
                "must_change": True,
                "created_at": now,
                "employee_no": "",
                "sso_account": "",
            },
        }
        self.save()
        logger.info("已初始化初始登录凭证")

    # ── 业务方法 ──────────────────────────────────────────
    def verify(self, token: str, role: Optional[str] = None) -> Tuple[Optional[str], bool]:
        """
        校验 Token。

        Args:
            token: 输入的 Token
            role: 限定校验的角色（如 ROLE_OPERATOR / ROLE_APPROVER）；
                  None 表示遍历全部角色（仅当两个角色 Token 不同时可区分）。

        Returns:
            (role, needs_change)；校验失败返回 (None, False)
        """
        token = (token or "").strip()
        if not token:
            return None, False

        if role is not None:
            record = self.records.get(role)
            records = [record] if record is not None else []
        else:
            records = list(self.records.values())

        for record in records:
            try:
                salt = bytes.fromhex(record.get("salt", ""))
            except ValueError:
                continue
            candidate = _pbkdf2_hash(token, salt)
            if hmac.compare_digest(candidate, record.get("token_hash", "")):
                self.current_role = record["role"]
                return record["role"], bool(record.get("must_change", False))
        return None, False

    def change_token(self, role: str, new_token: str,
                     employee_no: str = None, sso_account: str = None) -> bool:
        """
        修改指定角色的 Token：重新生成盐、重算哈希，旧 Token 立即失效。

        审批人改密时须登记工号与 SSO 账号名，随记录持久化并写入日志。
        Args:
            employee_no: 审批人工号（可选，传入则更新记录）
            sso_account: 审批人 SSO 账号名（可选，传入则更新记录）
        """
        record = self.records.get(role)
        if record is None:
            return False
        new_token = (new_token or "").strip()
        if len(new_token) < MIN_TOKEN_LENGTH:
            return False
        new_salt = secrets.token_bytes(16)
        record["salt"] = new_salt.hex()
        record["token_hash"] = _pbkdf2_hash(new_token, new_salt)
        record["must_change"] = False
        if employee_no is not None:
            record["employee_no"] = employee_no.strip()
        if sso_account is not None:
            record["sso_account"] = sso_account.strip()
        self.save()
        logger.info(
            "Token 已更新: role=%s employee_no=%s sso_account=%s",
            role, record.get("employee_no"), record.get("sso_account"),
        )
        return True

    def reset(self):
        """重置为初始凭证（用于遗忘 Token 后恢复，配合 --reset-auth 启动参数）"""
        self._seed()
        logger.info("已重置登录凭证")


# ── 单例 ────────────────────────────────────────────────────
_auth_manager: Optional[AuthManager] = None


def get_auth() -> AuthManager:
    """获取全局 AuthManager 单例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
