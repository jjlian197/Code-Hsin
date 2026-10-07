"""GPT-SoVITS 调用与 WAV 校验；桌面端和 PC 桥接共用，不依赖 Qt。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

from src.core.app_config import project_path
from src.core.voice_catalog import voice_profiles
from src.core.preset_voice import PresetVoice


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
        self.operation_lock = threading.Lock()
        self.idle_released = False
        self.closed = threading.Event()
        self.presets = PresetVoice()

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
            self.idle_released = False
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
                frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
                if frozen_windows:
                    # 外部 GPT 环境不能继承冻结程序的 DLL 搜索目录或 Qt PATH。
                    import ctypes
                    bundle_root = Path(sys._MEIPASS).resolve()
                    env["PATH"] = os.pathsep.join(item for item in env["PATH"].split(os.pathsep)
                        if item and not Path(item).resolve().is_relative_to(bundle_root))
                with (self.runtime / "server.log").open("ab") as log:
                    if frozen_windows:
                        ctypes.windll.kernel32.SetDllDirectoryW(None)
                    try:
                        self.process = subprocess.Popen([data["installation"]["python"], "-u", "-s",
                            str(project_path("tools/hsin_voice_server.py")), "--profiles", str(self.profiles_path),
                            "--runtime", str(self.runtime), "--port", str(self.port)],
                            cwd=data["installation"]["gptsovits_root"], env=env, stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    finally:
                        if frozen_windows:
                            ctypes.windll.kernel32.SetDllDirectoryW(str(bundle_root))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not self.closed.wait(0.15):
            try:
                health = self.health()
                if health.get("service") == "hsin-gptsovits" and health.get("profile_id") == data["profile_id"]:
                    self.idle_released = False
                    return
                raise RuntimeError("语音服务身份不匹配")
            except urllib.error.URLError:
                if self.process.poll() is not None:
                    raise RuntimeError("语音服务启动失败，请查看 .runtime/tts/server.log")
        raise RuntimeError("语音服务启动超时或已退出")

    def synthesize(self, text, language, speed, voice_id="hsin"):
        with self.operation_lock:
            return self._synthesize(text, language, speed, voice_id)

    def _synthesize(self, text, language, speed, voice_id="hsin"):
        preset = self.presets.find(text, language, speed) if voice_id == "hsin" else None
        if preset:
            wave_info(preset.read_bytes())
            return preset
        if not self.profiles_path.is_file():
            raise RuntimeError("这段文字不在预存语音中；请导入 GPT-SoVITS 音色配置，或选择 Edge 联网语音")
        data = json.loads(self.profiles_path.read_text(encoding="utf8"))
        profile = voice_profiles(data, voice_id)[language]
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
            {"text": text, "language": language, "speed": speed, "voice_id": voice_id}, ensure_ascii=False).encode(),
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

    def warmup(self, language, voice_id="hsin"):
        with self.operation_lock:
            self._warmup(language, voice_id)

    def _warmup(self, language, voice_id="hsin"):
        data = json.loads(self.profiles_path.read_text(encoding="utf8"))
        self.ensure_server(data)
        # 独立端点强制做一次推理，不能由磁盘音频缓存代替模型预热。
        request = urllib.request.Request(self.base + "/warmup", data=json.dumps({"language": language, "voice_id": voice_id}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        if result.get("language") != language or result.get("ready") is not True:
            raise RuntimeError("语音预热未完成")

    def close(self):
        self.closed.set()
        self._stop_owned_process()

    def _stop_owned_process(self):
        with self.process_lock:
            process, self.process = self.process, None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            return process is not None

    def release_idle(self):
        # 只释放自己启动的服务；已连接的用户服务不受影响。
        if not self.operation_lock.acquire(blocking=False):
            return False
        try:
            released = self._stop_owned_process()
            if released:
                self.idle_released = True
            return released
        finally:
            self.operation_lock.release()
