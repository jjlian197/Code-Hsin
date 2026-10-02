"""本地原声播放：以实际解码的 PCM 音量驱动口型，不依赖文字时长猜测。"""
from array import array
import math
import sys

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaPlayer


def pcm_level(data, sample_format):
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        samples = [(v - 128) / 128 for v in data]
    else:
        types = {QAudioFormat.SampleFormat.Int16: ("h", 32768),
                 QAudioFormat.SampleFormat.Int32: ("i", 2147483648),
                 QAudioFormat.SampleFormat.Float: ("f", 1)}
        if sample_format not in types:
            return 0.0
        code, scale = types[sample_format]
        values = array(code)
        values.frombytes(data)
        if sys.byteorder != "little":
            values.byteswap()
        samples = [float(v) / scale for v in values]
    if not samples:
        return 0.0
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    # 原声静音阈值与柔和增益，避免轻微底噪也让嘴持续张开。
    return min(1.0, max(0.0, (rms - 0.008) * 7))


class LocalVoicePlayer(QObject):
    level_changed = pyqtSignal(float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(0.65)
        self.player.setAudioOutput(self.output)
        self.buffers = QAudioBufferOutput(self)
        self.player.setAudioBufferOutput(self.buffers)
        self.buffers.audioBufferReceived.connect(self._buffer_received)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._error)
        self.path = None
        self.error = None
        self.buffer_count = 0
        self.last_level = 0.0
        self.peak_level = 0.0

    def play(self, path, volume=0.65):
        if not path.is_file() or path.suffix.lower() not in {".wav", ".opus", ".ogg", ".mp3", ".flac", ".m4a"}:
            raise ValueError("需要存在的本地音频文件")
        self.stop()
        self.path = path
        self.error = None
        self.buffer_count = 0
        self.peak_level = 0.0
        self.output.setVolume(volume)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def stop(self):
        self.player.stop()
        self.last_level = 0.0
        self.level_changed.emit(0.0, False)

    def _buffer_received(self, buffer):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            # 停止后可能还有已排队的解码回调，不让旧缓冲重新张嘴。
            self.last_level = 0.0
            self.level_changed.emit(0.0, False)
            return
        if not buffer.isValid() or not buffer.byteCount():
            self.level_changed.emit(0.0, False)
            return
        data = buffer.constData().asstring(buffer.byteCount())
        self.last_level = pcm_level(data, buffer.format().sampleFormat())
        self.buffer_count += 1
        self.peak_level = max(self.peak_level, self.last_level)
        self.level_changed.emit(self.last_level, True)

    def _state_changed(self, state):
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self.last_level = 0.0
            self.level_changed.emit(0.0, False)

    def _error(self, error, message):
        self.error = message
        self.last_level = 0.0
        self.level_changed.emit(0.0, False)

    def snapshot(self):
        return {"state": self.player.playbackState().name, "path": str(self.path) if self.path else None,
                "position_ms": self.player.position(), "duration_ms": self.player.duration(), "error": self.error,
                "buffer_count": self.buffer_count, "level": self.last_level, "peak_level": self.peak_level}

    def cleanup(self):
        self.stop()
        self.player.setSource(QUrl())
