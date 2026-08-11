"""
Webhook 发送模块
负责向企业微信群机器人发送消息
"""

import json
import time
import logging
import requests
from datetime import datetime
from typing import Dict, List, Callable, Optional
from pathlib import Path

from core.config import LOGS_DIR


# 配置日志
log_file = LOGS_DIR / "send.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SendResult:
    """发送结果"""

    def __init__(self, group_name: str, success: bool, message: str, timestamp: str = None):
        self.group_name = group_name
        self.success = success
        self.message = message
        self.timestamp = timestamp or datetime.now().strftime("%H:%M:%S")

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"[{self.timestamp}] {status} {self.group_name} - {self.message}"


class WebhookSender:
    """Webhook 消息发送器"""

    def __init__(self, interval: float = 3.0, retries: int = 2, timeout: int = 10):
        """
        初始化发送器

        Args:
            interval: 发送间隔（秒），默认3秒（每分钟20条，留余量）
            retries: 失败重试次数，默认2次
            timeout: HTTP请求超时时间（秒），默认10秒
        """
        self.interval = interval
        self.retries = retries
        self.timeout = timeout
        self.is_running = False
        self._stop_flag = False

    def send_message(self, webhook_url: str, content: str) -> tuple:
        """
        发送单条消息

        Args:
            webhook_url: webhook地址
            content: 消息内容（Markdown格式）

        Returns:
            (success: bool, message: str)
        """
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }

        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=self.timeout
                )
                result = resp.json()

                if result.get("errcode") == 0:
                    return True, "发送成功"
                else:
                    error_msg = result.get("errmsg", "未知错误")
                    if attempt < self.retries:
                        logger.warning(f"发送失败，{2}秒后重试: {error_msg}")
                        time.sleep(2)
                        continue
                    return False, f"错误: {error_msg}"

            except requests.exceptions.Timeout:
                if attempt < self.retries:
                    logger.warning(f"请求超时，2秒后重试")
                    time.sleep(2)
                    continue
                return False, "请求超时"

            except requests.exceptions.ConnectionError:
                if attempt < self.retries:
                    logger.warning(f"连接失败，2秒后重试")
                    time.sleep(2)
                    continue
                return False, "连接失败，请检查网络"

            except Exception as e:
                if attempt < self.retries:
                    logger.warning(f"发送异常，2秒后重试: {str(e)}")
                    time.sleep(2)
                    continue
                return False, f"异常: {str(e)}"

        return False, "重试次数已用完"

    def send_to_groups(
        self,
        groups: List[Dict],
        content: str,
        progress_callback: Optional[Callable] = None,
        result_callback: Optional[Callable] = None
    ) -> List[SendResult]:
        """
        批量发送消息到多个群

        Args:
            groups: 群组列表，每个群组包含 name 和 webhook
            content: 消息内容
            progress_callback: 进度回调函数 callback(current, total, group_name)
            result_callback: 结果回调函数 callback(result: SendResult)

        Returns:
            发送结果列表
        """
        results = []
        total = len(groups)
        self.is_running = True
        self._stop_flag = False

        logger.info(f"开始发送消息到 {total} 个群")

        for i, group in enumerate(groups):
            # 检查停止标志
            if self._stop_flag:
                logger.info("发送已停止")
                break

            group_name = group.get("name", "未知群")
            webhook_url = group.get("webhook", "")

            # 更新进度
            if progress_callback:
                progress_callback(i + 1, total, group_name)

            # 发送消息
            logger.info(f"[{i+1}/{total}] 正在发送到: {group_name}")
            success, message = self.send_message(webhook_url, content)

            # 记录结果
            result = SendResult(group_name, success, message)
            results.append(result)

            if success:
                logger.info(f"✓ {group_name} - 发送成功")
            else:
                logger.error(f"✗ {group_name} - {message}")

            # 结果回调
            if result_callback:
                result_callback(result)

            # 发送间隔（最后一个不等待）
            if i < total - 1 and not self._stop_flag:
                time.sleep(self.interval)

        self.is_running = False
        logger.info(f"发送完成: {sum(1 for r in results if r.success)}/{len(results)} 成功")
        return results

    def stop(self):
        """停止发送"""
        self._stop_flag = True
        logger.info("正在停止发送...")

    def test_webhook(self, webhook_url: str) -> tuple:
        """
        测试 webhook 是否可用

        Args:
            webhook_url: webhook地址

        Returns:
            (success: bool, message: str)
        """
        test_content = "<font color=\"info\">【测试消息】</font>\n\n这是一条测试消息，用于验证 Webhook 配置是否正确。"
        return self.send_message(webhook_url, test_content)


class SendLog:
    """发送日志管理"""

    HISTORY_FILE = LOGS_DIR / "history.json"

    def __init__(self):
        self.logs: List[Dict] = []
        self.history: List[Dict] = self._load_history()

    def _load_history(self) -> List[Dict]:
        """加载历史记录"""
        if self.HISTORY_FILE.exists():
            try:
                with open(self.HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_history(self):
        """保存历史记录"""
        with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def add(self, result: SendResult, content: str = ""):
        """添加日志"""
        log_entry = {
            "timestamp": result.timestamp,
            "group_name": result.group_name,
            "success": result.success,
            "message": result.message
        }
        self.logs.append(log_entry)

    def save_to_history(self, content: str, stats: Dict):
        """保存本次发送记录到历史"""
        if not self.logs:
            return

        record = {
            "id": len(self.history) + 1,
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "content": content[:200] + "..." if len(content) > 200 else content,
            "total": stats["total"],
            "success": stats["success"],
            "failed": stats["failed"],
            "details": self.logs.copy()
        }
        self.history.append(record)
        self._save_history()

    def get_logs(self) -> List[Dict]:
        """获取当前日志"""
        return self.logs

    def get_history(self) -> List[Dict]:
        """获取历史记录"""
        return self.history

    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = len(self.logs)
        success = sum(1 for log in self.logs if log["success"])
        failed = total - success
        return {
            "total": total,
            "success": success,
            "failed": failed
        }

    def clear(self):
        """清空当前日志"""
        self.logs.clear()

    def clear_history(self):
        """清空历史记录"""
        self.history.clear()
        self._save_history()

    def export_to_text(self) -> str:
        """导出日志为文本"""
        lines = ["=" * 50]
        lines.append("发送日志")
        lines.append("=" * 50)

        for log in self.logs:
            status = "✓" if log["success"] else "✗"
            lines.append(f"[{log['timestamp']}] {status} {log['group_name']} - {log['message']}")

        stats = self.get_stats()
        lines.append("-" * 50)
        lines.append(f"总计: {stats['total']} | 成功: {stats['success']} | 失败: {stats['failed']}")
        lines.append("=" * 50)

        return "\n".join(lines)

    def export_history_to_text(self, record_id: int = None) -> str:
        """导出历史记录为文本"""
        lines = ["=" * 60]
        lines.append("发送历史记录")
        lines.append("=" * 60)

        records = self.history
        if record_id is not None:
            records = [r for r in records if r["id"] == record_id]

        for record in records:
            lines.append(f"\n发送时间: {record['datetime']}")
            lines.append(f"消息内容: {record['content']}")
            lines.append(f"发送结果: 总计 {record['total']} | 成功 {record['success']} | 失败 {record['failed']}")
            lines.append("-" * 40)

            for detail in record.get("details", []):
                status = "✓" if detail["success"] else "✗"
                lines.append(f"  [{detail['timestamp']}] {status} {detail['group_name']} - {detail['message']}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)
