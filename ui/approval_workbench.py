"""
审批工作台
审批人登录后查看待审批队列，勾选批量通过/驳回，通过后执行真实发送。

发送执行复用现有 WebhookSender / PersonalSender 内核，仅在其外围做
"决策先落盘 + 逐条进度落盘"的状态一致性保证，异常中断后可从断点续发。
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QTextEdit, QPlainTextEdit, QGroupBox,
    QProgressBar, QMessageBox, QDialog, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
from PyQt5.QtGui import QFont

from core.approval import (
    PendingTaskStore, AuditLog, AUDIT_FILE,
    STATUS_PENDING, STATUS_APPROVED, STATUS_SENDING,
    STATUS_DONE, STATUS_FAILED, STATUS_REJECTED,
)
from core.sender import WebhookSender, SendResult, SendLog
from core.personal_sender import PersonalSender
from core.auth import ROLE_LABELS


# ── 表格列索引 ─────────────────────────────────────────────
COL_CHECK = 0
COL_ID = 1
COL_TYPE = 2
COL_STATUS = 3
COL_TIME = 4
COL_SUBMITTER = 5
COL_COUNT = 6
COL_HIDDEN_ID = 7

TYPE_LABELS = {"group": "群组", "personal": "个人"}
STATUS_LABELS = {
    STATUS_PENDING: "待审批",
    STATUS_APPROVED: "已通过",
    STATUS_SENDING: "发送中",
    STATUS_DONE: "已完成",
    STATUS_FAILED: "失败",
    STATUS_REJECTED: "已驳回",
}


class ApprovalSendWorker(QObject):
    """在子线程中执行审批通过的发送任务（复用现有发送内核）"""

    progress = pyqtSignal(int, int, str)                 # current, total, target_name
    result = pyqtSignal(object)                          # SendResult
    task_finished = pyqtSignal(int, int, int, list)      # task_id, success, total, results

    def __init__(self, task: dict, store: PendingTaskStore):
        super().__init__()
        self.task = task
        self.store = store
        self.sender = None

    def run(self):
        task_id = self.task["id"]
        remaining = list(self.task.get("remaining_targets") or self.task.get("targets") or [])

        try:
            if self.task.get("type") == "personal":
                self.sender = PersonalSender(
                    search_delay=self.task.get("send_params", {}).get("search_delay", 1.5),
                    send_interval=self.task.get("send_params", {}).get("send_interval", 2.0),
                )
                results = self.sender.send_to_persons(
                    remaining,
                    self.task.get("content", ""),
                    self.task.get("file_paths") or [],
                    progress_callback=lambda c, t, n: self.progress.emit(c, t, n),
                    result_callback=self._on_result,
                )
            else:
                self.sender = WebhookSender(
                    interval=self.task.get("send_params", {}).get("interval", 3.0),
                    retries=self.task.get("send_params", {}).get("retries", 2),
                )
                results = self.sender.send_to_groups(
                    remaining,
                    self.task.get("content", ""),
                    progress_callback=lambda c, t, n: self.progress.emit(c, t, n),
                    result_callback=self._on_result,
                )

            success = sum(1 for r in results if r.success)
        except Exception as e:
            import traceback
            traceback.print_exc()
            results = [SendResult(self.task.get("content", ""), False, f"执行异常: {e}")]
            success = 0

        self.task_finished.emit(task_id, success, len(results), list(results))

    def _on_result(self, result: SendResult):
        """每条目标发送完成即落盘进度，供崩溃续发"""
        self.result.emit(result)
        task = self.store.get(self.task["id"])
        if task is None:
            return
        sent = list(task.get("sent_targets") or [])
        remaining = list(task.get("remaining_targets") or task.get("targets") or [])
        for t in remaining:
            if t.get("name") == result.group_name:
                remaining.remove(t)
                if result.success:
                    sent.append(t)
                break
        self.store.update_progress(self.task["id"], sent, remaining)

    def stop(self):
        if self.sender is not None:
            self.sender.stop()


class ApprovalWorkbench(QMainWindow):
    """审批工作台"""

    def __init__(self, store=None, auth=None, parent=None):
        super().__init__(parent)
        self.store = store or PendingTaskStore()
        self.auth = auth
        self.audit = AuditLog()
        self.worker = None
        self.thread = None
        self._queue = []
        self.is_executing = False
        self.setWindowTitle("审批工作台")
        self.setMinimumSize(960, 640)
        self.init_ui()
        self.check_stale_tasks()
        self.refresh()

    # ── UI 初始化 ─────────────────────────────────────────
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧：待审批列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)

        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_btn)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all)
        toolbar.addWidget(self.select_all_btn)

        toolbar.addStretch()
        self.stats_label = QLabel("")
        toolbar.addWidget(self.stats_label)
        left_layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["✓", "ID", "类型", "状态", "提交时间", "经办人", "目标数", ""])
        self.table.horizontalHeader().setSectionResizeMode(COL_TIME, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_CHECK, 36)
        self.table.setColumnWidth(COL_ID, 50)
        self.table.setColumnWidth(COL_TYPE, 60)
        self.table.setColumnWidth(COL_STATUS, 70)
        self.table.setColumnWidth(COL_SUBMITTER, 70)
        self.table.setColumnWidth(COL_COUNT, 60)
        self.table.setColumnHidden(COL_HIDDEN_ID, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.table)

        splitter.addWidget(left)

        # 右侧：详情 + 操作
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)

        detail_group = QGroupBox("通知内容")
        detail_inner = QVBoxLayout(detail_group)
        self.content_edit = QTextEdit()
        self.content_edit.setReadOnly(True)
        self.content_edit.setMinimumHeight(120)
        detail_inner.addWidget(self.content_edit)
        right_layout.addWidget(detail_group)

        targets_group = QGroupBox("发送对象")
        targets_inner = QVBoxLayout(targets_group)
        self.targets_edit = QPlainTextEdit()
        self.targets_edit.setReadOnly(True)
        targets_inner.addWidget(self.targets_edit)
        right_layout.addWidget(targets_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        right_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.approve_btn = QPushButton("✅ 通过并发送")
        self.approve_btn.clicked.connect(self.approve_selected)
        btn_row.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("❌ 驳回")
        self.reject_btn.clicked.connect(self.reject_selected)
        btn_row.addWidget(self.reject_btn)

        self.stop_btn = QPushButton("⏹ 停止发送")
        self.stop_btn.clicked.connect(self.stop_execution)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)

        self.audit_btn = QPushButton("📋 操作日志")
        self.audit_btn.clicked.connect(self.show_audit)
        btn_row.addWidget(self.audit_btn)

        self.token_btn = QPushButton("🔑 修改 Token")
        self.token_btn.clicked.connect(self.change_token)
        btn_row.addWidget(self.token_btn)

        right_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([520, 440])
        root.addWidget(splitter)

    # ── 列表刷新与勾选 ────────────────────────────────────
    def refresh(self):
        self.table.setRowCount(0)
        tasks = self.store.list(status=STATUS_PENDING)
        self.table.setRowCount(len(tasks))
        for i, t in enumerate(tasks):
            cb = QCheckBox()
            cell = QWidget()
            cb_lay = QHBoxLayout(cell)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, COL_CHECK, cell)

            self.table.setItem(i, COL_ID, QTableWidgetItem(str(t.get("id", ""))))
            self.table.setItem(i, COL_TYPE, QTableWidgetItem(TYPE_LABELS.get(t.get("type"), t.get("type", ""))))
            self.table.setItem(i, COL_STATUS, QTableWidgetItem(STATUS_LABELS.get(t.get("status"), t.get("status", ""))))
            self.table.setItem(i, COL_TIME, QTableWidgetItem(t.get("submitted_at", "")))
            self.table.setItem(i, COL_SUBMITTER, QTableWidgetItem(t.get("submitter", "")))
            self.table.setItem(i, COL_COUNT, QTableWidgetItem(str(len(t.get("targets") or []))))
            self.table.setItem(i, COL_HIDDEN_ID, QTableWidgetItem(str(t.get("id", ""))))
        self.stats_label.setText(f"待审批 {len(tasks)} 条")

    def select_all(self):
        all_checked = True
        for row in range(self.table.rowCount()):
            cb = self._get_row_checkbox(row)
            if cb is None or not cb.isChecked():
                all_checked = False
                break
        target = not all_checked
        for row in range(self.table.rowCount()):
            cb = self._get_row_checkbox(row)
            if cb is not None:
                cb.setChecked(target)
        self.select_all_btn.setText("取消全选" if target else "全选")

    def _get_row_checkbox(self, row: int):
        cell = self.table.cellWidget(row, COL_CHECK)
        if cell is None:
            return None
        for child in cell.children():
            if isinstance(child, QCheckBox):
                return child
        return None

    def _selected_ids(self) -> list:
        ids = []
        for row in range(self.table.rowCount()):
            cb = self._get_row_checkbox(row)
            if cb is not None and cb.isChecked():
                item = self.table.item(row, COL_HIDDEN_ID)
                if item is not None and item.text().isdigit():
                    ids.append(int(item.text()))
        return ids

    # ── 详情显示 ──────────────────────────────────────────
    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            item = self.table.item(row, COL_HIDDEN_ID)
            if item is not None:
                self._show_detail(int(item.text()))

    def _show_detail(self, task_id: int):
        task = self.store.get(task_id)
        if task is None:
            return
        self.content_edit.setPlainText(task.get("content", ""))
        lines = []
        for t in task.get("targets") or []:
            if task.get("type") == "group":
                lines.append(f"{t.get('name')}  [{t.get('category', '默认')}]")
            else:
                lines.append(f"{t.get('name')}  [{t.get('unit', '')}]")
        self.targets_edit.setPlainText("\n".join(lines))

    # ── 审批操作 ──────────────────────────────────────────
    def _reviewer(self) -> str:
        role = self.auth.current_role if self.auth else None
        return ROLE_LABELS.get(role, "审批人")

    @staticmethod
    def _summary(task: dict) -> str:
        count = len(task.get("targets") or [])
        unit = "群" if task.get("type") == "group" else "人"
        return f"{count} {unit}"

    def approve_selected(self):
        if self.is_executing:
            QMessageBox.information(self, "提示", "正在执行发送，请稍候")
            return
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先勾选要审批的记录")
            return
        reply = QMessageBox.question(
            self, "确认通过",
            f"确定通过 {len(ids)} 条记录并立即执行发送吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        reviewer = self._reviewer()
        approved_ids = []
        for tid in ids:
            task = self.store.get(tid)
            if task is None or task.get("status") != STATUS_PENDING:
                continue
            # 决策先落盘，再执行
            self.store.update_status(tid, STATUS_APPROVED, reviewer=reviewer)
            self.audit.log("approve", task_id=tid, reviewer=reviewer,
                           target_summary=self._summary(task))
            approved_ids.append(tid)
        if not approved_ids:
            QMessageBox.information(self, "提示", "没有可审批的记录")
            return
        self.start_execution(approved_ids)

    def reject_selected(self):
        if self.is_executing:
            QMessageBox.information(self, "提示", "正在执行发送，请稍候")
            return
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先勾选要审批的记录")
            return
        reply = QMessageBox.question(
            self, "确认驳回",
            f"确定驳回 {len(ids)} 条记录吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        reviewer = self._reviewer()
        for tid in ids:
            task = self.store.get(tid)
            if task is None or task.get("status") != STATUS_PENDING:
                continue
            self.store.update_status(tid, STATUS_REJECTED, reviewer=reviewer)
            self.audit.log("reject", task_id=tid, reviewer=reviewer,
                           target_summary=self._summary(task))
        self.refresh()

    # ── 批量执行 ──────────────────────────────────────────
    def start_execution(self, task_ids):
        self._queue = list(task_ids)
        self.is_executing = True
        self._set_controls_enabled(False)
        self._run_next()

    def _run_next(self):
        if not self._queue:
            self.is_executing = False
            self._set_controls_enabled(True)
            self.status_label.setText("执行完成")
            self.progress_bar.setVisible(False)
            self.refresh()
            return
        task_id = self._queue.pop(0)
        task = self.store.get(task_id)
        if task is None:
            self._run_next()
            return
        reviewer = self._reviewer()
        # 写前提交：先落盘 sending 与进度，再执行
        self.store.update_status(task_id, STATUS_SENDING, reviewer=reviewer)
        self.store.update_progress(task_id, [], list(task.get("targets") or []))
        self.audit.log("execute_start", task_id=task_id, reviewer=reviewer,
                       target_summary=self._summary(task))

        self.progress_bar.setMaximum(len(task.get("targets") or []))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"正在发送任务 #{task_id}...")

        self.thread = QThread()
        self.worker = ApprovalSendWorker(task, self.store)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._on_result)
        self.worker.task_finished.connect(self._on_task_finished)
        self.worker.task_finished.connect(self.thread.quit)
        self.thread.start()

    def _on_progress(self, current: int, total: int, name: str):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"[{current}/{total}] {name}")

    def _on_result(self, result):
        # 需要时可在右侧扩展逐条结果展示，当前仅推进进度
        pass

    def _on_task_finished(self, task_id: int, success: int, total: int, results: list):
        task = self.store.get(task_id)
        if task is not None:
            status = STATUS_DONE if success == total else STATUS_FAILED
            self.store.update_status(task_id, status, detail={"result": f"{success}/{total}"})
            # 群组任务复用现有 SendLog 写入历史记录
            if task.get("type") == "group":
                send_log = SendLog()
                for r in results:
                    send_log.add(r)
                send_log.save_to_history(
                    task.get("content", ""),
                    {"total": total, "success": success, "failed": total - success},
                )
            action = "execute_done" if status == STATUS_DONE else "execute_fail"
            self.audit.log(action, task_id=task_id, reviewer=self._reviewer(),
                           target_summary=self._summary(task), detail=f"{success}/{total}")
        self._run_next()

    def stop_execution(self):
        if self.worker is not None:
            self.worker.stop()
        self.status_label.setText("正在停止...")
        self.stop_btn.setEnabled(False)

    def _set_controls_enabled(self, enabled: bool):
        self.approve_btn.setEnabled(enabled)
        self.reject_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.select_all_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)

    def change_token(self):
        """主动修改当前审批人的 Token"""
        if self.auth is None:
            QMessageBox.information(self, "提示", "当前无登录会话，无法修改")
            return
        from ui.login import ChangeTokenDialog
        from core.auth import ROLE_APPROVER
        dialog = ChangeTokenDialog(self.auth, ROLE_APPROVER, forced=False, parent=self)
        dialog.exec_()

    # ── 崩溃恢复 ──────────────────────────────────────────
    def check_stale_tasks(self):
        """启动时检出中断的 sending 任务，续发或标记失败"""
        stale = self.store.get_stale_sending()
        if not stale:
            return
        resume_ids = []
        for task in stale:
            reply = QMessageBox.question(
                self, "发现中断的发送任务",
                f"任务 #{task['id']} 上次发送被中断。\n"
                f"是否继续发送剩余目标？\n"
                f"（选“是”续发剩余目标，选“否”标记为失败）",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                resume_ids.append(task["id"])
            else:
                self.store.update_status(task["id"], STATUS_FAILED,
                                         detail={"result": "中断标记失败"})
                self.audit.log("recover", task_id=task["id"], reviewer=self._reviewer(),
                               detail="标记失败")
        if resume_ids:
            self.start_execution(resume_ids)

    # ── 审计查看 ──────────────────────────────────────────
    def show_audit(self):
        lines = []
        if AUDIT_FILE.exists():
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()[-200:]

        dialog = QDialog(self)
        dialog.setWindowTitle("审计日志")
        dialog.setMinimumSize(720, 480)
        layout = QVBoxLayout(dialog)
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setFont(QFont("Consolas", 10))
        edit.setPlainText("\n".join(lines))
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec_()
