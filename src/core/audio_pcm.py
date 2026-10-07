"""将设备原生 PCM 连续转换为 ASR 的 16kHz 单声道 int16；不保存录音。"""
from array import array
import math


class SpeechPCMConverter:
    def __init__(self, sample_rate: int, channels: int, sample_format: str) -> None:
        formats = {"Int16": ("h", 32768.0), "Int32": ("i", 2147483648.0),
                   "Float": ("f", 1.0), "UInt8": ("B", 128.0)}
        if sample_rate <= 0 or channels <= 0 or sample_format not in formats:
            raise ValueError("不支持的麦克风录音格式")
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_format = sample_format
        self._typecode, self._scale = formats[sample_format]
        self._frame_bytes = array(self._typecode).itemsize * channels
        self._pending_bytes = bytearray()
        self._samples: list[float] = []
        self._position = 0.0

    def feed(self, captured_pcm: bytes) -> bytes:
        self._pending_bytes.extend(captured_pcm)
        complete_bytes = len(self._pending_bytes) // self._frame_bytes * self._frame_bytes
        if not complete_bytes:
            return b""
        values = array(self._typecode, self._pending_bytes[:complete_bytes])
        del self._pending_bytes[:complete_bytes]
        for offset in range(0, len(values), self.channels):
            mixed = sum(values[offset:offset + self.channels]) / self.channels
            if self.sample_format == "UInt8":
                mixed -= 128
            normalized = mixed / self._scale
            self._samples.append(normalized if math.isfinite(normalized) else 0.0)
        converted = array("h")
        step = self.sample_rate / 16000
        # 保留分数位置与相邻样本，避免每次 readyRead 重新采样造成断裂/时长漂移。
        while self._position + 1 < len(self._samples):
            index = int(self._position)
            fraction = self._position - index
            value = self._samples[index] * (1 - fraction) + self._samples[index + 1] * fraction
            converted.append(max(-32768, min(32767, round(value * 32768))))
            self._position += step
        consumed = min(int(self._position), len(self._samples))
        del self._samples[:consumed]
        self._position -= consumed
        return converted.tobytes()
