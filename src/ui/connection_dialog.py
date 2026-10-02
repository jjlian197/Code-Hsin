"""连接设置仅写项目本机覆盖文件，保留其他配置。"""
from copy import deepcopy
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QTabWidget, QVBoxLayout, QWidget
import yaml
from src.core.app_config import project_path, read_yaml, validate_chat_config


class ConnectionDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("心的连接设置")
        self.resize(520, 350)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.fields = {}
        groups = (("hermes", "Hermes · Hsin", (("url", "本地地址（留空自动连接）"), ("home", "Hermes 数据目录"), ("profile", "Agent 配置名称"), ("token", "会话凭据（通常留空）"))),
                  ("openclaw", "OpenClaw", (("url", "本地网关地址"), ("agent", "Agent 名称"), ("token", "网关凭据"))),
                  ("deepseek", "DeepSeek", (("model", "模型"), ("api_key", "API Key"))))
        for backend, title, fields in groups:
            page = QWidget()
            form = QFormLayout(page)
            for key, label in fields:
                field = QLineEdit(owner.chat.config[backend][key])
                if key in ("token", "api_key"):
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                form.addRow(label, field)
                self.fields[backend, key] = field
            tabs.addTab(page, title)
        layout.addWidget(QLabel("默认使用 Hermes 中已配置的心。切换通道请使用右键菜单“对话后端”。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        config = deepcopy(self.owner.chat.config)
        for (backend, key), field in self.fields.items():
            config[backend][key] = field.text().strip()
        config["provider"] = self.owner.chat.provider
        try:
            validate_chat_config(config)
            path = project_path("config.local.yaml")
            local = read_yaml(path) if path.is_file() else {}
            local["chat"] = config
            temp = path.with_suffix(".tmp")
            temp.write_text(yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf8")
            temp.replace(path)
            self.owner.stop_chat()
            self.owner.chat.config = config
            self.owner.config["chat"] = deepcopy(config)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "连接设置", str(exc))
            return
        self.accept()
