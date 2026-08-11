"""
零售通知自动分发工具
主程序入口
"""

import sys
import os

# 添加项目根目录到路径
if getattr(sys, 'frozen', False):
    # 打包后的路径
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 开发环境路径
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

import logging
from core.config import LOGS_DIR

logging.basicConfig(
    filename=os.path.join(str(LOGS_DIR), "app.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
    force=True
)


from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtGui import QFont
from ui.main_window import MainWindow


def main():
    """主函数"""
    # 处理 --reset-auth：重置为初始凭证（遗忘 Token 后恢复用）
    if "--reset-auth" in sys.argv:
        from core.auth import get_auth
        get_auth().reset()
        print("已重置为初始 Token（详见 core/auth.py 中的 INITIAL_*_TOKEN 常量）")
        return

    app = QApplication(sys.argv)

    # 设置应用程序字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # 设置应用程序样式
    app.setStyle("Fusion")

    # ── 登录拦截 ──────────────────────────────────────────
    from core.auth import get_auth, ROLE_APPROVER
    from ui.login import LoginDialog, ChangeTokenDialog

    auth = get_auth()

    login = LoginDialog(auth)
    if login.exec_() != QDialog.Accepted:
        return  # 用户未登录，退出

    # 首次登录强制改密（经办人 / 审批人）
    if login.needs_change:
        change = ChangeTokenDialog(auth, login.result_role)
        if change.exec_() != QDialog.Accepted:
            return

    # ── 路由/视图隔离 ─────────────────────────────────────
    if login.result_role == ROLE_APPROVER:
        from ui.approval_workbench import ApprovalWorkbench
        window = ApprovalWorkbench(auth=auth)
    else:
        window = MainWindow()

    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
