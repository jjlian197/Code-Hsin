"""PC 语音客户端：HTTPS 或 SSH 传输，播放和代次控制仍由桌面端管理。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import http.client
import json
import os
import sys
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse
import uuid
import wave

from src.core.app_config import DEFAULT_REMOTE, project_path


def validate_remote(settings: dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        raise ValueError("PC 语音桥接需要配置对象")
    endpoint = settings.get("url", "")
    if not isinstance(endpoint, str):
        raise ValueError("PC 语音地址需要字符串")
    if endpoint:
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("PC 语音地址端口无效") from exc
        local_http = parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and port is not None
        secure_remote = parsed.scheme == "https" and bool(parsed.hostname)
        if (not (local_http or secure_remote) or port is not None and not 1 <= port <= 65535
                or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("PC 语音地址需要 HTTPS 域名或 http://127.0.0.1:端口")
    token = settings.get("token", "")
    if not isinstance(token, str) or any(character in token for character in "\r\n\x00"):
        raise ValueError("PC 语音访问令牌无效")
    for key in ("ssh_host", "ssh_user", "ssh_key"):
        value = settings.get(key, DEFAULT_REMOTE[key])
        if not isinstance(value, str) or any(character in value for character in "\r\n\x00") or value.startswith("-"):
            raise ValueError("PC 语音 SSH 配置无效")
    for key, upper in (("ssh_port", 65535), ("remote_port", 65535), ("timeout", 600)):
        value = settings.get(key, DEFAULT_REMOTE[key])
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError("PC 语音端口或超时无效")


class SharedTunnel:
    def __init__(self, settings: dict[str, Any], runtime: Path) -> None:
        self.settings = settings
        self.runtime = runtime
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.references = 0
        self.closed = False

    def ensure(self) -> None:
        if urlparse(self.settings["url"]).scheme == "https" or not self.settings["ssh_host"]:
            return
        local_port = urlparse(self.settings["url"]).port
        with self.lock:
            if self.closed:
                raise RuntimeError("PC 语音隧道已关闭")
            if self.process is None or self.process.poll() is not None:
                self.runtime.mkdir(parents=True, exist_ok=True)
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", local_port)) == 0:
                        raise RuntimeError("PC 语音转发端口已被占用，请更换桥接地址的端口")
                command = ["ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                           "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
                           "-p", str(self.settings["ssh_port"]), "-i", str(Path(self.settings["ssh_key"]).expanduser()),
                           "-L", f"127.0.0.1:{local_port}:127.0.0.1:{self.settings['remote_port']}",
                           f"{self.settings['ssh_user']}@{self.settings['ssh_host']}"]
                if sys.platform == "darwin":
                    # Qt/打包进程被信号直接结束时，独立监护仍能关闭隧道。
                    command = ["/bin/sh", str(project_path("scripts/ssh_supervisor.sh")), str(os.getpid()), *command]
                with (self.runtime / "ssh.log").open("ab") as tunnel_log:
                    self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=tunnel_log)
            process = self.process
        # 网络等待不持有进程锁，关闭应用可以立即结束正在建立的隧道。
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.closed or process.poll() is not None:
                raise RuntimeError("PC 语音 SSH 连接失败，请检查主机、密钥与 ssh.log")
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", local_port)) == 0:
                    return
            time.sleep(0.05)
        with self.lock:
            self._stop_process()
        raise RuntimeError("PC 语音 SSH 连接超时")

    def stop(self) -> None:
        with self.lock:
            self.closed = True
            self._stop_process()

    def _stop_process(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process = None


_TUNNELS: dict[str, SharedTunnel] = {}
_TUNNEL_LOCK = threading.Lock()


class RemoteVoiceClient:
    def __init__(self, settings: dict[str, Any], runtime: Path) -> None:
        self.settings = {**DEFAULT_REMOTE, **deepcopy(settings)}
        validate_remote(self.settings)
        self.identity = hashlib.sha256(json.dumps(self.settings, sort_keys=True).encode()).hexdigest()
        with _TUNNEL_LOCK:
            self.tunnel = _TUNNELS.setdefault(self.identity, SharedTunnel(self.settings, runtime / "pc-voice"))
            self.tunnel.references += 1
        self.lock = threading.Lock()
        self.active: dict[str, http.client.HTTPConnection] = {}
        self.closed = False
        self.generation = 0
        self.transports: dict[str, socket.socket] = {}
        self.last_health: dict[str, Any] = {}
        self.last_error = ""

    def available(self) -> bool:
        return bool(self.settings["url"]) and not self.closed

    def request(self, path: str, payload: dict[str, Any] | None = None, *, timeout: int | None = None, expected_generation: int | None = None) -> bytes:
        if not self.available():
            raise RuntimeError("请在设置中配置 PC 语音桥接地址")
        self.tunnel.ensure()
        request_id = uuid.uuid4().hex
        connection = self._connection(timeout or self.settings["timeout"])
        with self.lock:
            if self.closed or expected_generation is not None and expected_generation != self.generation:
                raise RuntimeError("PC 语音请求已关闭或取消")
            self.active[request_id] = connection
        try:
            body = None if payload is None else json.dumps({**payload, "request_id": request_id}, ensure_ascii=False).encode()
            connection.connect()
            with self.lock:
                if request_id not in self.active:
                    raise RuntimeError("PC 语音请求已取消")
                self.transports[request_id] = connection.sock
            connection.request("GET" if body is None else "POST", path, body=body,
                               headers=self._headers())
            response = connection.getresponse()
            reply = response.read(24 * 1024 * 1024 + 1)
            if len(reply) > 24 * 1024 * 1024:
                raise RuntimeError("PC 语音结果超过大小限制")
            if response.status != 200:
                message = "PC 语音请求失败"
                try:
                    message = json.loads(reply).get("error", message)
                except (ValueError, AttributeError):
                    pass
                raise RuntimeError(f"{message}（HTTP {response.status}）")
            with self.lock:
                if request_id not in self.active:
                    raise RuntimeError("PC 语音请求已取消")
            self.last_error = ""
            return reply
        except (OSError, http.client.HTTPException) as exc:
            self.last_error = "PC 语音连接中断或服务未运行"
            raise RuntimeError(self.last_error) from exc
        finally:
            with self.lock:
                self.active.pop(request_id, None)
                self.transports.pop(request_id, None)
            connection.close()

    def _connection(self, timeout: int) -> http.client.HTTPConnection:
        parsed = urlparse(self.settings["url"])
        # HTTPSConnection verifies certificates and hostnames using the system trust store.
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        return connection_type(parsed.hostname, parsed.port, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Connection": "close", "User-Agent": "HsinBridge/1.0"}
        if self.settings.get("token"):
            headers["Authorization"] = "Bearer " + self.settings["token"]
        return headers

    def health(self, expected_generation: int | None = None) -> dict[str, Any]:
        reply = json.loads(self.request("/health", timeout=5, expected_generation=expected_generation))
        if reply.get("service") != "hsin-pc-voice" or reply.get("protocol") != 1:
            raise RuntimeError("PC 语音服务身份或协议不匹配")
        self.last_health = reply
        return reply

    def cancel(self) -> None:
        with self.lock:
            self.generation += 1
            requests = [(request_id, connection, self.transports.get(request_id)) for request_id, connection in self.active.items()]
            self.active.clear()
            self.transports.clear()
        for request_id, connection, transport in requests:
            # shutdown 唤醒后台的阻塞 read；取消端点另在线程发送，不阻塞 Qt。
            if transport is not None:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()
            threading.Thread(target=self._cancel_remote, args=(request_id,), daemon=True).start()

    def _cancel_remote(self, request_id: str) -> None:
        connection = self._connection(2)
        try:
            connection.request("POST", "/v1/cancel", json.dumps({"request_id": request_id}),
                               self._headers())
            response = connection.getresponse()
            response.read(4096)
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancel()
        with _TUNNEL_LOCK:
            self.tunnel.references -= 1
            if self.tunnel.references == 0:
                self.tunnel.stop()
                _TUNNELS.pop(self.identity, None)


class RemoteSynthesizer:
    def __init__(self, settings: dict[str, Any], runtime: Path, voice_id: str = "hsin") -> None:
        self.client = RemoteVoiceClient(settings, runtime)
        self.cache = runtime / "tts/remote/cache"
        self.voice_id = voice_id

    def _fingerprint(self, health: dict[str, Any]) -> str:
        if "voices" in health:
            if self.voice_id not in health["voices"]:
                raise RuntimeError("PC 音色未安装：" + self.voice_id)
            return health["voices"][self.voice_id]["fingerprint"]
        if self.voice_id != "hsin":
            raise RuntimeError("PC 桥接尚未安装爱弥斯音色")
        return health["voice_fingerprint"]

    def available(self) -> bool:
        return self.client.available()

    def synthesize(self, text: str, language: str, speed: float) -> Path:
        from src.core.local_synthesizer import wave_info
        generation = self.client.generation
        health = self.client.health(generation)
        fingerprint = self._fingerprint(health)
        identity = [text, language, speed, fingerprint, self.voice_id]
        cache_key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        audio_path = self.cache / language / (cache_key + ".wav")
        if audio_path.is_file():
            try:
                wave_info(audio_path.read_bytes())
                return audio_path
            except (OSError, ValueError, wave.Error, EOFError):
                audio_path.unlink(missing_ok=True)
        audio = self.client.request("/v1/tts", {"text": text, "language": language, "speed": speed,
                                               "voice_fingerprint": fingerprint, "voice_id": self.voice_id}, expected_generation=generation)
        wave_info(audio)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path = audio_path.with_suffix(".part")
        pending_path.write_bytes(audio)
        pending_path.replace(audio_path)
        return audio_path

    def warmup(self, language: str) -> None:
        generation = self.client.generation
        self._fingerprint(self.client.health(generation))
        reply = json.loads(self.client.request("/v1/warmup", {"language": language, "voice_id": self.voice_id}, expected_generation=generation))
        if reply.get("ready") is not True:
            raise RuntimeError("PC 语音预热未完成")

    def cancel(self) -> None:
        self.client.cancel()

    def close(self) -> None:
        self.client.close()
