"""麦克风、识别语言和引擎设置；凭据只保存到忽略提交的本机配置。"""
from copy import deepcopy
import os
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QCheckBox, QPlainTextEdit
import yaml
from src.core.app_config import PROJECT_ROOT, read_yaml
from src.core.stt_manager import validate_stt
from src.core.stt_hotwords import hotwords


class MicrophoneDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("麦克风识别设置")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.device = QComboBox()
        self.device.addItem("跟随 Windows 默认输入", "")
        for device in owner.stt.devices():
            self.device.addItem(device["name"], device["id"])
        self.language = QComboBox()
        for name, code in (("中文", "zh"), ("日本語", "ja"), ("自动检测", "auto")):
            self.language.addItem(name, code)
        self.provider = QComboBox()
        for name, code in (("自动：中文优先智谱，日语本地", "auto"), ("本地 Whisper（离线）", "whisper"), ("智谱 GLM-ASR（联网）", "zhipu")):
            self.provider.addItem(name, code)
        config = owner.stt.config
        for widget, key, default in ((self.device, "device", ""), (self.language, "language", "zh"), (self.provider, "provider", "auto")):
            value = config.get(key, default)
            index = widget.findData(value)
            if index < 0:
                widget.addItem("原设备（当前未连接）", value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        self.key = QLineEdit(config.get("zhipu", {}).get("api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("可留空使用本地；也支持 ZHIPU_API_KEY 环境变量")
        self.model_path = QLineEdit(config.get("model_path", ""))
        self.model_path.setPlaceholderText("留空使用已缓存的 faster-whisper-base")
        self.silence = QSpinBox()
        self.silence.setRange(300, 2000)
        self.silence.setSuffix(" ms")
        self.silence.setValue(config.get("silence_ms", 700))
        self.energy = QSpinBox()
        self.energy.setRange(50, 5000)
        self.energy.setValue(config.get("energy_threshold", 250))
        self.fallback = QCheckBox("智谱失败时使用本地 Whisper")
        self.fallback.setChecked(config.get("fallback", True))
        self.hotwords = QPlainTextEdit("\n".join(config["hotwords"]))
        self.hotwords.setMaximumHeight(110)
        self.hotwords.setPlaceholderText("每行一个词；清空可关闭热词提示。最多 100 项，每项 40 字。")
        for name, widget in (("输入设备", self.device), ("识别语言", self.language), ("识别引擎", self.provider), ("智谱 API Key", self.key), ("本地模型目录", self.model_path), ("说完后的停顿", self.silence), ("底噪门限", self.energy), ("", self.fallback)):
            form.addRow(name, widget)
        form.addRow("识别热词", self.hotwords)
        note = QLabel("开麦后，说完停顿即可发送到当前对话后端。\n识别语言与心的回复语言分别设置。智谱识别会上传当前短句；\n本地 Whisper 不上传音频。心回复与朗读期间暂停收音。")
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        candidate = deepcopy(self.owner.stt.config)
        candidate.update(device=self.device.currentData(), language=self.language.currentData(),
            provider=self.provider.currentData(), model_path=self.model_path.text().strip(),
            silence_ms=self.silence.value(), energy_threshold=self.energy.value(), fallback=self.fallback.isChecked(),
            hotwords=[line.strip() for line in self.hotwords.toPlainText().splitlines() if line.strip()],
            zhipu={"api_key": self.key.text().strip()})
        try:
            validate_stt(candidate)
            candidate["hotwords"] = hotwords(candidate)
            path = PROJECT_ROOT / "config.local.yaml"
            data = read_yaml(path) if path.exists() else {}
            data["stt"] = candidate
            temp = path.with_suffix(".tmp")
            temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            os.replace(temp, path)
            self.owner.stt.configure(**candidate)
            self.owner.config["stt"] = deepcopy(candidate)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
