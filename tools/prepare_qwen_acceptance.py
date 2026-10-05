"""准备隔离验收配置及资源清单，不下载、不启动服务、不复制云端凭据。"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.app_config import DEFAULT_CONFIG, load_config, validate_config

BASE = ROOT / '.runtime/local-model-tests'
OUT = BASE / 'acceptance'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config = deepcopy(DEFAULT_CONFIG)
    # 仅沿用角色资源；不将用户的密钥、历史或连接设置写入测试配置。
    config['sprite'] = deepcopy(load_config()['sprite'])
    config['runtime']['directory'] = str(OUT / 'runtime')
    config['logging']['file'] = str(OUT / 'runtime/hsin.log')
    config['setup'] = {'completed': True}
    config['chat'].update(provider='ollama', enabled=True, reply_length='normal', speech_scope='off')
    config['chat']['ollama'].update(url='http://127.0.0.1:11435', context_length=8192)
    config['voice'].update(enabled=False, fallback=False, auto_translate=False, port=19890)
    config['stt']['fallback'] = False
    config['http']['enabled'] = config['websocket']['enabled'] = False
    validate_config(config)
    path = OUT / 'config.yaml'
    if not path.exists():
        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
    resources = {
        'asr_model': BASE / 'models/qwen3-asr/model.safetensors',
        'asr_python': BASE / 'venv-asr/Scripts/python.exe',
        'tts_python': BASE / 'venv-tts/Scripts/python.exe',
        'tts_zh_model': ROOT / '.runtime/qwen3-tts-training/zh/checkpoint-epoch-3/model.safetensors',
        'tts_ja_model': BASE / 'models/qwen3-tts/model.safetensors',
        'reference_profiles': ROOT / 'voice/profiles.json'}
    info = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))
    resources['brain_blob'] = Path(info['path'])
    report = {'model': info['ollama_model'], 'config': str(path),
        'resources': {name: {'path': str(value), 'ready': value.is_file() and value.stat().st_size > 0} for name, value in resources.items()},
        'gpu_inventory': subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid,memory.total', '--format=csv,noheader'], text=True).strip(),
        'stages': {'chat_translation': 'experimental integration ready', 'tools': 'blocked by model protocol failures',
            'asr_tts_application': 'source adapters integrated; see voice-validation-4080.json for real verification', 'microphone': 'off; human recording pending',
            '8gb_joint_load': 'pending after full integration'}}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            tags = json.load(response)
        report['installed_in_ollama'] = any(row.get('name') == info['ollama_model'] for row in tags.get('models', []))
    except OSError:
        report['installed_in_ollama'] = None
    (OUT / 'resources.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('验收配置:', path)
    print('本机资源:', '齐备' if all(row['ready'] for row in report['resources'].values()) else '有缺失，见资源清单')
    print('Qwen听写/TTS源码入口已接入；真人收音与8GB共同运行尚待验收。')


if __name__ == '__main__':
    main()
