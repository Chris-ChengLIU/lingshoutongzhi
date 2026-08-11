"""
发送控制面板
配置发送参数、选择目标群组、控制发送流程
"""

import re
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QCheckBox, QProgressBar, QGroupBox, QListWidget,
    QListWidgetItem, QAbstractItemView, QMessageBox, QSplitter,
    QTextEdit, QFrame, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QTextCursor

from core.config import GroupConfig
from core.sender import WebhookSender, SendResult, SendLog


class VariableDialog(QDialog):
    """变量填写对话框"""

    # 常见变量的中文说明
    VAR_LABELS = {
        "{topic}": "会议主题",
        "{time}": "会议时间",
        "{location}": "会议地点",
        "{attendees}": "参会人员",
        "{notes}": "备注",
        "{content}": "通知内容",
        "{date}": "日期",
        "{title}": "标题",
    }

    def __init__(self, variables: list, parent=None):
        super().__init__(parent)
        self.variables = variables
        self.inputs = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("填写模板变量")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)

        tip = QLabel("检测到消息中包含以下变量，请填写对应内容：")
        tip.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(tip)

        form_layout = QFormLayout()

        for var in self.variables:
            label = self.VAR_LABELS.get(var, var)
            line_edit = QLineEdit()
            line_edit.setPlaceholderText(f"请输入{label}")
            form_layout.addRow(f"{label} ({var}):", line_edit)
            self.inputs[var] = line_edit

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        """获取用户填写的变量值"""
        return {var: edit.text() for var, edit in self.inputs.items()}


class SendThread(QThread):
    """发送线程"""
    progress = pyqtSignal(int, int, str)  # current, total, group_name
    result = pyqtSignal(object)  # SendResult
    finished = pyqtSignal(list)  # List[SendResult]

    def __init__(self, sender: WebhookSender, groups: list, content: str):
        super().__init__()
        self.sender = sender
        self.groups = groups
        self.content = content

    def run(self):
        results = self.sender.send_to_groups(
            self.groups,
            self.content,
            progress_callback=lambda c, t, n: self.progress.emit(c, t, n),
            result_callback=lambda r: self.result.emit(r)
        )
        self.finished.emit(results)


