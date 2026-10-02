"""文字聊天窗口；回复流式显示，后台工作不阻塞拖动和角色动画。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QHBoxLayout, QVBoxLayout
from src.core.chat_backends import PROVIDERS


class ChatDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner = owner
        self.setWindowTitle("和心聊天")
        self.resize(480, 440)
        layout = QVBoxLayout(self)
        self.provider_label = QLabel()
        layout.addWidget(self.provider_label)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        layout.addWidget(self.transcript)
        self.input = QLineEdit()
        self.input.setPlaceholderText("御者，想聊些什么？")
        self.input.setMaxLength(4000)
        self.input.returnPressed.connect(self.send)
        layout.addWidget(self.input)
        row = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.send_button)
        self.stop_button = QPushButton("停止回复")
        self.stop_button.clicked.connect(owner.stop_chat)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        owner.chat.changed.connect(self.refresh)
        owner.chat.updated.connect(self.refresh)
        self.refresh()

    def send(self):
        try:
            self.owner.send_chat(self.input.text())
            self.input.clear()
        except ValueError as exc:
            self.provider_label.setText(str(exc))

    def refresh(self):
        chat = self.owner.chat
        self.provider_label.setText(PROVIDERS[chat.provider] + (" · 正在回复…" if chat.busy else ""))
        text = "\n\n".join(f"{role}：{content}" for role, content in chat.messages)
        if chat.partial:
            text += "\n\n心：" + chat.partial
        bar = self.transcript.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.transcript.setPlainText(text)
        if at_end:
            bar.setValue(bar.maximum())
        self.send_button.setEnabled(not chat.busy)
        self.stop_button.setEnabled(chat.busy)

    def open_near(self, owner):
        self.move(max(0, owner.x() - self.width() - 12), max(0, owner.y()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
