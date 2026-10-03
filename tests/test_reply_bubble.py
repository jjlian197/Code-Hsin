"""气泡保持当前句：语音时序、无语音速度、范围余句、流式等待与修订取消。"""
import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.ui.reply_bubble import ReplyBubble


class ReplyBubbleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bubble = Mock()
        self.reply = ReplyBubble(self.bubble)
        self.reply.start()

    def tearDown(self):
        self.reply.stop()
        self.reply.deleteLater()
        self.app.processEvents()

    def test_audio_holds_first_and_only_playback_advances(self):
        self.reply.set_audio_pending(True)
        self.reply.update("第一句。第二句。")
        self.reply.finish("第一句。第二句。末句")
        self.bubble.show_message.assert_called_once_with("第一句。", 0)
        self.assertFalse(self.reply.timer.isActive())
        self.reply._advance()
        self.assertEqual(self.reply.index, 0)
        self.reply.playing("第一句。", 1)
        self.reply.playing("第二句。", 2)
        self.bubble.show_message.assert_called_with("第二句。", 0)
        self.reply.set_audio_pending(False)
        self.assertTrue(self.reply.timer.isActive(), "未朗读的范围外文字仍按速度显示")
        self.reply._advance()
        self.bubble.show_message.assert_called_with("末句", 0)

    def test_fixed_speed_and_new_sentence_after_stream_wait(self):
        text = "这是长度超过短句最小时间限制的第一个句子。"
        self.reply.update(text)
        self.assertEqual(self.reply.timer.interval(), round(len(text) / 6 * 1000))
        self.reply._advance()
        self.assertTrue(self.reply.waiting)
        self.reply.update(text + "接着说。")
        self.bubble.show_message.assert_called_with("接着说。", 0)
        self.assertEqual(self.reply.timer.interval(), 1800)
        self.reply.finish(text + "接着说。")
        self.reply._advance()
        self.assertFalse(self.reply.active)

    def test_revised_reply_restarts_text_and_new_chat_cancels_old(self):
        self.reply.set_audio_pending(True)
        self.reply.update("原第一句。")
        self.reply.finish("修订第一句。修订第二句。")
        self.bubble.show_message.assert_called_with("修订第一句。", 0)
        self.assertFalse(self.reply.audio_pending)
        self.reply.start()
        self.reply.finish("新的回答。")
        self.assertEqual(self.reply.sentences, ["新的回答。"])
        self.reply.stop()
        self.assertFalse(self.reply.timer.isActive())
