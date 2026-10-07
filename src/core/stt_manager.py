"""Qt 麦克风采集、VAD 断句及异步识别，所有界面回调返回 Qt 主线程。"""
from array import array
from collections import deque
from copy import deepcopy
import math
import sys
import threading
import time

from PyQt6.QtCore import QCoreApplication, QMicrophonePermission, QObject, QTimer, Qt, pyqtSignal
from loguru import logger
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices
from src.core.speech_recognizer import SpeechRecognizer
from src.core.stt_hotwords import hotwords
from src.core.audio_pcm import SpeechPCMConverter


def validate_stt(config):
    if not isinstance(config, dict):
        raise ValueError("stt 需要配置对象")
    hotwords(config)
    if config.get("provider", "auto") not in {"auto", "zhipu", "qwen", "remote"}:
        raise ValueError("识别引擎需要 auto、zhipu、qwen 或 remote")
    if config.get("provider") == "qwen":
        from src.core.app_config import validate_qwen
        validate_qwen(config.get("qwen"), ("python", "model", "gpu"))
    if config.get("language", "zh") not in {"auto", "zh", "ja"}:
        raise ValueError("识别语言需要 auto、zh 或 ja")
    for name in ("device",):
        if not isinstance(config.get(name, ""), str):
            raise ValueError(f"stt.{name} 需要字符串")
    for name, lower, upper, default in (("silence_ms", 300, 2000, 700), ("energy_threshold", 50, 5000, 250)):
        value = config.get(name, default)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"stt.{name} 需要 {lower}–{upper} 的整数")
    zhipu = config.get("zhipu", {})
    if not isinstance(zhipu, dict) or not isinstance(zhipu.get("api_key", ""), str):
        raise ValueError("stt.zhipu.api_key 需要字符串")


class VadSegmenter:
    """20ms 帧，300ms 前滚/最短语音，700ms 停顿，最长 25 秒。"""
    def __init__(self, is_speech, silence_ms=700):
        self.is_speech = is_speech
        self.silence_frames = math.ceil(silence_ms / 20)
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=15)
        self.frames = []
        self.speech_frames = 0
        self.silence_run = 0

    @property
    def active(self):
        return bool(self.frames)

    def feed(self, frame):
        if len(frame) != 640:
            raise ValueError("VAD 需要完整的 20ms PCM 帧")
        speech = self.is_speech(frame)
        if not self.frames:
            if not speech:
                self.preroll.append(frame)
                return None
            self.frames = list(self.preroll)
            self.preroll.clear()
        self.frames.append(frame)
        self.speech_frames += int(speech)
        self.silence_run = 0 if speech else self.silence_run + 1
        if len(self.frames) >= 1250 or self.silence_run >= self.silence_frames:
            result = b"".join(self.frames) if self.speech_frames >= 15 else None
            self.reset()
            return result
        return None


