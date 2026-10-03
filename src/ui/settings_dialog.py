"""统一设置与首次引导共用表单；高级参数折叠在最后一页。"""
from copy import deepcopy
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from src.core.app_config import project_path
from src.core.speech_recognizer import SpeechRecognizer
from src.core.user_settings import save_settings
from src.core.chat_preferences import REPLY_LENGTHS, SPEECH_SCOPES


class SettingsDialog(QDialog):
    def __init__(self, owner, *, first_run=False, page=0):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner, self.first_run = owner, first_run
        self.setWindowTitle("欢迎与心相伴" if first_run else "心的设置")
        self.resize(640, 680)
        self.fields = {}
        self.initial = deepcopy(owner.config)
        self.initial["chat"] = deepcopy(owner.chat.config)
        self.initial["chat"]["provider"] = owner.chat.provider
        self.initial["voice"].update(enabled=owner.tts.enabled, language=owner.tts.language,
            provider=owner.tts.engine, auto_translate=owner.tts.auto_translate,
            fallback=owner.tts.fallback, volume=owner.tts.volume)
        self.initial["stt"] = deepcopy(owner.stt.config)
        self.initial["sprite"]["window"].update(always_on_top=owner._always_on_top,
                                                opacity=owner.windowOpacity())
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        if first_run:
            welcome = QWidget()
            intro = QVBoxLayout(welcome)
            intro.addWidget(self.note("御者，欢迎。先选择使用方式，接下来可设置语言、语音和模型。\n已有配置会保留；没有 Key 也能使用基础陪伴。"))
            for title, provider in (("连接已有 Hermes", "hermes"), ("使用 DeepSeek 直连", "deepseek"), ("先使用基础陪伴", None)):
                button = QPushButton(title)
                button.clicked.connect(lambda checked=False, key=provider: self.choose_start(key))
                intro.addWidget(button)
            intro.addWidget(self.note("设置过程不会开启麦克风。之后随时从右键或托盘菜单 → 设置修改。"))
            intro.addStretch()
            self.tabs.addTab(welcome, "欢迎")
        self.connection_page()
        self.voice_page()
        self.microphone_page()
        self.resources_page()
        self.appearance_page()
        self.advanced_page()
        # 首次引导只走到资源页；外观与内部端口留在之后的普通设置。
        self.last_page = 4 if first_run else self.tabs.count() - 1
        self.error = self.note("")
        self.error.setStyleSheet("color: #bd3546;")
        layout.addWidget(self.error)
        refresh = QPushButton("检查本地配置（不联网）")
        refresh.clicked.connect(self.refresh_status)
        layout.addWidget(refresh)
        layout.addWidget(self.note("连接、语音、麦克风和外观保存后生效；模型资源及端口修改在重启后生效。密钥仅存于本机配置。"))
        row = QHBoxLayout()
        self.back = QPushButton("上一步")
        self.back.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tabs.currentIndex() - 1))
        row.addWidget(self.back)
        row.addStretch()
        cancel = QPushButton("稍后设置" if first_run else "取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.next = QPushButton("下一步")
        self.next.clicked.connect(self.advance)
        row.addWidget(self.next)
        self.save_button = QPushButton("完成设置" if first_run else "保存")
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.save_button)
        layout.addLayout(row)
        self.tabs.currentChanged.connect(self.refresh_page)
        if first_run:
            self.tabs.tabBar().hide()
        else:
            self.tabs.setCurrentIndex(page)
        self.refresh_page()

    @staticmethod
    def note(text):
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def page(self, title):
        content = QWidget()
        form = QFormLayout(content)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)
        return form

    def value(self, key, default=""):
        value = self.initial
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def field(self, form, key, title, *, choices=None, check=False, integer=None, decimal=None, browse=None, secret=False):
        value = self.value(key, True if check else "")
        if choices:
            widget = QComboBox()
            for label, code in choices:
                widget.addItem(label, code)
            index = widget.findData(value)
            if index < 0:
                widget.addItem("原设备（未连接）", value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        elif check:
            widget = QCheckBox(title)
            widget.setChecked(value)
        elif integer:
            widget = QSpinBox()
            widget.setRange(*integer)
            widget.setValue(value)
        elif decimal:
            widget = QDoubleSpinBox()
            widget.setRange(*decimal)
            widget.setSingleStep(.05)
            widget.setValue(value)
        else:
            widget = QLineEdit(str(value))
            if secret:
                widget.setEchoMode(QLineEdit.EchoMode.Password)
        self.fields[key] = widget
        if browse:
            line = QWidget()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget)
            button = QPushButton("选择…")
            button.clicked.connect(lambda: self.browse(widget, browse))
            row.addWidget(button)
            form.addRow(title, line)
        else:
            form.addRow("" if check else title, widget)
        return widget

    def browse(self, widget, kind):
        if kind == "directory":
            path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择本地文件", "", kind)
        if path:
            widget.setText(path)
            self.refresh_page()

    def connection_page(self):
        form = self.page("连接")
        self.field(form, "chat.enabled", "启用 AI 对话", check=True)
        self.field(form, "chat.provider", "连接方式", choices=(("Hermes · 本地 Agent", "hermes"), ("DeepSeek · 云端直连", "deepseek"), ("OpenClaw · 预留接口", "openclaw")))
        self.field(form, "chat.hermes.profile", "Hermes Agent 名称")
        self.field(form, "chat.deepseek.api_key", "DeepSeek Key", secret=True).setPlaceholderText("直连聊天及自动翻译共用；支持环境变量")
        self.field(form, "chat.reply_length", "回复长度", choices=tuple((label, key) for key, label in REPLY_LENGTHS.items()))
        self.field(form, "chat.speech_scope", "自动朗读范围", choices=tuple((label, key) for key, label in SPEECH_SCOPES.items()))
        self.field(form, "chat.speech_sentence_count", "前几句", integer=(1, 30))
        self.field(form, "chat.speech_prefix_chars", "前几字（保留完整分段）", integer=(50, 10000))
        form.addRow(self.note("Hermes 默认自动发现本机服务，需先配置心的 Agent。DeepSeek 会发送聊天文字；基础陪伴可关闭 AI 对话。OpenClaw 暂未联调。"))
        self.connection_status = self.note("")
        form.addRow(self.connection_status)

    def voice_page(self):
        form = self.page("语音")
        self.field(form, "voice.enabled", "开启语音", check=True)
        self.field(form, "voice.language", "回复语言", choices=(("中文", "zh"), ("日本語", "ja")))
        self.field(form, "voice.provider", "音色", choices=(("心 · 本地 GPT-SoVITS", "gptsovits"), ("通用女声 · Edge（联网）", "edge")))
        self.field(form, "voice.volume", "音量", decimal=(0, 1))
        self.field(form, "voice.auto_translate", "自动翻译直接朗读的文本（使用 DeepSeek）", check=True)
        self.field(form, "voice.fallback", "合成失败尝试备用音色（可能联网）", check=True)
        form.addRow(self.note("内置固定台词可离线播放；任意新句使用心的音色需要 GPT-SoVITS 和 CUDA 环境。Edge 无需 Key，但会发送待朗读文字，属于通用音色。聊天按回复语言生成，不重复翻译。"))
        self.voice_status = self.note("")
        form.addRow(self.voice_status)

    def microphone_page(self):
        form = self.page("麦克风")
        devices = [("系统默认输入", "")] + [(d["name"], d["id"]) for d in self.owner.stt.devices()]
        self.field(form, "stt.device", "输入设备", choices=devices)
        self.field(form, "stt.language", "识别语言", choices=(("中文", "zh"), ("日本語", "ja"), ("自动检测", "auto")))
        self.field(form, "stt.provider", "识别方式", choices=(("自动选择", "auto"), ("本地 Whisper（离线）", "whisper"), ("智谱（联网）", "zhipu")))
        self.field(form, "stt.zhipu.api_key", "智谱 Key", secret=True).setPlaceholderText("本地识别可留空；支持环境变量")
        self.field(form, "stt.model_path", "Whisper 模型文件夹", browse="directory").setPlaceholderText("留空使用已下载的 base 模型")
        self.field(form, "stt.fallback", "云识别失败时尝试本地 Whisper", check=True)
        words = QPlainTextEdit("\n".join(self.value("stt.hotwords", [])))
        words.setMaximumHeight(100)
        self.fields["stt.hotwords"] = words
        form.addRow("热词（每行一项）", words)
        form.addRow(self.note("保存不会自动开麦，请在右键菜单或聊天窗口主动开启。智谱会上传当前短句；自动模式有 Key 时中文优先云端，日语使用本地。"))
        self.microphone_status = self.note("")
        form.addRow(self.microphone_status)

    def resources_page(self):
        form = self.page("资源")
        for name, label, pattern in (("sprite.model.forms.first", "一阶段模型", "PMX 模型 (*.pmx)"),
            ("sprite.model.forms.second", "二阶段模型", "PMX 模型 (*.pmx)"),
            ("sprite.animation.side_lying", "侧躺动作", "FBX 动作 (*.fbx)"),
            ("sprite.animation.transitions.first", "一阶段过渡校准", "JSON 文件 (*.json)"),
            ("sprite.animation.transitions.second", "二阶段过渡校准", "JSON 文件 (*.json)"),
            ("voice.profiles", "中日音色配置", "JSON 文件 (*.json)")):
            self.field(form, name, label, browse=pattern)
        form.addRow(self.note("选择已有资源即可，不需要在这里训练音色。PMX 与贴图保持原文件夹结构；动作校准需匹配模型。音色配置引用的环境、权重与参考音频也必须存在。资源修改重启后生效。"))
        self.resource_status = self.note("")
        form.addRow(self.resource_status)

    def appearance_page(self):
        form = self.page("外观")
        self.field(form, "sprite.window.always_on_top", "保持置顶", check=True)
        self.field(form, "sprite.window.opacity", "窗口不透明度", decimal=(.1, 1))
        form.addRow(self.note("大头视角、物理、眼神跟随、尺寸和背景仍可在右键菜单快速切换。"))

    def advanced_page(self):
        form = self.page("高级")
        for key, title, browse in (("chat.hermes.home", "Hermes 数据目录", "directory"),
            ("chat.hermes.url", "Hermes 地址（留空自动发现）", None),
            ("chat.hermes.token", "Hermes 会话凭据（通常留空）", None),
            ("chat.deepseek.model", "DeepSeek 模型", None),
            ("chat.openclaw.url", "OpenClaw 地址", None),
            ("chat.openclaw.agent", "OpenClaw Agent", None),
            ("chat.openclaw.token", "OpenClaw 凭据", None)):
            self.field(form, key, title, browse=browse, secret=key.endswith("token"))
        for key, title in (("http.port", "桌面 HTTP 端口"), ("websocket.port", "桌面 WebSocket 端口"), ("voice.port", "本地语音端口")):
            self.field(form, key, title, integer=(1, 65535))
        self.field(form, "stt.silence_ms", "说完后的停顿（毫秒）", integer=(300, 2000))
        self.field(form, "stt.energy_threshold", "底噪门限", integer=(50, 5000))
        form.addRow(self.note("通常无需修改。端口修改需重启，目前不会自动解决占用；本地服务地址只接受 localhost 或回环 IP。"))

    def collect(self):
        changes = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            elif isinstance(widget, QPlainTextEdit):
                value = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
            else:
                value = widget.text().strip()
            # 空的可选资源不新增无效映射；原配置的资源则仍保留。
            if value == "" and key.startswith("sprite."):
                continue
            target = changes
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        model = changes["sprite"].get("model", {})
        old_model = self.initial["sprite"]["model"]
        form = "second" if old_model["path"] == old_model.get("forms", {}).get("second") else "first"
        if model.get("forms", {}).get(form):
            model["path"] = model["forms"][form]
        return changes

    def choose_start(self, provider):
        self.fields["chat.enabled"].setChecked(provider is not None)
        if provider:
            self.fields["chat.provider"].setCurrentIndex(self.fields["chat.provider"].findData(provider))
        else:
            for key in ("voice.enabled", "voice.auto_translate", "voice.fallback"):
                self.fields[key].setChecked(False)
            self.fields["stt.provider"].setCurrentIndex(self.fields["stt.provider"].findData("whisper"))
        self.tabs.setCurrentIndex(1)

    def advance(self):
        self.tabs.setCurrentIndex(min(self.last_page, self.tabs.currentIndex() + 1))

    def refresh_page(self, *_):
        index = self.tabs.currentIndex()
        self.heading.setText((f"第 {index + 1} / {self.last_page + 1} 步 · " if self.first_run else "") + self.tabs.tabText(index))
        self.back.setVisible(self.first_run)
        self.back.setEnabled(index > 0)
        self.next.setVisible(self.first_run and index < self.last_page)
        self.save_button.setVisible(not self.first_run or index == self.last_page)
        self.refresh_status()

    def refresh_status(self):
        data = self.collect()
        chat = data["chat"]
        key = bool(os.environ.get("DEEPSEEK_API_KEY") or chat["deepseek"]["api_key"])
        ledger = project_path(chat["hermes"]["home"]) / "spawn-ledger.json"
        self.connection_status.setText("DeepSeek：" + ("已配置凭据（未发起网络验证）" if key else "未配置 Key") +
            "\nHermes：" + ("发现服务登记（实际连接需启动服务）" if ledger.is_file() else "未发现服务登记，请先打开 Hermes，或填写高级地址"))
        self.voice_status.setText("自动翻译：" + ("凭据已配置" if key else "需要 DeepSeek Key，可关闭") +
            "\n本地音色：" + self.voice_readiness(data["voice"]["profiles"]) +
            ("\n已内置中日固定语音；新句仍需推理环境或 Edge。" if self.owner.tts.provider.presets.available() else ""))
        stt = data["stt"]
        self.microphone_status.setText("当前识别选择：" + ("智谱（上传短句）" if SpeechRecognizer.provider(stt) == "zhipu" else "本地 Whisper") +
            "\n本地组件：" + ("已安装；还需已下载模型" if SpeechRecognizer.local_available() else "未安装本地识别组件"))
        resources = [("一阶段模型", data["sprite"].get("model", {}).get("forms", {}).get("first", "")),
                     ("二阶段模型", data["sprite"].get("model", {}).get("forms", {}).get("second", ""))]
        self.resource_status.setText("\n".join(label + "：" + ("文件存在（重启后加载验证）" if path and project_path(path).is_file() else "未找到，可选择本地文件") for label, path in resources))

    @staticmethod
    def voice_readiness(path):
        try:
            data = json.loads(project_path(path).read_text(encoding="utf8"))
            installation = data["installation"]
            files = [installation[key] for key in ("python", "gptsovits_root", "bert_pretrained_dir", "cnhubert_base_dir")]
            for language in ("zh", "ja"):
                files += [data["profiles"][language][key] for key in ("gpt_weights", "sovits_weights", "reference_audio")]
            if not all(isinstance(value, str) and value and project_path(value).exists() for value in files):
                return "配置引用的环境或音色文件缺失"
            return "配置与资源存在；仍需可用 CUDA 环境，未运行合成验证"
        except (OSError, ValueError, KeyError, TypeError):
            return "未导入有效的中日音色配置"

    def save(self):
        try:
            restart = save_settings(self.owner, self.collect())
        except (OSError, ValueError, KeyError, TypeError):
            # 不回显配置内容或底层路径异常，避免错误提示带出凭据。
            self.error.setText("未能保存，请检查地址格式、必填名称、热词数量与端口是否重复，并确认配置文件可写。")
            return
        self.owner.show_message("设置已保存；资源或端口修改需重启心。" if restart else "设置已保存，御者。", 6000)
        self.accept()
