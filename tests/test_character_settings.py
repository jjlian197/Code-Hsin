"""角色草稿、凭据隔离、切换取消和启动恢复；不发起聊天或语音请求。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.app_config import DEFAULT_CONFIG
from src.core.character_settings import CharacterSettings, profile_from_config, profile_config
from src.core.sprite_window import HsinSpriteWindow
from src.ui.settings_dialog import SettingsDialog


class CharacterSettingsTest(unittest.TestCase):
    def test_role_activation_switches_remote_voice_in_worker(self):
        previous_remote = self.window.tts.remote
        profile = self.profile()
        profile["voice"].update(provider="remote", enabled=False, remote_voice="aemeath")
        self.window.characters.save(profile)
        self.window.characters.activate(profile["id"])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.window.tts.remote.voice_id != "aemeath":
            self.app.processEvents()
            time.sleep(.01)
        self.assertEqual(self.window.tts.remote.voice_id, "aemeath")
        self.assertIsNot(self.window.tts.remote, previous_remote)
        self.assertEqual(self.window.tts.snapshot()["remote_voice"], "aemeath")
        self.assertFalse(self.window.stt.enabled)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config["sprite"]["renderer"] = "placeholder"
        self.config["runtime"]["directory"] = self.temp.name
        self.config["chat"]["deepseek"]["api_key"] = "global-test-secret"
        self.window = HsinSpriteWindow(deepcopy(self.config))
        self.windows = [self.window]

    def tearDown(self):
        for window in self.windows:
            window.cleanup()
            window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def profile(self, name="爱弥斯"):
        return profile_from_config(self.window.config, name, persona="你是" + name)

    def test_save_draft_no_live_change_and_no_credentials(self):
        manager = self.window.characters
        before = manager.active
        profile = self.profile()
        manager.save(profile)
        data = manager.path.read_text(encoding="utf8")
        self.assertNotIn("global-test-secret", data)
        self.assertNotIn("api_key", data)
        self.assertEqual(manager.active, before)
        self.assertEqual(self.window.chat.character_name, "心")
        profile["chat"]["deepseek"]["api_key"] = "bad"
        with self.assertRaises(ValueError):
            profile_config(self.window.config, profile)

    def test_settings_editor_save_and_activate_then_restart(self):
        dialog = SettingsDialog(self.window, page=6)
        page = dialog.character_page
        page.new()
        page.fields["name"].setText("角色甲")
        page.persona.setPlainText("你是角色甲")
        page.fields["voice.language"].setCurrentIndex(1)
        page.fields["voice.enabled"].setChecked(False)
        page.save()
        identity = page.draft["id"]
        page.activate()
        self.assertEqual(self.window.characters.active, identity)
        self.assertEqual(self.window.chat.character_name, "角色甲")
        self.assertEqual(self.window.chat.config["persona"], "你是角色甲")
        self.assertEqual(self.window.tts.language, "ja")
        restored = HsinSpriteWindow(deepcopy(self.config))
        self.windows.append(restored)
        self.app.processEvents()
        self.assertEqual(restored.characters.active, identity)
        self.assertEqual(restored.chat.character_name, "角色甲")
        self.assertEqual(restored.tts.language, "ja")
        self.assertFalse(restored.stt.enabled)
        dialog.close()

    def test_switch_invalidates_late_chat_tts_stt_and_keeps_role_history(self):
        manager = self.window.characters
        original = manager.active
        other = self.profile()
        manager.save(other)
        self.window.chat.messages = [("心", "心的记录")]
        old_chat, old_tts, old_stt = self.window.chat.generation, self.window.tts.generation, self.window.stt._generation
        manager.activate(other["id"])
        self.assertGreater(self.window.chat.generation, old_chat)
        self.assertGreater(self.window.tts.generation, old_tts)
        self.assertGreater(self.window.stt._generation, old_stt)
        self.window.chat._complete(old_chat, ("迟到回复", "zh", None), None)
        self.window.tts._complete(old_tts, None, "迟到错误")
        self.assertEqual(self.window.chat.messages, [])
        self.assertIsNone(self.window.tts.error)
        self.window.chat.messages = [("爱弥斯", "爱弥斯的记录")]
        manager.activate(original)
        self.assertEqual(self.window.chat.messages, [("心", "心的记录")])
        manager.activate(other["id"])
        self.assertEqual(self.window.chat.messages, [("爱弥斯", "爱弥斯的记录")])

    def test_missing_package_does_not_change_selection_or_config(self):
        profile = self.profile()
        profile["package"] = str(Path(self.temp.name) / "missing.json")
        manager = self.window.characters
        manager.save(profile)
        original = manager.active
        with self.assertRaises((OSError, ValueError)):
            manager.activate(profile["id"])
        self.assertEqual(manager.active, original)
        self.assertIsNone(manager.pending)
        self.assertNotIn("persona", self.window.chat.config)

    def test_native_failure_keeps_original_persona_and_voice(self):
        manager = self.window.characters
        profile = self.profile()
        candidate = profile_config(self.window.config, profile)
        manager.pending = (profile, candidate)
        manager.finish(False)
        self.assertIsNone(manager.pending)
        self.assertEqual(self.window.chat.character_name, "心")
        self.assertNotIn("persona", self.window.chat.config)

    def test_voice_resource_swap_disables_hsin_presets_and_stale_warmup(self):
        voice = deepcopy(self.window.config["voice"])
        voice["profiles"] = str(Path(self.temp.name) / "other-voice.json")
        self.window.tts.configure_resources(voice, presets=False)
        deadline = time.monotonic() + 3
        while self.window.tts.provider.profiles_path != Path(voice["profiles"]) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertEqual(self.window.tts.provider.profiles_path, Path(voice["profiles"]))
        self.assertEqual(self.window.tts.qwen.profiles, Path(voice["profiles"]))
        self.assertEqual(self.window.tts.provider.presets.entries, {})
        self.window.tts._warmup_target = "zh"
        self.window.tts.warmup_state = "warming"
        self.window.tts._warmup_complete(self.window.tts.generation - 1, "zh", None)
        self.assertEqual(self.window.tts.warmup_state, "warming")

    def test_backend_sessions_are_isolated_by_role_and_receive_persona(self):
        created = []
        class Backend:
            def __init__(self, provider, config):
                self.config, self.history = config, []
                created.append(self)
            async def chat(self, text, language, delta, **kwargs):
                self.history.append(text)
                return text
        import asyncio
        with patch("src.core.chat_manager.make_backend", Backend):
            for identity, text in (("hsin", "甲"), ("aemeath", "乙"), ("hsin", "丙")):
                asyncio.run(self.window.chat._chat(0, text, "zh", "deepseek", "normal", {"persona": identity}, identity))
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].history, ["甲", "丙"])
        self.assertEqual(created[1].history, ["乙"])
        self.assertEqual(created[1].config["persona"], "aemeath")


if __name__ == "__main__":
    unittest.main()