class STTManager(QObject):
    changed = pyqtSignal()
    transcript = pyqtSignal(str)
    failed = pyqtSignal(str)
    completed = pyqtSignal(int, object, object)

    def __init__(self, config, parent=None, recognizer=None):
        super().__init__(parent)
        self.config = deepcopy(config.get("stt", {}))
        if self.config.get("provider") == "whisper":
            self.config["provider"] = "qwen"
        self.config.pop("model_path", None)
        self.config.pop("fallback", None)
        validate_stt(self.config)
        self.config["hotwords"] = hotwords(self.config)
        self.enabled = False  # 每次启动都由用户主动开麦。
        self.blocked = False
        self.busy = False
        self.error = ""
        self.warning = ""
        self.last_text = ""
        self.actual_provider = ""
        self.level = 0.0
        self.permission = "unchecked"
        self._permission_pending = False
        self._capture_started = 0.0
        self._received_bytes = 0
        self._last_meter_update = 0.0
        self._pcm_converter = None
        self.capture_format = ""
        self.source = self.io = None
        self._buffer = bytearray()
        self._generation = 0
        self._closed = False
        self._cooldown = 0.0
        self._recognizer = recognizer or SpeechRecognizer(config.get("runtime", {}).get("directory"), config.get("speech_bridge", {}))
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(2)
        except ImportError:
            self._vad = None
        self._segmenter = VadSegmenter(self._is_speech, self.config.get("silence_ms", 700))
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._tick)

    @staticmethod
    def devices():
        return [{"id": bytes(device.id()).hex(), "name": device.description(), "default": device.isDefault()}
                for device in QMediaDevices.audioInputs()]

    def snapshot(self):
        from src.core.app_config import project_path
        qwen = self.config.get("qwen", {})
        local_ready = (project_path(qwen.get("python", "")).is_file() and
            (project_path(qwen.get("model", "")) / "config.json").is_file()) if self.config.get("provider") == "qwen" else False
        return {"enabled": self.enabled, "listening": self.source is not None,
                "recognizing": self.busy, "blocked": self.blocked,
                "speech_active": self._segmenter.active, "level": round(self.level, 3),
                "permission": self.permission, "received_bytes": self._received_bytes,
                "capture_format": self.capture_format,
                "provider": self.config.get("provider", "auto"),
                "actual_provider": self.actual_provider or SpeechRecognizer.provider(self.config),
                "language": self.config.get("language", "zh"), "device": self.config.get("device", ""),
                "hotwords": list(self.config["hotwords"]),
                "last_text": self.last_text, "error": self.error, "warning": self.warning,
                "cloud_configured": bool(SpeechRecognizer.key(self.config)),
                "local_installed": local_ready}

    def configure(self, enabled=None, **settings):
        if self._closed:
            raise ValueError("语音识别正在退出")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled 需要布尔值")
        if any(key not in {"provider", "language", "device", "silence_ms", "energy_threshold", "zhipu", "hotwords", "qwen"} for key in settings):
            raise ValueError("未知语音识别设置")
        candidate = {**self.config, **deepcopy(settings)}
        validate_stt(candidate)
        candidate["hotwords"] = hotwords(candidate)
        changing = candidate != self.config
        stopping = enabled is False
        if changing or stopping:
            self._generation += 1  # 关麦/切换后，迟到的识别结果一律丢弃。
            self._stop_capture()
            if hasattr(self._recognizer, "cancel"):
                self._recognizer.cancel()
        self.config = candidate
        if changing:
            self._segmenter = VadSegmenter(self._is_speech, candidate.get("silence_ms", 700))
        if enabled is not None:
            self.enabled = enabled
        self.error = self.warning = ""
        if self.enabled:
            self.timer.start()
            self._tick()
        else:
            self.timer.stop()
        self.changed.emit()
        return self.snapshot()

    def set_blocked(self, blocked):
        blocked = bool(blocked)
        if blocked == self.blocked or self._closed:
            return
        self.blocked = blocked
        if blocked:
            self._generation += 1
            self._stop_capture()
            if hasattr(self._recognizer, "cancel"):
                self._recognizer.cancel()
        else:
            self._cooldown = time.monotonic() + 0.7
        self.changed.emit()

    def _tick(self):
        if self._closed or not self.enabled or self.blocked or self.busy or time.monotonic() < self._cooldown:
            return
        if self.source is None:
            self._start_capture()
        else:
            # 部分原生后端的 readyRead 通知不可靠；定时排空同一个 IO，不重复采集。
            self._read_audio()
            if not self._received_bytes and time.monotonic() - self._capture_started > 5:
                self._fail("麦克风已打开但没有收到音频，请检查系统麦克风权限与输入设备")
            elif time.monotonic() - self._last_meter_update >= 0.25:
                self._last_meter_update = time.monotonic()
                self.changed.emit()

    def _microphone_permission_ready(self) -> bool:
        if sys.platform != "darwin":
            return True
        application = QCoreApplication.instance()
        microphone_permission = QMicrophonePermission()
        status = application.checkPermission(microphone_permission)
        self.permission = status.name.lower()
        if status == Qt.PermissionStatus.Granted:
            return True
        if status == Qt.PermissionStatus.Denied:
            self._fail("麦克风权限未授权，请在系统设置 → 隐私与安全性 → 麦克风中允许心，然后重新开麦")
        elif not self._permission_pending:
            # 仅在用户主动开麦后申请；授权回调不能让已关麦/退出的任务重新启动。
            self._permission_pending = True
            application.requestPermission(microphone_permission, self._permission_completed)
            self.changed.emit()
        return False

    def _permission_completed(self, permission: QMicrophonePermission) -> None:
        self._permission_pending = False
        if not self._closed and self.enabled:
            self._tick()

    def _start_capture(self):
        if not self._microphone_permission_ready():
            return
        devices = QMediaDevices.audioInputs()
        selected = self.config.get("device", "")
        device = next((d for d in devices if bytes(d.id()).hex() == selected), None) if selected else QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            self._fail("没有可用麦克风，请检查 系统录音权限和麦克风设置")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        # macOS 设备虽可能宣称支持 16kHz，实际 CoreAudio 输入使用原生格式更可靠。
        if sys.platform == "darwin" or not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        if not device.isFormatSupported(fmt):
            self._fail("所选麦克风没有可用录音格式，请换一个输入设备")
            return
        self._pcm_converter = SpeechPCMConverter(fmt.sampleRate(), fmt.channelCount(), fmt.sampleFormat().name)
        self.capture_format = f"{fmt.sampleRate()}Hz/{fmt.channelCount()}ch/{fmt.sampleFormat().name}"
        self.source = QAudioSource(device, fmt, self)
        self.source.setBufferSize(fmt.bytesForDuration(200000))
        self.source.stateChanged.connect(self._audio_state)
        self._received_bytes = 0
        self._capture_started = time.monotonic()
        self.io = self.source.start()
        if self.io is None or self.source is None or self.source.error() != QAudio.Error.NoError:
            self._fail("麦克风打开失败，请检查 系统麦克风权限或设备占用")
            return
        self.io.readyRead.connect(self._read_audio)
        logger.info("STT capture started: device={}, permission={}, format={}",
                    device.description(), self.permission, self.capture_format)
        self.changed.emit()

    def _audio_state(self, state):
        if self.source and state == QAudio.State.StoppedState and self.source.error() != QAudio.Error.NoError:
            self._fail("麦克风已断开或录音失败，请重新选择输入设备")

    def _stop_capture(self):
        source, self.source = self.source, None
        self.io = None
        if source:
            source.stop()
            source.deleteLater()
        self._buffer.clear()
        self._segmenter.reset()
        self.level = 0.0
        self._pcm_converter = None

    def _is_speech(self, frame):
        samples = array("h", frame)
        rms = math.sqrt(sum(v * v for v in samples) / len(samples))
        self.level = min(1.0, rms / 5000)
        return rms >= self.config.get("energy_threshold", 250) and (self._vad is None or self._vad.is_speech(frame, 16000))

    def _read_audio(self):
        if self.io is None or self.blocked or self.busy or not self.enabled:
            return
        captured_pcm = bytes(self.io.readAll())
        self._received_bytes += len(captured_pcm)
        self.feed_pcm(self._pcm_converter.feed(captured_pcm) if self._pcm_converter else captured_pcm)

    def feed_pcm(self, pcm):
        """共用录音帧入口，供原生回归用固定语音验证断句与对话链路。"""
        if self._closed or not self.enabled or self.blocked or self.busy or time.monotonic() < self._cooldown:
            return
        self._buffer.extend(pcm)
        while len(self._buffer) >= 640:
            frame = bytes(self._buffer[:640])
            del self._buffer[:640]
            utterance = self._segmenter.feed(frame)
            if utterance:
                self._submit(utterance)
                break

    def _submit(self, pcm):
        logger.info("STT utterance submitted: provider={}, seconds={:.2f}",
                    SpeechRecognizer.provider(self.config), len(pcm) / 32000)
        self.busy = True
        self._stop_capture()
        token = self._generation
        config = deepcopy(self.config)
        self.changed.emit()
        def worker():
            try:
                result = self._recognizer.transcribe(pcm, config)
                error = None
            except (ValueError, RuntimeError) as exc:
                result, error = None, str(exc)
            except Exception:
                result, error = None, "语音识别失败，请检查识别设置"
            if not self._closed:
                self.completed.emit(token, result, error)
        threading.Thread(target=worker, name="HsinSTT", daemon=True).start()

    def _complete(self, token, result, error):
        self.busy = False
        if self._closed:
            return
        if token != self._generation or not self.enabled or self.blocked:
            self.changed.emit()
            return
        if error:
            self._fail(error)
            return
        text, self.actual_provider, self.warning = result
        self.last_text = text
        self.changed.emit()
        if text:
            self.transcript.emit(text)
        self._cooldown = time.monotonic() + 0.7

    def _fail(self, error):
        logger.warning("STT failed: {}", error)
        self._generation += 1
        self.enabled = False
        self.error = error
        self.timer.stop()
        self._stop_capture()
        self.changed.emit()
        self.failed.emit(error)

    def close(self):
        self._closed = True
        self.enabled = False
        self._generation += 1
        self.timer.stop()
        self._stop_capture()
        self._recognizer.close()
