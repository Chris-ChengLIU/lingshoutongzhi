"""
Windows 剪贴板文件操作辅助模块
将本地文件路径写入剪贴板，使 Ctrl+V 能在企业微信中粘贴文件。
"""

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def copy_files_to_clipboard(file_paths: List[str]) -> bool:
    """
    将文件列表写入 Windows 剪贴板。
    粘贴时企业微信会识别为文件附件。

    Args:
        file_paths: 本地文件路径列表

    Returns:
        True = 成功，False = 失败
    """
    try:
        import win32clipboard
        import win32con

        # 验证文件存在
        valid_paths = []
        for p in file_paths:
            if Path(p).exists():
                valid_paths.append(p)
            else:
                logger.warning(f"文件不存在，跳过: {p}")

        if not valid_paths:
            logger.error("没有有效的文件路径")
            return False

        # 构建 HDROP 格式的文件列表
        # Windows 剪贴板文件格式：每个路径以 \0 分隔，末尾双 \0
        file_list = "\0".join(valid_paths) + "\0\0"
        file_list_bytes = file_list.encode("utf-16-le")

        # DROPFILES 结构头部（20字节）
        import struct
        # pFiles=20（头部大小）, x=0, y=0, fNC=0, fWide=1（Unicode）
        dropfiles_header = struct.pack("IIIII", 20, 0, 0, 0, 1)
        data = dropfiles_header + file_list_bytes

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, data)
        win32clipboard.CloseClipboard()

        logger.info(f"已复制 {len(valid_paths)} 个文件到剪贴板")
        return True

    except ImportError:
        logger.error("缺少 pywin32 依赖，请运行: pip install pywin32")
        return False
    except Exception as e:
        logger.error(f"复制文件到剪贴板失败: {e}")
        try:
            import win32clipboard
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return False


def check_dependencies() -> tuple:
    """
    检查依赖是否已安装。
    Returns:
        (ok: bool, message: str)
    """
    try:
        import win32clipboard  # noqa
        import win32con        # noqa
        return True, "依赖已安装"
    except ImportError:
        return False, "缺少 pywin32 依赖，请运行: pip install pywin32"