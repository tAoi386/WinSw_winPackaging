"""Run slow operations off the Qt thread while keeping timers and painting alive."""
from PyQt5.QtCore import QThread, QTimer, Qt
from PyQt5.QtWidgets import QProgressDialog


class TaskThread(QThread):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.result = None

    def run(self):
        try:
            self.result = self.task()
        except Exception as exc:
            self.result = {"success": False, "message": str(exc)}


class BusyDialog(QProgressDialog):
    def reject(self):
        pass  # A service operation cannot safely be cancelled halfway through.

    def closeEvent(self, event):
        event.ignore()


def run_task(parent, task, message="正在执行，请稍候…"):
    window = parent.window()
    if getattr(window, "_operation_active", False):
        return {"success": False, "message": "已有操作正在执行"}
    window._operation_active = True
    dialog = BusyDialog(message, "", 0, 0, parent)
    dialog.setCancelButton(None)
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowCloseButtonHint)
    thread = TaskThread(task, dialog)
    thread.finished.connect(dialog.accept)
    try:
        QTimer.singleShot(0, thread.start)
        dialog.exec_()
        thread.wait()
        return thread.result
    finally:
        window._operation_active = False
        dialog.deleteLater()
