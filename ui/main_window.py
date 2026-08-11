"""
主窗口
整合各个面板，提供主界面
"""

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QLabel, QStatusBar, QMessageBox, QAction, QMenuBar
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon

from core.config import GroupConfig, TemplateConfig
from ui.group_panel import GroupPanel
from ui.msg_editor import MsgEditorPanel
from ui.send_panel import SendPanel
from ui.personal_panel import PersonalPanel


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()

        # 初始化配置
        self.group_config = GroupConfig()
        self.template_config = TemplateConfig()

        self.init_ui()

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("零售通知自动分发工具")
        self.setMinimumSize(900, 650)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        # 创建标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont("Microsoft YaHei", 10))

        # 消息编辑标签页
        self.msg_editor = MsgEditorPanel(self.template_config)
        self.tab_widget.addTab(self.msg_editor, "📝 通知编辑")

        # 群组管理标签页
        self.group_panel = GroupPanel(self.group_config)
        self.tab_widget.addTab(self.group_panel, "👥 群组管理")

        # 发送控制标签页
        self.send_panel = SendPanel(self.group_config)
        self.tab_widget.addTab(self.send_panel, "🚀 发送控制")

        # 个人发送标签页
        self.personal_panel = PersonalPanel()
        self.tab_widget.addTab(self.personal_panel, "👤 个人发送")

        layout.addWidget(self.tab_widget)

        # 创建菜单栏（需要在面板初始化之后，因为菜单项引用了面板的方法）
        self.create_menu_bar()

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 | 共配置 0 个群组")

        # 更新状态栏
        self.update_status_bar()

    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        import_csv_action = QAction("导入群组(CSV)", self)
        import_csv_action.triggered.connect(self.group_panel.import_csv)
        file_menu.addAction(import_csv_action)

        import_excel_action = QAction("导入群组(Excel)", self)
        import_excel_action.triggered.connect(self.group_panel.import_excel)
        file_menu.addAction(import_excel_action)

        file_menu.addSeparator()

        export_action = QAction("导出群组列表", self)
        export_action.triggered.connect(self.group_panel.export_groups)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")

        test_action = QAction("测试选中群组Webhook", self)
        test_action.triggered.connect(self.test_selected_webhook)
        tools_menu.addAction(test_action)

        tools_menu.addSeparator()

        change_token_action = QAction("修改 Token", self)
        change_token_action.triggered.connect(self.change_token)
        tools_menu.addAction(change_token_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        usage_action = QAction("使用说明", self)
        usage_action.triggered.connect(self.show_usage)
        help_menu.addAction(usage_action)

    def update_status_bar(self):
        """更新状态栏"""
        total = len(self.group_config.groups)
        enabled = len(self.group_config.get_enabled_groups())
        self.status_bar.showMessage(f"就绪 | 共配置 {total} 个群组，已启用 {enabled} 个")

    def test_selected_webhook(self):
        """测试选中的群组Webhook"""
        from core.sender import WebhookSender

        # 获取当前选中的群组
        selected = self.send_panel.get_selected_groups()
        if not selected:
            QMessageBox.information(self, "提示", "请先在发送控制页面选择要测试的群组")
            return

        sender = WebhookSender()
        results = []

        for group in selected:
            success, msg = sender.test_webhook(group["webhook"])
            results.append(f"{'✓' if success else '✗'} {group['name']}: {msg}")

        QMessageBox.information(
            self, "测试结果",
            "Webhook测试结果:\n\n" + "\n".join(results)
        )

    def change_token(self):
        """主动修改当前经办人的 Token"""
        from core.auth import get_auth, ROLE_OPERATOR
        from ui.login import ChangeTokenDialog
        auth = get_auth()
        dialog = ChangeTokenDialog(auth, ROLE_OPERATOR, forced=False, parent=self)
        dialog.exec_()

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self, "关于",
            "<h3>零售通知自动分发工具</h3>"
            "<p>版本: 1.0.0</p>"
            "<p>通过企业微信群机器人Webhook，自动将通知消息发送到多个工作群。</p>"
            "<hr>"
            "<p><b>使用前准备:</b></p>"
            "<ol>"
            "<li>在每个目标群中添加群机器人</li>"
            "<li>复制机器人Webhook地址</li>"
            "<li>在群组管理中配置Webhook</li>"
            "</ol>"
        )

    def show_usage(self):
        """显示使用说明"""
        usage_text = """
<h3>使用说明</h3>

<h4>一、前置准备</h4>
<ol>
<li>让49个群的群主或管理员在群里添加群机器人</li>
<li>每个群机器人会生成一个Webhook地址</li>
<li>收集所有群的Webhook地址</li>
</ol>

<h4>二、配置群组</h4>
<ol>
<li>切换到"群组管理"标签页</li>
<li>点击"添加群组"逐个添加，或使用"导入CSV/Excel"批量导入</li>
<li>CSV格式: 第一列群名称，第二列Webhook地址，第三列分类(可选)</li>
</ol>

<h4>三、发送通知</h4>
<ol>
<li>在"通知编辑"标签页输入消息内容</li>
<li>可以使用模板快速填写，支持Markdown格式</li>
<li>切换到"发送控制"标签页</li>
<li>选择目标群组</li>
<li>设置发送间隔（建议3秒以上）</li>
<li>点击"开始发送"</li>
</ol>

<h4>四、注意事项</h4>
<ul>
<li>每个群机器人每分钟最多发送20条消息</li>
<li>建议发送间隔设为3秒或以上</li>
<li>发送前可以先测试单个群的Webhook是否正常</li>
</ul>
"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("使用说明")
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(usage_text)
        msg_box.exec_()

    def closeEvent(self, event):
        """关闭窗口事件"""
        if self.send_panel.is_sending:
            reply = QMessageBox.question(
                self, "确认退出",
                "正在发送消息，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.send_panel.sender.stop()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
