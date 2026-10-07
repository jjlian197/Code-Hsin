"""异步合成、语言持久化与按音色隔离的缓存，播放和口型留在 Qt 主线程。"""
from collections import deque
from copy import deepcopy
import json
import threading

from loguru import logger
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer
from src.core.app_config import project_path
from src.core.voice_auxiliary import EdgeSynthesizer, VoiceTranslator

# 保留旧导入路径，桌面与无 Qt 的 PC 服务共用同一套音频校验/合成逻辑。
from src.core.local_synthesizer import LocalSynthesizer, cache_key, wave_info


class TTSManager(QObject):
    changed = pyqtSignal()
    completed = pyqtSignal(int, object, object)
    speech_started = pyqtSignal(str)
    failed = pyqtSignal(str)
    stage_changed = pyqtSignal(int, str)
    warmup_completed = pyqtSignal(int, str, object)

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
            if state.get("provider") in ("gptsovits", "edge", "qwen", "remote"):
                self.engine = state["provider"]
            for name in ("auto_translate", "fallback"):
                if type(state.get(name)) is bool:
                    setattr(self, name, state[name])
        except (OSError, ValueError):
            pass
        self.provider = LocalSynthesizer(self.profiles_path, self.state_path.parent, voice.get("port", 19880))
        from src.core.qwen_voice import QwenSynthesizer
        from src.core.app_config import DEFAULT_CONFIG
        self.qwen = QwenSynthesizer(voice.get("qwen", DEFAULT_CONFIG["voice"]["qwen"]), self.profiles_path, self.state_path.parent)
        from src.core.remote_voice import RemoteSynthesizer
        self._remote_settings = deepcopy(config.get("speech_bridge", {}))
        self.remote_voice = voice.get("remote_voice", "hsin")
        self.remote = RemoteSynthesizer(self._remote_settings, self.state_path.parent, self.remote_voice)
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
        self.model_work_active = threading.Event()
        self._jobs = deque()
        self._ready = deque()
        self._pending = self._prefetched = self._sequence = 0
        self._playing = self._starting = self._finishing = False
        self._announced = False
        self._stream = None
        self._stream_source = None
        self._playing_segment = None
        self._playing_text = ""
        self._stream_open = False
        self._stream_language = None
        self._warmup_language = self._warmup_target = None
        self._prewarm_enabled = False
        self._resource_identity = (str(self.profiles_path), json.dumps(voice.get("qwen", {}), sort_keys=True), voice.get("port", 19880), True, self.remote_voice)
        self._resources_pending = None
        self.warmup_state, self.warmup_error = "idle", None
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self.stage_changed.connect(self._stage, Qt.ConnectionType.QueuedConnection)
        self.warmup_completed.connect(self._warmup_complete, Qt.ConnectionType.QueuedConnection)
        if hasattr(self.player, "player"):
            self.player.player.playbackStateChanged.connect(self._playback_state)
            self.player.player.errorOccurred.connect(self._playback_error)
        self._worker = threading.Thread(target=self._work, name="HsinTTS", daemon=True)
        self._worker.start()

    def snapshot(self):
        available = {"gptsovits": self.profiles_path.is_file() or self.provider.presets.available(), "edge": self.edge.available(), "qwen": self.qwen.available(), "remote": self.remote.available()}
        configured = available[self.engine] or (self.fallback and self.engine in ("gptsovits", "edge")
                                               and (available["gptsovits"] or available["edge"]))
        return {"enabled": self.enabled, "configured": configured,
                "language": self.language, "languages": ["zh", "ja"], "provider": self.engine,
                "providers": available, "actual_provider": self.actual_provider, "remote_voice": self.remote_voice,
                "preset_voice": self.provider.presets.available(), "trained_voice": self.profiles_path.is_file(),
                "auto_translate": self.auto_translate, "fallback": self.fallback,
                "stage": self.stage, "warning": self.warning,
                "synthesizing": self.busy, "last_request": self.last_request, "error": self.error,
                "streaming": self._stream is not None, "stream_open": self._stream_open,
                "queued_segments": self._pending, "ready_segments": len(self._ready),
                "playing_segment": self._playing_segment if self._playing else None, "playing_text": self._playing_text if self._playing else "",
                "warmup": {"state": self.warmup_state, "language": self._warmup_target, "error": self.warmup_error},
                "active": self.busy or bool(self._ready) or self._playing or self._finishing}

    def prewarm(self):
        self._prewarm_enabled = True
        if self.engine == "gptsovits" and not self.profiles_path.is_file():
            return  # 仅预存台词时无需启动不存在的推理环境。
        if self._closed or self.engine not in ("gptsovits", "qwen", "remote") or not self.snapshot()["configured"]:
            return
        if self._warmup_target == self.language and self.warmup_state in {"warming", "ready"}:
            return
        self._warmup_target = self.language
        self.warmup_state, self.warmup_error = "warming", None
        with self._condition:
            self._warmup_language = self.language
            self._condition.notify()
        self.changed.emit()

    def _warmup_complete(self, generation, language, error):
        if self._closed or generation != self.generation or language != self._warmup_target:
            return
        self.warmup_state, self.warmup_error = ("failed" if error else "ready"), error
        self.changed.emit()

    def configure(self, language=None, enabled=None, provider=None, auto_translate=None, fallback=None):
        if language is not None and language not in ("zh", "ja"):
            raise ValueError("语言需要 zh 或 ja")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled 需要布尔值")
        if provider is not None and provider not in ("gptsovits", "edge", "qwen", "remote"):
            raise ValueError("provider 需要 gptsovits、edge、qwen 或 remote")
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
            if self.engine == "qwen" and provider != "qwen":
                self.qwen.cancel()
            self.engine = provider
            self._warmup_target = None
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
        # 语言改变会让窗口停止旧对话，先完成该清理，再排入新语言预热。
        if self._prewarm_enabled:
            self.prewarm()
        return self.snapshot()

    def configure_resources(self, voice, *, presets=True):
        """音色更换与合成在同一工作线程串行；旧任务仍由generation失效。"""
        voice_id = voice.get("remote_voice", "hsin")
        identity = (str(project_path(voice["profiles"])), json.dumps(voice["qwen"], sort_keys=True), voice["port"], presets, voice_id)
        if identity == self._resource_identity:
            return
        self.stop()
        self.profiles_path = project_path(voice["profiles"])
        self._resource_identity = identity
        self.remote_voice = voice_id
        self._warmup_target = None
        self.warmup_state = "idle"
        with self._condition:
            self._resources_pending = (self.profiles_path, dict(voice["qwen"]), voice["port"], presets, voice_id)
            self._condition.notify()

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

    def begin_stream(self, language, *, source="chat"):
        if language not in ("zh", "ja"):
            raise ValueError("语言需要 zh 或 ja")
        self.stop()
        self._stream, self._stream_language = self.generation, language
        self._stream_source = source
        self._stream_open = True
        return self._stream

    def enqueue_sentence(self, token, text, language, *, translate=False):
        if self._closed or not self.enabled or self._stream != token or self.generation != token or not self._stream_open:
            return False
        if language != self._stream_language or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            return False
        self._submit(text.strip(), language, 1.0, self.volume, translate)
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
        self.last_request["source"] = self._stream_source if self._stream is not None else "speak"
        with self._condition:
            self._jobs.append((self.generation, text, language, speed, volume, self.engine, translate, self.fallback, dict(self.last_request)))
            self._condition.notify()
        self.changed.emit()
        return dict(self.last_request)

    def _work(self):
        while True:
            with self._condition:
                # 当前句播放时最多预合成两句，避免长回复一次占满缓存/显存。
                self._condition.wait_for(lambda: self._jobs and self._prefetched < 2
                    or self._warmup_language is not None and not self._jobs or self._resources_pending is not None or self._closed)
                if self._closed:
                    return
                if self._resources_pending is not None:
                    resources, self._resources_pending = self._resources_pending, None
                    self.model_work_active.set()
                else:
                    resources = None
                if resources is not None:
                    job = None
                elif not self._jobs and self._warmup_language is not None:
                    warmup_language, self._warmup_language = self._warmup_language, None
                    warmup_engine, warmup_generation = self.engine, self.generation
                    job = None
                else:
                    job = self._jobs.popleft()
                    self._prefetched += 1
                self.model_work_active.set()
            if resources is not None:
                profiles, settings, port, presets, voice_id = resources
                self.provider.close()
                self.qwen.close()
                self.provider = LocalSynthesizer(profiles, self.state_path.parent, port)
                if not presets:
                    self.provider.presets.entries = {}
                from src.core.qwen_voice import QwenSynthesizer
                self.qwen = QwenSynthesizer(settings, profiles, self.state_path.parent)
                self.remote.close()
                from src.core.remote_voice import RemoteSynthesizer
                self.remote = RemoteSynthesizer(self._remote_settings, self.state_path.parent, voice_id)
                if self._closed:
                    self.provider.close()
                    self.qwen.close()
                    self.remote.close()
                self.model_work_active.clear()
                continue
            if job is None:
                try:
                    {"gptsovits": self.provider, "qwen": self.qwen, "remote": self.remote}[warmup_engine].warmup(warmup_language)
                    error = None
                except Exception as exc:
                    error = str(exc)
                    logger.warning("心的语音后台预热失败：{}", exc)
                if warmup_engine == self.engine and warmup_generation == self.generation:
                    self.warmup_completed.emit(warmup_generation, warmup_language, error)
                self.model_work_active.clear()
                continue
            generation, text, language, speed, volume, engine, translate, fallback, request = job
            try:
                spoken = text
                if translate:
                    self.stage_changed.emit(generation, "translating")
                    spoken = self.translator.translate(text, language)
                if self._closed or generation != self.generation:
                    continue
                providers = {"gptsovits": self.provider, "edge": self.edge, "qwen": self.qwen, "remote": self.remote}
                warning = None
                self.stage_changed.emit(generation, "synthesizing")
                try:
                    path = providers[engine].synthesize(spoken, language, speed)
                except Exception as primary_error:
                    if self._closed or generation != self.generation:
                        continue
                    if not fallback or engine in ("qwen", "remote"):
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
                if not self._closed and generation == self.generation:
                    logger.warning("心的语音合成失败：{}", exc)
                    self.completed.emit(generation, None, str(exc))
            finally:
                self.model_work_active.clear()

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
            if (result[3] in ("gptsovits", "qwen", "remote") and result[5]["language"] == self._warmup_target
                    and (result[3] != "gptsovits" or not self.provider.idle_released)):
                self.warmup_state, self.warmup_error = "ready", None
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
        self._playing_segment, self._playing_text = request["segment"], text
        self._playing = self._starting = True
        self._announced = False
        try:
            self.player.play(path, volume)
            if not hasattr(self.player, "player"):
                self._announce_speech()
        except Exception as exc:
            self.error = str(exc)
            self.stop()
            self.failed.emit(self.error)
        finally:
            self._starting = False
        if not self.busy and self._playing:
            self.stage = "playing"

    def _playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._announce_speech()
        if state == QMediaPlayer.PlaybackState.StoppedState and self._playing and not self._starting:
            self._playing = False
            self._finishing = True
            token = self.generation
            # 同一轮事件中的解码错误优先取消队列，不能误播下一句。
            QTimer.singleShot(0, lambda: self._after_playback(token))

    def _announce_speech(self):
        if self._playing and not self._announced:
            self._announced = True
            self.speech_started.emit(self._playing_text)

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
        self.remote.cancel()
        if self.qwen.worker.active.is_set():
            self.qwen.cancel()
            self.warmup_state = "idle"
            self._warmup_target = None
        with self._condition:
            self._jobs.clear()
            self._warmup_language = None
            self._prefetched = 0
            self._condition.notify()
        self._ready.clear()
        self._pending = self._sequence = 0
        self._stream = self._stream_language = None
        self._stream_source = self._playing_segment = None
        self._playing_text = ""
        self._stream_open = self._playing = self._finishing = False
        self._announced = False
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
        self.qwen.close()
        self.edge.close()
        self.remote.close()
