"""
登录与改密对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFormLayout, QDialogButtonBox,
    QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core.auth import (
    AuthManager, MIN_TOKEN_LENGTH,
    ROLE_OPERATOR, ROLE_APPROVER, ROLE_LABELS,
)


class LoginDialog(QDialog):
    """登录对话框：输入 Token 验证"""

    def __init__(self, auth: AuthManager, parent=None):
        super().__init__(parent)
        self.auth = auth
        self.result_role = None      # 登录成功后的角色
        self.needs_change = False    # 是否必须强制改密
        self.setWindowTitle("登录")
        self.setMinimumWidth(380)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("零售通知自动分发工具")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(QLabel("角色："))
        self.role_combo = QComboBox()
        self.role_combo.addItem(ROLE_LABELS[ROLE_OPERATOR], ROLE_OPERATOR)
        self.role_combo.addItem(ROLE_LABELS[ROLE_APPROVER], ROLE_APPROVER)
        layout.addWidget(self.role_combo)

        layout.addWidget(QLabel("Token："))
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("请输入 Token")
        self.token_edit.returnPressed.connect(self.do_login)
        layout.addWidget(self.token_edit)

        btn_row = QHBoxLayout()
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self.do_login)
        btn_row.addWidget(self.login_btn)

        self.cancel_btn = QPushButton("退出")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

    def do_login(self):
        token = self.token_edit.text().strip()
        selected_role = self.role_combo.currentData()
        result_role, needs_change = self.auth.verify(token, role=selected_role)
        if not result_role:
            QMessageBox.warning(self, "提示", "Token 错误，请重试")
            self.token_edit.clear()
            self.token_edit.setFocus()
            return
        self.result_role = result_role
        self.needs_change = needs_change
        self.accept()


class ChangeTokenDialog(QDialog):
    """首次登录强制修改 Token"""

    def __init__(self, auth: AuthManager, role: str, forced: bool = True, parent=None):
        super().__init__(parent)
        self.auth = auth
        self.role = role
        self.forced = forced
        self.is_approver = (role == ROLE_APPROVER)   # 审批人改密必须登记工号与 SSO 账号
        self.employee_no = ""
        self.sso_account = ""
        self.setWindowTitle("首次登录，请修改 Token" if forced else "修改 Token")
        self.setMinimumWidth(420)
        self.init_ui()

    def init_ui(self):
        form = QFormLayout(self)
        form.setSpacing(10)

        tip_text = (
            "您正在使用初始 Token，为安全起见请立即修改。"
            if self.forced else
            "请输入新 Token，修改后旧 Token 立即失效。"
        )
        tip = QLabel(tip_text)
        tip.setWordWrap(True)
        form.addRow(tip)

        self.new_token_edit = QLineEdit()
        self.new_token_edit.setEchoMode(QLineEdit.Password)
        self.new_token_edit.setPlaceholderText(f"至少 {MIN_TOKEN_LENGTH} 位")
        form.addRow("新 Token：", self.new_token_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit.setPlaceholderText("再次输入新 Token")
        form.addRow("确认 Token：", self.confirm_edit)

        if self.is_approver:
            # 审批人改密必须登记身份信息，便于审计追溯
            self.employee_no_edit = QLineEdit()
            self.employee_no_edit.setPlaceholderText("请输入工号")
            form.addRow("工号：", self.employee_no_edit)

            self.sso_account_edit = QLineEdit()
            self.sso_account_edit.setPlaceholderText("请输入 SSO 账号名")
            form.addRow("SSO 账号名：", self.sso_account_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate_and_accept(self):
        new_token = self.new_token_edit.text().strip()
        confirm = self.confirm_edit.text().strip()
        if len(new_token) < MIN_TOKEN_LENGTH:
            QMessageBox.warning(self, "提示", f"Token 长度至少 {MIN_TOKEN_LENGTH} 位")
            return
        if new_token != confirm:
            QMessageBox.warning(self, "提示", "两次输入的 Token 不一致")
            return

        employee_no, sso_account = "", ""
        if self.is_approver:
            # 审批人改密强制登记工号与 SSO 账号名
            employee_no = self.employee_no_edit.text().strip()
            sso_account = self.sso_account_edit.text().strip()
            if not employee_no:
                QMessageBox.warning(self, "提示", "审批人修改 Token 必须填写工号")
                return
            if not sso_account:
                QMessageBox.warning(self, "提示", "审批人修改 Token 必须填写 SSO 账号名")
                return

        if not self.auth.change_token(
            self.role, new_token,
            employee_no=employee_no or None,
            sso_account=sso_account or None,
        ):
            QMessageBox.warning(self, "提示", "修改失败，请重试")
            return

        self.employee_no = employee_no
        self.sso_account = sso_account
        if self.is_approver:
            self._audit_change(employee_no, sso_account)

        QMessageBox.information(self, "成功", "Token 已更新，后续请使用新 Token 登录")
        self.accept()

    def _audit_change(self, employee_no: str, sso_account: str):
        """把审批人改密事件连同工号/SSO 账号写入审计日志（audit.jsonl + app.log）"""
        from core.approval import AuditLog
        AuditLog().log(
            "change_token",
            reviewer=ROLE_LABELS.get(self.role, self.role),
            detail=f"工号={employee_no}, SSO账号={sso_account}",
        )
