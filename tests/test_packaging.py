"""发行必要行为：资源可搬迁、状态可写、无训练资源时固定语音可播放。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock, call
import ctypes
import os
from src.core import app_config
from src.core.preset_voice import preset_key
from src.core.tts_manager import LocalSynthesizer
from test_tts import sample_wave


class PackagingTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows 冻结 DLL 搜索目录')
    def test_external_gpt_environment_is_cleaned_and_dll_directory_restored_on_launch_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / '_internal'
            synth = LocalSynthesizer(root / 'profiles.json', root)
            kernel = Mock()
            data = {'profile_id': 'test', 'installation': {'python': 'external-python.exe', 'gptsovits_root': str(root)}}
            with patch.object(synth, 'health', side_effect=OSError), \
                 patch('src.core.tts_manager.sys.frozen', True, create=True), \
                 patch('src.core.tts_manager.sys._MEIPASS', str(bundle), create=True), \
                 patch.object(ctypes.windll, 'kernel32', kernel), \
                 patch.dict(os.environ, {'PATH': str(bundle / 'PyQt6') + os.pathsep + str(root / 'external')}), \
                 patch('src.core.tts_manager.subprocess.Popen', side_effect=OSError('launch failed')) as launch:
                with self.assertRaisesRegex(OSError, 'launch failed'):
                    synth.ensure_server(data)
                self.assertNotIn(str(bundle), launch.call_args.kwargs['env']['PATH'])
                self.assertIn(str(root / 'external'), launch.call_args.kwargs['env']['PATH'])
                self.assertEqual(kernel.SetDllDirectoryW.call_args_list, [call(None), call(str(bundle))])
            synth.close()

    def test_frozen_resource_fallback_keeps_configuration_beside_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / '_internal'
            resource.mkdir()
            (resource / 'image.png').write_bytes(b'image')
            with patch.object(app_config, 'PROJECT_ROOT', root), patch.object(app_config, 'RESOURCE_ROOT', resource):
                self.assertEqual(app_config.project_path('image.png'), resource / 'image.png')
                self.assertEqual(app_config.project_path('config.local.yaml'), root / 'config.local.yaml')
                (root / 'image.png').write_bytes(b'override')
                self.assertEqual(app_config.project_path('image.png'), root / 'image.png')

    def test_preset_works_without_weights_profile_or_server_and_new_text_requires_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifest.json'
            text = '御者，我在这里。'
            (root / 'voice.wav').write_bytes(sample_wave())
            manifest.write_text(json.dumps({'entries': {preset_key(text, 'zh'): {'text': text, 'language': 'zh', 'file': 'voice.wav'}}}), encoding='utf8')
            with patch('src.core.preset_voice.project_path', return_value=manifest):
                synth = LocalSynthesizer(root / 'missing-profile.json', root)
            with patch.object(synth, 'ensure_server') as server:
                self.assertEqual(synth.synthesize(text, 'zh', 1), root / 'voice.wav')
                server.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, '预存语音'):
                    synth.synthesize('新的回答', 'zh', 1)
                with self.assertRaises(RuntimeError):
                    synth.synthesize(text, 'zh', 1.5)
            synth.close()
