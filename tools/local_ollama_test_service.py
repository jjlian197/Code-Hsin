"""只管理验收自己启动的Ollama实例，不修改已有服务或下载模型。"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def test_service(gpu='4080', port=11435):
    base = ROOT / '.runtime/local-model-tests'
    output = base / 'acceptance'
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError('验收端口已被使用，请先结束此前的验收服务')
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
    target = 'RTX 4080 SUPER' if gpu == '4080' else 'RTX 5060 Laptop'
    matches = [line for line in inventory.splitlines() if target in line]
    if len(matches) != 1:
        raise RuntimeError('未唯一找到指定验收显卡')
    uuid = matches[0].rsplit(',', 1)[1].strip()
    info = json.loads((base / 'qwen-brain.json').read_text(encoding='utf-8'))
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES=uuid, CUDA_DEVICE_ORDER='PCI_BUS_ID', OLLAMA_HOST=f'127.0.0.1:{port}',
        OLLAMA_MODELS=str(Path(info['path']).parent.parent), OLLAMA_NO_CLOUD='true', OLLAMA_CONTEXT_LENGTH='8192' if gpu == '4080' else '4096',
        OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
    executable = shutil.which('ollama')
    if not executable:
        raise RuntimeError('未找到已安装的Ollama')
    url = f'http://127.0.0.1:{port}'
    client = requests.Session()
    client.trust_env = False
    with (output / 'ollama.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([executable, 'serve'], env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('验收Ollama启动失败')
                try:
                    client.get(url + '/api/version', timeout=1).raise_for_status()
                    break
                except requests.RequestException:
                    time.sleep(.2)
            else:
                raise RuntimeError('验收Ollama就绪超时')
            yield {'url': url, 'gpu_uuid': uuid, 'gpu': target, 'model': info['ollama_model']}
        finally:
            if process.poll() is None:
                try:
                    resident = client.get(url + '/api/ps', timeout=5).json().get('models', [])
                    for row in resident:
                        client.post(url + '/api/generate', json={'model': row['name'], 'keep_alive': 0}, timeout=15).raise_for_status()
                except requests.RequestException:
                    pass
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=20)
            client.close()
