"""Full-size console using the same reader as the service and upload tabs."""
import os
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
                            QListWidgetItem, QPushButton, QLabel, QMessageBox)
from ui.console import ConsolePanel
from ui.worker import run_task


class LogTab(QWidget):
    def __init__(self, service_manager, parent=None):
        super().__init__(parent)
        self.service_manager = service_manager
        self.current_service = None
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        self.service_list = QListWidget()
        self.service_list.itemSelectionChanged.connect(self._on_service_changed)
        splitter.addWidget(self.service_list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.status = QLabel("请选择服务")
        right_layout.addWidget(self.status)
        self.console = ConsolePanel(service_manager)
        right_layout.addWidget(self.console, 1)
        buttons = QHBoxLayout()
        for title, callback in [("刷新列表", self.refresh_service_list), ("打开日志目录", self._open_folder),
                                ("复制全部", self._copy), ("清空磁盘日志", self._clear_log)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        right_layout.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setSizes([220, 900])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(1000)
        self.refresh_service_list()

    def refresh_service_list(self):
        try:
            services = self.service_manager.get_all_services()
        except OSError as exc:
            self.status.setText(f"读取服务列表失败: {exc}")
            return
        previous = self.current_service
        self.service_list.blockSignals(True)
        self.service_list.clear()
        for service in services:
            item = QListWidgetItem(f"{service.display_name} ({service.name})")
            item.setData(Qt.UserRole, service.name)
            self.service_list.addItem(item)
            if service.name == previous:
                self.service_list.setCurrentItem(item)
        if not self.service_list.currentItem() and self.service_list.count():
            self.service_list.setCurrentRow(0)
        self.service_list.blockSignals(False)
        self._on_service_changed()

    def _on_service_changed(self):
        item = self.service_list.currentItem()
        self.current_service = item.data(Qt.UserRole) if item else None
        self.console.set_service(self.current_service)
        self._refresh_status()

    def _refresh_status(self):
        name = self.current_service
        self.status.setText(f"{name} · Windows 服务: {self.service_manager.get_service_status(name)}" if name else "请选择服务")

    def _open_folder(self):
        if self.current_service:
            try:
                path = self.service_manager.get_log_dir(self.current_service)
                os.startfile(path)
            except Exception as exc:
                QMessageBox.warning(self, "打开失败", str(exc))

    def _copy(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(self.console.text.toPlainText())

    def _clear_log(self):
        if not self.current_service:
            return
        if QMessageBox.question(self, "清空磁盘日志", f"确定永久清空 {self.current_service} 的日志文件？\n仅清屏请使用控制台下方的“清屏”。",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        name = self.current_service
        result = run_task(self, lambda: self.service_manager.clear_log(name))
        self.console.reload()
        (QMessageBox.information if result["success"] else QMessageBox.warning)(self, "日志清理", result["message"])

    def on_services_changed(self):
        self.refresh_service_list()
