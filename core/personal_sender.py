"""
企业微信个人发送模块
通过模拟键盘操作，在企业微信 PC 端逐个搜索联系人并发送消息。

原理：Ctrl+F 搜索联系人 → 选定结果 → 回车进入聊天 → 粘贴消息 → 发送

与 WebhookSender 保持一致的接口设计，复用 SendResult 类。
"""

import time
import logging
from datetime import datetime
from typing import List, Dict, Callable, Optional

from core.sender import SendResult
from core.config import LOGS_DIR
import traceback


logger = logging.getLogger(__name__)


# ── 发送参数默认值（可在 UI 中覆盖） ──────────────────────
DEFAULT_SEARCH_DELAY        = 1.5   # 搜索后等结果加载（秒）
DEFAULT_CHAT_LOAD_DELAY     = 1.0   # 进入聊天后等加载（秒）
DEFAULT_SEND_INTERVAL       = 2.0   # 每条消息发完后等待（秒）
DEFAULT_COOLDOWN_AFTER_SEND = 1.0   # 发送后冷却（秒）


def _require_pyautogui():
    """懒加载 pyautogui，避免在无 GUI 环境下 import 报错"""
    try:
        import pyautogui
        import pyperclip
        return pyautogui, pyperclip
    except ImportError as e:
        raise ImportError(
            "个人发送功能需要安装额外依赖，请运行：\n"
            "  pip install pyautogui pyperclip"
        ) from e


