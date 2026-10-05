"""Qwen分工方案的独立本机评估，不调用真实工具或开启麦克风。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime/local-model-tests'


def save(name, value):
    output = BASE / 'results' / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def server():
    info = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))
    environment = os.environ.copy()
    environment.update({'OLLAMA_HOST': '127.0.0.1:11435',
        'OLLAMA_MODELS': str(Path(info['path']).parent.parent), 'OLLAMA_CONTEXT_LENGTH': '4096',
        'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NUM_PARALLEL': '1', 'OLLAMA_NO_CLOUD': 'true'})
    process = subprocess.Popen([shutil.which('ollama'), 'serve'], env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process.wait()
        if process.returncode:
            raise RuntimeError(f'Ollama测试服务退出：{process.returncode}')
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            import requests
            try:
                requests.post('http://127.0.0.1:11435/api/generate',
                    json={'model': info['ollama_model'], 'keep_alive': 0}, timeout=15).raise_for_status()
            except requests.RequestException:
                pass
            process.terminate()
            process.wait(timeout=10)


def brain():
    import requests
    info = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT / 'docs/local_model_test_cases.json').read_text(encoding='utf-8'))['text']
    results = []
    for case in cases:
        payload = {'model': info['ollama_model'], 'messages': case['messages'], 'stream': False,
                   'think': False, 'keep_alive': '5m',
                   'options': {'temperature': 0.2, 'num_predict': 768, 'num_ctx': 4096}}
        if 'tools' in case:
            payload['tools'] = case['tools']
        started = time.perf_counter()
        response = requests.post('http://127.0.0.1:11435/api/chat', json=payload, timeout=300)
        response.raise_for_status()
        result = response.json()
        results.append({'id': case['id'], 'seconds': time.perf_counter() - started,
                        'response': result, 'review': case['review']})
        save('qwen-brain.json', {'model': info, 'thinking': False, 'max_tokens': 768, 'results': results})
        print(case['id'], flush=True)


def asr():
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    from qwen_asr import Qwen3ASRModel
    profiles = json.loads((ROOT / 'voice/profiles.json').read_text(encoding='utf-8'))['profiles']
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(str(BASE / 'models/qwen3-asr'), device_map='cuda:0',
        dtype=torch.bfloat16, attn_implementation='sdpa', max_inference_batch_size=1,
        max_new_tokens=256, local_files_only=True)
    loading = time.perf_counter() - started
    results = []
    for language in ('zh', 'ja'):
        for hinted in (False, True):
            context = '心、心月狐、御者、鸣潮、鳴潮、Hsin' if hinted else ''
            torch.cuda.synchronize()
            started = time.perf_counter()
            transcription = model.transcribe(audio=profiles[language]['reference_audio'], context=context,
                language={'zh': 'Chinese', 'ja': 'Japanese'}[language], return_time_stamps=False)[0]
            torch.cuda.synchronize()
            results.append({'language': language, 'context': context, 'expected': profiles[language]['prompt_text'],
                'text': transcription.text, 'detected_language': transcription.language,
                'seconds': time.perf_counter() - started})
            save('qwen-asr.json', {'gpu': torch.cuda.get_device_name(0), 'loading_seconds': loading,
                'peak_allocated_mib': torch.cuda.max_memory_allocated() / 2**20,
                'peak_reserved_mib': torch.cuda.max_memory_reserved() / 2**20, 'results': results})
            print(language, 'context' if hinted else 'plain', transcription.text, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('server', 'brain', 'asr'))
    args = parser.parse_args()
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
    os.environ['CUDA_VISIBLE_DEVICES'] = next(line.rsplit(',', 1)[1].strip() for line in inventory.splitlines() if 'RTX 5060 Laptop' in line)
    os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
    print('Target GPU: RTX 5060 Laptop (8GB)', flush=True)
    {'server': server, 'brain': brain, 'asr': asr}[args.mode]()
