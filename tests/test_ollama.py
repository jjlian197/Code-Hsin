"""本机流协议、取消与翻译路由的回归检查，不使用真实模型或云端。"""
import asyncio
from copy import deepcopy
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from src.core.app_config import DEFAULT_CONFIG, validate_chat_config
from src.core.ollama_bridge import OllamaBridge
from src.core.voice_auxiliary import VoiceTranslator


class LocalProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.payloads = []
        self.release = asyncio.Event()
        async def serve(request):
            payload = await request.json()
            self.payloads.append(payload)
            text = payload['messages'][-1]['content']
            response = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson'})
            await response.prepare(request)
            async def frame(value):
                await response.write((json.dumps(value, ensure_ascii=False) + '\n').encode())
            await frame({'message': {'thinking': '不应显示或朗读'}})
            await frame({'message': {'content': '御者，我在。'}})
            if text == 'cancel':
                await self.release.wait()
            if text != 'interrupted':
                try:
                    await frame({'done': True, 'done_reason': 'length' if text == 'limited' else 'stop'})
                except ConnectionResetError:
                    pass
            return response
        app = web.Application()
        app.router.add_post('/api/chat', serve)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, '127.0.0.1', 0).start()
        self.bridge = OllamaBridge({'url': f'http://127.0.0.1:{self.runner.addresses[0][1]}', 'model': 'fixture'})

    async def asyncTearDown(self):
        self.release.set()
        await self.runner.cleanup()

    async def test_only_final_text_streams_and_history_commits_after_done(self):
        chunks = []
        async def delta(text): chunks.append(text)
        self.assertEqual(await self.bridge.chat('limited', 'ja', delta), '御者，我在。')
        self.assertEqual(chunks, ['御者，我在。'])
        self.assertIn('预算', self.bridge.warning)
        self.assertFalse(self.payloads[0]['think'])
        self.assertNotIn('tools', self.payloads[0])
        self.assertEqual(len(self.bridge.history), 2)
        with self.assertRaisesRegex(RuntimeError, '中断'):
            await self.bridge.chat('interrupted', 'zh', delta)
        self.assertEqual(len(self.bridge.history), 2)

    async def test_cancelled_stream_does_not_commit_history_and_next_request_works(self):
        started = asyncio.Event()
        async def delta(text): started.set()
        task = asyncio.create_task(self.bridge.chat('cancel', 'zh', delta))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.bridge.history, [])
        self.release.set()
        self.assertEqual(await self.bridge.chat('new', 'zh', delta), '御者，我在。')
        self.assertEqual(self.bridge.history[0]['content'], 'new')


class LocalTranslationTest(unittest.TestCase):
    def test_local_translation_never_uses_cloud_key_and_cache_is_separate(self):
        config = deepcopy(DEFAULT_CONFIG)
        config['chat']['provider'] = 'ollama'
        output = {'message': {'content': '御者、おはよう。'}, 'done': True, 'done_reason': 'stop'}
        requests = []
        def open_local(request, **kwargs):
            requests.append(request)
            return io.BytesIO(json.dumps(output).encode())
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.build_opener') as opener, patch('urllib.request.urlopen') as cloud:
            opener.return_value.open.side_effect = open_local
            translator = VoiceTranslator(config, folder)
            self.assertEqual(translator.translate('御者，早安。', 'ja'), '御者、おはよう。')
            translator.translate('御者，早安。', 'ja')
            self.assertEqual(len(requests), 1)
            self.assertNotIn('Authorization', requests[0].headers)
            self.assertFalse(json.loads(requests[0].data)['think'])
            output['done_reason'] = 'length'
            with self.assertRaisesRegex(ValueError, '截断'):
                translator.translate('御者，午安。', 'ja')
            cloud.assert_not_called()
            config['chat']['provider'] = 'deepseek'
            config['chat']['deepseek']['api_key'] = 'test-only'
            cloud.return_value = io.BytesIO(json.dumps({'choices': [{'message': {'content': '別の訳文。'}}]}).encode())
            self.assertEqual(translator.translate('御者，早安。', 'ja'), '別の訳文。')
            cloud.assert_called_once()

    def test_config_rejects_remote_address_and_invalid_budget(self):
        config = deepcopy(DEFAULT_CONFIG['chat'])
        config['provider'] = 'ollama'
        config['ollama']['url'] = 'http://example.com'
        with self.assertRaises(ValueError): validate_chat_config(config)
        config['ollama']['url'] = 'http://127.0.0.1:11434'
        config['ollama']['context_length'] = True
        with self.assertRaises(ValueError): validate_chat_config(config)
