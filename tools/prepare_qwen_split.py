"""复用Ollama主模型，准备Qwen专用ASR；不下载另一份主模型。"""
from pathlib import Path
import concurrent.futures
import json
import subprocess
import sys
import venv

from prepare_local_models import BASE, model
import requests

NAME = 'huihui_ai/qwen3.5-abliterated:4b'


def brain():
    response = requests.post('http://127.0.0.1:11434/api/show', json={'model': NAME}, timeout=30)
    response.raise_for_status()
    info = response.json()
    path = next(line[5:].strip().strip('"') for line in info['modelfile'].splitlines() if line.startswith('FROM '))
    if not Path(path).is_file():
        raise RuntimeError('Ollama模型文件不存在')
    with Path(path).open('rb') as source:
        if source.read(4) != b'GGUF':
            raise RuntimeError('Ollama文件不是可复用的GGUF')
    (BASE / 'qwen-brain.json').write_text(json.dumps({'ollama_model': NAME, 'path': path,
        'variant': 'Huihui abliteration, not original Qwen release', 'capabilities': info.get('capabilities')},
        ensure_ascii=False, indent=2), encoding='utf-8')


def asr_model():
    model('Qwen/Qwen3-ASR-0.6B', BASE / 'models/qwen3-asr')


def asr_environment():
    directory = BASE / 'venv-asr'
    python = directory / 'Scripts/python.exe'
    if not python.is_file():
        venv.create(directory, with_pip=True)
    commands = [
        ['pip', 'install', '--upgrade', 'pip'],
        ['pip', 'install', 'torch==2.7.1', 'torchaudio==2.7.1', '--index-url', 'https://download.pytorch.org/whl/cu128'],
        ['pip', 'install', 'qwen-asr==0.0.6'],
    ]
    for command in commands:
        subprocess.run([str(python), '-m', *command], check=True)
    with (BASE / 'asr-environment-lock.txt').open('w', encoding='utf-8') as output:
        subprocess.run([str(python), '-m', 'pip', 'freeze'], stdout=output, check=True)


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(task): task.__name__ for task in (brain, asr_model, asr_environment)}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                future.result()
                results[name] = 'ready'
            except Exception as error:
                results[name] = str(error)
            print(name, results[name], flush=True)
            (BASE / 'qwen-preparation-status.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(value == 'ready' for value in results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
