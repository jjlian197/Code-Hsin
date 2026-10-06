"""后台对话与 Qt 信号分离；停止或切换后丢弃旧回复，凭据不进入状态接口。"""
import asyncio
from copy import deepcopy
import json
import re
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from src.core.app_config import project_path
from src.core.chat_backends import PROVIDERS, make_backend
from src.core.speech_stream import SentenceStream
from src.core.chat_preferences import PREFERENCE_KEYS


class ChatManager(QObject):
    changed = pyqtSignal()
    updated = pyqtSignal()
    progress = pyqtSignal(int, str)
    completed = pyqtSignal(int, object, object)
    reply_ready = pyqtSignal(str, str)
    sentence_ready = pyqtSignal(int, str, str)
    speech_finished = pyqtSignal(int, bool)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = deepcopy(config["chat"])
        self.provider = self.config["provider"]
        self.state_path = project_path(config["runtime"]["directory"]) / "chat.json"
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf8"))
            if saved.get("provider") in PROVIDERS:
                self.provider = saved["provider"]
            candidate = {**self.config, **{key: saved[key] for key in PREFERENCE_KEYS if key in saved}}
            from src.core.app_config import validate_chat_config
            validate_chat_config(candidate)
            self.config = candidate
        except (OSError, ValueError, AttributeError):
            pass
        self.busy, self.error = False, None
        self.warning = None
        self.generation, self.partial, self.messages = 0, "", []
        self.last_request, self.future = None, None
        self.backends = {}
        self.character_id, self.character_name = "default", "心"
        self.closed = False
        self.speech = SentenceStream()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="HsinChat", daemon=True)
        self.thread.start()
        self.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            for _, backend in self.backends.values():
                if hasattr(backend, "close"):
                    self.loop.run_until_complete(backend.close())
            self.loop.close()

    def snapshot(self):
        return {"provider": self.provider, "enabled": self.config.get("enabled", True), "providers": list(PROVIDERS), "busy": self.busy,
                "last_request": self.last_request, "error": self.error, "warning": self.warning, "reply": self.messages[-1][1] if self.messages and self.messages[-1][0] == self.character_name else None,
                "preferences": {key: self.config[key] for key in PREFERENCE_KEYS},
                "speech": {"limit": self.speech.limit, "emitted_characters": self.speech.spoken_chars,
                           "limited": self.speech.limited, "scope": (self.last_request or {}).get("speech_scope", self.config["speech_scope"]),
                           "final_revised": self.speech.revised}}

    def configure(self, provider):
        if provider not in PROVIDERS:
            raise ValueError("后端需要 hermes、openclaw、deepseek 或 ollama")
        if provider != self.provider:
            self.stop()
        self.provider = provider
        self.error = None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"provider": provider, **{key: self.config[key] for key in PREFERENCE_KEYS}}), encoding="utf8")
        temp.replace(self.state_path)
        self.changed.emit()
        return self.snapshot()

    def configure_preferences(self, **settings):
        if any(key not in PREFERENCE_KEYS for key in settings):
            raise ValueError("未知对话偏好")
        from src.core.app_config import validate_chat_config
        candidate = {**self.config, **settings}
        validate_chat_config(candidate)
        if candidate != self.config:
            self.stop()
            self.config = candidate
        return self.configure(self.provider)

    def send(self, text, language):
        if self.closed:
            raise ValueError("对话服务正在退出")
        if not self.config.get("enabled", True):
            raise ValueError("当前使用基础陪伴，请在右键菜单的设置中开启 AI 对话")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000 or language not in ("zh", "ja"):
            raise ValueError("需要 1–4000 字符的文字与 zh/ja 语言")
        if self.busy:
            raise ValueError("正在回复，请等待或先停止")
        self.generation += 1
        generation, provider = self.generation, self.provider
        self.busy, self.error, self.partial = True, None, ""
        self.warning = None
        scope = self.config["speech_scope"]
        self.speech = SentenceStream(limit=0 if scope == "off" else self.config["speech_prefix_chars"] if scope == "prefix" else None,
            sentence_limit=self.config["speech_sentence_count"] if scope == "sentences" else None)
        self.last_request = {"id": generation, "text": text.strip(), "language": language, "provider": provider,
                             "reply_length": self.config["reply_length"], "speech_scope": scope}
        self.messages.append(("御者", text.strip()))
        self.messages = self.messages[-24:]
        backend_config = deepcopy(self.config[provider])
        if provider in ("deepseek", "ollama") and self.config.get("persona"):
            backend_config["persona"] = self.config["persona"]
        self.future = asyncio.run_coroutine_threadsafe(self._chat(generation, text.strip(), language, provider, self.last_request["reply_length"], backend_config, self.character_id), self.loop)
        self.changed.emit()
        self.updated.emit()
        return dict(self.last_request)

    async def _chat(self, generation, text, language, provider, reply_length, config=None, character_id=None):
        try:
            config = config if config is not None else deepcopy(self.config[provider])
            key = (character_id or self.character_id, provider)
            # 设置变更后在工作线程上更换客户端，避免跨线程改写会话。
            identity = json.dumps(config, sort_keys=True)
            if key not in self.backends or self.backends[key][0] != identity:
                if key in self.backends and hasattr(self.backends[key][1], "close"):
                    await self.backends[key][1].close()
                self.backends[key] = (identity, make_backend(provider, config))
            async def delta(chunk):
                if not self.closed:
                    self.progress.emit(generation, chunk)
            backend = self.backends[key][1]
            reply = await backend.chat(text, language, delta, reply_length=reply_length)
            if not self.closed:
                self.completed.emit(generation, (reply, language, getattr(backend, "warning", None)), None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 不把 URL（可能含会话凭据）或响应正文写入日志。
            detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "后端连接失败或超时，请检查本地服务和连接设置"
            if not self.closed:
                self.completed.emit(generation, None, detail)

    def _progress(self, generation, chunk):
        if not self.closed and self.busy and generation == self.generation:
            self.partial += chunk
            for sentence in self.speech.feed(chunk):
                self.sentence_ready.emit(generation, sentence, self.last_request["language"])
            self.updated.emit()

    def _complete(self, generation, result, error):
        if self.closed or generation != self.generation:
            return
        self.busy, self.error, self.partial = False, error, ""
        if result:
            reply, language, self.warning = result
            self.messages.append((self.character_name, reply))
            for sentence in self.speech.finish(reply):
                self.sentence_ready.emit(generation, sentence, language)
            self.speech_finished.emit(generation, not self.speech.revised)
            self.reply_ready.emit(reply, language)
        elif error:
            self.messages.append(("连接提示", error))
            self.speech_finished.emit(generation, False)
        self.changed.emit()
        self.updated.emit()

    def stop(self):
        self.generation += 1
        if self.future:
            self.future.cancel()
            self.future = None
        if self.busy:
            self.messages.append(("连接提示", "已停止回复"))
        self.busy, self.partial = False, ""
        self.changed.emit()
        self.updated.emit()

    def close(self):
        self.closed = True
        self.stop()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


def spoken_reply(text):
    text = re.sub(r"<think[^>]*>.*?</think\s*>", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*#`_<>]", "", text).strip()
    return text
