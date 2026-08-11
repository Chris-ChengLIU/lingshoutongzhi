"""
个人发送面板
通过企业微信 PC 端模拟操作，向指定联系人逐一发送消息。

设计对齐 group_panel.py + send_panel.py 的 PyQt5 风格。
"""

import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QTextEdit, QPlainTextEdit, QProgressBar,
    QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QFileDialog, QGroupBox, QSpinBox, QDoubleSpinBox,
    QFrame, QListWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor
from typing import List, Dict, Callable, Optional
from core.config import PersonConfig
from core.personal_sender import PersonalSender
from core.sender import SendResult
from PyQt5.QtWidgets import QToolButton, QMenu, QWidgetAction, QCheckBox
from PyQt5.QtCore import pyqtSignal


class MultiCheckFilterButton(QToolButton):
    """多选筛选按钮：点击弹出带复选框的菜单，可勾选多项；不勾选=全部"""
    changed = pyqtSignal()

    def __init__(self, label="全部", parent=None):
        super().__init__(parent)
        self._label = label
        self._checkboxes = {}   # text -> QCheckBox
        self.setPopupMode(QToolButton.InstantPopup)
        self.setText(label)
        self.setFixedWidth(110)          # ← 新增：固定宽度，不随文字变化
        self.setStyleSheet(              # ← 新增：让它看起来更像下拉框而不是普通按钮
            "QToolButton { text-align: left; padding: 3px 6px; }"
            "QToolButton::menu-indicator { subcontrol-position: right center; }"
        )
        self.menu = QMenu(self)
        self.setMenu(self.menu)

    def set_options(self, options: list):
        """重建菜单选项，尽量保留之前已勾选的项"""
        old_checked = set(self.checked_items())
        self.menu.clear()
        self._checkboxes.clear()
        self.menu.setMinimumWidth(self.width()) 
        for text in options:
            cb = QCheckBox(text, self.menu)
            cb.setChecked(text in old_checked)
            cb.stateChanged.connect(self._on_changed)
            action = QWidgetAction(self.menu)
            action.setDefaultWidget(cb)
            self.menu.addAction(action)
            self._checkboxes[text] = cb
        self._update_text()

    def checked_items(self) -> list:
        return [text for text, cb in self._checkboxes.items() if cb.isChecked()]

    def _on_changed(self, _state):
        self._update_text()
        self.changed.emit()

    def _update_text(self):
        n = len(self.checked_items())
        self.setText(f"{self._label}({n})" if n else self._label)


# ── 后台发送线程 ───────────────────────────────────────────────────────────

class PersonalSendWorker(QObject):
    """在子线程中运行发送任务，通过信号与 UI 通信"""

    progress  = pyqtSignal(int, int, str)     # current, total, name
    result    = pyqtSignal(object)            # SendResult
    finished  = pyqtSignal(int, int)          # success_count, total

    # def __init__(self, sender: PersonalSender, persons: list, content: str):
    #     super().__init__()
    #     self.sender  = sender
    #     self.persons = persons
    #     self.content = content
    def __init__(self, sender: PersonalSender, persons: list, content: str, file_paths: list = None):
        super().__init__()
        self.sender     = sender
        self.persons    = persons
        self.content    = content
        self.file_paths = file_paths or []

    def run(self):
        # results = self.sender.send_to_persons(
        #     self.persons,
        #     self.content,
        #     progress_callback=lambda cur, tot, name: self.progress.emit(cur, tot, name),
        #     result_callback=lambda r: self.result.emit(r),
        # )
        results = self.sender.send_to_persons(
            self.persons,
            self.content,
            self.file_paths,
            progress_callback=lambda cur, tot, name: self.progress.emit(cur, tot, name),
            result_callback=lambda r: self.result.emit(r),
        )
        #new
        success = sum(1 for r in results if r.success)
        self.finished.emit(success, len(results))


# ── 联系人编辑对话框 ───────────────────────────────────────────────────────

