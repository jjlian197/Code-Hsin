"""完整语音往返结束后保温，再释放自己管理的ASR/GPT进程。"""
import threading
import time

from loguru import logger
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal


class VoiceIdleRelease(QObject):
    completed = pyqtSignal(object)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.since = time.monotonic()
        self.pending = self.closed = False
        self.release_count = 0
        self.last_release = {}
        self.allowed = threading.Event()
        self.worker = None
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        for signal in (owner.chat.changed, owner.stt.changed, owner.tts.changed,
                       owner.voice_player.player.playbackStateChanged):
            signal.connect(self.activity)

    def busy(self):
        tts = self.owner.tts
        return (self.owner._rest_activity_busy() or tts._stream_open
                or tts.model_work_active.is_set() or tts._warmup_language is not None)

    def activity(self, *_):
        self.since = time.monotonic()
        self.allowed.clear()

    def tick(self):
        seconds = self.owner.config.get('runtime', {}).get('model_idle_seconds', 600)
        if self.closed or not seconds or self.busy():
            self.activity()
            return
        if self.pending or time.monotonic() - self.since < seconds:
            return
        recognizer = self.owner.stt._recognizer
        qwen = getattr(recognizer, '_qwen', None)
        if not (qwen and qwen.process is not None or self.owner.tts.provider.process is not None):
            return
        self.allowed.set()
        self.pending = True
        def release():
            result = {}
            try:
                if self.allowed.is_set() and not self.closed:
                    result['asr'] = recognizer.release_idle()
                if self.allowed.is_set() and not self.closed:
                    result['gptsovits'] = self.owner.tts.provider.release_idle()
            except Exception as error:
                logger.warning('本地语音模型闲置释放失败：{}', error)
            if not self.closed:
                self.completed.emit(result)
        self.worker = threading.Thread(target=release, name='VoiceIdleRelease', daemon=True)
        self.worker.start()

    def _complete(self, result):
        if self.closed:
            return
        self.pending = False
        self.last_release = result
        self.since = time.monotonic()
        if any(result.values()):
            self.release_count += 1
        tts = self.owner.tts
        if (result.get('gptsovits') and tts.engine == 'gptsovits' and tts.provider.process is None
                and not tts.model_work_active.is_set() and tts._warmup_language is None):
            # 不立即预热，否则刚释放就会再次占用；下次请求自然重新加载。
            tts.warmup_state, tts.warmup_error = 'idle', None
            tts.changed.emit()

    def close(self):
        self.closed = True
        self.allowed.clear()
        self.timer.stop()
        if self.worker:
            self.worker.join(timeout=5)
