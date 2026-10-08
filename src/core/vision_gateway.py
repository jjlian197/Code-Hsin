"""Independent headset sessions; never dispatch chat or playback to the desktop window."""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import hmac
import io
import json
from pathlib import Path
import re
import time
import uuid
import wave
from typing import Any, Callable

from aiohttp import web
from src.core.chat_backends import make_backend
from src.core.remote_hermes import RemoteHermesBridge
from src.core.remote_voice import RemoteSynthesizer
from src.core.speech_recognizer import SpeechRecognizer
from src.core.speech_stream import SentenceStream

IDENTITY = re.compile(r"[a-f0-9]{32}")


def audio_pcm(encoded: object) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > 1100000:
        raise ValueError("录音过大或格式无效")
    audio = base64.b64decode(encoded, validate=True)
    with wave.open(io.BytesIO(audio), "rb") as recording:
        if (recording.getframerate(), recording.getnchannels(), recording.getsampwidth()) != (16000, 1, 2):
            raise ValueError("需要 16kHz 单声道 Int16 WAV")
        if not 0 < recording.getnframes() <= 25 * 16000:
            raise ValueError("录音需要在 25 秒以内")
        pcm = recording.readframes(recording.getnframes())
        if len(pcm) != recording.getnframes() * 2:
            raise ValueError("录音不完整")
    return pcm


class HeadsetSession:
    def __init__(self, socket: web.WebSocketResponse, configuration: dict[str, Any],
                 profiles: dict[str, dict[str, Any]], runtime: Path,
                 backend_factory: Callable[..., Any] = make_backend,
                 voice_factory: Callable[..., Any] = RemoteSynthesizer,
                 recognizer_factory: Callable[..., Any] = SpeechRecognizer) -> None:
        self.socket, self.configuration, self.profiles = socket, configuration, profiles
        self.runtime = runtime / uuid.uuid4().hex
        self.backend_factory, self.voice_factory = backend_factory, voice_factory
        self.recognizer = recognizer_factory(str(self.runtime), configuration["speech_bridge"])
        self.backends: dict[tuple[str, str], Any] = {}
        self.task: asyncio.Task[None] | None = None
        self.turn_id: str | None = None
        self.voice: Any = None
        self.audio_slots = asyncio.BoundedSemaphore(2)
        self.pending_audio: set[int] = set()

    async def emit(self, kind: str, identity: str, **fields: Any) -> None:
        if identity == self.turn_id and not self.socket.closed:
            await self.socket.send_json({"type": kind, "turn_id": identity, **fields})

    async def interrupt(self) -> None:
        # Revoke identity before waking blocked HTTP reads: late results cannot become events.
        self.turn_id = None
        self.recognizer.cancel()
        if self.voice is not None:
            self.voice.cancel()
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def run_turn(self, command: dict[str, Any]) -> None:
        identity = command["turn_id"]
        language = command.get("language", "zh")
        role = command.get("character_id", "aemeath")
        voice = None
        consumer: asyncio.Task[None] | None = None
        try:
            if language not in ("zh", "ja") or role not in self.profiles:
                raise ValueError("角色或回复语言无效")
            profile = self.profiles[role]
            if not profile["chat"].get("enabled", True):
                raise ValueError("该角色尚未开启聊天")
            spatial_chat = self.configuration.get("vision_chat", {})
            role_chat = spatial_chat.get("roles", {}).get(role, {})
            provider = command.get("chat_provider", role_chat.get("provider", profile["chat"]["provider"]))
            if provider not in ("hermes", "openclaw", "deepseek", "ollama"):
                raise ValueError("聊天后端无效")
            backend_configuration = {**deepcopy(self.configuration["chat"][provider]),
                                     **profile["chat"].get(provider, {}), "persona": profile["persona"] +
                                     "\n当前对话来自 visionOS 空间伙伴。你只能接收本轮文字或识别文本和聊天历史，"
                                     "没有屏幕、文件、现实环境、网络状态或工具权限。不能声称已经看见屏幕、读取应用状态"
                                     "或感知连接状态；网络由程序处理，你无法观察其状态。"}
            if provider in ("openclaw", "hermes"):
                # Match the reference's existing Agent/session; its persona and tools belong to OpenClaw.
                backend_configuration = {**deepcopy(self.configuration["chat"][provider]),
                                         **profile["chat"].get(provider, {}),
                                         **deepcopy(role_chat.get(provider, {}))}
            backend_key = (role, provider)
            if backend_key not in self.backends:
                if provider == "hermes" and backend_configuration.get("transport") == "pc_bridge":
                    self.backends[backend_key] = RemoteHermesBridge(self.configuration["speech_bridge"])
                else:
                    self.backends[backend_key] = self.backend_factory(provider, backend_configuration)
            if command["type"] == "user_audio":
                selected_stt = command.get("stt_provider", "remote")
                if selected_stt not in ("remote", "zhipu"):
                    raise ValueError("识别方式需要 PC 或智谱")
                pcm = audio_pcm(command.get("audio_base64"))
                recognition_started = time.monotonic()
                try:
                    async with asyncio.timeout(90):
                        text, _, _ = await asyncio.to_thread(self.recognizer.transcribe, pcm,
                            {**deepcopy(self.configuration["stt"]), "provider": selected_stt, "language": language})
                except TimeoutError:
                    self.recognizer.cancel()
                    raise ValueError("识别超时，请检查语音服务或切换识别方式") from None
                await self.emit("transcript", identity, text=text, recognition_seconds=round(time.monotonic() - recognition_started, 3))
            else:
                text = command.get("text")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
                raise ValueError("对话需要 1–4000 字文字")
            voice = self.voice_factory(self.configuration["speech_bridge"], self.runtime,
                                       profile["voice"].get("remote_voice", role))
            self.voice = voice
            self.audio_slots = asyncio.BoundedSemaphore(2)
            self.pending_audio.clear()
            sentences: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2)
            stream = SentenceStream()

            async def synthesize_sentences() -> None:
                index = 0
                while True:
                    sentence = await sentences.get()
                    if sentence is None:
                        return
                    await self.audio_slots.acquire()
                    self.pending_audio.add(index)
                    await self.emit("reply_sentence", identity, index=index, text=sentence)
                    try:
                        path = await asyncio.to_thread(voice.synthesize, sentence, language, 1.0)
                        audio = await asyncio.to_thread(path.read_bytes)
                        await self.emit("sentence_audio", identity, index=index, text=sentence,
                                        audio_base64=base64.b64encode(audio).decode())
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if index in self.pending_audio:
                            self.pending_audio.remove(index)
                            self.audio_slots.release()
                        await self.emit("sentence_audio", identity, index=index, text=sentence,
                                        audio_error="本句语音合成失败")
                    index += 1

            consumer = asyncio.create_task(synthesize_sentences())

            async def delta(chunk: str) -> None:
                await self.emit("reply_delta", identity, text=chunk)
                for sentence in stream.feed(chunk):
                    await sentences.put(sentence)

            async with asyncio.timeout(240):
                reply = await self.backends[backend_key].chat(text.strip(), language, delta,
                    reply_length=profile["chat"].get("reply_length", "normal"))
                remaining = stream.finish(reply)
                if stream.revised:
                    # Previously played text cannot be undone. Stop remaining old audio and show final text.
                    voice.cancel()
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)
                    await self.emit("speech_reset", identity, reply=reply)
                else:
                    for sentence in remaining:
                        await sentences.put(sentence)
                    await sentences.put(None)
                    await consumer
                await self.emit("turn_done", identity, reply=reply)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Avoid upstream exception strings containing URLs, credentials or transcripts.
            message = str(error) if isinstance(error, ValueError) else "对话或识别失败，请检查 Mac 网关与语音服务"
            await self.emit("turn_error", identity, error=message)
        finally:
            if consumer is not None:
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)
            if voice is not None:
                voice.close()
                if self.voice is voice:
                    self.voice = None

    async def close(self) -> None:
        await self.interrupt()
        self.recognizer.close()
        for backend in self.backends.values():
            if hasattr(backend, "close"):
                await backend.close()
        # Headset-generated replies are session data, not a reusable desktop voice cache.
        import shutil
        await asyncio.to_thread(shutil.rmtree, self.runtime, True)


