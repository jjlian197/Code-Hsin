import threading
import time
import unittest
import os
from unittest.mock import patch, Mock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.stt_manager import STTManager, VadSegmenter
from src.core.speech_recognizer import SpeechRecognizer, wav_bytes


APP = QApplication.instance() or QApplication([])


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class VADTests(unittest.TestCase):
    def setUp(self):
        self.voice = b"\x01\x00" * 320
        self.silence = bytes(640)
        self.vad = VadSegmenter(lambda frame: frame == self.voice)

    def feed(self, frame, count):
        return [value for _ in range(count) if (value := self.vad.feed(frame)) is not None]

    def test_silence_and_short_noise_are_dropped(self):
        self.assertEqual(self.feed(self.silence, 100), [])
        self.feed(self.voice, 5)
        self.assertEqual(self.feed(self.silence, 35), [])
        self.assertFalse(self.vad.active)

    def test_sentence_contains_preroll_and_waits_for_pause(self):
        self.feed(self.silence, 30)
        self.feed(self.voice, 25)
        self.assertEqual(self.feed(self.silence, 34), [])
        result = self.feed(self.silence, 1)
        self.assertEqual(result, [self.silence * 15 + self.voice * 25 + self.silence * 35])

    def test_pause_inside_sentence_and_maximum_length(self):
        self.feed(self.voice, 20)
        self.feed(self.silence, 12)
        self.feed(self.voice, 20)
        self.assertEqual(len(self.feed(self.silence, 35)), 1)
        result = self.feed(self.voice, 1250)
        self.assertEqual(len(result[0]), 25 * 16000 * 2)

    def test_reset_discards_unfinished_speech(self):
        self.feed(self.voice, 25)
        self.vad.reset()
        self.assertEqual(self.feed(self.silence, 35), [])


class BackendTests(unittest.TestCase):
    def test_wav_format_and_provider_routing(self):
        import io, wave
        with wave.open(io.BytesIO(wav_bytes(bytes(640))), "rb") as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (16000, 1, 2))
        with patch.dict("os.environ", {"ZHIPU_API_KEY": ""}):
            config = {"provider": "auto", "language": "zh", "zhipu": {"api_key": "test"}}
            self.assertEqual(SpeechRecognizer.provider(config), "zhipu")
            config["language"] = "ja"
            self.assertEqual(SpeechRecognizer.provider(config), "whisper")

    def test_cloud_failure_falls_back_but_empty_result_does_not(self):
        backend = SpeechRecognizer()
        with patch.object(backend, "_cloud", side_effect=RuntimeError("HTTP 503")), patch.object(backend, "_local", return_value="你好"):
            result = backend.transcribe(bytes(640), {"provider": "zhipu"})
            self.assertEqual(result[:2], ("你好", "whisper"))
            self.assertIn("HTTP 503", result[2])
            with self.assertRaises(RuntimeError):
                backend.transcribe(bytes(640), {"provider": "zhipu", "fallback": False})
        with patch.object(backend, "_cloud", return_value=""), patch.object(backend, "_local") as local:
            self.assertEqual(backend.transcribe(bytes(640), {"provider": "zhipu"})[0], "")
            local.assert_not_called()

    def test_cloud_http_errors_do_not_expose_response_or_key(self):
        with patch("requests.post", return_value=Mock(status_code=401, text="sensitive")) as post:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
                SpeechRecognizer().transcribe(bytes(640), {"provider": "zhipu", "fallback": False, "zhipu": {"api_key": "secret"}})
            self.assertNotIn("secret", str(error.exception))
            self.assertNotIn("sensitive", str(error.exception))
            self.assertNotIn("language", post.call_args.kwargs["data"])


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.started = threading.Event()
        def recognize(*args):
            self.started.set()
            self.release.wait(2)
            return "你好", "whisper", ""
        self.backend = Mock()
        self.backend.transcribe.side_effect = recognize
        self.manager = STTManager({"stt": {"language": "zh", "zhipu": {"api_key": "secret"}}}, recognizer=self.backend)
        self.manager._tick = Mock()  # 单元测试不打开真实麦克风。
        self.texts = []
        self.manager.transcript.connect(self.texts.append)

    def tearDown(self):
        self.release.set()
        self.manager.close()
        wait_for(lambda: not self.manager.busy, 0.1)

    def begin(self):
        self.manager.configure(enabled=True)
        self.manager._submit(bytes(640))
        self.assertTrue(self.started.wait(1))

    def test_default_off_and_status_has_no_credentials(self):
        self.assertFalse(self.manager.enabled)
        self.assertNotIn("secret", str(self.manager.snapshot()))

    def test_disable_and_reenable_discards_late_result(self):
        self.begin()
        self.manager.configure(enabled=False)
        self.manager.configure(enabled=True)
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.manager.busy))
        self.assertEqual(self.texts, [])

    def test_language_change_discards_late_result(self):
        self.begin()
        self.manager.configure(language="ja")
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.manager.busy))
        self.assertEqual(self.texts, [])

    def test_external_reply_blocks_pending_result_and_audio(self):
        self.begin()
        self.manager.set_blocked(True)
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.manager.busy))
        self.manager.feed_pcm(bytes(64000))
        self.assertEqual(self.texts, [])
        self.assertEqual(len(self.manager._buffer), 0)
        self.manager.set_blocked(False)
        self.manager.feed_pcm(bytes(64000))
        self.assertEqual(len(self.manager._buffer), 0)  # 播放结束后还有冷却。

    def test_valid_result_reaches_qt_thread(self):
        callback_threads = []
        self.manager.transcript.connect(lambda _: callback_threads.append(threading.get_ident()))
        self.begin()
        self.release.set()
        self.assertTrue(wait_for(lambda: self.texts == ["你好"]))
        self.assertEqual(callback_threads, [threading.get_ident()])

    def test_error_closes_microphone_and_can_retry(self):
        self.backend.transcribe.side_effect = RuntimeError("识别失败")
        self.manager.configure(enabled=True)
        self.manager._submit(bytes(640))
        self.assertTrue(wait_for(lambda: self.manager.error))
        self.assertFalse(self.manager.enabled)
        self.manager.configure(enabled=True)
        self.assertEqual(self.manager.error, "")

    def test_invalid_setting_is_atomic(self):
        with self.assertRaises(ValueError):
            self.manager.configure(language="xx", enabled=True)
        self.assertFalse(self.manager.enabled)
        self.assertEqual(self.manager.config["language"], "zh")
