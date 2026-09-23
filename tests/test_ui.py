import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAbstractItemView
from core.config_manager import ConfigManager
from core.service_manager import ServiceManager
from ui.main_window import MainWindow
from ui.worker import run_task


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ServiceManager(self.tmp.name)
        self.states = {"alpha": "StartPending", "beta": "Running"}
        for name in self.states:
            folder = Path(self.tmp.name, name)
            folder.mkdir()
            (folder / f"{name}.xml").write_text(f'<service><id>{name}</id><name>{name}</name></service>')
            (folder / f"{name}.out.log").write_text("Spring Boot\nStarted application\n")
        self.manager.get_service_status = lambda name: self.states.get(name, "Not Found")
        config = Mock()
        config.get_apps_dir.return_value = self.tmp.name
        config.is_winsw_configured.return_value = False
        config.get_jdk_path.return_value = ""
        with patch("ui.main_window.ConfigManager", return_value=config), \
             patch("ui.main_window.ServiceManager", return_value=self.manager), \
             patch("ui.main_window.WinSWDownloader"):
            self.window = MainWindow()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_pending_refreshes_when_checkbox_is_off(self):
        tab = self.window.service_tab
        tab._select_service_by_name("alpha")
        tab.auto_refresh_cb.setChecked(False)
        self.states["alpha"] = "Running"
        tab._auto_tick()
        self.assertEqual(tab.service_table.item(0, 2).text(), "Running")
        self.assertIn("Running", tab.status_pill.text())
        self.assertTrue(tab.stop_btn.isEnabled())
        self.assertEqual(tab._get_selected_service_name(), "alpha")

    def test_refresh_preserves_identity_when_rows_shift(self):
        tab = self.window.service_tab
        tab._select_service_by_name("beta")
        Path(self.tmp.name, "alpha", "alpha.xml").unlink()
        tab.refresh_services()
        self.assertEqual(tab._get_selected_service_name(), "beta")
        self.assertEqual(tab.service_table.editTriggers(), QAbstractItemView.NoEditTriggers)

    def test_deleted_selection_clears_console(self):
        tab = self.window.service_tab
        tab._select_service_by_name("alpha")
        Path(self.tmp.name, "alpha", "alpha.xml").unlink()
        tab.refresh_services()
        self.assertIsNone(tab._get_selected_service_name())
        self.assertIsNone(tab.console.service)

    def test_console_appends_and_pause_is_effective(self):
        console = self.window.service_tab.console
        console.set_service("alpha")
        source = Path(self.tmp.name, "alpha", "alpha.out.log")
        with source.open("a") as stream:
            stream.write("next\n")
        console.pause.setChecked(True)
        console.tick()
        self.assertNotIn("next", console.text.toPlainText())
        console.pause.setChecked(False)
        console.tick()
        self.assertIn("next", console.text.toPlainText())

    def test_background_task_keeps_event_loop_alive(self):
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        result = run_task(self.window, lambda: (time.sleep(.12) or {"success": True}), "test")
        timer.stop()
        self.assertTrue(result["success"])
        self.assertGreater(len(ticks), 2)
        self.assertFalse(self.window._operation_active)

    def test_upload_keeps_absolute_source_and_remove_targets_current_row(self):
        tab = self.window.upload_tab
        for i, name in enumerate(("alpha", "beta")):
            tab.service_list.clearSelection()
            tab.service_list.item(i).setSelected(True)
            folder = Path(self.tmp.name, f"source{i}")
            folder.mkdir()
            source = folder / "same.jar"
            source.write_bytes(b"jar")
            tab.selected_jar_files = [str(source)]
            tab._add_update_task()
        self.assertNotEqual(tab.update_table.item(0, 1).data(Qt.UserRole), tab.update_table.item(1, 1).data(Qt.UserRole))
        second = tab.update_table.cellWidget(1, 3)
        tab.update_table.removeRow(0)
        second.click()
        self.assertEqual(tab.update_table.rowCount(), 0)

    def test_all_tabs_share_directory_change(self):
        new = Path(self.tmp.name, "new-root")
        self.manager.set_apps_dir(str(new))
        self.window._refresh_services()
        for tab in (self.window.service_tab, self.window.upload_tab, self.window.log_tab):
            self.assertIs(tab.service_manager, self.manager)
        self.assertEqual(self.window.log_tab.service_list.count(), 0)
        self.assertEqual(self.window.upload_tab.service_list.count(), 0)

    def test_unavailable_service_root_keeps_lists_interactive(self):
        tab = self.window.upload_tab
        with patch.object(self.manager, 'get_all_services', side_effect=PermissionError('offline')):
            tab._refresh_service_list()
            self.window.log_tab.refresh_service_list()
        self.assertFalse(tab.service_list.signalsBlocked())
        self.assertEqual(tab.service_list.count(), 2)
        self.assertIn('offline', self.window.log_tab.status.text())

    def test_config_dialog_rejects_file_as_root_without_partial_save(self):
        from ui.main_window import WinswConfigDialog
        config = Mock()
        config.get_winsw_path.return_value = ''
        config.get_apps_dir.return_value = ''
        config.get_jdk_path.return_value = ''
        dialog = WinswConfigDialog(config, self.window)
        source = Path(self.tmp.name, 'a-file')
        source.write_text('not a directory')
        dialog.apps_dir_input.setText(str(source))
        with patch('ui.main_window.QMessageBox.warning') as warning:
            dialog._save_and_close()
            warning.assert_called_once()
        config.update.assert_not_called()
        self.assertEqual(dialog.result(), 0)
        dialog.deleteLater()

    def test_config_dialog_can_restore_default_directory(self):
        from ui.main_window import WinswConfigDialog
        config = Mock()
        config.get_winsw_path.return_value = ''
        config.get_apps_dir.return_value = 'old-root'
        config.get_jdk_path.return_value = ''
        dialog = WinswConfigDialog(config, self.window)
        dialog.apps_dir_input.clear()
        dialog._save_and_close()
        config.update.assert_called_once_with(winsw_path='', apps_dir='', jdk_path='')
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
