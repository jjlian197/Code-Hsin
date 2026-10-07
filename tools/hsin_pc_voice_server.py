"""PC 回环语音桥接；配置只在 PC 读取，客户端只能提交音频或文本。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
from typing import Any
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.local_synthesizer import LocalSynthesizer, voice_profiles
from src.core.model_process import ModelProcess
from src.core.stt_hotwords import normalize_hotwords
from src.core.pc_hermes import PCHermesSessions


class VoiceBackend:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.runtime = Path(settings["runtime"])
        self.gpu_uuid = settings["gpu_uuid"]
        if not self.gpu_uuid.startswith("GPU-"):
            raise ValueError("PC 推理必须显式选择已确认的 GPU UUID")
        # 两个独立环境只看见选定设备，不影响其他应用或系统 GPU 配置。
        os.environ["CUDA_VISIBLE_DEVICES"] = self.gpu_uuid
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        self.asr_model = Path(settings["asr_model"])
        if not (self.asr_model / "config.json").is_file():
            raise ValueError("PC Qwen3-ASR 模型缺失")
        self.asr = ModelProcess(settings["asr_python"], self.gpu_uuid, self.runtime / "asr")
        self.profiles = json.loads(Path(settings["voice_profiles"]).read_text(encoding="utf8"))
        self.profiles["voices"] = {"hsin": self.profiles["profiles"]}
        for voice_id, profile_path in settings.get("voice_catalog", {}).items():
            if voice_id not in ("hsin", "aemeath"):
                raise ValueError("不支持的 PC 音色")
            additional = json.loads(Path(profile_path).read_text(encoding="utf8"))
            if additional["installation"] != self.profiles["installation"]:
                raise ValueError("多角色音色需要共用已验证的 GPT-SoVITS 环境")
            self.profiles["voices"][voice_id] = additional["profiles"]
        self.profiles["profile_id"] = hashlib.sha256(json.dumps(self.profiles, sort_keys=True).encode()).hexdigest()
        self.runtime.mkdir(parents=True, exist_ok=True)
        combined = self.runtime / "voice-catalog.json"
        combined.write_text(json.dumps(self.profiles, ensure_ascii=False), encoding="utf8")
        self.voice = LocalSynthesizer(combined, self.runtime, settings["tts_port"])
        # 此服务证明真实推理，不让预存台词命中代替新句合成。
        self.voice.presets.entries = {}
        self.last_asr: dict[str, Any] = {}

    def fingerprint(self, voice_id: str = "hsin") -> str:
        resource_identity = []
        selected_profiles = voice_profiles(self.profiles, voice_id)
        for language, profile in selected_profiles.items():
            for name in ("gpt_weights", "sovits_weights", "reference_audio"):
                resource_path = Path(profile[name])
                resource_identity.append((language, name, str(resource_path), resource_path.stat().st_size,
                                          resource_path.stat().st_mtime_ns))
        identity = [voice_id, selected_profiles, resource_identity]
        return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def health(self) -> dict[str, Any]:
        return {"service": "hsin-pc-voice", "protocol": 1, "gpu_uuid": self.gpu_uuid,
                "stt": "qwen3-asr", "tts": "gptsovits", "languages": list(self.profiles["profiles"]),
                "voice_fingerprint": self.fingerprint(), "last_asr": self.last_asr,
                "voices": {voice_id: {"fingerprint": self.fingerprint(voice_id), "languages": list(profiles)}
                           for voice_id, profiles in self.profiles["voices"].items()}}

    def transcribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        audio = base64.b64decode(payload["audio_base64"], validate=True)
        with wave.open(io.BytesIO(audio), "rb") as recording:
            if (recording.getnchannels() != 1 or recording.getsampwidth() != 2 or recording.getframerate() != 16000
                    or not 0 < recording.getnframes() <= 25 * 16000):
                raise ValueError("识别需要 25 秒以内的 16kHz 单声道 PCM WAV")
        language = payload.get("language", "zh")
        if language not in ("zh", "ja", "auto"):
            raise ValueError("识别语言无效")
        words = normalize_hotwords(payload.get("hotwords", []))
        response = self.asr.request("asr", model=str(self.asr_model), audio=payload["audio_base64"],
                                    language=language, context="、".join(words))
        self.last_asr = {key: response[key] for key in ("device", "gpu", "seconds")}
        return {"text": response["text"], "provider": "remote-qwen", **self.last_asr}

    def synthesize(self, payload: dict[str, Any]) -> bytes:
        voice_id = payload.get("voice_id", "hsin")
        selected_profiles = voice_profiles(self.profiles, voice_id)
        if payload.get("voice_fingerprint") != self.fingerprint(voice_id):
            raise ValueError("PC 音色资源已变化，请重新请求")
        language = payload.get("language")
        text = payload.get("text")
        speed = payload.get("speed", 1.0)
        if (language not in selected_profiles or not isinstance(text, str)
                or not 1 <= len(text.strip()) <= 500 or type(speed) not in (int, float) or not 0.5 <= speed <= 2):
            raise ValueError("合成文本、语言或语速无效")
        return self.voice.synthesize(text.strip(), language, speed, voice_id).read_bytes()

    def warmup(self, payload: dict[str, Any]) -> dict[str, Any]:
        language = payload.get("language")
        voice_id = payload.get("voice_id", "hsin")
        if language not in voice_profiles(self.profiles, voice_id):
            raise ValueError("预热语言无效")
        self.voice.warmup(language, voice_id)
        return {"ready": True, "language": language, "voice_id": voice_id}

    def close(self) -> None:
        self.asr.close()
        self.voice.close()


class VoiceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], backend: VoiceBackend, token: str = "", hermes: dict[str, Any] | None = None) -> None:
        self.hermes = PCHermesSessions(hermes) if hermes else None
        self.backend = backend
        self.token = token
        self.jobs: dict[str, dict[str, Any]] = {}
        self.jobs_lock = threading.Lock()
        self.cancelled_ids: dict[str, float] = {}
        self.inference_lock = threading.Lock()
        self.capacity = threading.BoundedSemaphore(8)
        super().__init__(address, VoiceHandler)


class VoiceHandler(BaseHTTPRequestHandler):
    server: VoiceServer

    def log_message(self, format: str, *arguments: Any) -> None:
        # 不记录台词、录音、客户端地址或配置内容。
        pass

    def send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self) -> bool:
        if not self.server.token:
            return True
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + self.server.token).encode()):
            self.send(401, {"error": "桥接访问令牌无效"})
            return False
        return True

    def do_GET(self) -> None:
        if not self.authorized():
            return
        if self.path != "/health":
            return self.send(404, {"error": "unknown endpoint"})
        try:
            self.send(200, self.server.backend.health())
        except Exception:
            self.send(503, {"error": "PC 音色资源不可用"})

    def read_payload(self) -> dict[str, Any]:
        self.connection.settimeout(10)
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 1200000:
            raise ValueError("请求长度无效")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict) or not re.fullmatch(r"[a-f0-9]{32}", payload.get("request_id", "")):
            raise ValueError("请求标识无效")
        return payload

    def do_POST(self) -> None:
        if not self.authorized():
            return
        try:
            payload = self.read_payload()
        except (ValueError, TypeError, OSError) as exc:
            return self.send(400, {"error": str(exc)})
        request_id = payload["request_id"]
        if self.path == "/v1/cancel":
            with self.server.jobs_lock:
                self.server.cancelled_ids = {identity: expiry for identity, expiry in self.server.cancelled_ids.items()
                                             if expiry > time.monotonic()}
                if len(self.server.cancelled_ids) < 1024:
                    self.server.cancelled_ids[request_id] = time.monotonic() + 600
                job = self.server.jobs.get(request_id)
                if job is not None:
                    job["cancelled"] = True
                    loop, task = job.get("loop"), job.get("task")
                    if loop and task and not loop.is_closed():
                        loop.call_soon_threadsafe(task.cancel)
                state = "running_result_discarded" if job and job["running"] else "cancelled_or_finished"
            return self.send(200, {"state": state})
        operations = {"/v1/stt": self.server.backend.transcribe,
                      "/v1/tts": self.server.backend.synthesize, "/v1/warmup": self.server.backend.warmup}
        if self.path == "/v1/hermes" and self.server.hermes:
            operations[self.path] = None
        if self.path not in operations:
            return self.send(404, {"error": "unknown endpoint"})
        if not self.server.capacity.acquire(blocking=False):
            return self.send(429, {"error": "PC 语音队列已满"})
        job = {"cancelled": False, "running": False}
        with self.server.jobs_lock:
            job["cancelled"] = self.server.cancelled_ids.pop(request_id, 0) > time.monotonic()
            duplicate = request_id in self.server.jobs
            if not duplicate:
                self.server.jobs[request_id] = job
        if duplicate:
            self.server.capacity.release()
            return self.send(409, {"error": "重复请求标识"})
        try:
            if self.path == "/v1/hermes":
                self.server.hermes.stream(self, payload, job)
                return
            # 两个推理环境共享同一 GPU，先串行调度，避免并发冷启动争用显存。
            with self.server.inference_lock:
                with self.server.jobs_lock:
                    if job["cancelled"]:
                        return self.send(409, {"error": "语音任务已取消"})
                    job["running"] = True
                response = operations[self.path](payload)
            if job["cancelled"]:
                return self.send(409, {"error": "语音结果已取消；已运行推理正常结束"})
            self.send(200, response, "audio/wav" if isinstance(response, bytes) else "application/json")
        except (ValueError, KeyError, wave.Error) as exc:
            self.send(400, {"error": str(exc)})
        except Exception as exc:
            print(f"Voice job failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            self.send(500, {"error": "PC 推理失败，请检查 PC 语音日志"})
        finally:
            with self.server.jobs_lock:
                self.server.jobs.pop(request_id, None)
            self.server.capacity.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19881)
    options = parser.parse_args()
    settings = json.loads(options.config.read_text(encoding="utf8"))
    token = ""
    if settings.get("token_file"):
        token = Path(settings["token_file"]).read_text(encoding="utf8").strip()
        if len(token) < 32 or any(character.isspace() for character in token):
            raise ValueError("桥接令牌文件无效")
    backend = VoiceBackend(settings)
    server = VoiceServer(("127.0.0.1", options.port), backend, token, settings.get("hermes"))

    def stop(signum: int, frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Hsin PC voice ready on 127.0.0.1:{options.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        backend.close()


if __name__ == "__main__":
    main()
