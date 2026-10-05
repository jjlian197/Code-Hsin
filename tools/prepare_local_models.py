"""第一批离线模型测试资源；不修改应用配置或全局 Python。"""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import time
import venv
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime' / 'local-model-tests'


def download(url, target, sha256=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256:
            with target.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != sha256:
                    raise RuntimeError(f'已有文件校验失败，请检查：{target}')
        return
    partial = target.with_name(target.name + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    with requests.get(url, headers={'Range': f'bytes={offset}-'} if offset else {},
                      stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        append = offset > 0 and response.status_code == 206
        if not append:
            offset = 0
        print(f'下载 {target.name}，已完成 {offset / 1e6:.1f} MB', flush=True)
        last = time.monotonic()
        with partial.open('ab' if append else 'wb') as output:
            for block in response.iter_content(4 * 1024 * 1024):
                output.write(block)
                offset += len(block)
                if time.monotonic() - last > 30:
                    print(f'{target.name}: {offset / 1e6:.1f} MB', flush=True)
                    last = time.monotonic()
    if sha256:
        with partial.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != sha256:
                raise RuntimeError(f'下载校验失败：{partial}')
    partial.replace(target)


def model(repo, directory, selected=None):
    response = requests.get(f'https://huggingface.co/api/models/{repo}?blobs=true', timeout=60)
    response.raise_for_status()
    info = response.json()
    revision = info['sha']
    if selected:
        missing = selected - {entry['rfilename'] for entry in info['siblings']}
        if missing:
            raise RuntimeError(f'仓库中缺少指定资源：{sorted(missing)}')
    records = []
    for entry in info['siblings']:
        name = entry['rfilename']
        if selected is not None and name not in selected and name not in ('README.md', 'LICENSE'):
            continue
        if name == '.gitattributes':
            continue
        digest = entry.get('lfs', {}).get('sha256')
        download(f'https://huggingface.co/{repo}/resolve/{revision}/{name}', directory / name, digest)
        records.append({'file': name, 'sha256': digest})
    (directory / 'download-manifest.json').write_text(json.dumps(
        {'repo': repo, 'revision': revision, 'files': records}, indent=2), encoding='utf-8')


def gemma():
    model('ggml-org/gemma-4-E4B-it-GGUF', BASE / 'models' / 'gemma',
          {'gemma-4-E4B-it-Q4_0.gguf', 'mmproj-gemma-4-E4B-it-BF16.gguf'})


def llama():
    release = requests.get('https://github.com/ggml-org/llama.cpp/releases', timeout=60)
    release.raise_for_status()
    tag = re.search(r'/ggml-org/llama.cpp/releases/tag/(b\d+)', release.text).group(1)
    response = requests.get(f'https://github.com/ggml-org/llama.cpp/releases/expanded_assets/{tag}', timeout=60)
    response.raise_for_status()
    links = re.findall(r'href="([^"]+\.zip)"', response.text)
    chosen = [link for link in links if 'win' in link and 'x64' in link and 'cuda-13' in link]
    if not chosen:
        chosen = [link for link in links if 'win' in link and 'x64' in link and 'cuda' in link and '13.' not in link]
    if not chosen:
        raise RuntimeError('未找到 Windows x64 CUDA 发布包')
    # 一个二进制包及对应运行库，避免同时解压多个 CUDA 版本。
    binary = next(link for link in chosen if 'cudart' not in link)
    version = re.search(r'cuda-([\d.]+)', binary).group(1)
    chosen = [binary] + [link for link in chosen if 'cudart' in link and f'cuda-{version}' in link]
    for link in chosen:
        archive = BASE / 'downloads' / link.rsplit('/', 1)[-1]
        download('https://github.com' + link, archive)
        with zipfile.ZipFile(archive) as source:
            source.extractall(BASE / 'llama.cpp')
    (BASE / 'llama.cpp' / 'release.txt').write_text(tag, encoding='utf-8')


def tts():
    model('Qwen/Qwen3-TTS-12Hz-0.6B-Base', BASE / 'models' / 'qwen3-tts')


def environment():
    directory = BASE / 'venv-tts'
    if not (directory / 'Scripts' / 'python.exe').exists():
        venv.create(directory, with_pip=True)
    python = str(directory / 'Scripts' / 'python.exe')
    for args in [ ['pip', 'install', '--upgrade', 'pip'],
                  ['pip', 'install', 'torch==2.7.1', 'torchaudio==2.7.1', '--index-url',
                   'https://download.pytorch.org/whl/cu128'],
                  ['pip', 'install', 'qwen-tts==0.1.1'] ]:
        subprocess.run([python, '-m', *args], check=True)
    with (BASE / 'tts-environment-lock.txt').open('w', encoding='utf-8') as output:
        subprocess.run([python, '-m', 'pip', 'freeze'], stdout=output, check=True)


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(task): task.__name__ for task in (gemma, llama, tts, environment)}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                future.result()
                results[name] = 'ready'
            except Exception as error:
                results[name] = str(error)
            print(name, results[name], flush=True)
            (BASE / 'preparation-status.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(value == 'ready' for value in results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
