"""
主窗口 - WinSw_winPackaging
"""
import sys
import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QMessageBox, QStatusBar, QLabel,
    QPushButton, QProgressBar, QToolBar, QAction,
    QDialog, QVBoxLayout as DVLayout, QFormLayout,
    QLineEdit, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from core.winsw_downloader import WinSWDownloader
from core.service_manager import ServiceManager
from core.config_manager import ConfigManager
from ui.service_tab import ServiceTab
from ui.upload_tab import UploadTab
from ui.log_tab import LogTab
from ui.worker import run_task


class DownloadThread(QThread):
    """下载线程"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        try:
            path = self.downloader.download(
                progress_callback=lambda p: self.progress.emit(p)
            )
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


class WinswConfigDialog(QDialog):
    """WinSW配置对话框"""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("WinSW 配置")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.winsw_path_input = QLineEdit()
        self.winsw_path_input.setText(self.config_manager.get_winsw_path())
        self.winsw_path_input.setPlaceholderText("选择 WinSW.exe 文件...")
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_winsw)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.winsw_path_input)
        path_layout.addWidget(browse_btn)
        form.addRow("WinSW 路径:", path_layout)

        self.jdk_path_input = QLineEdit()
        self.jdk_path_input.setText(self.config_manager.get_jdk_path())
        self.jdk_path_input.setPlaceholderText("选择 JDK bin 目录（如 F:\\Work\\JDK\\java17\\bin）...")
        browse_jdk_btn = QPushButton("浏览...")
        browse_jdk_btn.clicked.connect(self._browse_jdk)
        auto_detect_btn = QPushButton("自动检测")
        auto_detect_btn.clicked.connect(self._auto_detect_jdk)
        jdk_layout = QHBoxLayout()
        jdk_layout.addWidget(self.jdk_path_input)
        jdk_layout.addWidget(browse_jdk_btn)
        jdk_layout.addWidget(auto_detect_btn)
        form.addRow("JDK 路径:", jdk_layout)

        self.apps_dir_input = QLineEdit()
        self.apps_dir_input.setText(self.config_manager.get_apps_dir())
        self.apps_dir_input.setPlaceholderText("如: D:/TEST (服务将放在 D:/TEST/服务ID)")
        browse_dir_btn = QPushButton("浏览...")
        browse_dir_btn.clicked.connect(self._browse_apps_dir)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.apps_dir_input)
        dir_layout.addWidget(browse_dir_btn)
        form.addRow("应用根目录:", dir_layout)

        hint_label = QLabel("服务目录结构: 应用根目录/服务ID/\n例如: D:/TEST/myapp/winsw.exe, myapp.jar, myapp.xml")
        hint_label.setStyleSheet("color: #666; font-size: 12px;")
        form.addRow("", hint_label)

        layout.addLayout(form)

        info_label = QLabel(
            "提示: WinSW.exe 是 Windows 服务包装器。<br>"
            "JDK 路径请选择 <b>bin 目录</b>（如 F:\\Work\\JDK\\java17\\bin）。<br>"
            "服务将使用 bin\\java.exe 启动。"
        )
        info_label.setStyleSheet("color: #666; padding: 10px;")
        layout.addWidget(info_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.download_btn = QPushButton("从 GitHub 下载")
        self.download_btn.clicked.connect(self._download_winsw)
        btn_layout.addWidget(self.download_btn)

        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _browse_winsw(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 WinSW.exe", "", "Executable Files (*.exe)"
        )
        if path:
            self.winsw_path_input.setText(path)

    def _browse_apps_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择应用根目录"
        )
        if path:
            self.apps_dir_input.setText(path)

    def _browse_jdk(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择 JDK bin 目录（如 F:\\Work\\JDK\\java17\\bin）"
        )
        if path:
            self.jdk_path_input.setText(path)

    def _auto_detect_jdk(self):
        import shutil
        # 优先从 JAVA_HOME 环境变量读取
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home and os.path.isfile(os.path.join(java_home, "bin", "java.exe")):
            jdk_bin = os.path.join(java_home, "bin")
            self.jdk_path_input.setText(jdk_bin)
            return
        # 其次从 PATH 中找
        java_path = shutil.which("java")
        if java_path:
            jdk_bin = os.path.dirname(java_path)
            self.jdk_path_input.setText(jdk_bin)
            return
        QMessageBox.information(self, "未找到 JDK", "未检测到 JDK，请手动选择 JDK bin 目录。")

    def _download_winsw(self):
        self.download_btn.setEnabled(False)
        self.download_btn.setText("下载中...")

        try:
            downloader = WinSWDownloader()
            result = run_task(self, lambda: {"success": True, "path": downloader.download()}, "正在下载 WinSW…")
            if not result["success"]:
                raise RuntimeError(result["message"])
            path = result["path"]
            if path:
                self.winsw_path_input.setText(path)
                self.download_btn.setText("下载完成")
                QMessageBox.information(self, "成功", f"WinSW 已下载到:\n{path}")
            else:
                self.download_btn.setText("下载失败")
                QMessageBox.critical(self, "失败", "下载失败，请手动下载 WinSW")
        except Exception as e:
            self.download_btn.setText("下载失败")
            QMessageBox.critical(self, "失败", f"下载失败:\n{e}")
        finally:
            self.download_btn.setEnabled(True)
            self.download_btn.setText("从 GitHub 下载")

    def _save_and_close(self):
        winsw_path = self.winsw_path_input.text().strip()
        apps_dir = self.apps_dir_input.text().strip()
        jdk_path = self.jdk_path_input.text().strip()

        if winsw_path and not os.path.isfile(winsw_path):
            QMessageBox.warning(self, "警告", "WinSW 路径不存在!")
            return

        if jdk_path and not os.path.isfile(os.path.join(jdk_path, "java.exe")):
            QMessageBox.warning(self, "警告", "JDK bin 目录中不存在 java.exe")
            return
        try:
            if apps_dir:
                os.makedirs(apps_dir, exist_ok=True)
            self.config_manager.update(winsw_path=winsw_path, apps_dir=apps_dir, jdk_path=jdk_path)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", f"配置未更改: {exc}")
            return
        self.accept()


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.downloader = WinSWDownloader()
        self.service_manager = ServiceManager(self.config_manager.get_apps_dir() or None, self.config_manager)
        self.download_thread = None

        self._init_ui()
        self._check_winsw()

    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("WinSw_winPackaging - Windows服务可视化部署工具")
        self.setGeometry(200, 100, 1200, 800)

        self._create_menu()
        self._create_toolbar()
        self._create_central_widget()
        self._create_statusbar()

    def _create_menu(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")

        config_action = QAction("配置", self)
        config_action.triggered.connect(self._show_config_dialog)
        file_menu.addAction(config_action)

        refresh_action = QAction("刷新服务列表", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_services)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("工具(&T)")

        download_action = QAction("下载WinSW", self)
        download_action.triggered.connect(self._download_winsw)
        tools_menu.addAction(download_action)

        about_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        about_menu.addAction(about_action)

    def _create_toolbar(self):
        """创建工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.config_btn = QPushButton("配置")
        self.config_btn.clicked.connect(self._show_config_dialog)
        toolbar.addWidget(self.config_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh_services)
        toolbar.addWidget(self.refresh_btn)

        toolbar.addSeparator()

        self.apps_dir_label = QLabel("目录: 未设置")
        toolbar.addWidget(self.apps_dir_label)

        toolbar.addWidget(QLabel("    "))

        self.status_indicator = QLabel("● 未配置")
        self.status_indicator.setStyleSheet("color: #cc0000; font-weight: bold;")
        toolbar.addWidget(self.status_indicator)

        toolbar.addWidget(QLabel("    "))

        self.jdk_status_label = QLabel("● JDK 未配置")
        self.jdk_status_label.setStyleSheet("color: #cc8800; font-weight: bold;")
        toolbar.addWidget(self.jdk_status_label)

        toolbar.addWidget(QLabel("    "))

        self.version_label = QLabel("v0.3.1")
        toolbar.addWidget(self.version_label)

    def _create_central_widget(self):
        """创建中央部件"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.service_tab = ServiceTab(self.service_manager, self)
        self.upload_tab = UploadTab(self.service_manager, self)
        self.log_tab = LogTab(self.service_manager, self)

        self.tabs.addTab(self.service_tab, "服务管理")
        self.tabs.addTab(self.upload_tab, "上传更新")
        self.tabs.addTab(self.log_tab, "日志")
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _create_statusbar(self):
        """创建状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪")

    def _check_winsw(self):
        """检查WinSW和JDK配置状态"""
        if self.config_manager.is_winsw_configured():
            self.status_indicator.setText("● WinSW已就绪")
            self.status_indicator.setStyleSheet("color: #00aa00; font-weight: bold;")
            self.statusbar.showMessage(f"WinSW: {self.config_manager.get_winsw_path()}")
        else:
            self.status_indicator.setText("● 未配置WinSW")
            self.status_indicator.setStyleSheet("color: #cc0000; font-weight: bold;")

        apps_dir = self.config_manager.get_apps_dir()
        if apps_dir:
            self.apps_dir_label.setText(f"目录: {apps_dir}")
        else:
            self.apps_dir_label.setText("目录: 默认位置")

        jdk = self.config_manager.get_jdk_path()
        if jdk and os.path.isfile(os.path.join(jdk, "java.exe")):
            self.jdk_status_label.setText(f"● JDK: {jdk}")
            self.jdk_status_label.setStyleSheet("color: #00aa00; font-weight: bold;")
        elif jdk:
            self.jdk_status_label.setText("● JDK 路径无效")
            self.jdk_status_label.setStyleSheet("color: #cc0000; font-weight: bold;")
        else:
            self.jdk_status_label.setText("● JDK 未配置")
            self.jdk_status_label.setStyleSheet("color: #cc8800; font-weight: bold;")

    def _show_config_dialog(self):
        """显示配置对话框"""
        previous_dir = self.service_manager.apps_dir
        dialog = WinswConfigDialog(self.config_manager, self)
        if dialog.exec_():
            self.service_manager.set_apps_dir(self.config_manager.get_apps_dir() or os.path.join(os.path.expanduser("~"), ".winsw-manager", "apps"))
            if self.service_manager.apps_dir != previous_dir:
                self.upload_tab.update_table.setRowCount(0)
            self.service_tab.console.reload()
            self.upload_tab.console.reload()
            self.log_tab.console.reload()
            self._check_winsw()
            self._refresh_services()

    def _download_winsw(self):
        """下载WinSW"""
        winsw_path = self.config_manager.get_winsw_path()
        if winsw_path:
            QMessageBox.information(self, "已有WinSW", f"WinSW已配置:\n{winsw_path}")
            return

        try:
            self.statusbar.showMessage("正在下载WinSW...")
            result = run_task(self, lambda: {"success": True, "path": self.downloader.download()}, "正在下载 WinSW…")
            if not result["success"]:
                raise RuntimeError(result["message"])
            path = result["path"]
            if path:
                self.config_manager.set_winsw_path(path)
                self._check_winsw()
                QMessageBox.information(self, "下载完成", f"WinSW已下载:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "下载失败", f"下载失败:\n{e}")
        finally:
            self.statusbar.showMessage("就绪")

    def _refresh_services(self):
        """刷新服务列表"""
        self.service_tab.refresh_services()
        self.notify_services_changed()
        self.statusbar.showMessage("服务列表已刷新")

    def _on_tab_changed(self, idx: int):
        if self.tabs.widget(idx) is self.log_tab:
            self.log_tab.on_services_changed()

    def notify_services_changed(self):
        """下层（service/upload/log）通知服务列表变化 → 刷新日志页左侧列表"""
        if hasattr(self, "log_tab"):
            self.log_tab.on_services_changed()
        if hasattr(self, "upload_tab"):
            self.upload_tab._refresh_service_list()

    def closeEvent(self, event):
        if getattr(self, "_operation_active", False):
            event.ignore()
            return
        super().closeEvent(event)

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于",
            "<h3>WinSw_winPackaging</h3>"
            "<p>Windows服务可视化部署工具</p>"
            "<p>版本: 0.3.1</p>"
            "<p>日期: 2026/9/23</p>"
            "<p>基于 WinSW 构建</p>"
            "<hr>"
            "<p style='margin-top:12px;'><b>作者：</b>Tao</p>"
            "<p><b>邮箱：</b><a href='mailto:2027883286@qq.com'>2027883286@qq.com</a></p>"
        )

    def get_winsw_path(self):
        """获取WinSW路径"""
        if self.config_manager.is_winsw_configured():
            return self.config_manager.get_winsw_path()
        return None

    def is_winsw_ready(self):
        """检查WinSW是否就绪"""
        return self.config_manager.is_winsw_configured()

    def get_apps_dir(self):
        """获取应用目录"""
        return self.config_manager.get_apps_dir()

    def get_jdk_path(self):
        """获取JDK bin目录路径"""
        return self.config_manager.get_jdk_path()
