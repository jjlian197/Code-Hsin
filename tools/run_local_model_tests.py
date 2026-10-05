"""独立模型评估入口，不调用真实工具、不修改角色配置。"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime' / 'local-model-tests'


def references():
    profiles = json.loads((ROOT / 'voice' / 'profiles.json').read_text(encoding='utf-8'))['profiles']
    return {language: {'audio': profile['reference_audio'], 'text': profile['prompt_text']}
            for language, profile in profiles.items() if language in ('zh', 'ja')}


def server():
    executable = next((BASE / 'llama.cpp').rglob('llama-server.exe'))
    # 保留显存给音频编码、桌面渲染和后续 TTS；只绑定本机。
    subprocess.run([str(executable), '-m', str(BASE / 'models/gemma/gemma-4-E4B-it-Q4_0.gguf'),
                    '--mmproj', str(BASE / 'models/gemma/mmproj-gemma-4-E4B-it-BF16.gguf'),
                    '--host', '127.0.0.1', '--port', '18790', '-c', '2048',
                    '-ngl', '99', '-np', '1', '--jinja', '--reasoning', 'off',
                    '--reasoning-budget', '0'], check=True)


def gemma():
    import requests
    cases = json.loads((ROOT / 'docs/local_model_test_cases.json').read_text(encoding='utf-8'))
    results = []
    for case in cases['text']:
        payload = {'model': 'gemma', 'messages': case['messages'], 'temperature': 0.2, 'max_tokens': 384}
        if 'tools' in case:
            payload['tools'] = case['tools']
        started = time.perf_counter()
        response = requests.post('http://127.0.0.1:18790/v1/chat/completions', json=payload, timeout=300)
        response.raise_for_status()
        results.append({'id': case['id'], 'seconds': time.perf_counter() - started,
                        'response': response.json(), 'review': case['review']})
        print(case['id'], flush=True)
    for language, reference in references().items():
        audio = base64.b64encode(Path(reference['audio']).read_bytes()).decode('ascii')
        started = time.perf_counter()
        response = requests.post('http://127.0.0.1:18790/v1/chat/completions', json={
            'model': 'gemma', 'temperature': 0, 'max_tokens': 256,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': '请逐字转写这段音频，保持原语言，只输出听到的内容。'},
                {'type': 'input_audio', 'input_audio': {'data': audio, 'format': 'wav'}}]}]}, timeout=300)
        response.raise_for_status()
        results.append({'id': f'asr-{language}', 'seconds': time.perf_counter() - started,
                        'expected': reference['text'], 'response': response.json()})
    output = BASE / 'results/gemma.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)


def tts():
    # 只加载本机完整目录；资源缺失时禁止隐式联网。
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA 不可用，请先检查独立环境及显卡驱动')
    print('GPU:', torch.cuda.get_device_name(0), flush=True)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(str(BASE / 'models/qwen3-tts'),
        device_map='cuda:0', dtype=torch.bfloat16, attn_implementation='sdpa', local_files_only=True)
    loading = time.perf_counter() - started
    refs = references()
    cases = json.loads((ROOT / 'docs/local_model_test_cases.json').read_text(encoding='utf-8'))
    output = BASE / 'results/tts'
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases['tts']:
        ref = refs[case['language']]
        torch.cuda.synchronize()
        started = time.perf_counter()
        wavs, rate = model.generate_voice_clone(text=case['text'],
            language={'zh': 'Chinese', 'ja': 'Japanese'}[case['language']],
            ref_audio=ref['audio'], ref_text=ref['text'], max_new_tokens=1024)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        sf.write(str(output / (case['id'] + '.wav')), wavs[0], rate)
        results.append({'id': case['id'], 'text': case['text'], 'seconds': elapsed,
                        'audio_seconds': len(wavs[0]) / rate,
                        'peak_allocated_mib': torch.cuda.max_memory_allocated() / 2**20,
                        'peak_reserved_mib': torch.cuda.max_memory_reserved() / 2**20})
        print(case['id'], round(elapsed, 2), flush=True)
    (output / 'report.json').write_text(json.dumps({'gpu': torch.cuda.get_device_name(0),
        'loading_seconds': loading, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('server', 'gemma', 'tts'))
    args = parser.parse_args()
    # 两张显卡的 CUDA 序号与 nvidia-smi 顺序不同，按 UUID 固定8GB设备。
    os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
    if 'CUDA_VISIBLE_DEVICES' not in os.environ:
        inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid',
                                             '--format=csv,noheader'], text=True)
        selected = next((line.rsplit(',', 1)[1].strip() for line in inventory.splitlines()
                         if 'RTX 5060 Laptop' in line), None)
        if selected is None:
            raise RuntimeError('未找到目标8GB显卡，请明确设置CUDA_VISIBLE_DEVICES后重试')
        os.environ['CUDA_VISIBLE_DEVICES'] = selected
    print('CUDA_VISIBLE_DEVICES:', os.environ['CUDA_VISIBLE_DEVICES'], flush=True)
    {'server': server, 'gemma': gemma, 'tts': tts}[args.mode]()
