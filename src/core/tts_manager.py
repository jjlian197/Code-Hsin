"""异步合成、语言持久化与按音色隔离的缓存，播放和口型留在 Qt 主线程。"""
import hashlib
from collections import deque
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave

from loguru import logger
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer
from src.core.app_config import PROJECT_ROOT, project_path
from src.core.voice_auxiliary import EdgeSynthesizer, VoiceTranslator


def wave_info(payload):
    with wave.open(io.BytesIO(payload), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or not 0.1 <= duration <= 300:
            raise ValueError("语音服务返回了无效的单声道 PCM 音频")
        return duration


def cache_key(text, language, speed, profile):
    # 内容摘要识别正式权重，文件状态同时防止手动替换权重仍复用旧缓存。
    resources = {key: (str(Path(profile[key]).resolve()), Path(profile[key]).stat().st_size,
                       Path(profile[key]).stat().st_mtime_ns)
                 for key in ("gpt_weights", "sovits_weights", "reference_audio")}
    identity = {"text": text, "language": language, "speed": speed,
                "profile": profile, "resources": resources, "engine": "hsin-v2ProPlus-1"}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class LocalSynthesizer:
    def __init__(self, profiles, runtime, port=19880):
        self.profiles_path = Path(profiles)
        self.runtime = Path(runtime) / "tts"
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.process = None
        self.process_lock = threading.Lock()
        self.closed = threading.Event()

    def health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=2) as response:
            return json.load(response)

    def ensure_server(self, data):
        try:
            health = self.health()
        except (OSError, ValueError):
            health = None
        if health:
            if health.get("service") != "hsin-gptsovits" or health.get("profile_id") != data["profile_id"]:
                raise RuntimeError("心的语音端口已被其他配置占用，请更换 voice.port")
            return
        with self.process_lock:
            if self.closed.is_set():
                raise RuntimeError("语音服务正在退出")
            if self.process is None or self.process.poll() is not None:
                self.runtime.mkdir(parents=True, exist_ok=True)
                temp = self.runtime / "temp"
                temp.mkdir(exist_ok=True)
                env = os.environ.copy()
                env.update(TEMP=str(temp), TMP=str(temp), PYTHONIOENCODING="utf-8",
                           PYTHONPYCACHEPREFIX=str(temp / "pycache"), HF_HOME=str(temp / "hf"),
                           TORCH_HOME=str(temp / "torch"), HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
                env.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
                env["PATH"] = data["installation"]["gptsovits_root"] + os.pathsep + env.get("PATH", "")
                with (self.runtime / "server.log").open("ab") as log:
                    self.process = subprocess.Popen([data["installation"]["python"], "-u", "-s",
                        str(PROJECT_ROOT / "tools/hsin_voice_server.py"), "--profiles", str(self.profiles_path),
                        "--runtime", str(self.runtime), "--port", str(self.port)],
                        cwd=data["installation"]["gptsovits_root"], env=env, stdout=log, stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not self.closed.wait(0.15):
            try:
                health = self.health()
                if health.get("service") == "hsin-gptsovits" and health.get("profile_id") == data["profile_id"]:
                    return
                raise RuntimeError("语音服务身份不匹配")
            except urllib.error.URLError:
                if self.process.poll() is not None:
                    raise RuntimeError("语音服务启动失败，请查看 .runtime/tts/server.log")
        raise RuntimeError("语音服务启动超时或已退出")

    def synthesize(self, text, language, speed):
        data = json.loads(self.profiles_path.read_text(encoding="utf8"))
        profile = data["profiles"][language]
        key = cache_key(text, language, speed, profile)
        cache = self.runtime / "cache" / language
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / (key + ".wav")
        if path.is_file():
            try:
                wave_info(path.read_bytes())
                return path
            except (OSError, ValueError, wave.Error, EOFError):
                path.unlink(missing_ok=True)
        self.ensure_server(data)
        request = urllib.request.Request(self.base + "/tts", data=json.dumps(
            {"text": text, "language": language, "speed": speed}, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = response.read(24 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(8192).decode("utf8", errors="replace")
            raise RuntimeError("语音合成失败：" + detail) from exc
        if len(payload) > 24 * 1024 * 1024:
            raise ValueError("语音结果超过大小限制")
        wave_info(payload)
        temp = path.with_suffix(".part")
        temp.write_bytes(payload)
        temp.replace(path)
        return path

    def close(self):
        self.closed.set()
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self.process = None


class TTSManager(QObject):
    changed = pyqtSignal()
    completed = pyqtSignal(int, object, object)
    speech_started = pyqtSignal(str)
    failed = pyqtSignal(str)
    stage_changed = pyqtSignal(int, str)

    def __init__(self, config, player, parent=None):
        super().__init__(parent)
        voice = config["voice"]
        self.player = player
        self.language = voice.get("language", "zh")
        self.enabled = voice.get("enabled", False)
        self.volume = voice.get("volume", 0.65)
        self.engine = voice.get("provider", "gptsovits")
        self.auto_translate = voice.get("auto_translate", False)
        self.fallback = voice.get("fallback", False)
        self.profiles_path = project_path(voice.get("profiles", "voice/profiles.json"))
        self.state_path = project_path(config["runtime"]["directory"]) / "voice.json"
        try:
            state = json.loads(self.state_path.read_text(encoding="utf8"))
            if not isinstance(state, dict):
                raise ValueError("语音状态需要对象")
            if state.get("language") in ("zh", "ja"):
                self.language = state["language"]
            if type(state.get("enabled")) is bool:
                self.enabled = state["enabled"]
            if state.get("provider") in ("gptsovits", "edge"):
                self.engine = state["provider"]
            for name in ("auto_translate", "fallback"):
                if type(state.get(name)) is bool:
                    setattr(self, name, state[name])
        except (OSError, ValueError):
            pass
        self.provider = LocalSynthesizer(self.profiles_path, self.state_path.parent, voice.get("port", 19880))
        self.edge = EdgeSynthesizer(self.state_path.parent)
        self.translator = VoiceTranslator(config, self.state_path.parent)
        self.generation = 0
        self.error = None
        self.busy = False
        self.last_request = None
        self.actual_provider = None
        self.warning = None
        self.stage = "idle"
        self._closed = False
        self._condition = threading.Condition()
        self._jobs = deque()
        self._ready = deque()
        self._pending = self._prefetched = self._sequence = 0
        self._playing = self._starting = self._finishing = False
        self._stream = None
        self._stream_open = False
        self._stream_language = None
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self.stage_changed.connect(self._stage, Qt.ConnectionType.QueuedConnection)
        if hasattr(self.player, "player"):
            self.player.player.playbackStateChanged.connect(self._playback_state)
            self.player.player.errorOccurred.connect(self._playback_error)
        self._worker = threading.Thread(target=self._work, name="HsinTTS", daemon=True)
        self._worker.start()

    def snapshot(self):
        available = {"gptsovits": self.profiles_path.is_file(), "edge": self.edge.available()}
        configured = available[self.engine] or (self.fallback and any(available.values()))
        return {"enabled": self.enabled, "configured": configured,
                "language": self.language, "languages": ["zh", "ja"], "provider": self.engine,
                "providers": available, "actual_provider": self.actual_provider,
                "auto_translate": self.auto_translate, "fallback": self.fallback,
                "stage": self.stage, "warning": self.warning,
                "synthesizing": self.busy, "last_request": self.last_request, "error": self.error,
                "streaming": self._stream is not None, "stream_open": self._stream_open,
                "queued_segments": self._pending, "ready_segments": len(self._ready),
                "active": self.busy or bool(self._ready) or self._playing or self._finishing}

    def configure(self, language=None, enabled=None, provider=None, auto_translate=None, fallback=None):
        if language is not None and language not in ("zh", "ja"):
            raise ValueError("语言需要 zh 或 ja")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled 需要布尔值")
        if provider is not None and provider not in ("gptsovits", "edge"):
            raise ValueError("provider 需要 gptsovits 或 edge")
        for name, value in (("auto_translate", auto_translate), ("fallback", fallback)):
            if value is not None and type(value) is not bool:
                raise ValueError(name + " 需要布尔值")
        settings = {"language": language, "enabled": enabled, "provider": provider,
                    "auto_translate": auto_translate, "fallback": fallback}
        if enabled is False or any(value is not None and value != getattr(self, "engine" if name == "provider" else name)
                                  for name, value in settings.items()):
            self.stop()
        if language is not None:
            self.language = language
        if enabled is not None:
            self.enabled = enabled
        if provider is not None:
            self.engine = provider
        if auto_translate is not None:
            self.auto_translate = auto_translate
        if fallback is not None:
            self.fallback = fallback
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"language": self.language, "enabled": self.enabled,
            "provider": self.engine, "auto_translate": self.auto_translate, "fallback": self.fallback}), encoding="utf8")
        temp.replace(self.state_path)
        self.changed.emit()
        return self.snapshot()

    def speak(self, text, language=None, speed=1.0, volume=None, translate=None):
        if not self.snapshot()["configured"]:
            raise ValueError("所选语音引擎尚未就绪")
        if not self.enabled:
            raise ValueError("语音已关闭，请先开启语音")
        language = self.language if language is None else language
        if language not in ("zh", "ja") or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            raise ValueError("需要 zh/ja 语言和 1–500 字符的文本")
        if type(speed) not in (int, float) or not 0.5 <= speed <= 2:
            raise ValueError("语速需要在 0.5–2 之间")
        volume = self.volume if volume is None else volume
        if type(volume) not in (int, float) or not 0 <= volume <= 1:
            raise ValueError("音量需要在 0–1 之间")
        if translate is not None and type(translate) is not bool:
            raise ValueError("translate 需要布尔值")
        self.stop()
        translate = self.auto_translate if translate is None else translate
        return self._submit(text.strip(), language, speed, volume, translate)

    def begin_stream(self, language):
        if language not in ("zh", "ja"):
            raise ValueError("语言需要 zh 或 ja")
        self.stop()
        self._stream, self._stream_language = self.generation, language
        self._stream_open = True
        return self._stream

    def enqueue_sentence(self, token, text, language):
        if self._closed or not self.enabled or self._stream != token or self.generation != token or not self._stream_open:
            return False
        if language != self._stream_language or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            return False
        self._submit(text.strip(), language, 1.0, self.volume, False)
        return True

    def finish_stream(self, token):
        if self._stream == token and self.generation == token:
            self._stream_open = False
            self._finish_if_idle()
            self.changed.emit()

    def _submit(self, text, language, speed, volume, translate):
        self._pending += 1
        self._sequence += 1
        self.busy = True
        self.error = None
        if self._sequence == 1:
            self.warning = self.actual_provider = None
        self.stage = "queued"
        self.last_request = {"id": self.generation, "text": text, "language": language,
                             "provider": self.engine, "translate": translate, "segment": self._sequence,
                             "stream": self._stream is not None}
        with self._condition:
            self._jobs.append((self.generation, text, language, speed, volume, self.engine, translate, self.fallback, dict(self.last_request)))
            self._condition.notify()
        self.changed.emit()
        return dict(self.last_request)

    def _work(self):
        while True:
            with self._condition:
                # 当前句播放时最多预合成两句，避免长回复一次占满缓存/显存。
                self._condition.wait_for(lambda: self._jobs and self._prefetched < 2 or self._closed)
                if self._closed:
                    return
                job = self._jobs.popleft()
                self._prefetched += 1
            generation, text, language, speed, volume, engine, translate, fallback, request = job
            try:
                spoken = text
                if translate:
                    self.stage_changed.emit(generation, "translating")
                    spoken = self.translator.translate(text, language)
                if self._closed or generation != self.generation:
                    continue
                providers = {"gptsovits": self.provider, "edge": self.edge}
                warning = None
                self.stage_changed.emit(generation, "synthesizing")
                try:
                    path = providers[engine].synthesize(spoken, language, speed)
                except Exception as primary_error:
                    if self._closed or generation != self.generation:
                        continue
                    if not fallback:
                        raise
                    alternate = "edge" if engine == "gptsovits" else "gptsovits"
                    self.stage_changed.emit(generation, "fallback")
                    try:
                        path = providers[alternate].synthesize(spoken, language, speed)
                    except Exception as backup_error:
                        raise RuntimeError(f"首选和备用语音均失败：{primary_error}；{backup_error}") from backup_error
                    warning = "心的音色暂不可用，已使用 Edge 通用音色" if alternate == "edge" else "Edge 暂不可用，已使用心的音色"
                    engine = alternate
                if not self._closed and generation == self.generation:
                    self.completed.emit(generation, (path, spoken, volume, engine, warning, request), None)
            except Exception as exc:
                if not self._closed:
                    logger.warning("心的语音合成失败：{}", exc)
                    self.completed.emit(generation, None, str(exc))

    def _complete(self, generation, result, error):
        if self._closed or generation != self.generation:
            return
        self._pending -= 1
        self.busy = self._pending > 0
        self.stage = "queued" if self.busy else "idle"
        self.error = error
        if self.error:
            self.stop()
            self.failed.emit(self.error)
        elif result:
            self._ready.append(result)
            self._play_next()
        self.changed.emit()

    def _play_next(self):
        if self._closed or self._playing or self._finishing or not self._ready:
            self._finish_if_idle()
            return
        path, text, volume, self.actual_provider, self.warning, request = self._ready.popleft()
        with self._condition:
            self._prefetched -= 1
            self._condition.notify()
        self.last_request = dict(request, spoken_text=text)
        self._playing = self._starting = True
        try:
            self.player.play(path, volume)
            self.speech_started.emit(text)
        except Exception as exc:
            self.error = str(exc)
            self.stop()
            self.failed.emit(self.error)
        finally:
            self._starting = False
        if not self.busy and self._playing:
            self.stage = "playing"

    def _playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.StoppedState and self._playing and not self._starting:
            self._playing = False
            self._finishing = True
            token = self.generation
            # 同一轮事件中的解码错误优先取消队列，不能误播下一句。
            QTimer.singleShot(0, lambda: self._after_playback(token))

    def _after_playback(self, token):
        if token == self.generation and not self._closed:
            self._finishing = False
            self._play_next()
            self.changed.emit()

    def _playback_error(self, _error, message):
        if self._playing or self._finishing or self._pending or self._ready:
            self.error = message or "音频播放失败"
            self.stop()
            self.failed.emit(self.error)

    def _finish_if_idle(self):
        if not self.busy and not self._ready and not self._playing and not self._finishing:
            if not self._stream_open:
                self._stream = None
            self.stage = "waiting" if self._stream_open else "idle"

    def _stage(self, generation, stage):
        if not self._closed and generation == self.generation and self.busy:
            self.stage = stage
            self.changed.emit()

    def stop(self):
        self.generation += 1
        with self._condition:
            self._jobs.clear()
            self._prefetched = 0
            self._condition.notify()
        self._ready.clear()
        self._pending = self._sequence = 0
        self._stream = self._stream_language = None
        self._stream_open = self._playing = self._finishing = False
        self.busy = False
        self.stage = "idle"
        self.player.stop()
        self.changed.emit()

    def close(self):
        self.stop()
        with self._condition:
            self._closed = True
            self._condition.notify()
        self.provider.close()
        self.edge.close()
