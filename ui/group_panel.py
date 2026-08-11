"""
群组管理面板
管理群组列表、导入导出、编辑删除
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox, QDialog,
    QFormLayout, QDialogButtonBox, QMessageBox, QFileDialog, QHeaderView,
    QGroupBox, QAbstractItemView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core.config import GroupConfig


class GroupEditDialog(QDialog):
    """群组编辑对话框"""

    def __init__(self, parent=None, group=None, categories=None):
        super().__init__(parent)
        self.group = group
        self.categories = categories or ["默认"]
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("编辑群组" if self.group else "添加群组")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)

        # 群名称
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入群名称")
        if self.group:
            self.name_edit.setText(self.group.get("name", ""))
        layout.addRow("群名称:", self.name_edit)

        # Webhook地址
        self.webhook_edit = QLineEdit()
        self.webhook_edit.setPlaceholderText("请输入Webhook地址")
        if self.group:
            self.webhook_edit.setText(self.group.get("webhook", ""))
        layout.addRow("Webhook地址:", self.webhook_edit)

        # 分类
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(self.categories)
        if self.group:
            category = self.group.get("category", "默认")
            index = self.category_combo.findText(category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
            else:
                self.category_combo.setCurrentText(category)
        layout.addRow("分类:", self.category_combo)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate_and_accept(self):
        """验证输入并接受"""
        name = self.name_edit.text().strip()
        webhook = self.webhook_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "提示", "请输入群名称")
            return

        if not webhook:
            QMessageBox.warning(self, "提示", "请输入Webhook地址")
            return

        if not webhook.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send"):
            QMessageBox.warning(self, "提示", "Webhook地址格式不正确，请检查")
            return

        self.accept()

    def get_data(self):
        """获取输入数据"""
        return {
            "name": self.name_edit.text().strip(),
            "webhook": self.webhook_edit.text().strip(),
            "category": self.category_combo.currentText().strip()
        }


class GroupPanel(QWidget):
    """群组管理面板"""

    def __init__(self, config: GroupConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton("➕ 添加群组")
        self.add_btn.clicked.connect(self.add_group)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ 编辑")
        self.edit_btn.clicked.connect(self.edit_group)
        toolbar.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("🗑️ 删除")
        self.delete_btn.clicked.connect(self.delete_group)
        toolbar.addWidget(self.delete_btn)

        toolbar.addStretch()

        self.import_csv_btn = QPushButton("📥 导入CSV")
        self.import_csv_btn.clicked.connect(self.import_csv)
        toolbar.addWidget(self.import_csv_btn)

        self.import_excel_btn = QPushButton("📥 导入Excel")
        self.import_excel_btn.clicked.connect(self.import_excel)
        toolbar.addWidget(self.import_excel_btn)

        self.export_btn = QPushButton("📤 导出")
        self.export_btn.clicked.connect(self.export_groups)
        toolbar.addWidget(self.export_btn)

        layout.addLayout(toolbar)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入群名称或分类进行搜索...")
        self.search_edit.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_edit)

        # 分类筛选
        search_layout.addWidget(QLabel("分类:"))
        self.category_filter = QComboBox()
        self.category_filter.addItem("全部")
        self.category_filter.currentIndexChanged.connect(self.filter_table)
        search_layout.addWidget(self.category_filter)

        layout.addLayout(search_layout)

        # 群组表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["启用", "群名称", "Webhook地址", "分类", "ID"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_group)

        # 隐藏ID列
        self.table.setColumnHidden(4, True)

        layout.addWidget(self.table)

        # 统计信息
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)

    def refresh_table(self):
        """刷新表格数据"""
        self.table.setRowCount(0)
        groups = self.config.groups

        self.table.setRowCount(len(groups))
        for i, group in enumerate(groups):
            # 启用复选框
            checkbox = QCheckBox()
            checkbox.setChecked(group.get("enabled", True))
            checkbox.stateChanged.connect(lambda state, gid=group["id"]: self.toggle_group(gid, state))
            cell_widget = QWidget()
            cb_layout = QHBoxLayout(cell_widget)
            cb_layout.addWidget(checkbox)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 0, cell_widget)

            # 群名称
            self.table.setItem(i, 1, QTableWidgetItem(group.get("name", "")))

            # Webhook地址（截断显示）
            webhook = group.get("webhook", "")
            display_webhook = webhook[:50] + "..." if len(webhook) > 50 else webhook
            item = QTableWidgetItem(display_webhook)
            item.setToolTip(webhook)
            self.table.setItem(i, 2, item)

            # 分类
            self.table.setItem(i, 3, QTableWidgetItem(group.get("category", "默认")))

            # ID（隐藏）
            self.table.setItem(i, 4, QTableWidgetItem(str(group.get("id", ""))))

        self.update_stats()
        self.update_category_filter()

    def update_stats(self):
        """更新统计信息"""
        total = len(self.config.groups)
        enabled = len(self.config.get_enabled_groups())
        self.stats_label.setText(f"共 {total} 个群组，已启用 {enabled} 个")

    def update_category_filter(self):
        """更新分类筛选下拉框"""
        current = self.category_filter.currentText()
        self.category_filter.clear()
        self.category_filter.addItem("全部")
        categories = self.config.get_categories()
        self.category_filter.addItems(categories)

        # 恢复之前的选择
        index = self.category_filter.findText(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)

    def filter_table(self):
        """根据搜索条件筛选表格"""
        search_text = self.search_edit.text().strip().lower()
        category = self.category_filter.currentText()

        for row in range(self.table.rowCount()):
            show = True

            # 搜索过滤
            if search_text:
                name = self.table.item(row, 1).text().lower()
                webhook = self.config.groups[row].get("webhook", "").lower()
                if search_text not in name and search_text not in webhook:
                    show = False

            # 分类过滤
            if category != "全部":
                item_category = self.table.item(row, 3).text()
                if item_category != category:
                    show = False

            self.table.setRowHidden(row, not show)

    def toggle_group(self, group_id: int, state: int):
        """切换群组启用状态"""
        enabled = state == Qt.Checked
        self.config.update_group(group_id, enabled=enabled)

    def add_group(self):
        """添加群组"""
        categories = self.config.get_categories()
        dialog = GroupEditDialog(self, categories=categories)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.config.add_group(data["name"], data["webhook"], data["category"])
            self.refresh_table()

    def edit_group(self):
        """编辑群组"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的群组")
            return

        group_id = int(self.table.item(row, 4).text())
        group = self.config.get_group(group_id)
        if not group:
            return

        categories = self.config.get_categories()
        dialog = GroupEditDialog(self, group=group, categories=categories)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.config.update_group(
                group_id,
                name=data["name"],
                webhook=data["webhook"],
                category=data["category"]
            )
            self.refresh_table()

    # def delete_group(self):
    #     """删除群组"""
    #     row = self.table.currentRow()
    #     if row < 0:
    #         QMessageBox.information(self, "提示", "请先选择要删除的群组")
    #         return

    #     group_id = int(self.table.item(row, 4).text())
    #     group = self.config.get_group(group_id)
    #     if not group:
    #         return

    #     reply = QMessageBox.question(
    #         self, "确认删除",
    #         f"确定要删除群组 [{group['name']}] 吗？",
    #         QMessageBox.Yes | QMessageBox.No
    #     )

    #     if reply == QMessageBox.Yes:
    #         self.config.delete_group(group_id)
    #         self.refresh_table()
    def delete_group(self):
        """删除选中的群组（支持多选）"""
        selected_rows = list(set(idx.row() for idx in self.table.selectedIndexes()))
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要删除的群组")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 个群组吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        ids_to_delete = []
        for row in selected_rows:
            id_item = self.table.item(row, 4)
            if id_item:
                ids_to_delete.append(int(id_item.text()))

        for gid in ids_to_delete:
            self.config.delete_group(gid)

        self.refresh_table()

    def import_csv(self):
        """从CSV导入"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择CSV文件", "", "CSV文件 (*.csv);;所有文件 (*)"
        )
        if file_path:
            success, fail, errors = self.config.import_from_csv(file_path)
            msg = f"导入完成\n成功: {success} 个\n失败: {fail} 个"
            if errors:
                msg += "\n\n错误详情:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    msg += f"\n...还有 {len(errors) - 10} 个错误"
            QMessageBox.information(self, "导入结果", msg)
            self.refresh_table()

    def import_excel(self):
        """从Excel导入"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择Excel文件", "", "Excel文件 (*.xlsx *.xls);;所有文件 (*)"
        )
        if file_path:
            success, fail, errors = self.config.import_from_excel(file_path)
            msg = f"导入完成\n成功: {success} 个\n失败: {fail} 个"
            if errors:
                msg += "\n\n错误详情:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    msg += f"\n...还有 {len(errors) - 10} 个错误"
            QMessageBox.information(self, "导入结果", msg)
            self.refresh_table()

    def export_groups(self):
        """导出群组列表"""
        file_path, file_type = QFileDialog.getSaveFileName(
            self, "导出群组列表", "群组列表",
            "Excel文件 (*.xlsx);;CSV文件 (*.csv)"
        )
        if file_path:
            if file_path.endswith(".csv"):
                success = self.config.export_to_csv(file_path)
            else:
                if not file_path.endswith(".xlsx"):
                    file_path += ".xlsx"
                success = self.config.export_to_excel(file_path)

            if success:
                QMessageBox.information(self, "导出成功", f"群组列表已导出到:\n{file_path}")
            else:
                QMessageBox.warning(self, "导出失败", "导出群组列表时发生错误")
