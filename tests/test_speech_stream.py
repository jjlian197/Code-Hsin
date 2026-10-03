"""分句边界与语音队列；模拟播放结束，不访问远程服务或麦克风。"""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication
from src.core.speech_stream import SentenceStream
from src.core.tts_manager import TTSManager


class SplitterTest(unittest.TestCase):
    def test_chunk_boundaries_markup_and_no_duplicate_final(self):
        text = '<think>不能读。秘密。</think>御者，你好！\n```py\n秘密。\n```\n看看[资料。](https://x.test/a(b))。今日は元気ですか？末句'
        stream, result = SentenceStream(), []
        for char in text:
            result.extend(stream.feed(char))
        result.extend(stream.finish(text))
        self.assertEqual(result, ["御者，你好！", "看看资料。", "今日は元気ですか？", "末句"])
        self.assertFalse(stream.revised)

    def test_final_only_missing_suffix_and_decimal(self):
        stream = SentenceStream()
        self.assertEqual(stream.feed("版本 1."), [])
        self.assertEqual(stream.feed("2 很好。下一"), ["版本 1.2 很好。"])
        self.assertEqual(stream.finish("版本 1.2 很好。下一句没有句号"), ["下一句没有句号"])
        self.assertEqual(SentenceStream().finish("完整回复。"), ["完整回复。"])
        stream = SentenceStream()
        self.assertEqual(stream.feed("\n御者，我在。\n\n"), ["御者，我在。"])
        self.assertEqual(stream.finish("御者，我在。接着说。"), ["接着说。"])

    def test_incomplete_constructs_and_revised_final(self):
        for tail in ("<think>秘密。", "```秘密。", "[秘密。](https://test", "https://secret.test"):
            stream = SentenceStream()
            self.assertEqual(stream.feed("你好。" + tail), ["你好。"])
            self.assertEqual(stream.finish("你好。" + tail), [])
        stream = SentenceStream()
        self.assertEqual(stream.feed("已经读过。"), ["已经读过。"])
        self.assertEqual(stream.finish("已经修订。不要再读。"), [])
        self.assertTrue(stream.revised)
        stream, parts = SentenceStream(), []
        text = "看看![图片。](https://x.test)。继续！"
        for char in text:
            parts.extend(stream.feed(char))
        parts.extend(stream.finish(text))
        self.assertEqual(parts, ["看看。", "继续！"])
        self.assertFalse(stream.revised)

    def test_long_sentence_cap_and_list_boundaries(self):
        text = "第一句。\n\n1. 第二句。\n2. 第三句。"
        stream, result = SentenceStream(), []
        for char in text:
            result.extend(stream.feed(char))
        result.extend(stream.finish(text))
        self.assertEqual(result, ["第一句。", "第二句。", "第三句。"])
        stream = SentenceStream()
        result = stream.feed("心" * 900) + stream.finish("心" * 900)
        self.assertEqual(sum(map(len, result)), 500)
        self.assertTrue(all(len(piece) <= 160 for piece in result))


class Media(QObject):
    playbackStateChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object, str)


class QueuePlayer:
    def __init__(self):
        self.player = Media()
        self.played = []

    def play(self, path, volume):
        self.played.append((path.name, volume, threading.get_ident()))
        self.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)

    def stop(self):
        self.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.StoppedState)

    def finish(self):
        self.stop()


class QueueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        profiles = self.root / "profiles.json"
        profiles.write_text("{}")
        self.player = QueuePlayer()
        self.tts = TTSManager({"runtime": {"directory": str(self.root)}, "voice": {
            "enabled": True, "profiles": str(profiles), "fallback": True}}, self.player)
        self.calls = []
        def synth(text, language, speed):
            self.calls.append((text, language))
            return self.root / (text + ".wav")
        self.tts.provider.synthesize = synth

    def tearDown(self):
        self.tts.close()
        self.temp.cleanup()

    def pump(self, condition, timeout=3):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.003)
        self.assertTrue(condition())

    def test_order_prefetch_playback_and_finish(self):
        token = self.tts.begin_stream("zh")
        for text in ["一", "二", "三", "四", "五"]:
            self.assertTrue(self.tts.enqueue_sentence(token, text, "zh"))
        self.tts.finish_stream(token)
        self.pump(lambda: len(self.player.played) == 1 and len(self.tts._ready) == 2)
        self.assertEqual(len(self.calls), 3, "当前句加两句预合成，不应合成所有积压句")
        self.assertEqual(len(self.player.played), 1, "下一句不能打断当前句")
        for count in range(2, 6):
            self.player.finish()
            self.pump(lambda: len(self.player.played) == count)
        self.player.finish()
        self.pump(lambda: not self.tts.snapshot()["active"])
        self.assertFalse(self.tts.snapshot()["streaming"])
        self.assertEqual([p[0] for p in self.player.played], [t + ".wav" for t in "一二三四五"])
        self.assertTrue(all(p[2] == threading.get_ident() for p in self.player.played))

    def test_stop_switch_and_stale_callbacks(self):
        begun, release = threading.Event(), threading.Event()
        def synth(text, language, speed):
            if text == "旧":
                begun.set()
                release.wait(2)
            return self.root / (language + text + ".wav")
        self.tts.provider.synthesize = synth
        token = self.tts.begin_stream("zh")
        self.tts.enqueue_sentence(token, "旧", "zh")
        self.assertTrue(begun.wait(1))
        self.tts.enqueue_sentence(token, "排队", "zh")
        self.tts.configure(language="ja")
        self.assertFalse(self.tts.enqueue_sentence(token, "迟到", "zh"))
        fresh = self.tts.begin_stream("ja")
        self.tts.enqueue_sentence(fresh, "新", "ja")
        self.tts.finish_stream(fresh)
        release.set()
        self.pump(lambda: len(self.player.played) == 1)
        self.assertEqual(self.player.played[0][0], "ja新.wav")
        self.player.finish()
        self.tts.stop()  # 丢弃已经排入 Qt 的播放结束回调。
        self.app.processEvents()
        self.assertEqual(len(self.player.played), 1)

    def test_segment_fallback_and_failure_clear_queue(self):
        def primary(*args):
            raise RuntimeError("primary fixture")
        self.tts.provider.synthesize = primary
        self.tts.edge.synthesize = lambda text, *_: self.root / (text + ".mp3")
        token = self.tts.begin_stream("ja")
        self.tts.enqueue_sentence(token, "先", "ja")
        self.tts.enqueue_sentence(token, "次", "ja")
        self.pump(lambda: len(self.player.played) == 1 and len(self.tts._ready) == 1)
        self.assertEqual(self.tts.actual_provider, "edge")
        self.assertIn("Edge", self.tts.warning)
        self.tts.enqueue_sentence(token, "第三", "ja")
        self.assertEqual(self.tts.actual_provider, "edge", "排入后句不能抹掉正在播放的实际音色")
        self.player.player.errorOccurred.emit(None, "decode fixture")
        self.app.processEvents()
        self.assertEqual(self.tts.error, "decode fixture")
        self.assertFalse(self.tts.snapshot()["active"])
        self.assertFalse(self.tts.enqueue_sentence(token, "不能播", "ja"))
        self.assertEqual(len(self.player.played), 1)


if __name__ == "__main__":
    unittest.main()
