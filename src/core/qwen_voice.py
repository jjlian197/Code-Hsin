"""中文单说话人检查点与日文Base克隆；缓存隔离，停止可取消真实推理。"""
import base64
import hashlib
import json
from pathlib import Path
import wave

from src.core.app_config import project_path
from src.core.model_process import ModelProcess


class QwenSynthesizer:
    def __init__(self, settings, profiles, runtime):
        self.settings, self.profiles = settings, Path(profiles)
        self.runtime = Path(runtime) / 'tts/qwen'
        self.worker = ModelProcess(settings['python'], settings.get('gpu', '4080'), self.runtime)

    def available(self):
        return project_path(self.settings['python']).is_file() and all(
            (project_path(self.settings[key]) / 'config.json').is_file() for key in ('zh_model', 'ja_model')) and self.profiles.is_file()

    def _request(self, text, language):
        model = project_path(self.settings['zh_model' if language == 'zh' else 'ja_model'])
        params = dict(model=str(model), text=text, language=language)
        resources = [model / 'model.safetensors', model / 'config.json']
        if language == 'ja':
            profile = json.loads(self.profiles.read_text(encoding='utf-8'))['profiles']['ja']
            params.update(reference_audio=str(project_path(profile['reference_audio'])), reference_text=profile['prompt_text'])
            resources.append(Path(params['reference_audio']))
        identity = [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in resources]
        key = hashlib.sha256(json.dumps(['qwen-selected-1', params, identity], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return params, key

    def synthesize(self, text, language, speed):
        if speed != 1:
            raise ValueError('Qwen实验音色当前使用原始语速1.0，请勿自动减速')
        from src.core.tts_manager import wave_info
        params, key = self._request(text, language)
        path = self.runtime / 'cache' / language / (key + '.wav')
        if path.is_file():
            try:
                wave_info(path.read_bytes())
                return path
            except (OSError, ValueError, wave.Error, EOFError):
                path.unlink(missing_ok=True)
        result = self.worker.request('tts', **params)
        payload = base64.b64decode(result['audio'], validate=True)
        wave_info(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.part')
        temp.write_bytes(payload)
        temp.replace(path)
        return path

    def warmup(self, language):
        # 不查磁盘缓存，真实运行一次所选音色。
        params, _ = self._request('御者，我在。' if language == 'zh' else '御者、お疲れさま。', language)
        self.worker.request('tts', **params)

    def cancel(self):
        self.worker.cancel()

    def close(self):
        self.worker.close()