class SendPanel(QWidget):
    """发送控制面板"""

    def __init__(self, group_config: GroupConfig, parent=None):
        super().__init__(parent)
        self.group_config = group_config
        self.sender = WebhookSender()
        self.send_log = SendLog()
        self.send_thread = None
        self.is_sending = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 发送参数设置
        settings_group = QGroupBox("发送设置")
        settings_layout = QHBoxLayout(settings_group)

        settings_layout.addWidget(QLabel("发送间隔:"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 30)
        self.interval_spin.setValue(3)
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setToolTip("企业微信限制每个机器人每分钟最多20条消息")
        settings_layout.addWidget(self.interval_spin)

        settings_layout.addWidget(QLabel("重试次数:"))
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 5)
        self.retries_spin.setValue(2)
        self.retries_spin.setSuffix(" 次")
        settings_layout.addWidget(self.retries_spin)

        settings_layout.addStretch()

        layout.addWidget(settings_group)

        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：群组选择
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        group_header = QHBoxLayout()
        group_header.addWidget(QLabel("📋 目标群组:"))

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all)
        group_header.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("全不选")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        group_header.addWidget(self.deselect_all_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh_group_list)
        group_header.addWidget(self.refresh_btn)

        left_layout.addLayout(group_header)

        # 群组列表（带复选框）
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QAbstractItemView.NoSelection)
        left_layout.addWidget(self.group_list)

        # 选中数量统计
        self.selection_label = QLabel("已选: 0/0")
        left_layout.addWidget(self.selection_label)

        splitter.addWidget(left_widget)

        # 右侧：发送控制和日志
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 发送按钮区域
        btn_layout = QHBoxLayout()

        self.send_btn = QPushButton("🚀 提交审批")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.send_btn.clicked.connect(self.start_send)
        btn_layout.addWidget(self.send_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_send)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        right_layout.addLayout(btn_layout)

        # 进度条
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("进度:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        right_layout.addLayout(progress_layout)

        # 状态标签
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-size: 12px; padding: 5px;")
        right_layout.addWidget(self.status_label)

        # 发送日志
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("📝 发送日志:"))
        log_header.addStretch()

        self.history_btn = QPushButton("📋 历史记录")
        self.history_btn.clicked.connect(self.show_history)
        log_header.addWidget(self.history_btn)

        self.clear_log_btn = QPushButton("清空")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_header.addWidget(self.clear_log_btn)

        self.export_log_btn = QPushButton("导出")
        self.export_log_btn.clicked.connect(self.export_log)
        log_header.addWidget(self.export_log_btn)

        right_layout.addLayout(log_header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.log_text)

        splitter.addWidget(right_widget)

        # 设置分割比例
        splitter.setSizes([300, 500])
        layout.addWidget(splitter)

        # 初始加载群组列表
        self.refresh_group_list()

    def refresh_group_list(self):
        """刷新群组列表"""
        self.group_list.clear()
        groups = self.group_config.groups

        for group in groups:
            item = QListWidgetItem()
            item.setText(f"{group['name']} ({group.get('category', '默认')})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            if group.get("enabled", True):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)

            item.setData(Qt.UserRole, group)
            self.group_list.addItem(item)

        self.update_selection_count()

        # 连接信号
        self.group_list.itemChanged.connect(self.update_selection_count)

    def select_all(self):
        """全选"""
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            item.setCheckState(Qt.Checked)

    def deselect_all(self):
        """全不选"""
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            item.setCheckState(Qt.Unchecked)

    def update_selection_count(self):
        """更新选中数量"""
        total = self.group_list.count()
        selected = sum(1 for i in range(self.group_list.count())
                      if self.group_list.item(i).checkState() == Qt.Checked)
        self.selection_label.setText(f"已选: {selected}/{total}")

    def get_selected_groups(self) -> list:
        """获取选中的群组"""
        groups = []
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            if item.checkState() == Qt.Checked:
                group = item.data(Qt.UserRole)
                groups.append(group)
        return groups

    def start_send(self):
        """提交审批任务（不再直接发送，交由审批人审批后执行）"""
        # 获取消息内容
        content = self.get_message_content()
        if not content:
            QMessageBox.warning(self, "提示", "请先在通知编辑页面输入消息内容")
            return

        # 检测消息中的变量
        variables = re.findall(r'\{[a-zA-Z_]+\}', content)
        variables = list(set(variables))  # 去重

        if variables:
            dialog = VariableDialog(variables, self)
            if dialog.exec_() != QDialog.Accepted:
                return
            # 替换变量
            values = dialog.get_values()
            for var, value in values.items():
                content = content.replace(var, value)

        # 获取选中的群组
        groups = self.get_selected_groups()
        if not groups:
            QMessageBox.warning(self, "提示", "请至少选择一个目标群组")
            return

        # 确认提交
        reply = QMessageBox.question(
            self, "确认提交",
            f"确定要向 {len(groups)} 个群组提交审批任务吗？\n\n"
            f"审批通过后才会真实发送。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # 组装审批任务（复用现有发送内核，由审批人审批后执行）
        from core.approval import PendingTaskStore, AuditLog
        from core.auth import ROLE_OPERATOR, ROLE_LABELS

        task = {
            "type": "group",
            "content": content,
            "targets": groups,
            "send_params": {
                "interval": self.interval_spin.value(),
                "retries": self.retries_spin.value(),
            },
            "submitter": ROLE_LABELS.get(ROLE_OPERATOR, "经办人"),
        }
        store = PendingTaskStore()
        task = store.add(task)
        AuditLog().log(
            "submit", task_id=task["id"], operator=task["submitter"],
            target_summary=f"{len(groups)} 群",
        )

        QMessageBox.information(
            self, "已提交审批",
            f"任务已提交审批（编号 #{task['id']}）。\n"
            "审批人通过后才会真实发送。"
        )


    def stop_send(self):
        """停止发送"""
        self.sender.stop()
        self.status_label.setText("正在停止...")

    def on_progress(self, current: int, total: int, group_name: str):
        """更新进度"""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"[{current}/{total}] 正在发送到: {group_name}")

    def on_result(self, result: SendResult):
        """处理单条发送结果"""
        self.send_log.add(result)

        # 添加到日志显示
        if result.success:
            self.log_text.append(f'<span style="color: green;">{str(result)}</span>')
        else:
            self.log_text.append(f'<span style="color: red;">{str(result)}</span>')

        # 滚动到底部
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def on_finished(self, results: list):
        """发送完成"""
        self.is_sending = False
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        stats = self.send_log.get_stats()
        self.status_label.setText(
            f"发送完成 - 总计: {stats['total']} | "
            f"成功: {stats['success']} | "
            f"失败: {stats['failed']}"
        )

        # 保存到历史记录
        content = self.get_message_content()
        self.send_log.save_to_history(content, stats)

        QMessageBox.information(
            self, "发送完成",
            f"消息发送完成\n\n"
            f"总计: {stats['total']} 个群组\n"
            f"成功: {stats['success']} 个\n"
            f"失败: {stats['failed']} 个"
        )

    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.send_log.clear()

    def export_log(self):
        """导出日志"""
        from PyQt5.QtWidgets import QFileDialog

        if not self.send_log.get_logs():
            QMessageBox.information(self, "提示", "暂无日志可导出")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "发送日志.txt",
            "文本文件 (*.txt);;所有文件 (*)"
        )

        if file_path:
            content = self.send_log.export_to_text()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "导出成功", f"日志已导出到:\n{file_path}")

    def show_history(self):
        """显示历史记录对话框"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox

        history = self.send_log.get_history()
        if not history:
            QMessageBox.information(self, "提示", "暂无发送历史记录")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("发送历史记录")
        dialog.setMinimumSize(700, 500)

        layout = QVBoxLayout(dialog)

        # 历史记录显示
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Consolas", 10))

        # 构建历史记录文本
        lines = []
        for record in reversed(history):  # 最新的在前面
            lines.append(f"{'='*50}")
            lines.append(f"发送时间: {record['datetime']}")
            lines.append(f"消息内容: {record['content']}")
            lines.append(f"发送结果: 总计 {record['total']} | 成功 {record['success']} | 失败 {record['failed']}")
            lines.append(f"{'-'*40}")

            for detail in record.get("details", []):
                status = "✓" if detail["success"] else "✗"
                lines.append(f"  [{detail['timestamp']}] {status} {detail['group_name']} - {detail['message']}")

            lines.append("")

        text_edit.setPlainText("\n".join(lines))
        layout.addWidget(text_edit)

        # 按钮区域
        btn_layout = QHBoxLayout()

        export_btn = QPushButton("导出全部历史")
        export_btn.clicked.connect(lambda: self.export_history())
        btn_layout.addWidget(export_btn)

        clear_btn = QPushButton("清空历史")
        clear_btn.clicked.connect(lambda: self.clear_history(dialog))
        btn_layout.addWidget(clear_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        dialog.exec_()

    def export_history(self):
        """导出历史记录"""
        from PyQt5.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出历史记录", "发送历史记录.txt",
            "文本文件 (*.txt);;所有文件 (*)"
        )

        if file_path:
            content = self.send_log.export_history_to_text()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "导出成功", f"历史记录已导出到:\n{file_path}")

    def clear_history(self, dialog=None):
        """清空历史记录"""
        reply = QMessageBox.question(
            self, "确认清空",
            "确定要清空所有发送历史记录吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.send_log.clear_history()
            QMessageBox.information(self, "清空成功", "历史记录已清空")
            if dialog:
                dialog.close()

    def get_message_content(self) -> str:
        """获取消息内容（从父窗口的消息编辑面板）"""
        # 向上遍历找到主窗口
        parent = self.parent()
        while parent:
            if hasattr(parent, 'msg_editor'):
                return parent.msg_editor.get_content()
            parent = parent.parent()
        return ""
