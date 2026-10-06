"""验证跨语言缓存隔离、取消旧播放、Qt 主线程回调及本地语音请求。"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.tts_manager import LocalSynthesizer, TTSManager, cache_key, wave_info


def sample_wave():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(32000)
        wav.writeframes(b"\x00\x20" * 6400)
    return stream.getvalue()


class Player:
    def __init__(self):
        self.played = []
        self.stopped = 0

    def stop(self):
        self.stopped += 1

    def play(self, path, volume):
        self.played.append((str(path), volume, threading.get_ident()))


class VoiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["tts-test"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = {"prompt_text": "原声", "sha256": {}}
        for key in ("gpt_weights", "sovits_weights", "reference_audio"):
            path = self.root / key
            path.write_bytes(b"resource")
            self.profile[key] = str(path)

    def tearDown(self):
        self.temp.cleanup()

    def pump(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def manager(self):
        profiles = self.root / "profiles.json"
        profiles.write_text("{}")
        player = Player()
        manager = TTSManager({"runtime": {"directory": str(self.root)},
            "voice": {"profiles": str(profiles), "enabled": True}}, player)
        return manager, player

    def test_idle_release_preserves_active_request_and_unowned_service(self):
        voice = LocalSynthesizer(self.root / 'profiles.json', self.root)
        self.assertFalse(voice.release_idle(), '不会结束非本实例启动的服务')
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        voice.process = process
        try:
            voice.operation_lock.acquire()
            try:
                self.assertFalse(voice.release_idle())
                self.assertIsNone(process.poll())
            finally:
                voice.operation_lock.release()
            self.assertTrue(voice.release_idle())
            self.assertIsNotNone(process.poll())
            self.assertFalse(voice.closed.is_set(), '释放后仍允许下一次加载')
        finally:
            voice.close()

    def test_cached_playback_after_idle_release_does_not_claim_model_warm(self):
        manager, player = self.manager()
        path = self.root / 'cached.wav'
        path.write_bytes(sample_wave())
        manager.provider.idle_released = True
        manager._warmup_target = 'zh'
        try:
            with patch.object(manager.provider, 'synthesize', return_value=path):
                manager.speak('缓存朗读。', 'zh', translate=False)
                self.pump(lambda: bool(player.played))
            self.assertEqual(manager.warmup_state, 'idle')
        finally:
            manager.close()

    def test_cache_identity_language_weights_reference_and_speed(self):
        original = cache_key("同文", "zh", 1, self.profile)
        self.assertNotEqual(original, cache_key("同文", "ja", 1, self.profile))
        self.assertNotEqual(original, cache_key("同文", "zh", 1.1, self.profile))
        altered = dict(self.profile, prompt_text="另一原文")
        self.assertNotEqual(original, cache_key("同文", "zh", 1, altered))
        Path(self.profile["gpt_weights"]).write_bytes(b"new weights")
        self.assertNotEqual(original, cache_key("同文", "zh", 1, self.profile))

    def test_switch_cancels_inflight_and_latest_job_plays_on_gui_thread(self):
        manager, player = self.manager()
        begun, release = threading.Event(), threading.Event()
        def synth(text, language, speed):
            if text == "old":
                begun.set()
                release.wait(2)
            return self.root / (language + ".wav")
        manager.provider.synthesize = synth
        try:
            manager.speak("old")
            self.assertTrue(begun.wait(1))
            manager.configure(language="ja")
            manager.speak("new")
            release.set()
            self.pump(lambda: len(player.played) == 1)
            self.assertEqual(player.played[0], (str(self.root / "ja.wav"), 0.65, threading.get_ident()))
            self.assertFalse(manager.busy)
            manager.configure(enabled=False)
            with self.assertRaises(ValueError):
                manager.speak("muted")
            saved = json.loads(manager.state_path.read_text())
            self.assertEqual(saved, {"enabled": False, "language": "ja", "provider": "gptsovits",
                                     "auto_translate": False, "fallback": False})
        finally:
            release.set()
            manager.close()

    def test_stop_discards_pending_result_and_error_is_observable(self):
        manager, player = self.manager()
        begun, release = threading.Event(), threading.Event()
        def synth(*args):
            begun.set()
            release.wait(2)
            return self.root / "old.wav"
        manager.provider.synthesize = synth
        try:
            manager.speak("cancel")
            self.assertTrue(begun.wait(1))
            manager.stop()
            release.set()
            self.pump(lambda: not manager.busy)
            self.assertEqual(player.played, [])
            def fail(*args):
                raise RuntimeError("test failure")
            manager.provider.synthesize = fail
            manager.speak("failure")
            self.pump(lambda: manager.error is not None)
            self.assertIn("test failure", manager.snapshot()["error"])
        finally:
            release.set()
            manager.close()

    def test_restart_restores_language_and_mute_and_corrupt_state_uses_defaults(self):
        manager, _ = self.manager()
        manager.configure(language="ja", enabled=False)
        manager.close()
        restored, _ = self.manager()
        try:
            self.assertEqual(restored.language, "ja")
            self.assertFalse(restored.enabled)
        finally:
            restored.close()
        (self.root / "voice.json").write_text("[]")
        fallback, _ = self.manager()
        try:
            self.assertEqual(fallback.language, "zh")
            self.assertTrue(fallback.enabled)
        finally:
            fallback.close()

    def test_http_request_cache_and_service_identity(self):
        requests = []
        profile = self.profile
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"service": "hsin-gptsovits", "profile_id": "fixture"}).encode())
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"ready": True, "language": requests[-1]["language"]}).encode()
                    if self.path == "/warmup" else sample_wave())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        profiles = self.root / "profiles.json"
        profiles.write_text(json.dumps({"profiles": {"zh": profile, "ja": profile}, "profile_id": "fixture"}))
        provider = LocalSynthesizer(profiles, self.root, server.server_port)
        try:
            zh = provider.synthesize("test", "zh", 1)
            self.assertEqual(zh, provider.synthesize("test", "zh", 1))
            ja = provider.synthesize("test", "ja", 1)
            self.assertNotEqual(zh, ja)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[1]["language"], "ja")
            self.assertAlmostEqual(wave_info(ja.read_bytes()), 0.2)
            provider.warmup("ja")
            self.assertEqual(requests[-1], {"language": "ja"}, "缓存存在仍须实际预热")
            data = {"profile_id": "wrong"}
            with self.assertRaises(RuntimeError):
                provider.ensure_server(data)
        finally:
            provider.close()
            server.shutdown()
            server.server_close()

    def test_prewarm_is_background_silent_nonblocking_and_tracks_language(self):
        manager, player = self.manager()
        begun, release = threading.Event(), threading.Event()
        calls = []
        def warmup(language):
            calls.append(language)
            begun.set()
            release.wait(2)
        manager.provider.warmup = warmup
        try:
            manager.configure(enabled=False)
            manager.prewarm()
            self.assertTrue(begun.wait(1))
            self.assertEqual(manager.snapshot()["warmup"]["state"], "warming")
            self.assertFalse(manager.snapshot()["active"], "后台预热不应占用对话/收音状态")
            self.assertEqual(player.played, [])
            manager.configure(language="ja")
            release.set()
            self.pump(lambda: manager.snapshot()["warmup"]["state"] == "ready")
            self.assertEqual(calls, ["zh", "ja"])
            self.assertEqual(manager.snapshot()["warmup"]["language"], "ja")
            manager.prewarm()
            self.assertIsNone(manager._warmup_language, "已完成预热无需重复")
            self.assertEqual(player.played, [])
        finally:
            release.set()
            manager.close()

    def test_prewarm_failure_does_not_disable_normal_speech(self):
        manager, player = self.manager()
        def fail(language):
            raise RuntimeError("预热失败")
        manager.provider.warmup = fail
        manager.provider.synthesize = lambda *_: self.root / "speech.wav"
        try:
            manager.prewarm()
            self.pump(lambda: manager.snapshot()["warmup"]["state"] == "failed")
            self.assertFalse(manager.busy)
            self.assertIsNone(manager.error)
            manager.speak("你好", translate=False)
            self.pump(lambda: bool(player.played))
            self.assertEqual(manager.snapshot()["warmup"]["state"], "ready")
        finally:
            manager.close()

    def test_presets_without_training_profile_do_not_start_prewarm(self):
        manager, player = self.manager()
        manager.profiles_path.unlink()
        try:
            with patch.object(manager.provider, 'warmup') as warmup:
                manager.prewarm()
                self.assertIsNone(manager._warmup_language)
                self.assertEqual(manager.warmup_state, 'idle')
                warmup.assert_not_called()
                self.assertEqual(player.played, [])
        finally:
            manager.close()
