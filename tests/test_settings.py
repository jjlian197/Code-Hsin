"""统一设置：真实 Qt 表单、取消、持久化、无网络/录音及错误隔离。"""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import yaml
from PyQt6.QtWidgets import QApplication, QDialog
from src.core.app_config import DEFAULT_CONFIG, load_config
from src.core.sprite_window import HsinSpriteWindow
from src.core.user_settings import needs_setup
from src.ui.settings_dialog import SettingsDialog


class SettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = deepcopy(DEFAULT_CONFIG)
        config["sprite"]["renderer"] = "placeholder"
        config["runtime"]["directory"] = str(self.root / "runtime")
        config["voice"]["profiles"] = str(self.root / "voice.json")
        self.source = self.root / "config.yaml"
        self.source.write_text(yaml.safe_dump(config), encoding="utf8")
        self.local = self.root / "config.local.yaml"
        self.window = HsinSpriteWindow(load_config(self.source))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.window.cleanup()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def dialog(self, **kwargs):
        dialog = SettingsDialog(self.window, **kwargs)
        self.dialogs.append(dialog)
        return dialog

    def test_first_run_cancel_and_menu_reopen(self):
        self.assertTrue(needs_setup(self.window.config))
        self.window.show_first_run_setup()
        self.assertTrue(self.window.settings_dialog.first_run)
        self.window.settings_dialog.reject()
        self.assertFalse(self.local.exists())
        self.assertTrue(needs_setup(self.window.config))
        self.assertIsNone(self.window.settings_dialog)
        self.window.configure_microphone()
        self.assertEqual(self.window.settings_dialog.tabs.currentIndex(), 2)
        actions = [a.text() for a in self.window._tray_menu.actions()]
        self.assertIn("设置…", actions)

    def test_basic_companion_without_keys_preserves_existing_values(self):
        self.local.write_text("custom:\n  keep: true\nchat:\n  deepseek:\n    api_key: saved-test-key\n", encoding="utf8")
        self.window.chat.config["deepseek"]["api_key"] = "saved-test-key"
        dialog = self.dialog(first_run=True)
        dialog.choose_start(None)
        with patch.object(self.window.chat, "send") as send, patch.object(self.window.stt, "_start_capture") as capture:
            dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(self.window.stt.enabled)
        send.assert_not_called()
        capture.assert_not_called()
        self.assertFalse(self.window.tts.enabled)
        self.assertFalse(self.window.chat.config["enabled"])
        with self.assertRaisesRegex(ValueError, "基础陪伴"):
            self.window.chat.send("测试", "zh")
        saved = load_config(self.source)
        self.assertFalse(needs_setup(saved))
        self.assertTrue(saved["custom"]["keep"])
        self.assertEqual(saved["chat"]["deepseek"]["api_key"], "saved-test-key")
        self.assertFalse(saved["chat"]["enabled"])
        self.assertFalse(saved["voice"]["enabled"])
        self.window.show_first_run_setup()
        self.assertIsNone(self.window.settings_dialog)

    def test_invalid_batch_leaves_disk_and_runtime_unchanged(self):
        dialog = self.dialog()
        old = deepcopy(self.window.chat.config)
        dialog.fields["chat.deepseek.api_key"].setText("should-not-save")
        dialog.fields["http.port"].setValue(dialog.fields["websocket.port"].value())
        dialog.save()
        self.assertFalse(self.local.exists())
        self.assertEqual(self.window.chat.config, old)
        self.assertTrue(needs_setup(self.window.config))
        self.assertNotIn("should-not-save", dialog.error.text())
        dialog.fields["http.port"].setValue(18766)
        dialog.fields["chat.hermes.url"].setText("https://example.com")
        dialog.save()
        self.assertFalse(self.local.exists())

    def test_saved_fields_live_apply_and_restart_only_resources(self):
        dialog = self.dialog()
        dialog.fields["chat.provider"].setCurrentIndex(dialog.fields["chat.provider"].findData("deepseek"))
        dialog.fields["voice.language"].setCurrentIndex(1)
        dialog.fields["voice.volume"].setValue(.4)
        dialog.fields["stt.hotwords"].setPlainText("心\n心月狐\n心")
        dialog.fields["voice.port"].setValue(19881)
        dialog.fields["voice.profiles"].setText(str(self.root / "imported.json"))
        with patch.object(self.window, "show_message") as message:
            dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.window.chat.provider, "deepseek")
        self.assertEqual(self.window.tts.language, "ja")
        self.assertEqual(self.window.tts.volume, .4)
        self.assertEqual(self.window.stt.config["hotwords"], ["心", "心月狐"])
        self.assertEqual(self.window.tts.provider.port, 19880)
        self.assertEqual(self.window.tts.profiles_path, self.root / "voice.json")
        self.assertIn("重启", message.call_args.args[0])
        saved = load_config(self.source)
        self.assertEqual(saved["voice"]["port"], 19881)
        self.assertEqual(saved["voice"]["profiles"], str(self.root / "imported.json"))

    def test_save_error_does_not_mark_complete_or_change_live_settings(self):
        dialog = self.dialog()
        old = deepcopy(self.window.chat.config)
        with patch("src.core.user_settings.read_yaml", side_effect=OSError("private-credential")):
            self.local.write_text("{}", encoding="utf8")
            dialog.save()
        self.assertEqual(self.window.chat.config, old)
        self.assertEqual(self.local.read_text(encoding="utf8"), "{}")
        self.assertTrue(needs_setup(self.window.config))
        self.assertNotIn("private-credential", dialog.error.text())

    def test_chat_range_controls_and_selected_long_text_use_queue(self):
        import time
        from src.ui.chat_dialog import ChatDialog
        from PyQt6.QtMultimedia import QMediaPlayer
        dialog = ChatDialog(self.window)
        self.dialogs.append(dialog)
        dialog.reply_length.setCurrentIndex(dialog.reply_length.findData("detailed"))
        dialog.speech_scope.setCurrentIndex(dialog.speech_scope.findData("prefix"))
        dialog.scope_amount.setValue(800)
        self.assertEqual(self.window.chat.config["speech_prefix_chars"], 800)
        self.assertEqual(self.window.chat.config["reply_length"], "detailed")
        self.window.tts.profiles_path.write_text("{}")
        self.window.tts.configure(enabled=True, auto_translate=False, fallback=False)
        self.window.tts.provider.synthesize = lambda *_: self.root / "silent.wav"
        text = "请把所选的内容完整读出来。" * 50
        heard = []
        self.window.tts.speech_started.connect(heard.append)
        with patch.object(self.window.voice_player, "play", side_effect=lambda *_:
                          self.window.voice_player.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)):
            dialog.read_text(text)
            deadline = time.monotonic() + 3
            while (not heard or self.window.tts.snapshot()["active"]) and time.monotonic() < deadline:
                self.app.processEvents()
                self.window.voice_player.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.StoppedState)
                time.sleep(.003)
        self.assertEqual("".join(heard), text)
        self.assertFalse(self.window.tts.snapshot()["active"])
        self.assertGreater(len(text), 500)
        self.assertEqual(self.window.tts.last_request["source"], "manual")
        self.assertEqual(self.window.chat.config["speech_scope"], "prefix", "手动选中文字不改变自动朗读范围")


if __name__ == "__main__":
    unittest.main()
