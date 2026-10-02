"""短句识别后端；音频只存在内存，密钥不进入状态、日志或命令行。"""
import importlib.util
import io
import os
import base64
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import wave
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
    def __init__(self):
        self._process = None
        self._responses = None
        self._lock = threading.Lock()
        self._closed = False

    @staticmethod
    def key(config):
        return (os.environ.get("ZHIPU_API_KEY") or config.get("zhipu", {}).get("api_key", "")).strip()

    @classmethod
    def provider(cls, config):
        requested = config.get("provider", "auto")
        if requested != "auto":
            return requested
        return "zhipu" if cls.key(config) and config.get("language") != "ja" else "whisper"

    @staticmethod
    def local_available():
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, pcm, config):
        if not pcm or len(pcm) > 16000 * 2 * 25 or len(pcm) % 2:
            raise ValueError("识别音频需要 25 秒以内的 16kHz 单声道 PCM")
        audio = wav_bytes(pcm)
        provider = self.provider(config)
        warning = ""
        if provider == "zhipu":
            try:
                return self._cloud(audio, config), "zhipu", warning
            except (RuntimeError, ValueError) as exc:
                if not config.get("fallback", True):
                    raise
                warning = str(exc) + "；已使用本地 Whisper"
        return self._local(audio, config), "whisper", warning

    def _cloud(self, audio, config):
        key = self.key(config)
        if not key:
            raise ValueError("请在麦克风设置中填写智谱 API Key，或选择本地 Whisper")
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

    def _local(self, audio, config):
        if not self.local_available():
            raise RuntimeError("本地识别组件未安装，请安装 requirements-stt.txt")
        path = config.get("model_path", "").strip() or "base"
        language = config.get("language", "zh")
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("语音识别已关闭")
                if self._process is None or self._process.poll() is not None:
                    if self._process:
                        for stream in (self._process.stdin, self._process.stdout):
                            if stream:
                                stream.close()
                    self._responses = queue.Queue()
                    env = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
                    # Qt/OpenMP 与 Whisper 隔离；仅在收到语音后加载 CPU 模型。
                    self._process = subprocess.Popen([sys.executable, "-u", "-m", "src.core.stt_worker"],
                        cwd=str(Path(__file__).resolve().parents[2]), env=env,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    process, responses = self._process, self._responses
                    def read():
                        try:
                            for line in process.stdout:
                                try:
                                    value = json.loads(line)
                                except (ValueError, UnicodeError):
                                    continue
                                responses.put(value)
                        except (OSError, ValueError):
                            pass
                        finally:
                            responses.put({"error": "Whisper 子进程异常退出，请检查本地识别依赖"})
                    threading.Thread(target=read, name="HsinSTTReader", daemon=True).start()
                process, responses = self._process, self._responses
                request = {"audio": base64.b64encode(audio).decode("ascii"), "language": language, "model": path,
                           "hotwords": hotwords(config)}
                process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
                process.stdin.flush()
            response = responses.get(timeout=60)
            if response.get("error"):
                raise RuntimeError(response["error"])
            return str(response.get("text", "")).strip()[:4000]
        except RuntimeError:
            raise
        except queue.Empty:
            self._terminate()
            raise RuntimeError("本地 Whisper 识别超时，请重试") from None
        except Exception:
            raise RuntimeError("本地 Whisper 识别失败") from None

    def _terminate(self):
        with self._lock:
            process, self._process = self._process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

    def close(self):
        with self._lock:
            self._closed = True
        self._terminate()
