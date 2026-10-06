"""角色管理入口：编辑草稿、保存配置、启用已保存角色。"""
from copy import deepcopy
from pathlib import Path

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget)
from src.core.app_config import project_path
from src.core.character_package import load_character_package
from src.core.character_settings import profile_from_config


class CharacterSettingsPage(QScrollArea):
    def __init__(self, owner):
        super().__init__()
        self.owner, self.manager = owner, owner.characters
        self.setWidgetResizable(True)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        self.roles = QComboBox()
        self.roles.setPlaceholderText("新角色草稿 · 未保存")
        layout.addWidget(self.roles)
        row = QHBoxLayout()
        for title, callback in (("新建角色", self.new), ("导入模型角色包…", self.import_package)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        save = QPushButton("保存角色配置")
        save.clicked.connect(self.save)
        row.addWidget(save)
        activate = QPushButton("一键启用已保存角色")
        activate.clicked.connect(self.activate)
        row.addWidget(activate)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        form = QFormLayout()
        layout.addLayout(form)
        self.fields = {}
        self.add(form, "name", "角色名称")
        self.add(form, "package", "模型角色包（空白使用心）", browse="JSON 文件 (*.json)")
        self.persona = QPlainTextEdit()
        self.persona.setMaximumHeight(140)
        form.addRow("人设", self.persona)
        for key, label, choices in (("chat.provider", "聊天后端", (("Hermes", "hermes"), ("DeepSeek", "deepseek"), ("Qwen · Ollama", "ollama"), ("OpenClaw", "openclaw"))),
            ("voice.provider", "TTS引擎", (("GPT-SoVITS", "gptsovits"), ("Qwen", "qwen"), ("Edge 通用音色", "edge"))),
            ("voice.language", "回复语言", (("中文", "zh"), ("日本語", "ja")))):
            self.add(form, key, label, choices=choices)
        self.add(form, "chat.enabled", "启用AI对话", check=True)
        for key, label in (("chat.hermes.profile", "Hermes Agent"), ("chat.openclaw.agent", "OpenClaw Agent"),
                           ("chat.deepseek.model", "DeepSeek 模型"), ("chat.ollama.model", "Ollama 模型")):
            self.add(form, key, label)
        self.add(form, "voice.enabled", "启用语音", check=True)
        self.add(form, "voice.profiles", "中日音色配置（权重、参考音频）", browse="JSON 文件 (*.json)")
        self.add(form, "voice.volume", "音量", volume=True)
        self.add(form, "voice.auto_translate", "直接朗读自动翻译", check=True)
        self.add(form, "voice.fallback", "失败使用备用音色", check=True)
        for key, label in (("python", "Qwen Python"), ("zh_model", "Qwen 中文模型"), ("ja_model", "Qwen 日文模型"), ("gpu", "Qwen 设备")):
            self.add(form, "voice.qwen." + key, label)
        note = QLabel("人设用于 DeepSeek / Ollama；Hermes、OpenClaw 使用所绑定Agent的人设。\n服务地址和密钥沿用连接设置。音色配置引用中日权重、参考音频及台词；导入模型不会自动生成音色。\n保存只保存角色草稿；启用后切换模型、聊天和音色，关闭麦克风，并记住启动角色。聊天记录按角色分开，本轮仅在当前会话保留。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.roles.currentIndexChanged.connect(self.select)
        self.refresh(self.manager.active)

    def add(self, form, key, label, *, choices=None, check=False, volume=False, browse=None):
        if choices:
            widget = QComboBox()
            for text, value in choices:
                widget.addItem(text, value)
        elif check:
            widget = QCheckBox()
        elif volume:
            widget = QDoubleSpinBox()
            widget.setRange(0, 1)
            widget.setSingleStep(.05)
        else:
            widget = QLineEdit()
        self.fields[key] = widget
        if browse:
            line = QWidget()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget)
            button = QPushButton("选择…")
            button.clicked.connect(lambda: self.browse(widget, browse))
            row.addWidget(button)
            form.addRow(label, line)
        else:
            form.addRow(label, widget)

    def browse(self, widget, pattern):
        path, _ = QFileDialog.getOpenFileName(self, "选择角色资源", "", pattern)
        if path:
            widget.setText(path)

    def refresh(self, identity=None):
        self.roles.blockSignals(True)
        self.roles.clear()
        for profile in self.manager.profiles:
            self.roles.addItem(profile["name"] + (" · 当前" if profile["id"] == self.manager.active else ""), profile["id"])
        self.roles.setCurrentIndex(max(0, self.roles.findData(identity)))
        self.roles.blockSignals(False)
        self.select()

    def select(self, *_):
        identity = self.roles.currentData()
        if identity:
            self.load(self.manager.get(identity))

    def load(self, profile):
        self.draft = deepcopy(profile)
        if self.roles.findData(profile["id"]) < 0:
            self.roles.blockSignals(True)
            self.roles.setCurrentIndex(-1)
            self.roles.blockSignals(False)
        self.persona.setPlainText(profile["persona"])
        for key, widget in self.fields.items():
            value = profile
            for part in key.split("."):
                value = value[part]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(value)
            else:
                widget.setText(value)

    def new(self):
        profile = profile_from_config(self.owner.config, name="新角色")
        self.load(profile)
        self.status.setText("新角色草稿；填写名称与人设后保存。")

    def import_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入模型角色包", str(project_path(".runtime/characters")), "角色包 (character.json);;JSON 文件 (*.json)")
        if not path:
            return
        try:
            package = load_character_package(Path(path))
            profile = profile_from_config(self.owner.config, name=package["name"], package=str(package["file"]),
                persona="你是" + package["name"] + "，在用户的桌面上陪伴他。回答自然、适合朗读；不编造未知经历或工具操作。")
            profile["voice"]["enabled"] = False
            profile["voice"]["fallback"] = False
            self.load(profile)
            self.status.setText("模型已检查。请填写人设、绑定后端和对应音色，再保存。")
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText("无法导入，请检查角色包、PMX和贴图资源是否完整。")

    def collect(self):
        profile = deepcopy(self.draft)
        profile["persona"] = self.persona.toPlainText().strip()
        for key, widget in self.fields.items():
            value = widget.currentData() if isinstance(widget, QComboBox) else widget.isChecked() if isinstance(widget, QCheckBox) else widget.value() if isinstance(widget, QDoubleSpinBox) else widget.text().strip()
            target = profile
            parts = key.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        if profile["package"]:
            profile["package"] = str(project_path(profile["package"]))
        return profile

    def save(self):
        try:
            profile = self.collect()
            if profile["package"]:
                load_character_package(project_path(profile["package"]))
            self.manager.save(profile)
            self.refresh(profile["id"])
            self.status.setText("角色配置已保存；点击一键启用即可切换。")
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText("未能保存，请检查角色名称、后端模型、音色路径和资源完整性。")

    def activate(self):
        try:
            profile = self.collect()
            if profile != self.manager.get(profile["id"]):
                self.status.setText("草稿有修改，请先保存角色配置。")
                return
            self.manager.activate(profile["id"])
            self.status.setText("正在启用角色；模型加载成功后应用人设与音色。")
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            self.status.setText("无法启用，请先保存，并确认模型和所选音色资源可用。")
