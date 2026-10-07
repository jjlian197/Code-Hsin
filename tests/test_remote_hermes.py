from __future__ import annotations

import asyncio
import threading
from typing import Any
import unittest
from unittest.mock import patch

from src.core.remote_hermes import RemoteHermesBridge
from tools.hsin_pc_voice_server import VoiceServer


class FakeAgent:
    instances: list['FakeAgent'] = []
    cancelled = threading.Event()
    started = threading.Event()

    def __init__(self, configuration: dict[str, Any]) -> None:
        self.configuration = configuration
        self.history: list[str] = []
        self.instances.append(self)

    async def chat(self, text: str, language: str, delta: Any, **preferences: Any) -> str:
        self.history.append(text)
        await delta('心：')
        self.started.set()
        if text == 'wait':
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
        await delta(text)
        return '心：' + text


class UnusedVoiceBackend:
    def transcribe(self, payload: Any) -> None: raise AssertionError('Unexpected voice request')
    synthesize = transcribe
    warmup = transcribe


class RemoteHermesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAgent.instances = []
        FakeAgent.cancelled.clear(); FakeAgent.started.clear()
        self.patch = patch('src.core.pc_hermes.HermesBridge', FakeAgent)
        self.patch.start()
        self.token = 'h' * 64
        self.server = VoiceServer(('127.0.0.1', 0), UnusedVoiceBackend(), self.token, {'profile': 'default'})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = RemoteHermesBridge({'url': f'http://127.0.0.1:{self.server.server_port}', 'token': self.token})

    async def asyncTearDown(self) -> None:
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close(); self.thread.join(2); self.patch.stop()

    async def test_stream_reuses_agent_history_and_rejects_bad_token(self) -> None:
        chunks: list[str] = []
        async def delta(chunk: str) -> None: chunks.append(chunk)
        self.assertEqual(await self.client.chat('one', 'zh', delta), '心：one')
        self.assertEqual(await self.client.chat('two', 'zh', delta), '心：two')
        self.assertEqual(chunks, ['心：', 'one', '心：', 'two'])
        self.assertEqual(len(FakeAgent.instances), 1)
        self.assertEqual(FakeAgent.instances[0].history, ['one', 'two'])
        self.assertEqual(FakeAgent.instances[0].configuration['profile'], 'default')
        self.client.token = 'wrong'
        with self.assertRaises(RuntimeError): await self.client.chat('three', 'zh', delta)
        self.assertEqual(FakeAgent.instances[0].history, ['one', 'two'])

    async def test_cancel_reaches_only_this_agent_request(self) -> None:
        async def delta(chunk: str) -> None: pass
        task = asyncio.create_task(self.client.chat('wait', 'zh', delta))
        self.assertTrue(await asyncio.to_thread(FakeAgent.started.wait, 3))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(await asyncio.to_thread(FakeAgent.cancelled.wait, 3))
        self.assertEqual(len(FakeAgent.instances), 1)
