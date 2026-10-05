"""在4080S上对照基础克隆与本次微调音色，生成文件供用户试听。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime/qwen3-tts-training'


def main():
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
    os.environ['CUDA_VISIBLE_DEVICES'] = next(line.rsplit(',', 1)[1].strip() for line in inventory.splitlines() if 'RTX 4080 SUPER' in line)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    import soundfile as sf
    import numpy as np
    from qwen_tts import Qwen3TTSModel
    profiles = json.loads((ROOT / 'voice/profiles.json').read_text(encoding='utf-8'))['profiles']
    all_cases = json.loads((ROOT / 'docs/local_model_test_cases.json').read_text(encoding='utf-8'))['tts']
    cases = [case for case in all_cases if case['id'] in ('zh-short', 'zh-names', 'ja-short', 'ja-numbers')]
    output = BASE / 'comparison'
    output.mkdir(exist_ok=True)
    results = []
    for language in ('zh', 'ja'):
        training = json.loads((BASE / language / 'training-report.json').read_text(encoding='utf-8'))
        checkpoint = next(row['checkpoint'] for row in training['epochs'] if row['epoch'] == training['best_epoch'])
        for mode, path in (('baseline', ROOT / '.runtime/local-model-tests/models/qwen3-tts'), ('finetuned', Path(checkpoint))):
            model = Qwen3TTSModel.from_pretrained(str(path), device_map='cuda:0', dtype=torch.bfloat16,
                                                 attn_implementation='sdpa', local_files_only=True)
            for case in [case for case in cases if case['language'] == language]:
                torch.manual_seed(42)
                torch.cuda.synchronize()
                started = time.perf_counter()
                kwargs = {'text': case['text'], 'language': {'zh': 'Chinese', 'ja': 'Japanese'}[language], 'max_new_tokens': 1024}
                if mode == 'baseline':
                    profile = profiles[language]
                    wavs, rate = model.generate_voice_clone(**kwargs, ref_audio=profile['reference_audio'], ref_text=profile['prompt_text'])
                else:
                    wavs, rate = model.generate_custom_voice(**kwargs, speaker='hsin_' + language)
                torch.cuda.synchronize()
                elapsed = time.perf_counter() - started
                audio = np.asarray(wavs[0])
                if not audio.size or not np.isfinite(audio).all():
                    raise RuntimeError(f'{mode} {case["id"]}音频异常')
                target = output / f'{case["id"]}-{mode}.wav'
                sf.write(str(target), audio, rate)
                results.append({'id': case['id'], 'mode': mode, 'model': str(path), 'text': case['text'],
                    'audio': str(target), 'seconds': elapsed, 'audio_seconds': audio.size / rate,
                    'rms': float(np.sqrt(np.mean(audio ** 2))), 'clipped_fraction': float(np.mean(np.abs(audio) >= 0.999))})
                (output / 'report.json').write_text(json.dumps({'gpu': torch.cuda.get_device_name(0),
                    'listening_review': 'pending', 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
                print(case['id'], mode, round(elapsed, 2), round(audio.size / rate, 2), flush=True)
            del model
            torch.cuda.empty_cache()


if __name__ == '__main__':
    main()
