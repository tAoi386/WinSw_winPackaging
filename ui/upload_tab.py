"""
上传更新标签页 - Jar包上传与批量更新
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QPushButton,
    QFileDialog, QMessageBox, QHeaderView, QAbstractItemView,
    QCheckBox, QProgressBar, QLabel, QTextEdit, QComboBox,
    QListWidget, QListWidgetItem, QSplitter, QSpinBox
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
import os

from core.service_manager import DEFAULT_LOG_LINES
from ui.console import ConsolePanel
from ui.worker import run_task


class UploadTab(QWidget):
    """上传更新标签页"""

    def __init__(self, service_manager, main_window):
        super().__init__()
        self.service_manager = service_manager
        self.main_window = main_window
        self.update_thread = None
        self.pending_updates = []
        self._init_ui()
        self._refresh_service_list()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # ---- 左侧：上传 + 批量更新 ----
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(self._create_upload_group())
        left_layout.addWidget(self._create_batch_update_group())

        # ---- 右侧：服务 SpringBoot 运行日志（实时刷新） ----
        right_widget = self._create_runtime_log_group()

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([700, 500])

        # 选中服务后右侧实时显示其 SpringBoot 日志
        self.service_list.itemSelectionChanged.connect(self._on_runtime_service_changed)
        self._setup_auto_refresh()

    def _create_runtime_log_group(self) -> QGroupBox:
        """右侧：当前选中服务的 SpringBoot 实时日志"""
        group = QGroupBox("服务实时控制台")
        layout = QVBoxLayout(group)

        # 状态行
        header = QHBoxLayout()
        self.runtime_service_label = QLabel("（未选择服务）")
        self.runtime_service_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self.runtime_service_label)
        header.addStretch()

        self.runtime_status_label = QLabel("")
        self.runtime_status_label.setStyleSheet(
            "QLabel { padding: 2px 8px; border-radius: 4px; font-weight: bold; }"
        )
        header.addWidget(self.runtime_status_label)
        layout.addLayout(header)

        self.console = ConsolePanel(self.service_manager)
        layout.addWidget(self.console, 1)

        return group

    def _setup_auto_refresh(self):
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(3000)
        self.runtime_timer.timeout.connect(self._runtime_tick)
        self.runtime_timer.start()

    def _runtime_tick(self):
        if not getattr(self, "_runtime_service_name", None):
            return
        self._refresh_runtime_log()

    def _on_runtime_service_changed(self):
        """选中服务变更时，加载该服务的最新日志"""
        items = self.service_list.selectedItems()
        if not items:
            self._runtime_service_name = None
            self.runtime_service_label.setText("（未选择服务）")
            self.console.set_service(None)
            self.runtime_status_label.clear()
            return
        service_name = items[0].data(Qt.UserRole)
        self._runtime_service_name = service_name
        self.runtime_service_label.setText(service_name)
        self._refresh_runtime_log()

    def _refresh_runtime_log(self):
        name = getattr(self, "_runtime_service_name", None)
        self.console.set_service(name)
        self.runtime_status_label.setText(self.service_manager.get_service_status(name) if name else "")

    def _create_upload_group(self) -> QGroupBox:
        """上传组"""
        group = QGroupBox("上传JAR包")
        layout = QVBoxLayout(group)

        row1 = QHBoxLayout()

        self.jar_path_input = QTextEdit()
        self.jar_path_input.setMaximumHeight(60)
        self.jar_path_input.setReadOnly(True)
        row1.addWidget(self.jar_path_input)

        select_btn = QPushButton("选择\nJAR文件")
        select_btn.setMinimumWidth(80)
        select_btn.clicked.connect(self._select_jar_files)
        row1.addWidget(select_btn)

        layout.addLayout(row1)

        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel("已选择文件:"))
        self.selected_count_label = QLabel("0 个文件")
        info_layout.addWidget(self.selected_count_label)
        info_layout.addStretch()

        layout.addLayout(info_layout)

        return group

    def _create_batch_update_group(self) -> QGroupBox:
        """批量更新组"""
        group = QGroupBox("批量更新")
        layout = QVBoxLayout(group)

        self.service_list = QListWidget()
        self.service_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.service_list)

        btn_layout = QHBoxLayout()

        self.refresh_list_btn = QPushButton("刷新服务列表")
        self.refresh_list_btn.clicked.connect(self._refresh_service_list)
        btn_layout.addWidget(self.refresh_list_btn)

        self.add_update_btn = QPushButton("添加更新任务")
        self.add_update_btn.clicked.connect(self._add_update_task)
        btn_layout.addWidget(self.add_update_btn)

        self.remove_update_btn = QPushButton("移除")
        self.remove_update_btn.clicked.connect(self._remove_update_task)
        btn_layout.addWidget(self.remove_update_btn)

        layout.addLayout(btn_layout)

        self.update_table = QTableWidget()
        self.update_table.setColumnCount(4)
        self.update_table.setHorizontalHeaderLabels(["服务", "JAR文件", "状态", "操作"])
        self.update_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.update_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.update_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.update_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.update_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.update_table.verticalHeader().setVisible(False)
        self.update_table.setMaximumHeight(150)
        layout.addWidget(self.update_table)

        # 批量更新选项（移到本组，原历史日志区已被右侧运行日志替代）
        opt_layout = QHBoxLayout()
        self.stop_before_update_cb = QCheckBox("更新前先停止服务")
        self.stop_before_update_cb.setChecked(True)
        opt_layout.addWidget(self.stop_before_update_cb)

        self.restart_after_update_cb = QCheckBox("更新后重启服务")
        self.restart_after_update_cb.setChecked(True)
        opt_layout.addWidget(self.restart_after_update_cb)
        opt_layout.addStretch()
        layout.addLayout(opt_layout)

        self.execute_update_btn = QPushButton("执行批量更新")
        self.execute_update_btn.clicked.connect(self._execute_batch_update)
        self.execute_update_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }")
        layout.addWidget(self.execute_update_btn)

        return group

    def _create_update_history_group(self) -> QGroupBox:
        """兼容保留：原"更新日志"组，已被右侧运行日志取代，不再调用。"""
        group = QGroupBox("更新日志")
        layout = QVBoxLayout(group)
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        layout.addWidget(self.history_text)
        return group

    def _select_jar_files(self):
        """选择JAR文件"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择JAR文件", "", "JAR Files (*.jar)"
        )

        if file_paths:
            self.selected_jar_files = file_paths
            self.jar_path_input.setPlainText("\n".join(file_paths))
            self.selected_count_label.setText(f"{len(file_paths)} 个文件")

    def _refresh_service_list(self):
        """刷新服务列表"""
        try:
            services = self.service_manager.get_all_services()
        except OSError as exc:
            self._log_history(f"读取服务列表失败: {exc}")
            return
        selected = {item.data(Qt.UserRole) for item in self.service_list.selectedItems()}
        self.service_list.blockSignals(True)
        self.service_list.clear()

        for service in services:
            item = QListWidgetItem(f"{service.display_name} ({service.name})")
            item.setData(Qt.UserRole, service.name)
            if service.status == "Running":
                item.setForeground(QColor(0, 150, 0))
            else:
                item.setForeground(QColor(200, 50, 50))
            self.service_list.addItem(item)
            item.setSelected(service.name in selected)
        self.service_list.blockSignals(False)
        self._on_runtime_service_changed()

    def _add_update_task(self):
        """添加更新任务"""
        if not hasattr(self, 'selected_jar_files') or not self.selected_jar_files:
            QMessageBox.warning(self, "错误", "请先选择JAR文件")
            return

        selected_services = self.service_list.selectedItems()
        if not selected_services:
            QMessageBox.warning(self, "错误", "请选择要更新的服务")
            return

        if len(self.selected_jar_files) != len(selected_services):
            QMessageBox.warning(
                self, "数量不匹配",
                f"已选择 {len(selected_services)} 个服务\n"
                f"已选择 {len(self.selected_jar_files)} 个JAR文件\n"
                "数量必须一致才能批量更新"
            )
            return

        for i, item in enumerate(selected_services):
            service_name = item.data(Qt.UserRole)
            jar_path = self.selected_jar_files[i]

            if any(self.update_table.item(r, 0).text() == service_name for r in range(self.update_table.rowCount())):
                QMessageBox.warning(self, "重复任务", f"{service_name} 已在更新列表中")
                continue
            row = self.update_table.rowCount()
            self.update_table.insertRow(row)
            self.update_table.setItem(row, 0, QTableWidgetItem(service_name))
            jar_item = QTableWidgetItem(os.path.basename(jar_path))
            jar_item.setData(Qt.UserRole, os.path.abspath(jar_path))
            jar_item.setToolTip(os.path.abspath(jar_path))
            self.update_table.setItem(row, 1, jar_item)
            status_item = QTableWidgetItem("等待更新")
            status_item.setForeground(QColor(150, 150, 0))
            self.update_table.setItem(row, 2, status_item)

            remove_btn = QPushButton("移除")
            remove_btn.clicked.connect(lambda _, button=remove_btn: self._remove_task_button(button))
            self.update_table.setCellWidget(row, 3, remove_btn)

        self._log_history(f"已添加 {len(selected_services)} 个更新任务")

    def _remove_task_button(self, button):
        for row in range(self.update_table.rowCount()):
            if self.update_table.cellWidget(row, 3) is button:
                self.update_table.removeRow(row)
                break

    def _remove_update_task(self):
        """移除选中的更新任务"""
        selected_rows = set(item.row() for item in self.update_table.selectedItems())
        for row in sorted(selected_rows, reverse=True):
            self.update_table.removeRow(row)

    def _execute_batch_update(self):
        updates = [(self.update_table.item(row, 0).text(), self.update_table.item(row, 1).data(Qt.UserRole))
                   for row in range(self.update_table.rowCount())]
        if not updates:
            QMessageBox.warning(self, "错误", "没有待更新的任务")
            return
        stop_before = self.stop_before_update_cb.isChecked()
        start_after = self.restart_after_update_cb.isChecked()
        def execute():
            return {name: self.service_manager.deploy_jar(name, path, stop_before, start_after)
                    for name, path in updates}
        results = run_task(self, execute, "正在逐个停止、更新并启动服务，请稍候…")
        if "message" in results and "success" in results:
            QMessageBox.warning(self, "更新失败", results["message"])
            return
        for row in range(self.update_table.rowCount()):
            name = self.update_table.item(row, 0).text()
            result = results[name]
            item = self.update_table.item(row, 2)
            item.setText("完成" if result["success"] else "失败")
            item.setToolTip(result["message"])
            item.setForeground(QColor(0, 150, 0) if result["success"] else QColor(200, 50, 50))
        self.main_window._refresh_services()
        details = "\n".join(f"{name}: {result['message']}" for name, result in results.items())
        QMessageBox.information(self, "批量更新结果", details)

    def _log_history(self, message):
        if hasattr(self.main_window, "statusbar"):
            self.main_window.statusbar.showMessage(message, 5000)
