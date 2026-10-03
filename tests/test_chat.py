"""后端协议、串流隔离、会话恢复及切换取消；不发送真实远程消息。"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aiohttp import web, ClientSession
from PyQt6.QtWidgets import QApplication
from src.core.app_config import DEFAULT_CONFIG, validate_chat_config
from src.core.chat_backends import read_sse
from src.core.chat_manager import ChatManager
from src.core.hermes_bridge import HermesBridge


class ProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_hermes_batched_reply_keeps_events_and_uses_own_session(self):
        calls = []
        async def root(request):
            return web.Response(text='window.__HERMES_SESSION_TOKEN__="fixture-secret";')
        async def socket(request):
            self.assertEqual(request.query["token"], "fixture-secret")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                frame = json.loads(msg.data)
                method, params = frame["method"], frame["params"]
                calls.append((method, params))
                result = {"session_id": "owned", "stored_session_id": "saved"} if method in ("session.create", "session.resume") else {"status": "streaming"}
                frames = [{"id": frame["id"], "result": result}]
                if method == "prompt.submit":
                    frames += [{"method": "event", "params": {"type": "message.complete", "session_id": "someone-else", "payload": {"text": "wrong"}}},
                               {"method": "event", "params": {"type": "message.delta", "session_id": "owned", "payload": {"text": "御者"}}},
                               {"method": "event", "params": {"type": "message.complete", "session_id": "owned", "payload": {"text": "御者，我在。", "status": "complete"}}}]
                await ws.send_str("\n".join(json.dumps(f) for f in frames))
            return ws
        app = web.Application()
        app.router.add_get("/", root)
        app.router.add_get("/api/ws", socket)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            bridge = HermesBridge({"url": f"http://127.0.0.1:{runner.addresses[0][1]}", "profile": "hsin"})
            chunks = []
            async def delta(text): chunks.append(text)
            self.assertEqual(await bridge.chat("你好", "zh", delta), "御者，我在。")
            self.assertEqual(await bridge.chat("もう一度", "ja", delta), "御者，我在。")
            self.assertEqual(chunks, ["御者", "御者"])
            resume = next(params for method, params in calls if method == "session.resume")
            self.assertEqual(resume["session_id"], "saved")
            self.assertEqual(resume["profile"], "hsin")
            self.assertIn("日语", calls[-1][1]["text"])
        finally:
            await runner.cleanup()

    async def test_sse_excludes_reasoning_progress_and_rejects_interruption(self):
        lines = [b': keepalive\n', b'event: hermes.tool.progress\n', b'data: {"tool":"terminal"}\n', b'\n',
                 b'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}\n', b'\n',
                 ('data: '+json.dumps({"choices":[{"delta":{"content":"心在这里。"}}]},ensure_ascii=False)+'\n').encode(), b'\n', b'data: [DONE]\n', b'\n']
        class Lines:
            def __aiter__(self):
                async def gen():
                    for line in lines: yield line
                return gen()
        chunks=[]
        async def delta(text): chunks.append(text)
        self.assertEqual(await read_sse(Lines(),delta), "心在这里。")
        self.assertEqual(chunks,["心在这里。"])
        lines.pop(-2)
        with self.assertRaisesRegex(RuntimeError,"中断"):
            await read_sse(Lines(),delta)


class ManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["chat-test"])

    def pump(self, condition):
        deadline=time.monotonic()+3
        while not condition() and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition())

    def test_switch_discards_late_result_persists_provider_and_delivers_on_gui(self):
        started=threading.Event()
        class Backend:
            async def chat(self,text,language,delta):
                if text=="old":
                    started.set()
                    try: await asyncio.sleep(10)
                    except asyncio.CancelledError: return "late"
                await delta("新回复")
                return "新回复"
        with tempfile.TemporaryDirectory() as temp, patch("src.core.chat_manager.make_backend", return_value=Backend()):
            config=deepcopy(DEFAULT_CONFIG)
            config["runtime"]["directory"]=temp
            manager=ChatManager(config)
            received=[]
            manager.reply_ready.connect(lambda *args: received.append((args,threading.get_ident())))
            try:
                manager.send("old","zh")
                self.pump(started.is_set)
                manager.configure("deepseek")
                manager.send("new","ja")
                self.pump(lambda: bool(received))
                self.assertEqual(received,[(('新回复','ja'),threading.get_ident())])
                self.assertNotIn("late",str(manager.messages))
                self.assertNotIn("api_key",json.dumps(manager.snapshot()))
            finally: manager.close()
            self.assertFalse(manager.thread.is_alive())
            restored=ChatManager(config)
            try: self.assertEqual(restored.provider,"deepseek")
            finally: restored.close()

    def test_local_backends_reject_remote_address_and_credential_url(self):
        config=deepcopy(DEFAULT_CONFIG["chat"])
        for value in ("http://example.com", "http://user:password@127.0.0.1:1234"):
            config["hermes"]["url"]=value
            with self.assertRaises(ValueError): validate_chat_config(config)

    def test_final_suffix_sentences_and_failed_stream_signal(self):
        class Backend:
            async def chat(self, text, language, delta):
                await delta("御者，我在。")
                if text == "error":
                    raise RuntimeError("fixture interrupted")
                return "御者，我在。まだここにいます。末句"
        with tempfile.TemporaryDirectory() as temp, patch("src.core.chat_manager.make_backend", return_value=Backend()):
            config = deepcopy(DEFAULT_CONFIG)
            config["runtime"]["directory"] = temp
            manager = ChatManager(config)
            sentences, finishes = [], []
            manager.sentence_ready.connect(lambda *args: sentences.append(args))
            manager.speech_finished.connect(lambda *args: finishes.append(args))
            try:
                request = manager.send("ok", "ja")
                self.pump(lambda: not manager.busy)
                self.assertEqual(sentences, [(request["id"], t, "ja") for t in ["御者，我在。", "まだここにいます。", "末句"]])
                self.assertEqual(finishes, [(request["id"], True)])
                request = manager.send("error", "zh")
                self.pump(lambda: not manager.busy)
                self.assertEqual(finishes[-1], (request["id"], False))
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
