"""真实回环 HTTP 检查协议、音色缓存、取消与智谱选择，模拟后端不证明推理性能。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
import unittest
from unittest.mock import Mock, patch
import wave

from src.core.remote_voice import RemoteSynthesizer, RemoteVoiceClient, validate_remote
from src.core.speech_recognizer import SpeechRecognizer
from tools.hsin_pc_voice_server import VoiceServer


def test_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 3200)
    return buffer.getvalue()


class FakeBackend:
    def __init__(self) -> None:
        self.fingerprint = "first-voice"
        self.syntheses = 0
        self.calls: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def health(self) -> dict[str, Any]:
        return {"service": "hsin-pc-voice", "protocol": 1, "voice_fingerprint": self.fingerprint}

    def transcribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("stt")
        return {"text": "心月狐", "provider": "remote-qwen"}

    def synthesize(self, payload: dict[str, Any]) -> bytes:
        self.calls.append(payload["text"])
        self.syntheses += 1
        if payload["text"] == "blocked":
            self.entered.set()
            self.release.wait(3)
        return test_wav()

    def warmup(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True}


class RemoteVoiceTests(unittest.TestCase):
    def test_role_voice_cache_isolation_and_missing_voice_never_falls_back(self) -> None:
        with patch.object(self.backend, "health", return_value={
                "service": "hsin-pc-voice", "protocol": 1,
                "voices": {"hsin": {"fingerprint": "same"}, "aemeath": {"fingerprint": "same"}}}):
            heart = RemoteSynthesizer(self.settings, self.root, "hsin")
            aemeath = RemoteSynthesizer(self.settings, self.root, "aemeath")
            try:
                self.assertNotEqual(heart.synthesize("相同台词", "zh", 1), aemeath.synthesize("相同台词", "zh", 1))
                self.assertEqual(self.backend.syntheses, 2)
            finally:
                heart.close()
                aemeath.close()
        missing = RemoteSynthesizer(self.settings, self.root, "aemeath")
        try:
            with self.assertRaisesRegex(RuntimeError, "爱弥斯"):
                missing.synthesize("不可回退", "zh", 1)
        finally:
            missing.close()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.backend = FakeBackend()
        self.server = VoiceServer(("127.0.0.1", 0), self.backend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.settings = {"url": f"http://127.0.0.1:{self.server.server_port}"}
        self.client = RemoteVoiceClient(self.settings, self.root)

    def tearDown(self) -> None:
        self.backend.release.set()
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.directory.cleanup()

    def test_local_only_endpoint_and_identity(self) -> None:
        for endpoint in ("http://192.168.50.230:19881", "http://127.0.0.1:80/bad", "http://user:pass@127.0.0.1:80", "http://127.0.0.1:bad"):
            with self.assertRaises(ValueError):
                validate_remote({"url": endpoint})
        self.assertEqual(self.client.health()["service"], "hsin-pc-voice")
        with patch.object(self.backend, "health", return_value={"service": "other", "protocol": 1}):
            with self.assertRaisesRegex(RuntimeError, "身份"):
                self.client.health()

    def test_token_protects_health_and_inference(self) -> None:
        self.server.token = "test-token-" * 4
        with self.assertRaisesRegex(RuntimeError, "401"):
            self.client.health()
        with self.assertRaisesRegex(RuntimeError, "401"):
            self.client.request("/v1/tts", {"text": "unauthorized"})
        self.assertEqual(self.backend.syntheses, 0)
        authorized = RemoteVoiceClient({**self.settings, "token": self.server.token}, self.root)
        try:
            self.assertEqual(authorized.health()["protocol"], 1)
            self.assertEqual(authorized.request("/v1/tts", {"text": "authorized"}), test_wav())
        finally:
            authorized.close()

    def test_https_transport_verifies_certificates_and_skips_ssh(self) -> None:
        secure = RemoteVoiceClient({"url": "https://bridge.example.test", "ssh_host": "unused", "token": "private"}, self.root)
        try:
            import http.client
            self.assertIsInstance(secure._connection(5), http.client.HTTPSConnection)
            self.assertEqual(secure._headers()["Authorization"], "Bearer private")
            self.assertNotIn("private", secure.identity)
            with patch("subprocess.Popen") as process:
                secure.tunnel.ensure()
                process.assert_not_called()
            for token in ("bad\r\nheader", 42):
                with self.assertRaises(ValueError):
                    validate_remote({"url": "https://bridge.example.test", "token": token})
        finally:
            secure.close()

    def test_remote_recognition_and_cloud_remain_separate(self) -> None:
        recognizer = SpeechRecognizer(self.root, self.settings)
        response = Mock(status_code=200)
        response.json.return_value = {"text": "智谱结果"}
        try:
            self.assertEqual(recognizer.transcribe(b"\x01\x00" * 3200, {"provider": "remote"}), ("心月狐", "remote-qwen", ""))
            with patch("requests.post", return_value=response) as cloud:
                self.assertEqual(recognizer.transcribe(bytes(640), {"provider": "zhipu", "zhipu": {"api_key": "test"}})[0], "智谱结果")
                self.assertEqual(cloud.call_count, 1)
            self.assertEqual(self.backend.calls, ["stt"])
        finally:
            recognizer.close()

    def test_voice_cache_isolated_by_server_fingerprint(self) -> None:
        voice = RemoteSynthesizer(self.settings, self.root)
        try:
            first = voice.synthesize("hello", "zh", 1.0)
            self.assertEqual(first.read_bytes(), test_wav())
            self.assertEqual(voice.synthesize("hello", "zh", 1.0), first)
            self.assertEqual(self.backend.syntheses, 1)
            self.backend.fingerprint = "second-voice"
            second = voice.synthesize("hello", "zh", 1.0)
            self.assertNotEqual(first, second)
            self.assertEqual(self.backend.syntheses, 2)
        finally:
            voice.close()

    def test_cancel_wakes_pending_read_and_server_discards_result(self) -> None:
        failures: list[str] = []

        def submit() -> None:
            try:
                self.client.request("/v1/tts", {"text": "blocked"})
            except RuntimeError as exc:
                failures.append(str(exc))

        worker = threading.Thread(target=submit)
        worker.start()
        self.assertTrue(self.backend.entered.wait(1))
        self.client.cancel()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(failures)
        self.backend.release.set()

    def test_cancel_prevents_next_stage_and_preserves_shared_connection(self) -> None:
        generation = self.client.generation
        sibling = RemoteVoiceClient(self.settings, self.root)
        self.assertIs(sibling.tunnel, self.client.tunnel)
        self.client.cancel()
        with self.assertRaisesRegex(RuntimeError, "取消"):
            self.client.request("/v1/stt", {}, expected_generation=generation)
        self.client.close()
        try:
            self.assertEqual(sibling.health()["protocol"], 1)
        finally:
            sibling.close()

    def test_cancel_before_submission_prevents_inference(self) -> None:
        request_id = "a" * 32
        self.client._cancel_remote(request_id)
        import urllib.request
        import urllib.error
        request = urllib.request.Request(self.settings["url"] + "/v1/tts",
                                         json.dumps({"request_id": request_id, "text": "never"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        self.assertEqual(rejected.exception.code, 409)
        self.assertEqual(self.backend.syntheses, 0)


@unittest.skipUnless(sys.platform == "darwin", "macOS SSH supervisor")
class TunnelSupervisorTests(unittest.TestCase):
    def test_parent_exit_terminates_owned_tunnel_child(self) -> None:
        supervisor_path = Path(__file__).resolve().parents[1] / "scripts/ssh_supervisor.sh"
        parent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        supervisor = subprocess.Popen(["/bin/sh", str(supervisor_path), str(parent.pid), sys.executable, "-u", "-c",
                                       "import os,time;print(os.getpid(),flush=True);time.sleep(30)"], stdout=subprocess.PIPE, text=True)
        try:
            child_pid = int(supervisor.stdout.readline())
            parent.terminate()
            parent.wait(timeout=2)
            self.assertEqual(supervisor.wait(timeout=3), 0)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=2)
            if supervisor.poll() is None:
                supervisor.terminate()
                supervisor.wait(timeout=3)
            supervisor.stdout.close()


if __name__ == "__main__":
    unittest.main()
