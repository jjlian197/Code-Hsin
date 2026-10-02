"""翻译缓存与失败语义、备用音色、切换取消和辅助设置持久化。"""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.tts_manager import TTSManager
from src.core.voice_auxiliary import VoiceTranslator, EdgeSynthesizer, needs_translation
from test_tts import Player


class AuxiliaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["voice-auxiliary"])

    def pump(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def manager(self, root):
        profiles = root / "profiles.json"
        profiles.write_text("{}")
        return TTSManager({"runtime": {"directory": str(root)}, "voice": {
            "profiles": str(profiles), "enabled": True, "fallback": True}}, Player())

    def test_translation_direction_cache_identity_and_credentials_not_cached(self):
        self.assertTrue(needs_translation("御者，早安。", "ja"))
        self.assertFalse(needs_translation("御者、おはよう。", "ja"))
        self.assertTrue(needs_translation("御者、おはよう。", "zh"))
        self.assertFalse(needs_translation("御者，早安。", "zh"))
        with tempfile.TemporaryDirectory() as directory:
            config = {"chat": {"deepseek": {"api_key": "unit-test-secret", "model": "fixture"}}}
            translator = VoiceTranslator(config, directory)
            output = {"choices": [{"message": {"content": "御者、おはようございます。"}, "finish_reason": "stop"}]}
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps(output).encode())) as request:
                self.assertEqual(translator.translate("御者，早安。", "ja"), output["choices"][0]["message"]["content"])
                self.assertEqual(translator.translate("御者，早安。", "ja"), output["choices"][0]["message"]["content"])
                self.assertEqual(request.call_count, 1)
                self.assertNotIn("unit-test-secret", "".join(p.read_text(encoding="utf8") for p in translator.cache.glob("*.json")))
                config["chat"]["deepseek"]["model"] = "other-model"
                translator.translate("御者，早安。", "ja")
                self.assertEqual(request.call_count, 2)
                output["choices"][0]["finish_reason"] = "length"
                with self.assertRaisesRegex(ValueError, "截断"):
                    translator.translate("御者，午安。", "ja")
            self.assertFalse(VoiceTranslator.valid("x" * 501))

    def test_translation_failure_does_not_read_original_or_attempt_other_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            calls = []
            manager.translator.translate = lambda *args: (_ for _ in ()).throw(RuntimeError("translation unavailable"))
            manager.provider.synthesize = manager.edge.synthesize = lambda *args: calls.append(args)
            try:
                manager.speak("御者，早安。", "ja", translate=True)
                self.pump(lambda: manager.error is not None)
                self.assertIn("translation unavailable", manager.error)
                self.assertEqual(calls, [])
                self.assertEqual(manager.player.played, [])
            finally:
                manager.close()

    def test_primary_failure_uses_translated_text_for_backup_and_persists_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.manager(root)
            calls = []
            manager.translator.translate = lambda *args: "御者、おはようございます。"
            manager.provider.synthesize = lambda *args: (_ for _ in ()).throw(RuntimeError("primary unavailable"))
            manager.edge.synthesize = lambda *args: (calls.append(args), root / "backup.mp3")[1]
            try:
                manager.configure(language="ja", auto_translate=True, fallback=True)
                manager.speak("御者，早安。")
                self.pump(lambda: bool(manager.player.played))
                state = manager.snapshot()
                self.assertEqual(state["provider"], "gptsovits")
                self.assertEqual(state["actual_provider"], "edge")
                self.assertIsNone(state["error"])
                self.assertIn("Edge", state["warning"])
                self.assertEqual(calls, [("御者、おはようございます。", "ja", 1.0)])
                self.assertEqual(state["last_request"]["spoken_text"], calls[0][0])
                before = manager.snapshot()
                with self.assertRaises(ValueError):
                    manager.configure(language="zh", provider="unknown", fallback=False)
                self.assertEqual(manager.snapshot(), before)
                manager.configure(provider="edge", fallback=False)
            finally:
                manager.close()
            restored = self.manager(root)
            try:
                self.assertEqual(restored.engine, "edge")
                self.assertEqual(restored.language, "ja")
                self.assertTrue(restored.auto_translate)
                self.assertFalse(restored.fallback)
            finally:
                restored.close()

    def test_cancelled_primary_failure_does_not_start_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory))
            started, release, completed = threading.Event(), threading.Event(), threading.Event()
            backups = []
            def fail(*args):
                started.set()
                release.wait(2)
                completed.set()
                raise RuntimeError("late failure")
            manager.provider.synthesize = fail
            manager.edge.synthesize = lambda *args: backups.append(args)
            try:
                manager.speak("御者，早安。")
                self.assertTrue(started.wait(1))
                manager.configure(language="ja")
                release.set()
                self.assertTrue(completed.wait(1))
                time.sleep(0.05)
                self.app.processEvents()
                self.assertEqual(backups, [])
                self.assertEqual(manager.player.played, [])
                self.assertIsNone(manager.error)
            finally:
                release.set()
                manager.close()

    def test_edge_cache_separates_language_speed_and_skips_network(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = EdgeSynthesizer(directory)
            calls = []
            class Communicate:
                def __init__(self, *args, **kwargs): calls.append((args, kwargs))
                async def save(self, path): Path(path).write_bytes(b"ID3" + b"audio" * 200)
            try:
                with patch("edge_tts.Communicate", Communicate):
                    zh = provider.synthesize("御者", "zh", 1)
                    self.assertEqual(zh, provider.synthesize("御者", "zh", 1))
                    ja = provider.synthesize("御者", "ja", 1)
                    quick = provider.synthesize("御者", "ja", 1.5)
                self.assertEqual(len(calls), 3)
                self.assertEqual(len({zh, ja, quick}), 3)
                self.assertEqual(calls[-1][1]["rate"], "+50%")
            finally:
                provider.close()


if __name__ == "__main__":
    unittest.main()
