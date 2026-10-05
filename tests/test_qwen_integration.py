"""隔离进程取消、新请求复用及Qwen音频缓存；不加载真实权重。"""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave
import base64

from src.core.model_process import ModelProcess
from src.core.qwen_voice import QwenSynthesizer


class QwenIntegrationTest(unittest.TestCase):
    def test_actual_child_cancellation_wakes_waiter_and_next_child_works(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'worker.py'
            script.write_text('import sys,json,time\nfrom pathlib import Path\nfor line in sys.stdin:\n r=json.loads(line)\n if r["operation"]=="hold":\n  Path(r["ready"]).touch()\n  time.sleep(60)\n print(json.dumps({"id":r["id"],"text":"new"}),flush=True)\n', encoding='utf-8')
            spawn = subprocess.Popen
            client = ModelProcess(sys.executable, 'cpu', root)
            with patch('src.core.model_process.subprocess.Popen', side_effect=lambda command, **kwargs: spawn([sys.executable, '-u', str(script)], **kwargs)), ThreadPoolExecutor(1) as pool:
                future = pool.submit(client.request, 'hold', ready=str(root / 'ready'))
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                try:
                    self.assertTrue((root / 'ready').exists())
                    old = client.process
                    self.assertFalse(client.release_idle(), '闲置释放不能终止运行中的请求')
                    self.assertIsNone(old.poll())
                    client.cancel()
                    with self.assertRaisesRegex(RuntimeError, '取消|结束'):
                        future.result(timeout=3)
                    self.assertIsNotNone(old.poll())
                    self.assertEqual(client.request('new')['text'], 'new')
                    self.assertNotEqual(client.process.pid, old.pid)
                    warm = client.process
                    self.assertTrue(client.release_idle())
                    self.assertIsNotNone(warm.poll())
                    self.assertEqual(client.request('new')['text'], 'new')
                    self.assertNotEqual(client.process.pid, warm.pid)
                finally:
                    client.close()

    def test_cache_isolated_by_language_weights_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for lang in ('zh', 'ja'):
                folder = root / lang
                folder.mkdir()
                (folder / 'config.json').write_text('{}')
                (folder / 'model.safetensors').write_bytes(b'fixture')
            ref = root / 'reference.wav'
            ref.write_bytes(b'fixture')
            profiles = root / 'profiles.json'
            profiles.write_text(json.dumps({'profiles': {'ja': {'reference_audio': str(ref), 'prompt_text': 'reference'}}}))
            settings = {'python': sys.executable, 'gpu': 'cpu', 'zh_model': str(root / 'zh'), 'ja_model': str(root / 'ja')}
            voice = QwenSynthesizer(settings, profiles, root)
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                output.writeframes(b'\0' * 24000)
            with patch.object(voice.worker, 'request', return_value={'audio': base64.b64encode(buffer.getvalue()).decode()}) as call:
                try:
                    zh = voice.synthesize('御者。', 'zh', 1)
                    self.assertEqual(voice.synthesize('御者。', 'zh', 1), zh)
                    ja = voice.synthesize('御者。', 'ja', 1)
                    self.assertNotEqual(zh, ja)
                    self.assertEqual(call.call_count, 2)
                    ref.write_bytes(b'changed reference')
                    self.assertNotEqual(voice.synthesize('御者。', 'ja', 1), ja)
                    voice.warmup('zh')
                    self.assertEqual(call.call_count, 4, '真实预热不应查缓存')
                    with self.assertRaisesRegex(ValueError, '语速'):
                        voice.synthesize('御者。', 'ja', .9)
                finally:
                    voice.close()