def create_app(configuration: dict[str, Any], profiles: dict[str, dict[str, Any]], token: str,
               runtime: Path, **factories: Any) -> web.Application:
    if len(token) < 32 or any(character.isspace() for character in token):
        raise ValueError("需要有效的私有网关令牌")
    sessions: set[HeadsetSession] = set()

    @web.middleware
    async def authorization(request: web.Request, handler: Any) -> web.StreamResponse:
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return web.json_response({"error": "访问令牌无效"}, status=401)
        return await handler(request)

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"service": "hsin-vision-gateway", "protocol": 1,
                                  "characters": list(profiles), "stt_providers": ["remote", "zhipu"]})

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        if len(sessions) >= 4:
            raise web.HTTPServiceUnavailable(reason="Headset session capacity reached")
        socket = web.WebSocketResponse(heartbeat=30, max_msg_size=1200000)
        await socket.prepare(request)
        session = HeadsetSession(socket, configuration, profiles, runtime, **factories)
        sessions.add(session)
        try:
            await socket.send_json({"type": "welcome", "service": "hsin-vision-gateway", "protocol": 1,
                                    "characters": [{"id": role, "name": profile["name"]} for role, profile in profiles.items()]})
            async for message in socket:
                if message.type not in (web.WSMsgType.TEXT, web.WSMsgType.BINARY):
                    continue
                try:
                    command = json.loads(message.data)
                    if not isinstance(command, dict):
                        raise ValueError("请求需要 JSON 对象")
                    if command.get("type") in ("playback_started", "audio_discarded"):
                        index = command.get("index")
                        if command.get("turn_id") == session.turn_id and type(index) is int and index in session.pending_audio:
                            session.pending_audio.remove(index)
                            session.audio_slots.release()
                        continue
                    if command.get("type") == "interrupt":
                        await session.interrupt()
                        await socket.send_json({"type": "interrupted"})
                        continue
                    identity = command.get("turn_id", "")
                    if command.get("type") not in ("user_text", "user_audio") or not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
                        raise ValueError("请求类型或回合编号无效")
                    if session.task is not None and not session.task.done():
                        await socket.send_json({"type": "turn_error", "turn_id": identity, "error": "上一回合尚未结束"})
                        continue
                    session.turn_id = identity
                    session.task = asyncio.create_task(session.run_turn(command))
                except (ValueError, TypeError):
                    await socket.send_json({"type": "protocol_error", "error": "请求格式无效"})
        finally:
            await session.close()
            sessions.discard(session)
        return socket

    async def cleanup(app: web.Application) -> None:
        await asyncio.gather(*(session.socket.close() for session in list(sessions)), return_exceptions=True)

    app = web.Application(client_max_size=1200000, middlewares=[authorization])
    app.router.add_get('/health', health)
    app.router.add_get('/ws', websocket)
    app.on_shutdown.append(cleanup)
    return app
