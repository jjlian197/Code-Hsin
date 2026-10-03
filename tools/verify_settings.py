"""原生首次引导与设置窗口验收：缺模型可进入、取消/保存/重开，不联网开麦。"""
from copy import deepcopy
import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
import yaml
from src.core.app_config import DEFAULT_CONFIG, load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from src.core.user_settings import needs_setup


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_settings"])
    app.setQuitOnLastWindowClosed(False)
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    root = Path(temp.name)
    config = deepcopy(DEFAULT_CONFIG)
    config["runtime"]["directory"] = str(root / "runtime")
    config["voice"]["profiles"] = str(root / "missing-voice.json")
    config["sprite"]["model"]["path"] = str(root / "missing.pmx")
    source = root / "config.yaml"
    source.write_text(yaml.safe_dump(config), encoding="utf8")
    window = HsinSpriteWindow(load_config(source))
    window.show_sprite()
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    def capture(name):
        path = project_path(f".runtime/settings-{name}.png")
        dialog = window.settings_dialog
        assert dialog.isVisible()
        assert dialog.width() <= dialog.screen().availableGeometry().width()
        assert dialog.height() <= dialog.screen().availableGeometry().height()
        assert not (dialog.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        dialog.grab().save(str(path))
        report["captures"].append(str(path))

    def guard(action):
        try:
            action()
        except Exception as error:
            report["failures"].append(type(error).__name__ + ": " + str(error))
            finish()

    def welcome():
        window.show_first_run_setup()
        QTimer.singleShot(400, lambda: guard(connection))

    def connection():
        capture("welcome")
        assert not window.sprite_view.model_loaded
        report["checks"].append("缺少模型仍可打开首次引导")
        window.settings_dialog.choose_start(None)
        QTimer.singleShot(150, lambda: guard(voice))

    def voice():
        capture("connection")
        window.settings_dialog.tabs.setCurrentIndex(2)
        QTimer.singleShot(150, lambda: guard(resources))

    def resources():
        capture("voice")
        window.settings_dialog.tabs.setCurrentIndex(4)
        QTimer.singleShot(150, lambda: guard(complete))

    def complete():
        capture("resources")
        assert window.settings_dialog.save_button.isVisible()
        assert not window.settings_dialog.next.isVisible()
        window.settings_dialog.save()
        assert window.settings_dialog is None
        assert not needs_setup(load_config(source))
        assert not window.chat.busy and not window.stt.enabled and not window.tts.enabled
        window.show_first_run_setup()
        assert window.settings_dialog is None
        report["checks"].append("基础陪伴保存后不连接/不开麦/不再弹出引导")
        window.open_settings(page=2)
        QTimer.singleShot(150, lambda: guard(advanced))

    def advanced():
        capture("microphone")
        assert not window.settings_dialog.first_run
        assert window.settings_dialog.tabs.tabBar().isVisible()
        window.settings_dialog.tabs.setCurrentIndex(5)
        QTimer.singleShot(150, lambda: guard(cancel))

    def cancel():
        capture("advanced")
        local = source.with_name("config.local.yaml")
        previous = local.read_bytes()
        window.settings_dialog.fields["chat.deepseek.api_key"].setText("discard-test-value")
        window.settings_dialog.reject()
        assert previous == local.read_bytes()
        report["checks"].append("普通设置可重开/输入，取消不保存")
        report["success"] = True
        finish()

    def finish():
        project_path(".runtime/settings-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
        window.cleanup()
        window.hide()
        app.quit()

    QTimer.singleShot(1500, lambda: guard(welcome))
    app.exec()
    temp.cleanup()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
