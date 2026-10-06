"""文字聊天窗口；回复流式显示，后台工作不阻塞拖动和角色动画。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QHBoxLayout, QVBoxLayout
from src.core.chat_backends import PROVIDERS
from src.core.chat_preferences import REPLY_LENGTHS, SPEECH_SCOPES


class ChatDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner = owner
        self.setWindowTitle("和心聊天")
        self.resize(580, 560)
        layout = QVBoxLayout(self)
        self.provider_label = QLabel()
        layout.addWidget(self.provider_label)
        preferences = QHBoxLayout()
        preferences.addWidget(QLabel("回复"))
        self.reply_length = QComboBox()
        for key, label in REPLY_LENGTHS.items():
            self.reply_length.addItem(label, key)
        preferences.addWidget(self.reply_length)
        preferences.addWidget(QLabel("朗读"))
        self.speech_scope = QComboBox()
        for key, label in SPEECH_SCOPES.items():
            self.speech_scope.addItem(label, key)
        preferences.addWidget(self.speech_scope)
        self.scope_amount = QSpinBox()
        preferences.addWidget(self.scope_amount)
        layout.addLayout(preferences)
        self.speech_status = QLabel()
        self.speech_status.setWordWrap(True)
        layout.addWidget(self.speech_status)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        layout.addWidget(self.transcript)
        reading = QHBoxLayout()
        self.read_selected = QPushButton("朗读选中内容")
        self.read_selected.clicked.connect(lambda: self.read_text(self.transcript.textCursor().selectedText().replace("\u2029", "\n")))
        reading.addWidget(self.read_selected)
        self.read_reply = QPushButton("重读最近回复")
        self.read_reply.clicked.connect(lambda: self.read_text(next((text for role, text in reversed(owner.chat.messages) if role == owner.chat.character_name), "")))
        reading.addWidget(self.read_reply)
        reading.addStretch()
        layout.addLayout(reading)
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
        self.microphone_button = QPushButton("开启麦克风")
        self.microphone_button.setCheckable(True)
        self.microphone_button.clicked.connect(owner.toggle_microphone)
        row.addWidget(self.microphone_button)
        layout.addLayout(row)
        self.microphone_status = QLabel()
        layout.addWidget(self.microphone_status)
        owner.stt.changed.connect(self.refresh_microphone)
        owner.chat.changed.connect(self.refresh)
        owner.chat.updated.connect(self.refresh)
        owner.tts.changed.connect(self.refresh)
        owner.reply_bubble.changed.connect(self.refresh)
        self.reply_length.currentIndexChanged.connect(self.configure_preferences)
        self.speech_scope.currentIndexChanged.connect(self.configure_preferences)
        self.scope_amount.valueChanged.connect(self.configure_preferences)
        self.refresh()
        self.refresh_microphone()

    def configure_preferences(self):
        scope = self.speech_scope.currentData()
        settings = {"reply_length": self.reply_length.currentData(), "speech_scope": scope}
        if scope in {"sentences", "prefix"} and scope == self.owner.chat.config["speech_scope"]:
            settings["speech_sentence_count" if scope == "sentences" else "speech_prefix_chars"] = self.scope_amount.value()
        try:
            self.owner.set_chat_preferences(**settings)
        except (ValueError, OSError):
            self.speech_status.setText("未能保存朗读设置，请检查配置文件权限。")

    def read_text(self, text):
        try:
            self.owner.read_chat_text(text)
        except ValueError as error:
            self.speech_status.setText(str(error))

    def refresh_microphone(self):
        state = self.owner.stt.snapshot()
        self.microphone_button.setChecked(state["enabled"])
        self.microphone_button.setText("关闭麦克风" if state["enabled"] else "开启麦克风")
        label = "识别中…" if state["recognizing"] else ("回复期间暂停收音" if state["blocked"] else "正在听你说话")
        self.microphone_status.setText(state["error"] or (label if state["enabled"] else "麦克风已关闭"))

    def send(self):
        try:
            self.owner.send_chat(self.input.text())
            self.input.clear()
        except ValueError as exc:
            self.provider_label.setText(str(exc))

    def refresh(self):
        self.setWindowTitle("和" + self.owner.chat.character_name + "聊天")
        chat = self.owner.chat
        self.provider_label.setText("基础陪伴 · 请在设置中开启 AI 对话" if not chat.config.get("enabled", True)
            else PROVIDERS[chat.provider] + (" · 正在回复…" if chat.busy else ""))
        for widget, key in ((self.reply_length, "reply_length"), (self.speech_scope, "speech_scope")):
            widget.blockSignals(True)
            widget.setCurrentIndex(widget.findData(chat.config[key]))
            widget.blockSignals(False)
        scope = chat.config["speech_scope"]
        self.scope_amount.blockSignals(True)
        self.scope_amount.setVisible(scope in {"sentences", "prefix"})
        self.scope_amount.setRange(1, 30) if scope == "sentences" else self.scope_amount.setRange(50, 10000)
        self.scope_amount.setSuffix(" 句" if scope == "sentences" else " 字")
        self.scope_amount.setValue(chat.config["speech_sentence_count"] if scope == "sentences" else chat.config["speech_prefix_chars"])
        self.scope_amount.blockSignals(False)
        tts = self.owner.tts.snapshot()
        if not tts["enabled"]:
            status = "语音已关闭，可在设置中开启。"
        elif tts["error"]:
            status = "语音失败：" + tts["error"]
        elif tts["playing_segment"]:
            status = f"正在分句朗读 · 第 {tts['playing_segment']} 段：" + tts["playing_text"][:80]
        elif tts["synthesizing"]:
            status = ("正在翻译所选文字…" if tts["stage"] == "translating" else
                      "音色正在后台预热，首句稍后播放…" if tts["warmup"]["state"] == "warming" else "正在合成下一句…")
        elif tts["warmup"]["state"] == "warming":
            status = "心的音色正在后台预热，不会播放声音。"
        elif chat.busy:
            status = "正在接收回复，完整短句到达后开始合成。" if scope != "off" else "只接收文字，不自动朗读。"
        elif chat.speech.limited and scope != "off":
            status = "已到所选朗读范围，全文仍保留；可选中文字继续朗读。"
        else:
            status = "分句朗读 · " + SPEECH_SCOPES[scope] + "；可选中文字重读。"
        self.speech_status.setText(status + ("\n" + chat.warning if chat.warning else ""))
        text = "\n\n".join(f"{role}：{content}" for role, content in chat.messages)
        if chat.partial:
            text += "\n\n" + chat.character_name + "：" + chat.partial
        bar = self.transcript.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.transcript.setPlainText(text)
        if at_end:
            bar.setValue(bar.maximum())
        self.send_button.setEnabled(not chat.busy)
        self.read_selected.setEnabled(not chat.busy and tts["enabled"])
        self.read_reply.setEnabled(not chat.busy and tts["enabled"] and any(role == chat.character_name for role, _ in chat.messages))
        self.stop_button.setEnabled(chat.busy or tts["active"] or self.owner.reply_bubble.active)

    def open_near(self, owner):
        self.move(max(0, owner.x() - self.width() - 12), max(0, owner.y()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
