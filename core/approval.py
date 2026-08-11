"""
审批流程管理模块

待审批任务持久化 + 审计日志，全部 JSON 落盘到 data/ 与 logs/，
单机运行、零外部依赖。所有写盘使用 tmp + os.replace 原子替换，
保证异常中断（崩溃/断电）下状态一致、可续发。
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.config import DATA_DIR, LOGS_DIR

logger = logging.getLogger(__name__)

# ── 任务状态常量 ──────────────────────────────────────────
STATUS_PENDING = "pending"        # 待审批
STATUS_APPROVED = "approved"      # 已通过（决策已固化，等待执行）
STATUS_SENDING = "sending"        # 发送中（写前提交，崩溃可恢复）
STATUS_DONE = "done"              # 已完成
STATUS_FAILED = "failed"          # 失败/中断标记
STATUS_REJECTED = "rejected"      # 已驳回

# ── 文件路径 ──────────────────────────────────────────────
PENDING_TASKS_FILE = DATA_DIR / "pending_tasks.json"
AUDIT_FILE = LOGS_DIR / "audit.jsonl"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write_json(file_path: Path, data) -> None:
    """写 tmp 文件后 os.replace 原子替换，避免崩溃损坏 JSON"""
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, file_path)


class PendingTaskStore:
    """待审批任务队列持久化（JSON 数组）"""

    def __init__(self, file_path: Path = PENDING_TASKS_FILE):
        self.file_path = file_path
        self.tasks: List[Dict] = []
        self.load()

    # ── 文件读写 ──────────────────────────────────────────
    def load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.tasks = json.load(f)
                return
            except (json.JSONDecodeError, IOError):
                logger.warning("pending_tasks.json 读取失败，按空队列处理")
        self.tasks = []

    def save(self):
        _atomic_write_json(self.file_path, self.tasks)

    # ── 查询 ──────────────────────────────────────────────
    def _next_id(self) -> int:
        return max((t["id"] for t in self.tasks), default=0) + 1

    def list(self, status: Optional[str] = None) -> List[Dict]:
        if status is None:
            return self.tasks
        return [t for t in self.tasks if t.get("status") == status]

    def get(self, task_id: int) -> Optional[Dict]:
        return next((t for t in self.tasks if t["id"] == task_id), None)

    def get_stale_sending(self) -> List[Dict]:
        """获取异常中断后残留的 sending 任务，供启动恢复"""
        return [t for t in self.tasks if t.get("status") == STATUS_SENDING]

    # ── 写操作 ────────────────────────────────────────────
    def add(self, task: Dict) -> Dict:
        """新增一条待审批任务"""
        task["id"] = self._next_id()
        task["status"] = task.get("status", STATUS_PENDING)
        task["submitted_at"] = task.get("submitted_at") or _now()
        task.setdefault("sent_targets", [])
        task.setdefault("remaining_targets", [])
        self.tasks.append(task)
        self.save()
        return task

    def update_status(self, task_id: int, status: str,
                      reviewer: str = None, detail: Dict = None) -> bool:
        """更新任务状态；进入 approved/rejected 时记录审批时间"""
        task = self.get(task_id)
        if task is None:
            return False
        task["status"] = status
        if reviewer is not None:
            task["reviewer"] = reviewer
        if status in (STATUS_APPROVED, STATUS_REJECTED):
            task["reviewed_at"] = task.get("reviewed_at") or _now()
        if detail:
            task.update(detail)
        self.save()
        return True

    def update_progress(self, task_id: int, sent: List[Dict],
                        remaining: List[Dict]) -> bool:
        """逐条发送进度落盘，供崩溃续发（只补发 remaining）"""
        task = self.get(task_id)
        if task is None:
            return False
        task["sent_targets"] = sent
        task["remaining_targets"] = remaining
        self.save()
        return True

    def remove(self, task_id: int) -> bool:
        """删除任务（队列清理用）"""
        for i, t in enumerate(self.tasks):
            if t["id"] == task_id:
                self.tasks.pop(i)
                self.save()
                return True
        return False


class AuditLog:
    """追加式审计日志（JSONL，每行一条 JSON）+ 同步写人类可读日志"""

    def __init__(self, file_path: Path = AUDIT_FILE):
        self.file_path = file_path

    def log(self, action: str, task_id: int = None, operator: str = None,
            reviewer: str = None, target_summary: str = None,
            detail: str = None) -> None:
        """追加一条审计记录"""
        record = {
            "ts": _now(),
            "action": action,
            "task_id": task_id,
            "operator": operator,
            "reviewer": reviewer,
            "target_summary": target_summary,
            "detail": detail,
        }
        # 结构化 JSONL
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # 人类可读，与现有 send.log 口径保持一致
        logger.info(
            "[审批] action=%s task_id=%s operator=%s reviewer=%s detail=%s",
            action, task_id, operator, reviewer, detail,
        )
