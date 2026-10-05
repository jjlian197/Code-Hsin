"""启动可手动验收的独立4B桌面窗口；配置和状态保存在独立会话目录。"""
import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.app_config import load_config, validate_config
from tools.local_ollama_test_service import test_service
from tools.prepare_qwen_acceptance import OUT, main as prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpu', choices=('4080', '8gb'), default='4080')
    parser.add_argument('--voice', action='store_true', help='启用Qwen ASR/TTS，麦克风仍默认关闭')
    args = parser.parse_args()
    if not (OUT / 'config.yaml').exists():
        prepare()
    with test_service(args.gpu) as service:
        config = load_config(OUT / 'config.yaml')
        config.pop('_config_path', None)
        folder = OUT / 'sessions' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
        folder.mkdir(parents=True)
        config['runtime']['directory'] = str(folder / 'runtime')
        config['logging']['file'] = str(folder / 'runtime/hsin.log')
        config['chat'].update(provider='ollama', enabled=True, speech_scope='off')
        config['chat']['ollama'].update(url=service['url'], model=service['model'], thinking=False,
                                       context_length=8192 if args.gpu == '4080' else 4096)
        config['voice'].update(enabled=False, auto_translate=False, fallback=False)
        config['stt']['fallback'] = False
        if args.voice:
            config['chat']['speech_scope'] = 'full'
            config['voice'].update(provider='qwen', enabled=True)
            config['voice']['qwen']['gpu'] = args.gpu
            config['stt']['provider'] = 'qwen'
            config['stt']['qwen']['gpu'] = args.gpu
        config['http']['enabled'] = config['websocket']['enabled'] = False
        validate_config(config)
        path = folder / 'config.yaml'
        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
        print('本次窗口使用Qwen听写、4B和选定中日Qwen音色；麦克风默认关闭。' if args.voice else '本次窗口只验收4B聊天与本地翻译，语音关闭、麦克风默认关闭。', flush=True)
        print('退出本次窗口后，本次模型服务会自动清理。', flush=True)
        print('独立配置:', path, flush=True)
        process = subprocess.Popen([sys.executable, '-m', 'src.main', '--config', str(path)], cwd=str(ROOT))
        try:
            return process.wait()
        except KeyboardInterrupt:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=20)
            return 130


if __name__ == '__main__':
    raise SystemExit(main())
