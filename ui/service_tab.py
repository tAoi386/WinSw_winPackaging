"""
服务管理标签页
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QSpinBox, QComboBox, QTextEdit, QSplitter,
    QMessageBox, QHeaderView, QAbstractItemView, QLabel,
    QCheckBox, QProgressDialog
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from core.service_manager import ServiceInfo
from ui.console import ConsolePanel
from ui.worker import run_task


class ServiceTab(QWidget):
    """服务管理标签页"""

    status_changed = pyqtSignal()

    def __init__(self, service_manager, main_window):
        super().__init__()
        self.service_manager = service_manager
        self.main_window = main_window
        self.auto_refresh_timer = None
        self._init_ui()
        self.refresh_services()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        left_layout.addWidget(self._create_service_list_group())
        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        right_layout.addWidget(self._create_create_service_group())
        right_layout.addWidget(self._create_log_viewer_group())

        splitter.addWidget(right_widget)
        splitter.setSizes([500, 700])

        self._setup_auto_refresh()

    def _create_service_list_group(self) -> QGroupBox:
        """服务列表组"""
        group = QGroupBox("已部署服务")
        layout = QVBoxLayout(group)

        btn_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_services)
        btn_layout.addWidget(self.refresh_btn)

        self.start_btn = QPushButton("启动")
        self.start_btn.clicked.connect(self._start_selected_service)
        self.start_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop_selected_service)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        self.restart_btn = QPushButton("重启")
        self.restart_btn.clicked.connect(self._restart_selected_service)
        self.restart_btn.setEnabled(False)
        btn_layout.addWidget(self.restart_btn)

        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._delete_selected_service)
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)

        self.upgrade_xml_btn = QPushButton("更新XML配置")
        self.upgrade_xml_btn.setToolTip(
            "重新生成WinSW XML（日志路径等），保持服务运行参数不变"
        )
        self.upgrade_xml_btn.clicked.connect(self._upgrade_selected_xml)
        self.upgrade_xml_btn.setEnabled(False)
        btn_layout.addWidget(self.upgrade_xml_btn)

        layout.addLayout(btn_layout)

        self.service_table = QTableWidget()
        self.service_table.setColumnCount(4)
        self.service_table.setHorizontalHeaderLabels(["服务ID", "显示名称", "状态", "目录"])
        self.service_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.service_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.service_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.service_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.service_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.service_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.service_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.service_table.verticalHeader().setVisible(False)
        self.service_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.service_table.itemDoubleClicked.connect(self._on_service_double_clicked)

        layout.addWidget(self.service_table)

        auto_layout = QHBoxLayout()
        self.auto_refresh_cb = QCheckBox("自动刷新 (2秒；过渡状态始终跟踪)")
        self.auto_refresh_cb.setChecked(True)
        self.auto_refresh_cb.stateChanged.connect(self._toggle_auto_refresh)
        auto_layout.addWidget(self.auto_refresh_cb)
        auto_layout.addStretch()
        layout.addLayout(auto_layout)

        return group

    def _create_create_service_group(self) -> QGroupBox:
        """创建服务组"""
        group = QGroupBox("创建新服务")
        layout = QFormLayout(group)

        self.service_id_input = QLineEdit()
        self.service_id_input.setPlaceholderText("如: myapp")
        layout.addRow("服务ID:", self.service_id_input)

        self.display_name_input = QLineEdit()
        self.display_name_input.setPlaceholderText("如: My Application")
        layout.addRow("显示名称:", self.display_name_input)

        self.jar_path_input = QLineEdit()
        self.jar_path_input.setPlaceholderText("选择JAR文件...")
        jar_btn = QPushButton("选择...")
        jar_btn.clicked.connect(self._select_jar_file)
        jar_layout = QHBoxLayout()
        jar_layout.addWidget(self.jar_path_input)
        jar_layout.addWidget(jar_btn)
        layout.addRow("JAR文件:", jar_layout)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        layout.addRow("端口:", self.port_spin)

        self.jvm_memory_combo = QComboBox()
        self.jvm_memory_combo.addItems(["256m", "512m", "1g", "2g", "4g"])
        self.jvm_memory_combo.setCurrentText("512m")
        layout.addRow("JVM内存:", self.jvm_memory_combo)

        self.create_btn = QPushButton("创建服务")
        self.create_btn.clicked.connect(self._create_service)
        layout.addRow("", self.create_btn)

        # 选中服务后，显示实时状态（颜色徽标）
        status_label = QLabel("（未选择）")
        status_label.setStyleSheet(
            "QLabel { background-color: #3a3a3a; color: #bbbbbb; "
            "padding: 2px 8px; border-radius: 4px; font-weight: bold; }"
        )
        self.status_pill = status_label
        layout.addRow("选中服务状态:", status_label)

        return group

    def _create_log_viewer_group(self) -> QGroupBox:
        """日志查看器组"""
        group = QGroupBox("日志查看")
        layout = QVBoxLayout(group)

        btn_layout = QHBoxLayout()

        self.log_btn = QPushButton("查看日志")
        self.log_btn.clicked.connect(self._view_logs)
        self.log_btn.setEnabled(False)
        btn_layout.addWidget(self.log_btn)

        self.err_log_btn = QPushButton("错误日志")
        self.err_log_btn.clicked.connect(self._view_err_logs)
        self.err_log_btn.setEnabled(False)
        btn_layout.addWidget(self.err_log_btn)

        self.open_folder_btn = QPushButton("打开目录")
        self.open_folder_btn.clicked.connect(self._open_service_folder)
        self.open_folder_btn.setEnabled(False)
        btn_layout.addWidget(self.open_folder_btn)

        self.clear_log_btn = QPushButton("清空")
        self.clear_log_btn.clicked.connect(self._clear_logs)
        btn_layout.addWidget(self.clear_log_btn)

        layout.addLayout(btn_layout)

        self.console = ConsolePanel(self.service_manager)
        self.log_text = self.console.text
        layout.addWidget(self.console)

        return group

    def _setup_auto_refresh(self):
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self._auto_tick)
        self.auto_refresh_timer.start(2000)

    def _toggle_auto_refresh(self, state):
        # Pending states must keep updating even when normal refresh is disabled.
        pass

    def _auto_tick(self):
        pending = any(self._is_transitional(self.service_table.item(row, 2).text())
                      for row in range(self.service_table.rowCount()) if self.service_table.item(row, 2))
        if self.auto_refresh_cb.isChecked() or pending or getattr(self.window(), '_operation_active', False):
            self.refresh_services()

    def refresh_services(self):
        """刷新服务列表"""
        try:
            services = self.service_manager.get_all_services()
        except Exception as e:
            print(f"获取服务列表失败: {e}")
            return

        selected_name = self._get_selected_service_name()
        previous_names = tuple(self.service_table.item(r, 0).text() for r in range(self.service_table.rowCount()) if self.service_table.item(r, 0))
        self.service_table.blockSignals(True)
        self.service_table.clearSelection()
        self.service_table.setCurrentCell(-1, -1)
        self.service_table.setRowCount(len(services))

        for i, service in enumerate(services):
            self.service_table.setItem(i, 0, QTableWidgetItem(service.name))
            self.service_table.setItem(i, 1, QTableWidgetItem(service.display_name))

            status_item = QTableWidgetItem(service.status)
            if service.status == "Running":
                status_item.setForeground(QColor(0, 150, 0))
            elif service.status == "Stopped":
                status_item.setForeground(QColor(200, 50, 50))
            else:
                status_item.setForeground(QColor(150, 150, 0))

            self.service_table.setItem(i, 2, status_item)

            dir_item = QTableWidgetItem(service.exe_path)
            dir_item.setForeground(QColor(80, 80, 80))
            self.service_table.setItem(i, 3, dir_item)

        if selected_name:
            self._select_service_by_name(selected_name)
        self.service_table.blockSignals(False)
        if previous_names != tuple(s.name for s in services) and hasattr(self.main_window, "notify_services_changed"):
            self.main_window.notify_services_changed()

        # 刷新后立即根据当前选中行的实时状态更新按钮可用性
        self._on_selection_changed()

    def _on_selection_changed(self):
        """选中项改变 - 根据当前服务状态启用/禁用按钮"""
        selected = self.service_table.selectedItems()
        has_selection = len(selected) > 0

        if not has_selection:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.restart_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.log_btn.setEnabled(False)
            self.err_log_btn.setEnabled(False)
            self.open_folder_btn.setEnabled(False)
            self.upgrade_xml_btn.setEnabled(False)
            self.clear_log_btn.setEnabled(False)
            self.status_pill.setText("（未选择）")
            self.console.set_service(None)
            return

        # 获取选中行的服务名，再查实时状态
        row = self.service_table.currentRow()
        if row < 0:
            return
        service_name = self.service_table.item(row, 0).text()
        status_item = self.service_table.item(row, 2)
        cur_status = status_item.text() if status_item else "Unknown"
        is_transitional = self._is_transitional(cur_status)
        is_running = "RUNNING" in cur_status.upper() and not is_transitional
        is_stopped = ("STOPPED" in cur_status.upper() or "NOT FOUND" in cur_status.upper()) and not is_transitional
        not_found = "NOT FOUND" in cur_status.upper()

        # 选中服务后，右侧日志区自动加载最新 SpringBoot 日志
        self._auto_refresh_log()

        # 按状态启用/禁用按钮：
        #   - Running          → 停止 / 重启 / 删除 / 更新XML / 查看日志
        #   - Stopped          → 启动 / 删除 / 更新XML / 查看日志
        #   - Not Found        → 启动（如果服务目录还在） / 删除 / 更新XML / 查看日志
        #   - Start/Stop/Pause Pending → 仅保留删除，全部禁用
        can_act = not is_transitional
        self.start_btn.setEnabled(cur_status == "Stopped" and can_act)
        self.stop_btn.setEnabled(is_running and can_act)
        self.restart_btn.setEnabled(is_running and can_act)
        self.delete_btn.setEnabled(can_act)
        self.log_btn.setEnabled(has_selection)
        self.err_log_btn.setEnabled(has_selection)
        self.open_folder_btn.setEnabled(has_selection)
        self.clear_log_btn.setEnabled(has_selection and can_act)
        self.upgrade_xml_btn.setEnabled(can_act)
        # 状态徽标
        self._set_status_pill(cur_status, not_found)
        # 缓存，供自动刷新使用
        self._last_selected_service = service_name
        self._last_status = cur_status

    @staticmethod
    def _is_transitional(status: str) -> bool:
        """过渡态：服务正在切换状态（不可执行新的启停操作）"""
        if not status:
            return False
        u = status.upper()
        # Windows sc.exe 状态字段：START_PENDING / STOP_PENDING / PAUSE_PENDING / PAUSED / CONTINUE_PENDING
        if "PENDING" in u:
            return True
        if u in ("STARTING", "STOPPING", "PAUSING", "CONTINUING"):
            return True
        return False

    def _set_status_pill(self, status: str, not_found: bool):
        """在状态栏上同步显示选中服务的实时状态（颜色徽标）"""
        if not hasattr(self, "status_pill"):
            return
        u = (status or "").upper()
        if "RUNNING" in u and "PENDING" not in u:
            bg, fg, icon = "#1a5c1a", "#6ddf6d", "●"
        elif "STOP" in u and "PENDING" not in u:
            bg, fg, icon = "#5c1a1a", "#df6d6d", "■"
        elif "PENDING" in u or "PAUSE" in u:
            bg, fg, icon = "#2a2a1a", "#dfdd6d", "◆"
        elif not_found:
            bg, fg, icon = "#3a3a3a", "#bbbbbb", "○"
        else:
            bg, fg, icon = "#3a3a3a", "#bbbbbb", "○"
        self.status_pill.setStyleSheet(
            f"QLabel {{ background-color: {bg}; color: {fg}; "
            f"padding: 2px 8px; border-radius: 4px; font-weight: bold; }}"
        )
        self.status_pill.setText(f"{icon} {status}")

    def _on_service_double_clicked(self, item):
        """双击服务项"""
        self._view_logs()

    def _get_selected_service_name(self) -> str:
        """获取选中的服务名"""
        row = self.service_table.currentRow()
        if row >= 0 and self.service_table.item(row, 0):
            return self.service_table.item(row, 0).text()
        return None

    def _get_selected_service_dir(self) -> str:
        """获取选中的服务目录"""
        row = self.service_table.currentRow()
        if row >= 0 and self.service_table.item(row, 3):
            return self.service_table.item(row, 3).text()
        return None

    def _start_selected_service(self):
        """启动选中服务"""
        service_name = self._get_selected_service_name()
        if not service_name:
            return

        result = run_task(self, lambda: self.service_manager.start_service(service_name), "正在处理服务 " + service_name)
        self._show_result(result)
        self.refresh_services()
        self._on_selection_changed()

    def _stop_selected_service(self):
        """停止选中服务"""
        service_name = self._get_selected_service_name()
        if not service_name:
            return

        result = run_task(self, lambda: self.service_manager.stop_service(service_name), "正在处理服务 " + service_name)
        self._show_result(result)
        self.refresh_services()
        self._on_selection_changed()

    def _restart_selected_service(self):
        """重启选中服务"""
        service_name = self._get_selected_service_name()
        if not service_name:
            return

        result = run_task(self, lambda: self.service_manager.restart_service(service_name), "正在处理服务 " + service_name)
        self._show_result(result)
        self.refresh_services()
        self._on_selection_changed()

    def _delete_selected_service(self):
        """删除选中服务"""
        service_name = self._get_selected_service_name()
        if not service_name:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除服务 '{service_name}' 吗?\n这将停止并卸载服务。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            result = run_task(self, lambda: self.service_manager.delete_service(service_name), "正在处理服务 " + service_name)
            self._show_result(result)
            self.refresh_services()
            self._on_selection_changed()

    def _upgrade_selected_xml(self):
        """为已部署服务重新生成XML（含新日志路径），可选自动重启"""
        service_name = self._get_selected_service_name()
        if not service_name:
            return

        reply = QMessageBox.question(
            self,
            "更新XML配置",
            f"确定要为服务 '{service_name}' 重新生成 WinSW XML 吗？\n\n"
            "将保留 JDK、启动参数、环境变量及自定义配置，仅调整日志配置；\n"
            "原配置会备份为 .bak；若服务正在运行会自动重启以装载新配置。\n\n"
            "是否自动重启服务？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Cancel:
            return
        restart = (reply == QMessageBox.Yes)

        result = run_task(self, lambda: self.service_manager.upgrade_service_xml(service_name, restart=restart), "正在更新日志配置…")
        self._show_result(result)
        self.refresh_services()

    def _select_jar_file(self):
        """选择JAR文件"""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择JAR文件", "", "JAR Files (*.jar)"
        )
        if file_path:
            self.jar_path_input.setText(file_path)

    def _create_service(self):
        """创建服务"""
        if not self.main_window.is_winsw_ready():
            QMessageBox.warning(self, "错误", "请先配置 WinSW 路径!\n点击菜单'文件 -> WinSW 配置'进行配置。")
            return

        service_id = self.service_id_input.text().strip()
        display_name = self.display_name_input.text().strip()
        jar_path = self.jar_path_input.text().strip()

        if not service_id:
            QMessageBox.warning(self, "输入错误", "请输入服务ID")
            return

        if not display_name:
            QMessageBox.warning(self, "输入错误", "请输入显示名称")
            return

        if not jar_path:
            QMessageBox.warning(self, "输入错误", "请选择JAR文件")
            return

        winsw_path = self.main_window.get_winsw_path()

        port, memory = self.port_spin.value(), self.jvm_memory_combo.currentText()
        jdk = self.main_window.get_jdk_path()
        result = run_task(self, lambda: self.service_manager.create_service(
            service_id, display_name, jar_path, winsw_path, port, memory, jdk), "正在创建服务…")

        self._show_result(result)

        if result["success"]:
            self.service_id_input.clear()
            self.display_name_input.clear()
            self.jar_path_input.clear()
            self.port_spin.setValue(8080)
            self.jvm_memory_combo.setCurrentText("512m")
            self.refresh_services()
            # 自动选中刚创建的服务行
            self._select_service_by_name(service_id)
            self._on_selection_changed()

    def _select_service_by_name(self, name: str):
        """按服务名选中表格行"""
        for row in range(self.service_table.rowCount()):
            item = self.service_table.item(row, 0)
            if item and item.text() == name:
                self.service_table.selectRow(row)
                break

    def _view_logs(self):
        self.console.set_service(self._get_selected_service_name())
        self.console.set_channel("console")

    def _view_err_logs(self):
        self.console.set_service(self._get_selected_service_name())
        self.console.set_channel("err")

    def _auto_refresh_log(self):
        self.console.set_service(self._get_selected_service_name())

    def _open_service_folder(self):
        import os
        folder = self._get_selected_service_dir()
        if folder:
            try:
                os.startfile(folder)
            except OSError as exc:
                QMessageBox.warning(self, "打开失败", str(exc))

    def _clear_logs(self):
        self.console.clear()

    def _show_result(self, result):
        """显示结果"""
        if result["success"]:
            QMessageBox.information(self, "操作成功", result["message"])
        else:
            QMessageBox.critical(self, "操作失败", result["message"])
