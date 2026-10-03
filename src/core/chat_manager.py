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
        except (OSError, ValueError, AttributeError):
            pass
        self.busy, self.error = False, None
        self.generation, self.partial, self.messages = 0, "", []
        self.last_request, self.future = None, None
        self.backends = {}
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
        return {"provider": self.provider, "providers": list(PROVIDERS), "busy": self.busy,
                "last_request": self.last_request, "error": self.error, "reply": self.messages[-1][1] if self.messages and self.messages[-1][0] == "心" else None,
                "speech": {"limit": self.speech.limit, "emitted_characters": self.speech.spoken_chars,
                           "final_revised": self.speech.revised}}

    def configure(self, provider):
        if provider not in PROVIDERS:
            raise ValueError("后端需要 hermes、openclaw 或 deepseek")
        if provider != self.provider:
            self.stop()
        self.provider = provider
        self.error = None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"provider": provider}), encoding="utf8")
        temp.replace(self.state_path)
        self.changed.emit()
        return self.snapshot()

    def send(self, text, language):
        if self.closed:
            raise ValueError("对话服务正在退出")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000 or language not in ("zh", "ja"):
            raise ValueError("需要 1–4000 字符的文字与 zh/ja 语言")
        if self.busy:
            raise ValueError("正在回复，请等待或先停止")
        self.generation += 1
        generation, provider = self.generation, self.provider
        self.busy, self.error, self.partial = True, None, ""
        self.speech = SentenceStream()
        self.last_request = {"id": generation, "text": text.strip(), "language": language, "provider": provider}
        self.messages.append(("御者", text.strip()))
        self.messages = self.messages[-24:]
        self.future = asyncio.run_coroutine_threadsafe(self._chat(generation, text.strip(), language, provider), self.loop)
        self.changed.emit()
        self.updated.emit()
        return dict(self.last_request)

    async def _chat(self, generation, text, language, provider):
        try:
            config = self.config[provider]
            # 设置变更后在工作线程上更换客户端，避免跨线程改写会话。
            identity = json.dumps(config, sort_keys=True)
            if provider not in self.backends or self.backends[provider][0] != identity:
                if provider in self.backends and hasattr(self.backends[provider][1], "close"):
                    await self.backends[provider][1].close()
                self.backends[provider] = (identity, make_backend(provider, config))
            async def delta(chunk):
                if not self.closed:
                    self.progress.emit(generation, chunk)
            reply = await self.backends[provider][1].chat(text, language, delta)
            if not self.closed:
                self.completed.emit(generation, (reply, language), None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 不把 URL（可能含会话凭据）或响应正文写入日志。
            detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "后端连接失败或超时，请检查本地服务和连接设置"
            if not self.closed:
                self.completed.emit(generation, None, detail)

    def _progress(self, generation, chunk):
        if not self.closed and self.busy and generation == self.generation:
            self.partial = (self.partial + chunk)[-20000:]
            for sentence in self.speech.feed(chunk):
                self.sentence_ready.emit(generation, sentence, self.last_request["language"])
            self.updated.emit()

    def _complete(self, generation, result, error):
        if self.closed or generation != self.generation:
            return
        self.busy, self.error, self.partial = False, error, ""
        if result:
            reply, language = result
            self.messages.append(("心", reply))
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
    if len(text) > 500:
        prefix = text[:500]
        endings = [prefix.rfind(char) for char in "。！？!?\n"]
        text = prefix[:max(endings) + 1] if max(endings) >= 100 else prefix
    return text