class PersonEditDialog(QDialog):
    """添加 / 编辑单个联系人"""

    def __init__(self, parent=None, person: dict = None, units: list = None):
        super().__init__(parent)
        self.person = person
        self.units  = units or []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("编辑联系人" if self.person else "添加联系人")
        self.setMinimumWidth(380)

        layout = QFormLayout(self)
        layout.setSpacing(10)

        # 姓名
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入姓名")
        if self.person:
            self.name_edit.setText(self.person.get("name", ""))
        layout.addRow("姓名：", self.name_edit)

        # 所在单位
        self.unit_combo = QComboBox()
        self.unit_combo.setEditable(True)
        self.unit_combo.addItem("")
        self.unit_combo.addItems(self.units)
        if self.person:
            unit = self.person.get("unit", "")
            idx  = self.unit_combo.findText(unit)
            self.unit_combo.setCurrentIndex(idx if idx >= 0 else 0)
            if idx < 0:
                self.unit_combo.setCurrentText(unit)
        self.unit_combo.setPlaceholderText("选择或输入所在单位")
        layout.addRow("所在单位：", self.unit_combo)

        #自定义标签
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("多个标签用英文逗号分隔")
        if self.person:
            self.tag_edit.setText(self.person.get("tag", ""))
        layout.addRow("自定义标签：", self.tag_edit)


        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _validate_and_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入姓名")
            return
        self.accept()

    def get_data(self) -> dict:
        #selector = str(self.selector_spin.value()) if self.has_selector_cb.isChecked() else None
        return {
            "name":     self.name_edit.text().strip(),
            "unit":     self.unit_combo.currentText().strip(),
            "tag":  self.tag_edit.text().strip(),
            # "selector": selector,
        }


# ── 主面板 ─────────────────────────────────────────────────────────────────

