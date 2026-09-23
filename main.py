"""
WinSw_winPackaging - Windows服务可视化部署工具
"""
import sys
import os
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WinSw_winPackaging")
    app.setOrganizationName("WinSW Tools")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
