"""短句识别后端；音频只存在内存，密钥不进入状态、日志或命令行。"""
import io
import os
import base64
import json
import threading
import wave
from pathlib import Path
from typing import Any
from src.core.stt_hotwords import hotwords


def wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(pcm)
    return buffer.getvalue()


class SpeechRecognizer:
    def __init__(self, runtime: str | Path | None = None, remote_settings: dict[str, Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._qwen = None
        self._qwen_identity = None
        self._runtime = runtime
        from src.core.app_config import project_path
        from src.core.remote_voice import RemoteVoiceClient
        self._remote = RemoteVoiceClient(remote_settings or {}, project_path(runtime or ".runtime"))

    @staticmethod
    def key(config):
        return (os.environ.get("ZHIPU_API_KEY") or config.get("zhipu", {}).get("api_key", "")).strip()

    @classmethod
    def provider(cls, config):
        requested = config.get("provider", "auto")
        if requested != "auto":
            return requested
        return "zhipu" if cls.key(config) and config.get("language") != "ja" else "qwen"

    def transcribe(self, pcm: bytes, config: dict[str, Any]) -> tuple[str, str, str]:
        if self._closed:
            raise RuntimeError("语音识别已关闭")
        if not pcm or len(pcm) > 16000 * 2 * 25 or len(pcm) % 2:
            raise ValueError("识别音频需要 25 秒以内的 16kHz 单声道 PCM")
        audio = wav_bytes(pcm)
        provider = self.provider(config)
        warning = ""
        if provider == "remote":
            generation = self._remote.generation
            self._remote.health(generation)
            response = json.loads(self._remote.request("/v1/stt", {
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "language": config.get("language", "zh"), "hotwords": hotwords(config)}, expected_generation=generation))
            if not isinstance(response.get("text"), str):
                raise RuntimeError("PC 识别响应格式无效")
            return response["text"], "remote-qwen", ""
        if provider == "qwen":
            from src.core.model_process import ModelProcess
            from src.core.app_config import project_path
            settings = config.get("qwen", {})
            identity = json.dumps(settings, sort_keys=True)
            with self._lock:
                if self._closed:
                    raise RuntimeError("语音识别已关闭")
                if self._qwen is None or identity != self._qwen_identity:
                    if self._qwen:
                        self._qwen.close()
                    self._qwen = ModelProcess(settings["python"], settings.get("gpu", "4080"), project_path(self._runtime or ".runtime") / "qwen-asr")
                    self._qwen_identity = identity
                worker = self._qwen
            result = worker.request("asr", model=str(project_path(settings["model"])),
                audio=base64.b64encode(audio).decode("ascii"), language=config.get("language", "zh"), context="、".join(hotwords(config)))
            return result["text"], "qwen", ""
        if provider == "zhipu":
            return self._cloud(audio, config), "zhipu", ""
        raise ValueError("识别引擎需要 qwen、zhipu 或 remote")

    def _cloud(self, audio, config):
        key = self.key(config)
        if not key:
            raise ValueError("请在麦克风设置中填写智谱 API Key，或选择本地 Qwen ASR")
        import requests
        data = {"model": "glm-asr-2512", "stream": "false"}
        words = hotwords(config)
        if words:
            data["hotwords"] = json.dumps(words, ensure_ascii=False)
        try:
            response = requests.post(
                "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions",
                headers={"Authorization": "Bearer " + key},
                data=data,
                files={"file": ("utterance.wav", audio, "audio/wav")},
                timeout=(5, 25),
            )
            if response.status_code != 200:
                raise RuntimeError(f"智谱识别失败（HTTP {response.status_code}）")
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise RuntimeError("智谱识别响应格式无效")
            return result["text"].strip()[:4000]
        except requests.RequestException:
            raise RuntimeError("智谱识别连接失败或超时") from None
        except ValueError:
            raise RuntimeError("智谱识别响应格式无效") from None

    def close(self):
        with self._lock:
            self._closed = True
        self._remote.close()
        if self._qwen:
            self._qwen.close()

    def cancel(self):
        self._remote.cancel()
        if self._qwen and self._qwen.active.is_set():
            self._qwen.cancel()

    def release_idle(self):
        with self._lock:
            worker = self._qwen
        return worker.release_idle() if worker else False