class PersonalPanel(QWidget):
    """个人发送面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.person_config = PersonConfig()
        self.sender        = None
        self.worker        = None
        self.thread        = None
        self.is_sending    = False
        self.init_ui()
        self.refresh_table()

    # ── UI 初始化 ──────────────────────────────────────────────────────────

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)

        # ── 左侧：联系人管理 ──────────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        # 工具栏
        toolbar = QHBoxLayout()
        self.add_btn    = QPushButton("➕ 添加")
        self.edit_btn   = QPushButton("✏️ 编辑")
        self.delete_btn = QPushButton("🗑️ 删除")
        for btn in (self.add_btn, self.edit_btn, self.delete_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        self.import_csv_btn   = QPushButton("📥 CSV")
        self.import_excel_btn = QPushButton("📥 Excel")
        self.export_btn       = QPushButton("📤 导出")
        for btn in (self.import_csv_btn, self.import_excel_btn, self.export_btn):
            toolbar.addWidget(btn)
        left_layout.addLayout(toolbar)

        # 筛选栏
        filter_row = QHBoxLayout()
        # filter_row.addWidget(QLabel("所在单位："))
        # # self.unit_filter = QComboBox()
        # # self.unit_filter.addItem("全部")
        # # self.unit_filter.setMinimumWidth(140)
        # # filter_row.addWidget(self.unit_filter)
        # self.unit_filter = MultiCheckFilterButton("所在单位")
        # filter_row.addWidget(self.unit_filter)

        # filter_row.addWidget(QLabel("搜索："))
        # self.search_edit = QLineEdit()
        # self.search_edit.setPlaceholderText("姓名关键词…")
        # self.search_edit.setMaximumWidth(160)
        # filter_row.addWidget(self.search_edit)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setFixedWidth(58)
        self.select_all_btn.setToolTip("全选/取消全选当前可见联系人的启用复选框")
        # filter_row.addWidget(self.select_all_btn)

        # filter_row.addWidget(QLabel("标签："))
        # # self.tag_filter = QComboBox()
        # # self.tag_filter.addItem("全部")
        # # self.tag_filter.setMinimumWidth(120)
        # # filter_row.addWidget(self.tag_filter)
        # self.tag_filter = MultiCheckFilterButton("标签")
        # filter_row.addWidget(self.tag_filter)
        self.unit_filter = MultiCheckFilterButton("所在单位")
        filter_row.addWidget(self.unit_filter)

        filter_row.addWidget(QLabel("搜索："))
        self.search_edit = QLineEdit()
        ...
        filter_row.addWidget(self.search_edit)

        filter_row.addWidget(self.select_all_btn)

        self.tag_filter = MultiCheckFilterButton("标签")
        filter_row.addWidget(self.tag_filter)

        filter_row.addStretch()
        left_layout.addLayout(filter_row)

        

        # 联系人表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["✓", "姓名", "所在单位", "自定义标签"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnHidden(4, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        left_layout.addWidget(self.table)

        # 统计行
        self.stats_label = QLabel("共 0 位联系人")
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        left_layout.addWidget(self.stats_label)

        splitter.addWidget(left)

        # ── 右侧：消息 + 发送控制 ─────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(8)

        # 消息编辑区
        msg_group = QGroupBox("消息内容")
        msg_inner  = QVBoxLayout(msg_group)
        self.msg_edit = QPlainTextEdit()
        self.msg_edit.setPlaceholderText(
            "请输入发送内容（纯文本）。\n\n"
            "个人会话不支持 Markdown 格式，内容将原文发送。"
        )
        self.msg_edit.setMinimumHeight(140)
        msg_inner.addWidget(self.msg_edit)

        char_row = QHBoxLayout()
        self.char_count_label = QLabel("0 字")
        self.char_count_label.setStyleSheet("color: #888; font-size: 11px;")
        char_row.addStretch()
        char_row.addWidget(self.char_count_label)
        msg_inner.addLayout(char_row)
        right_layout.addWidget(msg_group)

        # 文件上传区
        file_group = QGroupBox("附件文件（可选）")
        file_inner = QVBoxLayout(file_group)
 
        file_btn_row = QHBoxLayout()
        self.add_file_btn = QPushButton("➕ 添加文件")
        self.clear_file_btn = QPushButton("🗑️ 清空")
        file_btn_row.addWidget(self.add_file_btn)
        file_btn_row.addWidget(self.clear_file_btn)
        file_btn_row.addStretch()
        file_inner.addLayout(file_btn_row)
 
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(100)
        self.file_list.setAlternatingRowColors(True)
        file_inner.addWidget(self.file_list)
 
        right_layout.addWidget(file_group)
        # 文件上传区end

        # 发送参数
        param_group = QGroupBox("发送参数")
        param_grid  = QHBoxLayout(param_group)

        def _param_row(label, widget):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget)
            return row

        self.search_delay_spin = QDoubleSpinBox()
        self.search_delay_spin.setRange(0.5, 10.0)
        self.search_delay_spin.setValue(1.5)
        self.search_delay_spin.setSuffix(" 秒")
        self.search_delay_spin.setSingleStep(0.5)

        self.send_interval_spin = QDoubleSpinBox()
        self.send_interval_spin.setRange(1.0, 30.0)
        self.send_interval_spin.setValue(2.0)
        self.send_interval_spin.setSuffix(" 秒")
        self.send_interval_spin.setSingleStep(0.5)

        param_grid.addLayout(_param_row("搜索等待：", self.search_delay_spin))
        param_grid.addSpacing(16)
        param_grid.addLayout(_param_row("发送间隔：", self.send_interval_spin))
        param_grid.addStretch()
        right_layout.addWidget(param_group)

        # 发送前提示
        tip_frame = QFrame()
        tip_frame.setStyleSheet(
            "QFrame { background: #fff8e1; border: 1px solid #ffe082; border-radius: 4px; padding: 4px; }"
        )
        tip_layout = QVBoxLayout(tip_frame)
        tip_layout.setContentsMargins(8, 6, 8, 6)
        tip_label = QLabel(
            "⚠️  发送前请确认：企业微信 PC 端已打开并登录。\n"
            "点击「开始发送」后请勿操作鼠标和键盘。\n"
            "紧急停止：将鼠标快速移到屏幕<b>左上角</b>。"
        )
        tip_label.setTextFormat(Qt.RichText)
        tip_label.setStyleSheet("font-size: 12px; color: #5d4037;")
        tip_label.setWordWrap(True)
        tip_layout.addWidget(tip_label)
        right_layout.addWidget(tip_frame)

        # 进度条 + 控制按钮
        ctrl_row = QHBoxLayout()
        self.send_btn = QPushButton("🚀 开始发送")
        self.send_btn.setMinimumHeight(34)
        self.send_btn.setStyleSheet(
            "QPushButton { background: #1976d2; color: white; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton:disabled { background: #bdbdbd; }"
        )
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setMinimumHeight(34)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton { background: #e53935; color: white; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #c62828; }"
            "QPushButton:disabled { background: #bdbdbd; }"
        )
        ctrl_row.addWidget(self.send_btn)
        ctrl_row.addWidget(self.stop_btn)
        right_layout.addLayout(ctrl_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        right_layout.addWidget(self.progress_bar)

        # 日志区
        log_group = QGroupBox("发送日志")
        log_inner  = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 10))
        self.log_edit.setMinimumHeight(120)
        log_inner.addWidget(self.log_edit)

        log_btn_row = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.log_edit.clear)
        log_btn_row.addStretch()
        log_btn_row.addWidget(self.clear_log_btn)
        log_inner.addLayout(log_btn_row)
        right_layout.addWidget(log_group)

        splitter.addWidget(right)
        splitter.setSizes([480, 420])
        root.addWidget(splitter)

        # ── 信号连接 ──────────────────────────────────────────────────────
        self.add_btn.clicked.connect(self.add_person)
        self.edit_btn.clicked.connect(self.edit_person)
        self.delete_btn.clicked.connect(self.delete_person)
        self.import_csv_btn.clicked.connect(self.import_csv)
        self.import_excel_btn.clicked.connect(self.import_excel)
        self.export_btn.clicked.connect(self.export_persons)
        # self.unit_filter.currentIndexChanged.connect(self.filter_table)
        self.search_edit.textChanged.connect(self.filter_table)
        # new
        # self.tag_filter.currentIndexChanged.connect(self.filter_table)
        self.unit_filter.changed.connect(self.filter_table)
        self.tag_filter.changed.connect(self.filter_table)

        self.send_btn.clicked.connect(self.start_send)
        self.stop_btn.clicked.connect(self.stop_send)
        self.msg_edit.textChanged.connect(self._update_char_count)
        self.table.doubleClicked.connect(self.edit_person)
        # new
        self.add_file_btn.clicked.connect(self.add_files)
        self.clear_file_btn.clicked.connect(self.file_list.clear)
        self.select_all_btn.clicked.connect(self.toggle_select_all)

    # ── 表格管理 ──────────────────────────────────────────────────────────

    def refresh_table(self):
        """刷新联系人表格"""
        self.table.setRowCount(0)
        persons = self.person_config.persons
        self.table.setRowCount(len(persons))

        for i, p in enumerate(persons):
            # 启用复选框
            cb = QCheckBox()
            cb.setChecked(p.get("enabled", True))
            cb.stateChanged.connect(
                lambda state, pid=p["id"]: self.person_config.update_person(pid, enabled=(state == Qt.Checked))
            )
            cell = QWidget()
            cb_lay = QHBoxLayout(cell)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 0, cell)

            self.table.setItem(i, 1, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(p.get("unit", "")))

            tag_edit = QLineEdit(p.get("tag", ""))
            tag_edit.setPlaceholderText("标签1,标签2")
            tag_edit.setFrame(False)
            tag_edit.editingFinished.connect(
                lambda pid=p["id"], w=tag_edit: self._on_tag_edited(pid, w)
            )
            self.table.setCellWidget(i, 3, tag_edit)
            # selector = p.get("selector")
            # sel_item = QTableWidgetItem(f"第{selector}条" if selector else "")
            # sel_item.setTextAlignment(Qt.AlignCenter)
            # self.table.setItem(i, 3, sel_item)

            self.table.setItem(i, 4, QTableWidgetItem(str(p["id"])))

        self._update_stats()
        self._update_unit_filter()
        self._update_tag_filter()

    # def filter_table(self):
    #     unit_sel    = self.unit_filter.currentText()
    #     tag_sel     = self.tag_filter.currentText()
    #     search_text = self.search_edit.text().strip().lower()

    #     for row in range(self.table.rowCount()):
    #         show = True

    #         if unit_sel and unit_sel != "全部":
    #             unit_item = self.table.item(row, 2)
    #             if not unit_item or unit_item.text() != unit_sel:
    #                 show = False

    #         tag_widget = self.table.cellWidget(row, 3)
    #         tag_text = tag_widget.text() if tag_widget else ""
    #         tags = [t.strip() for t in tag_text.split(",") if t.strip()]

    #         if show and tag_sel and tag_sel != "全部":
    #             if tag_sel not in tags:
    #                 show = False

    #         if show and search_text:
    #             name_item = self.table.item(row, 1)
    #             name_text = name_item.text().lower() if name_item else ""
    #             if search_text not in name_text and search_text not in tag_text.lower():
    #                 show = False

    #         self.table.setRowHidden(row, not show)

    #     self._update_stats()
    #     self.select_all_btn.setText("全选")
    def filter_table(self):
        units_sel   = self.unit_filter.checked_items()   # 空列表 = 不筛选(全部)
        tags_sel    = self.tag_filter.checked_items()
        search_text = self.search_edit.text().strip().lower()

        for row in range(self.table.rowCount()):
            show = True

            if units_sel:
                unit_item = self.table.item(row, 2)
                unit_text = unit_item.text() if unit_item else ""
                if unit_text not in units_sel:
                    show = False

            tag_widget = self.table.cellWidget(row, 3)
            tag_text = tag_widget.text() if tag_widget else ""
            tags = [t.strip() for t in tag_text.split(",") if t.strip()]

            if show and tags_sel:
                if not any(t in tags_sel for t in tags):
                    show = False

            if show and search_text:
                name_item = self.table.item(row, 1)
                name_text = name_item.text().lower() if name_item else ""
                if search_text not in name_text and search_text not in tag_text.lower():
                    show = False

            self.table.setRowHidden(row, not show)

        self._update_stats()
        self.select_all_btn.setText("全选")

    def _update_stats(self):
        visible = sum(
            1 for row in range(self.table.rowCount())
            if not self.table.isRowHidden(row)
        )
        total   = len(self.person_config.persons)
        enabled = len(self.person_config.get_enabled_persons())
        self.stats_label.setText(
            f"共 {total} 位联系人，已启用 {enabled} 位"
            + (f"，当前筛选 {visible} 位" if visible != total else "")
        )

    # def _update_unit_filter(self):
    #     current = self.unit_filter.currentText()
    #     self.unit_filter.blockSignals(True)
    #     self.unit_filter.clear()
    #     self.unit_filter.addItem("全部")
    #     self.unit_filter.addItems(self.person_config.get_units())
    #     idx = self.unit_filter.findText(current)
    #     self.unit_filter.setCurrentIndex(idx if idx >= 0 else 0)
    #     self.unit_filter.blockSignals(False)

    # def _update_tag_filter(self):
    #     current = self.tag_filter.currentText()
    #     self.tag_filter.blockSignals(True)
    #     self.tag_filter.clear()
    #     self.tag_filter.addItem("全部")
    #     self.tag_filter.addItems(self.person_config.get_tags())
    #     idx = self.tag_filter.findText(current)
    #     self.tag_filter.setCurrentIndex(idx if idx >= 0 else 0)
    #     self.tag_filter.blockSignals(False)
    def _update_unit_filter(self):
        self.unit_filter.set_options(self.person_config.get_units())

    def _update_tag_filter(self):
        self.tag_filter.set_options(self.person_config.get_tags())

    def toggle_select_all(self):
        """全选 / 取消全选当前可见行的启用复选框"""
        # 判断当前可见行是否全部已启用，决定这次点击是"全选"还是"取消全选"
        visible_rows = [
            row for row in range(self.table.rowCount())
            if not self.table.isRowHidden(row)
        ]
        if not visible_rows:
            return

        # 统计可见行中已启用的数量
        all_checked = all(
            self._get_row_checkbox(row).isChecked()
            for row in visible_rows
        )
        target_state = not all_checked  # 全部已选则取消，否则全选

        for row in visible_rows:
            cb = self._get_row_checkbox(row)
            if cb:
                cb.setChecked(target_state)

        self.select_all_btn.setText("取消全选" if target_state else "全选")

    # def _get_row_checkbox(self, row: int) -> QCheckBox | None:
    def _get_row_checkbox(self, row: int) -> Optional[QCheckBox]:
        """取某行第 0 列的 QCheckBox"""
        cell = self.table.cellWidget(row, 0)
        if cell is None:
            return None
        for child in cell.children():
            if isinstance(child, QCheckBox):
                return child
        return None
    def _update_char_count(self):
        n = len(self.msg_edit.toPlainText())
        self.char_count_label.setText(f"{n} 字")

    # ── 联系人 CRUD ────────────────────────────────────────────────────────

    def add_person(self):
        dlg = PersonEditDialog(self, units=self.person_config.get_units())
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            self.person_config.add_person(data["name"], data["unit"], data["tag"])
            self.refresh_table()

    def edit_person(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的联系人")
            return
        id_item = self.table.item(row, 4)
        if not id_item:
            return
        person = self.person_config.get_person(int(id_item.text()))
        if not person:
            return

        dlg = PersonEditDialog(self, person=person, units=self.person_config.get_units())
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            self.person_config.update_person(
                person["id"],
                name=data["name"],
                unit=data["unit"],
                tag=data["tag"],
                # selector=data["selector"],
            )
            self.refresh_table()
    def _on_tag_edited(self, pid, widget):
        self.person_config.update_person(pid, tag=widget.text().strip())
        self._update_tag_filter()   # 新标签要能马上出现在筛选下拉框里

    # def delete_person(self):
    #     row = self.table.currentRow()
    #     if row < 0:
    #         QMessageBox.information(self, "提示", "请先选择要删除的联系人")
    #         return
    #     id_item = self.table.item(row, 4)
    #     if not id_item:
    #         return
    #     person = self.person_config.get_person(int(id_item.text()))
    #     if not person:
    #         return

    #     reply = QMessageBox.question(
    #         self, "确认删除",
    #         f"确定要删除联系人【{person['name']}】吗？",
    #         QMessageBox.Yes | QMessageBox.No,
    #     )
    #     if reply == QMessageBox.Yes:
    #         self.person_config.delete_person(person["id"])
    #         self.refresh_table()
    def delete_person(self):
        """删除选中的联系人（支持多选）"""
        selected_rows = list(set(idx.row() for idx in self.table.selectedIndexes()))
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要删除的联系人")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 位联系人吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 收集要删除的 ID
        ids_to_delete = []
        for row in selected_rows:
            id_item = self.table.item(row, 4)
            if id_item:
                ids_to_delete.append(int(id_item.text()))

        for pid in ids_to_delete:
            self.person_config.delete_person(pid)

        self.refresh_table()

    # ── 导入 / 导出 ────────────────────────────────────────────────────────

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 CSV 文件", "", "CSV 文件 (*.csv);;所有文件 (*)")
        if not path:
            return
        ok, fail, errors = self.person_config.import_from_csv(path)
        self._show_import_result(ok, fail, errors)
        self.refresh_table()

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 文件", "", "Excel 文件 (*.xlsx *.xls);;所有文件 (*)")
        if not path:
            return
        ok, fail, errors = self.person_config.import_from_excel(path)
        self._show_import_result(ok, fail, errors)
        self.refresh_table()

    def _show_import_result(self, ok, fail, errors):
        msg = f"导入完成\n成功：{ok} 位\n失败：{fail} 位"
        if errors:
            msg += "\n\n错误详情：\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n…还有 {len(errors) - 10} 条错误"
        QMessageBox.information(self, "导入结果", msg)

    def export_persons(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出联系人列表", "联系人列表", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        if self.person_config.export_to_csv(path):
            QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", "导出时发生错误，请检查文件路径")
    # new
    def add_files(self):
        """选择要发送的文件"""
        from PyQt5.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择附件文件", "", "所有文件 (*.*)"
        )
        for path in paths:
            # 避免重复添加
            existing = [self.file_list.item(i).text() for i in range(self.file_list.count())]
            if path not in existing:
                self.file_list.addItem(path)
 
    def get_file_paths(self) -> list:
        """获取已选文件路径列表"""
        return [self.file_list.item(i).text() for i in range(self.file_list.count())]
    # new

    # ── 发送控制 ───────────────────────────────────────────────────────────

    # def _get_target_persons(self) -> list:
    #     """
    #     收集当前筛选条件下所有启用的联系人，转换为 sender 所需格式。
    #     """
    #     unit_sel = self.unit_filter.currentText()
    #     if unit_sel == "全部":
    #         persons = self.person_config.get_enabled_persons()
    #     else:
    #         persons = self.person_config.get_by_unit(unit_sel)

    #     # 只取表格中可见行（尊重姓名搜索进一步过滤）
    #     visible_ids = set()
    #     for row in range(self.table.rowCount()):
    #         if not self.table.isRowHidden(row):
    #             id_item = self.table.item(row, 4)
    #             if id_item:
    #                 visible_ids.add(int(id_item.text()))

    #     return [
    #         {"name": p["name"], "unit": p.get("unit", ""), "selector": p.get("selector")}
    #         for p in persons
    #         if p["id"] in visible_ids
    #     ]
    def _get_target_persons(self) -> list:
        units_sel = self.unit_filter.checked_items()
        if not units_sel:
            persons = self.person_config.get_enabled_persons()
        else:
            persons = [p for p in self.person_config.get_enabled_persons()
                    if p.get("unit") in units_sel]

        visible_ids = set()
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                id_item = self.table.item(row, 4)
                if id_item:
                    visible_ids.add(int(id_item.text()))

        return [
            {"name": p["name"], "unit": p.get("unit", "")}
            for p in persons
            if p["id"] in visible_ids
        ]

    def start_send(self):
        """开始发送"""
        content = self.msg_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return

        targets = self._get_target_persons()
        if not targets:
            QMessageBox.warning(self, "提示", "没有符合条件的启用联系人\n请检查所在单位筛选或联系人列表")
            return

        # 检查依赖
        ok, dep_msg = PersonalSender.check_dependencies()
        if not ok:
            QMessageBox.critical(self, "缺少依赖", dep_msg)
            return

        # 确认对话框
        # unit_sel = self.unit_filter.currentText()
        # unit_desc = f"【{unit_sel}】" if unit_sel != "全部" else "【全部】"
        units_sel = self.unit_filter.checked_items()
        unit_desc = f"【{'、'.join(units_sel)}】" if units_sel else "【全部】"
        confirm_text = (
            f"即将向以下范围发送消息：\n\n"
            f"  部门筛选：{unit_desc}\n"
            f"  目标人数：{len(targets)} 位（已启用且可见）\n\n"   # ← 改这行
            f"消息内容（前50字）：\n{content[:50]}{'…' if len(content) > 50 else ''}\n\n"
            f"请确保企业微信 PC 端已打开，发送期间请勿操作鼠标。\n\n"
            f"确认开始发送？"
        )
        reply = QMessageBox.question(self, "确认发送", confirm_text, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # 构建 sender
        self.sender = PersonalSender(
            search_delay=self.search_delay_spin.value(),
            send_interval=self.send_interval_spin.value(),
            dry_run=False,                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     
        )

        # 构建工作线程
        self.thread = QThread()
        # self.worker = PersonalSendWorker(self.sender, targets, content)
        self.worker = PersonalSendWorker(self.sender, targets, content, self.get_file_paths())
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._on_result)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)

        # 更新 UI 状态
        self.is_sending = True
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(targets))
        self.progress_bar.setValue(0)
        self.log_edit.clear()
        self._log(f"开始发送，目标：{len(targets)} 位联系人", color="#1565c0")

        self.thread.start()

    def stop_send(self):
        if self.sender:
            self.sender.stop()
        self._log("⏹ 已发出停止信号，等待当前操作完成…", color="#e65100")
        self.stop_btn.setEnabled(False)

    def _on_progress(self, current: int, total: int, name: str):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}  {name}")

    def _on_result(self, result: SendResult):
        if result.success:
            self._log(f"✓ {result.group_name}  {result.message}", color="#2e7d32")
        else:
            self._log(f"✗ {result.group_name}  {result.message}", color="#c62828")

    def _on_finished(self, success: int, total: int):
        self.is_sending = False
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._log(
            f"\n发送完成 — 成功 {success} / 共 {total}",
            color="#1565c0" if success == total else "#e65100",
        )

    def _log(self, text: str, color: str = "#212121"):
        self.log_edit.append(f'<span style="color:{color};">{text}</span>')
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )