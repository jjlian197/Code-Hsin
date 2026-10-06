"""验证真实冻结EXE，隔离端口/用户数据；只用预存音频静音播放，不开麦、不请求聊天。"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import yaml
from src.core.app_config import DEFAULT_CONFIG, load_config, merge_config, project_path
from src.core.character_settings import profile_from_config
from src.core.voice_phrases import PREVIEW_PHRASES


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--private-models', action='store_true')
    args = parser.parse_args()
    exe, output, data = Path(args.exe).resolve(), Path(args.out).resolve(), Path(args.data).resolve()
    output.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    config = merge_config(DEFAULT_CONFIG, yaml.safe_load((exe.parent / 'config.yaml').read_text(encoding='utf8')))
    config['http']['port'], config['websocket']['port'], config['voice']['port'] = free_port(), free_port(), free_port()
    config['chat']['enabled'] = False
    config['voice'].update(enabled=True, auto_translate=False, fallback=False)
    checks = []
    if args.private_models:
        original = load_config()
        config['sprite']['model'] = deepcopy(original['sprite']['model'])
        model = config['sprite']['model']
        model['path'] = str(project_path(model['path']))
        model['forms'] = {key: str(project_path(value)) for key, value in model['forms'].items()}
        model['texture_overrides'] = {key: {source: str(project_path(target)) for source, target in mapping.items()}
                                      for key, mapping in model.get('texture_overrides', {}).items()}
        config['sprite']['animation']['physics'] = False
        hsin = profile_from_config(config)
        hsin['id'] = 'hsin'
        aemeath = profile_from_config(config, '爱弥斯', str(project_path('.runtime/characters/aemeath/character.json')), '你是爱弥斯，在桌面上陪伴用户。')
        aemeath['id'] = 'aemeath'
        aemeath['voice'].update(enabled=False, fallback=False)
        (data / '.runtime').mkdir(exist_ok=True)
        (data / '.runtime/characters.json').write_text(json.dumps({'version': 1, 'active': 'hsin', 'profiles': [hsin, aemeath]}, ensure_ascii=False), encoding='utf8')
    config_file = output / 'validation-config.yaml'
    config_file.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf8')
    base = f"http://127.0.0.1:{config['http']['port']}"
    def command(kind, payload):
        request = urllib.request.Request(base + '/api/command', data=json.dumps({'type': kind, 'data': payload}, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=8) as response:
            value = json.load(response)
        assert value['success'], value
        return value['data']
    def status():
        with urllib.request.urlopen(base + '/api/status', timeout=3) as response:
            return json.load(response)['data']
    def wait(check, timeout=60):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if process.poll() is not None:
                raise AssertionError('EXE exited before validation: ' + str(process.returncode))
            try:
                current = status()
                if check(current):
                    return current
            except (OSError, ValueError):
                pass
            time.sleep(.15)
        raise AssertionError('EXE condition timed out')
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)
    if (exe.parent / 'portable.txt').is_file() and data == exe.parent / 'data':
        env.pop('HSIN_DATA_DIR', None)
    else:
        env['HSIN_DATA_DIR'] = str(data)
    process = subprocess.Popen([str(exe), '--config', str(config_file), '--run-for', '180', '--snapshot', str(output / 'preview.png')], cwd=str(output), env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        current = wait(lambda item: bool(item['renderer']['model_loaded'] or item['renderer']['error']))
        assert not current['stt']['enabled'] and not current['chat']['enabled']
        checks.append('冻结EXE从非源码目录启动，麦克风和聊天关闭')
        assert (data / '.runtime/hsin.log').is_file()
        assert not (exe.parent / '.runtime').exists()
        checks.append('运行日志/状态写入独立用户数据目录')
        if args.private_models:
            assert current['renderer']['model_loaded'], current['renderer']['error']
            assert current['renderer']['info']['texture_errors'] == 0
            for form in ('first', 'second'):
                command('model', {'form': form})
                current = wait(lambda item: item['renderer']['model_loaded'])
                assert current['renderer']['info']['texture_errors'] == 0
                assert 'finger_heart' in current['available_motions']
            checks.append('用户导入心双形态，真实PMX和贴图加载完整')
        else:
            assert '需要存在的本地 PMX 模型' in (current['renderer']['error'] or '') and not current['renderer']['model_loaded'], current['renderer']['error']
            checks.append('缺少PMX时界面/设置/控制服务仍可运行')
        for language in ('zh', 'ja'):
            command('tts_config', {'language': language, 'enabled': True})
            request = command('speak', {'text': PREVIEW_PHRASES[language], 'language': language, 'volume': 0, 'translate': False})
            current = wait(lambda item: item['audio']['state'] == 'PlayingState')
            assert current['tts']['actual_provider'] == 'gptsovits'
            wait(lambda item: not item['tts']['active'])
        checks.append('无权重/推理环境时中日预存音频真实解码静音播放')
        if args.private_models:
            command('character', {'action': 'switch', 'id': 'aemeath'})
            current = wait(lambda item: item['character']['active'] == 'aemeath' and not item['character']['switching'])
            assert current['renderer']['info']['character'] == '爱弥斯'
            assert current['renderer']['info']['texture_errors'] == 0
            command('character', {'action': 'switch', 'id': 'hsin'})
            current = wait(lambda item: item['character']['active'] == 'hsin' and not item['character']['switching'])
            assert current['renderer']['info']['character'] is None
            checks.append('冻结EXE完整角色配置切换爱弥斯并恢复心')
        # 等待模型加载后的延迟截图完成，避免保存角色切换中的加载画面。
        time.sleep(1.2)
        command('window', {'action': 'quit'})
        process.wait(timeout=15)
        assert process.returncode == 0
        checks.append('退出成功，服务进程清理完成')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
    report = {'success': True, 'checks': checks}
    (output / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
