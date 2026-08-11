"""
消息编辑面板
编辑通知内容、管理消息模板、预览消息
"""

from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit, QDialog, QFormLayout,
    QDialogButtonBox, QMessageBox, QGroupBox, QSplitter, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QTextCursor

from core.config import TemplateConfig


class TemplateEditDialog(QDialog):
    """模板编辑对话框"""

    def __init__(self, parent=None, template=None):
        super().__init__(parent)
        self.template = template
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("编辑模板" if self.template else "新建模板")
        self.setMinimumWidth(500)

        layout = QFormLayout(self)

        # 模板名称
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入模板名称")
        if self.template:
            self.name_edit.setText(self.template.get("name", ""))
        layout.addRow("模板名称:", self.name_edit)

        # 模板内容
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("请输入模板内容，支持Markdown格式\n\n可用变量:\n{topic} - 会议主题\n{time} - 会议时间\n{location} - 会议地点\n{attendees} - 参会人员\n{notes} - 备注")
        self.content_edit.setMinimumHeight(200)
        if self.template:
            self.content_edit.setPlainText(self.template.get("content", ""))
        layout.addRow("模板内容:", self.content_edit)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate_and_accept(self):
        name = self.name_edit.text().strip()
        content = self.content_edit.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "提示", "请输入模板名称")
            return

        if not content:
            QMessageBox.warning(self, "提示", "请输入模板内容")
            return

        self.accept()

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "content": self.content_edit.toPlainText().strip()
        }