class PersonalSender:
    """
    企业微信个人消息发送器

    通过 pyautogui 模拟键盘操作发送消息，接口设计与 WebhookSender 对齐。
    """

    def __init__(
        self,
        search_delay: float       = DEFAULT_SEARCH_DELAY,
        chat_load_delay: float    = DEFAULT_CHAT_LOAD_DELAY,
        send_interval: float      = DEFAULT_SEND_INTERVAL,
        cooldown_after_send: float = DEFAULT_COOLDOWN_AFTER_SEND,
        dry_run: bool             = False # only search no sending
    ):
        self.search_delay        = search_delay
        self.chat_load_delay     = chat_load_delay
        self.send_interval       = send_interval
        self.cooldown_after_send = cooldown_after_send
        self.dry_run             = dry_run 

        self.is_running  = False
        self._stop_flag  = False

    # ── 私有操作 ──────────────────────────────────────────

    def _switch_to_wecom(self, pyautogui):
        """直接找到企业微信窗口并激活"""
        import pygetwindow as gw

        # 企业微信窗口标题关键词
        windows = gw.getWindowsWithTitle("企业微信")
        if not windows:
            raise RuntimeError("未找到企业微信窗口，请确认企业微信已打开")

        win = windows[0]
        win.restore()    # 如果最小化了，先还原
        win.activate()   # 激活窗口（置顶+获取焦点）
        time.sleep(0.8)  # 等窗口激活完成

    def _search_contact(self, name: str, unit: str, selector: Optional[str], pyautogui, pyperclip) -> bool:
        """
        搜索联系人，用 OCR 验证单位后进入聊天。
 
        流程：
            Ctrl+F 打开搜索 → 粘贴姓名 → 等待结果加载
            → OCR 读取第一条结果的部门文字
            → 匹配单位 → 回车进入聊天
            → 不匹配 → 跳过，记录警告
        """
        import pygetwindow as gw
        from core.ocr_helper import get_ocr
 
        # 激活企业微信窗口
        windows = gw.getWindowsWithTitle("企业微信")
        if not windows:
            raise RuntimeError("未找到企业微信窗口，请确认企业微信已打开")
        win = windows[0]
        win.restore()
        win.activate()
        time.sleep(0.8)
 
        # 打开搜索框
        pyautogui.hotkey("ctrl", "alt", "f")
        time.sleep(0.6)
 
        # 粘贴姓名（用粘贴代替逐字输入，避免中文乱码）
        pyperclip.copy(name)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(self.search_delay)

        ocr = get_ocr()


        contact = ocr.find_contact(name, unit)

        if not contact:

            logger.warning(
                f"未找到联系人: {name} / {unit}"
            )

            pyautogui.press("esc")
            time.sleep(0.3)

            return False

        pyautogui.click(
            contact["click_x"],
            contact["click_y"]
        )

        time.sleep(self.chat_load_delay)

        # pyautogui.press("enter")
        # time.sleep(self.chat_load_delay)

        return True
 

    # def _paste_and_send(self, message: str, pyautogui, pyperclip):
    #     """将消息粘贴到输入框并发送"""
    #     pyperclip.copy(message)
    #     time.sleep(0.2)
    #     pyautogui.hotkey("ctrl", "v")
    #     time.sleep(0.3)
    #     pyautogui.press("enter")
    #     time.sleep(self.cooldown_after_send)

    def _paste_and_send(self, message: str, file_paths: list, pyautogui, pyperclip):
        """
        先发文字消息，再发文件。
        每次发送之间留足够的间隔等企业微信处理。

        Args:
            message:    文字消息内容
            file_paths: 文件路径列表，空列表则只发文字
            pyautogui:  pyautogui 模块
            pyperclip:  pyperclip 模块
        """
        import time

        # ── 第一步：发文字 ──────────────────────────────────────
        if message:
            pyperclip.copy(message)
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(self.cooldown_after_send)

        # ── 第二步：逐个发文件 ──────────────────────────────────
        if file_paths:
            from core.clipboard_helper import copy_files_to_clipboard
            ok = copy_files_to_clipboard(file_paths)
            if ok:
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.8)   # 等企业微信加载文件预览
                pyautogui.press("enter")
                time.sleep(self.cooldown_after_send)
            else:
                logger.warning("文件复制到剪贴板失败，跳过文件发送")

    # ── 公开接口 ──────────────────────────────────────────

    def send_to_persons(
        self,
        persons: List[Dict],
        content: str,
        file_paths: list = None,
        progress_callback: Optional[Callable] = None,
        result_callback:   Optional[Callable] = None,
    ) -> List[SendResult]:
        """
        批量发送消息到多个联系人。

        Args:
            persons: 联系人列表，每项包含 name（姓名）和 selector（可选，
                     字符串数字表示选第几条搜索结果，None 表示选第 1 条）
            content: 消息内容（纯文本，企业微信个人会话不支持 Markdown）
            progress_callback: 进度回调 callback(current, total, name)
            result_callback:   结果回调 callback(result: SendResult)

        Returns:
            发送结果列表（复用 SendResult）
        """
        pyautogui, pyperclip = _require_pyautogui()
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE    = 0.3

        results: List[SendResult] = []
        total = len(persons)
        self.is_running = True
        self._stop_flag = False

        logger.info(f"开始发送消息到 {total} 位联系人")

        for i, person in enumerate(persons):
            if self._stop_flag:
                logger.info("发送已停止")
                break

            name     = person.get("name", "未知")
            selector = person.get("selector")   # None 或数字字符串

            if progress_callback:
                progress_callback(i + 1, total, name)

            logger.info(f"[{i+1}/{total}] 正在发送到: {name}")

            result = SendResult(name, False, "未知错误")  # ← 加这行
            try:
                self._switch_to_wecom(pyautogui)
                unit = person.get("unit", "")
                proceeded = self._search_contact(name, unit, selector, pyautogui, pyperclip)

                if not proceeded:
                    result = SendResult(name, False, "未找到匹配联系人")
                    if result_callback:
                        result_callback(result)
                    continue

                if self.dry_run:
                    time.sleep(0.5)
                    result = SendResult(name, True, "[测试] 已找到联系人，未发送")
                    logger.info(f"✓ [DRY RUN] {name} - 找到但未发送")
                else:
                    self._paste_and_send(content, file_paths or [], pyautogui, pyperclip)
                    result = SendResult(name, True, "发送成功")
                    logger.info(f"✓ {name} - 发送成功")

            # except Exception as e:
            #     # pyautogui.FailSafeException 也在此捕获
            #     msg = "鼠标触发紧急停止" if "FailSafe" in type(e).__name__ else str(e)
            #     result = SendResult(name, False, msg)
            #     # logger.error(f"✗ {name} - {msg}")
            except Exception as e:
                logger.error(traceback.format_exc())

                if "FailSafe" in type(e).__name__:
                    result = SendResult(name, False, "鼠标触发紧急停止")
                    results.append(result)
                    if result_callback:
                        result_callback(result)
                    self._stop_flag = True
                    break

                result = SendResult(name, False, f"错误: {e}")

            results.append(result)
            if result_callback:
                result_callback(result)

            # 发送间隔（最后一条不等待）
            if i < total - 1 and not self._stop_flag:
                time.sleep(self.send_interval)

        self.is_running = False
        success_count = sum(1 for r in results if r.success)
        logger.info(f"发送完成: {success_count}/{len(results)} 成功")
        return results

    def stop(self):
        """停止发送"""
        self._stop_flag = True
        logger.info("正在停止个人发送...")

    @staticmethod
    def check_dependencies() -> tuple:
        """
        检查依赖是否已安装。

        Returns:
            (ok: bool, message: str)
        """
        try:
            import pyautogui   # noqa: F401
            import pyperclip   # noqa: F401
            return True, "依赖已安装"
        except ImportError as e:
            return False, f"缺少依赖: {e}\n请运行: pip install pyautogui pyperclip"