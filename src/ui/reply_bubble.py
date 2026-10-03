"""回复气泡逐句展示；语音播放推进，无语音时按固定阅读速度推进。"""
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from src.core.speech_stream import SentenceStream


class ReplyBubble(QObject):
    changed = pyqtSignal()

    def __init__(self, bubble, parent=None):
        super().__init__(parent)
        self.bubble = bubble
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._advance)
        self.stop()

    def stop(self):
        self.timer.stop()
        self.active = self.audio_pending = self.finished = False
        self.waiting = False
        self.stream = SentenceStream()
        self.sentences, self.index = [], -1
        self.changed.emit()

    def start(self):
        self.stop()
        self.active = True
        self.bubble.hide()
        self.changed.emit()

    def update(self, text):
        if self.active and text.startswith(self.stream.raw):
            self._append(self.stream.feed(text[len(self.stream.raw):]))

    def finish(self, text):
        if not self.active:
            return
        sentences = self.stream.finish(text)
        if self.stream.revised:
            self.start()
            sentences = self.stream.finish(text)
        self.finished = True
        self._append(sentences)
        if self.index >= 0 and not self.audio_pending and not self.timer.isActive():
            self._schedule()

    def _append(self, sentences):
        self.sentences.extend(sentences)
        if self.index == -1 and self.sentences:
            self._show(0)
        elif self.waiting and not self.audio_pending and self.index + 1 < len(self.sentences):
            self._show(self.index + 1)

    def set_audio_pending(self, pending):
        if not self.active or self.audio_pending == pending:
            return
        self.audio_pending = pending
        if pending:
            self.timer.stop()
        elif self.index >= 0:
            self._schedule()

    def playing(self, text, segment):
        if not self.active:
            return
        self.timer.stop()
        self.waiting = False
        self.index = max(self.index, segment - 1)
        self.bubble.show_message(text, 0)

    def _show(self, index):
        self.index, self.waiting = index, False
        self.bubble.show_message(self.sentences[index], 0)
        if not self.audio_pending:
            self._schedule()
        self.changed.emit()

    def _schedule(self):
        # 固定每秒 6 字，短句至少保留 1.8 秒。
        text = self.sentences[self.index] if self.index < len(self.sentences) else ""
        self.timer.start(max(1800, round(len(text) / 6 * 1000)))

    def _advance(self):
        if not self.active or self.audio_pending:
            return
        if self.index + 1 < len(self.sentences):
            self._show(self.index + 1)
        elif self.finished:
            self.bubble.hide_timer.start(5000)
            self.active = False
            self.changed.emit()
        else:
            self.waiting = True