class MsgEditorPanel(QWidget):
    """消息编辑面板"""

    def __init__(self, template_config: TemplateConfig, parent=None):
        super().__init__(parent)
        self.template_config = template_config
        self.init_ui()
        self.load_template_list()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 模板选择区域
        template_group = QGroupBox("消息模板")
        template_layout = QHBoxLayout(template_group)

        template_layout.addWidget(QLabel("选择模板:"))
        self.template_combo = QComboBox()
        self.template_combo.currentIndexChanged.connect(self.on_template_changed)
        template_layout.addWidget(self.template_combo, 1)

        self.save_template_btn = QPushButton("💾 保存为模板")
        self.save_template_btn.clicked.connect(self.save_as_template)
        template_layout.addWidget(self.save_template_btn)

        self.edit_template_btn = QPushButton("✏️ 编辑模板")
        self.edit_template_btn.clicked.connect(self.edit_template)
        template_layout.addWidget(self.edit_template_btn)

        self.delete_template_btn = QPushButton("🗑️ 删除模板")
        self.delete_template_btn.clicked.connect(self.delete_template)
        template_layout.addWidget(self.delete_template_btn)

        layout.addWidget(template_group)

        # 使用分割器，上方编辑，下方预览
        splitter = QSplitter(Qt.Vertical)

        # 编辑区域
        edit_widget = QWidget()
        edit_layout = QVBoxLayout(edit_widget)

        edit_header = QHBoxLayout()
        edit_header.addWidget(QLabel("📝 消息内容:"))
        edit_header.addStretch()

        # 快捷插入变量
        self.var_combo = QComboBox()
        self.var_combo.addItem("插入变量...")
        self.var_combo.addItems(["{topic} 会议主题", "{time} 会议时间", "{location} 会议地点", "{attendees} 参会人员", "{notes} 备注"])
        self.var_combo.currentIndexChanged.connect(self.insert_variable)
        edit_header.addWidget(self.var_combo)
        edit_layout.addLayout(edit_header)

        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText(
            "请输入通知内容，支持Markdown格式\n\n"
            "可用变量:\n"
            "{topic} - 会议主题\n"
            "{time} - 会议时间\n"
            "{location} - 会议地点\n"
            "{attendees} - 参会人员\n"
            "{notes} - 备注\n\n"
            "示例:\n"
            "<font color=\"info\">【会议通知】</font>\n"
            "> **会议主题：** {topic}\n"
            "> **会议时间：** {time}\n"
            "> **会议地点：** {location}\n"
            "> **参会人员：** {attendees}\n\n"
            "{notes}"
        )
        self.content_edit.textChanged.connect(self.update_preview)
        edit_layout.addWidget(self.content_edit)

        splitter.addWidget(edit_widget)

        # 预览区域
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.addWidget(QLabel("👁️ 预览效果:"))

        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setMaximumHeight(150)
        preview_layout.addWidget(self.preview_edit)

        splitter.addWidget(preview_widget)

        # 设置分割比例
        splitter.setSizes([400, 150])
        layout.addWidget(splitter)

        # 底部变量说明
        tip_label = QLabel("💡 提示: 支持Markdown格式，使用 <font color=\"info\">文字</font> 添加颜色，**文字** 加粗")
        tip_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(tip_label)

    def load_template_list(self):
        """加载模板列表"""
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("自定义消息", None)
        for template in self.template_config.templates:
            self.template_combo.addItem(template["name"], template["id"])
        self.template_combo.blockSignals(False)

    def on_template_changed(self, index):
        """模板选择改变"""
        if index == 0:
            # 自定义消息，清空编辑器
            return

        template_id = self.template_combo.currentData()
        template = self.template_config.get_template(template_id)
        if template:
            self.content_edit.setPlainText(template["content"])

    def insert_variable(self, index):
        """插入变量"""
        if index == 0:
            return

        var_map = {
            1: "{topic}",
            2: "{time}",
            3: "{location}",
            4: "{attendees}",
            5: "{notes}"
        }

        var = var_map.get(index, "")
        if var:
            cursor = self.content_edit.textCursor()
            cursor.insertText(var)
            self.content_edit.setTextCursor(cursor)

        # 重置下拉框
        self.var_combo.setCurrentIndex(0)

    def update_preview(self):
        """更新预览"""
        content = self.content_edit.toPlainText()

        # 替换变量为示例值
        preview_content = content
        replacements = {
            "{topic}": "2024年零售业务推进会",
            "{time}": datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            "{location}": "总行3楼会议室",
            "{attendees}": "各分行零售负责人",
            "{notes}": "请各位准时参加，如有冲突请提前告知。"
        }

        for var, value in replacements.items():
            preview_content = preview_content.replace(var, value)

        self.preview_edit.setHtml(self._markdown_to_html(preview_content))

    def _markdown_to_html(self, text: str) -> str:
        """简单的Markdown转HTML"""
        html = text

        # 处理加粗
        import re
        html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)

        # 处理引用
        lines = html.split('\n')
        processed_lines = []
        for line in lines:
            if line.startswith('> '):
                processed_lines.append(f'<blockquote style="border-left: 3px solid #ccc; padding-left: 10px; color: #666;">{line[2:]}</blockquote>')
            else:
                processed_lines.append(line)
        html = '<br>'.join(processed_lines)

        # 处理font标签（保持原样）
        # 已经是HTML格式，不需要额外处理

        return html

    def get_content(self) -> str:
        """获取编辑的消息内容"""
        return self.content_edit.toPlainText()

    def set_content(self, content: str):
        """设置消息内容"""
        self.content_edit.setPlainText(content)

    def save_as_template(self):
        """保存为模板"""
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "提示", "请先输入消息内容")
            return

        dialog = TemplateEditDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.template_config.add_template(data["name"], data["content"])
            self.load_template_list()
            QMessageBox.information(self, "保存成功", f"模板 [{data['name']}] 已保存")

    def edit_template(self):
        """编辑当前选中的模板"""
        template_id = self.template_combo.currentData()
        if template_id is None:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return

        template = self.template_config.get_template(template_id)
        if not template:
            return

        dialog = TemplateEditDialog(self, template=template)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.template_config.update_template(template_id, data["name"], data["content"])
            self.load_template_list()
            # 重新选中编辑的模板
            for i in range(self.template_combo.count()):
                if self.template_combo.itemData(i) == template_id:
                    self.template_combo.setCurrentIndex(i)
                    break

    def delete_template(self):
        """删除当前选中的模板"""
        template_id = self.template_combo.currentData()
        if template_id is None:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return

        template = self.template_config.get_template(template_id)
        if not template:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除模板 [{template['name']}] 吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.template_config.delete_template(template_id)
            self.load_template_list()
