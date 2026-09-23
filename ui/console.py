"""Shared live console for all three tabs."""
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QFont, QPalette, QTextCursor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
                            QComboBox, QSpinBox, QLabel, QPushButton, QCheckBox, QLineEdit)
from core.log_reader import ConsoleReader, DEFAULT_LOG_LINES, MAX_LOG_LINES


class ConsolePanel(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager, self.service, self.reader, self.reader_key = manager, None, None, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.channel = QComboBox()
        for title, channel in [("控制台 stdout + stderr", "console"), ("标准输出", "out"),
                               ("标准错误（完整）", "err"), ("WinSW 诊断", "wrapper")]:
            self.channel.addItem(title, channel)
        self.channel.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.channel)
        self.encoding = QComboBox()
        self.encoding.addItems(["utf-8", "gb18030"])
        self.encoding.setToolTip("旧 JAR 出现中文乱码时可切换 GB18030")
        self.encoding.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.encoding)
        self.lines = QSpinBox()
        self.lines.setRange(200, MAX_LOG_LINES)
        self.lines.setValue(DEFAULT_LOG_LINES)
        self.lines.setSingleStep(2000)
        self.lines.setSuffix(" 行")
        self.lines.setToolTip("保留的控制台行数；增加后重新读取磁盘历史")
        self.lines.valueChanged.connect(self.reload)
        bar.addWidget(self.lines)
        self.pause = QCheckBox("暂停")
        bar.addWidget(self.pause)
        layout.addLayout(bar)
        self.search = QLineEdit()
        self.search.setPlaceholderText("查找日志（保留全部上下文，回车查找下一处）")
        self.search.returnPressed.connect(self.find_next)
        layout.addWidget(self.search)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFont(QFont("Consolas", 10))
        self.text.setStyleSheet("QPlainTextEdit { background-color:#1e1e1e; color:#d4d4d4; selection-background-color:#264f78; }")
        # Native Windows styles can paint the viewport using Window, not Base.
        viewport = self.text.viewport()
        viewport.setStyleSheet("background-color:#1e1e1e;")
        viewport.setAutoFillBackground(True)
        palette = viewport.palette()
        palette.setColor(QPalette.Window, QColor("#1e1e1e"))
        palette.setColor(QPalette.Base, QColor("#1e1e1e"))
        viewport.setPalette(palette)
        layout.addWidget(self.text, 1)
        actions = QHBoxLayout()
        for title, action in [("刷新历史", self.reload), ("回到最新", self.follow), ("清屏", self.clear)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            actions.addWidget(button)
        self.info = QLabel("请选择服务")
        actions.addWidget(self.info, 1)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def set_service(self, service):
        if service != self.service:
            self.service = service
            self.reload()
        elif service and self.reader_key and self.reader_key[0] != self.manager.apps_dir:
            self.reload()

    def set_channel(self, channel):
        self.channel.setCurrentIndex(self.channel.findData(channel))
        self.refresh()

    def reload(self, *_):
        self.reader, self.reader_key = None, None
        self.text.clear()
        self.refresh()

    def tick(self):
        if self.isVisible() and not self.pause.isChecked():
            self.refresh()

    def refresh(self):
        if not self.service:
            self.text.clear()
            self.info.setText("请选择服务")
            return
        try:
            key = (self.manager.apps_dir, self.service, self.channel.currentData(), self.lines.value(), self.encoding.currentText())
            if self.reader is None or self.reader_key != key:
                self.reader = ConsoleReader(self.manager, self.service, key[2], key[3], key[4])
                self.reader_key = key
                self.text.document().setMaximumBlockCount(key[3])
            content = self.reader.poll()
            self.render(content)
            self.info.setText("实时输出 · 向上滚动可查看历史" if content else "等待应用输出；启动失败可查看 WinSW 诊断")
        except Exception as exc:
            self.info.setText(f"日志读取失败: {exc}")

    def render(self, content):
        old = self.text.toPlainText()
        if old == content:
            return
        sb = self.text.verticalScrollBar()
        position, follow = sb.value(), sb.value() >= sb.maximum() - 2
        if content.startswith(old):
            cursor = QTextCursor(self.text.document())
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(content[len(old):])
        else:
            self.text.setPlainText(content)
        sb.setValue(sb.maximum() if follow else position)

    def follow(self):
        self.pause.setChecked(False)
        self.refresh()
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def find_next(self):
        if self.search.text() and not self.text.find(self.search.text()):
            self.text.moveCursor(QTextCursor.Start)
            self.text.find(self.search.text())

    def clear(self):
        try:
            if self.reader:
                self.reader.clear()
            self.text.clear()
        except OSError as exc:
            self.info.setText(f"清屏失败: {exc}")
