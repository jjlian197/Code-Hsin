"""Qwen ASR/TTS独立环境中的真实推理；stdout仅输出请求对应的JSON。"""
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import time


def main():
    model, identity = None, None
    cpu_configured = False
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            started = time.monotonic()
            with redirect_stdout(sys.stderr):
                import torch
                path = Path(request['model'])
                if not (path / 'config.json').is_file():
                    raise ValueError('Qwen模型目录缺失；不会自动下载')
                operation = request['operation']
                kind = 'asr' if operation == 'asr' else 'tts'
                import os
                # Windows子进程显式CPU选择不能依赖库的CUDA可用性探测缓存。
                device = 'cpu' if os.environ.get('CUDA_VISIBLE_DEVICES') == '' else ('cuda:0' if torch.cuda.is_available() else 'cpu')
                if device == 'cpu' and not cpu_configured:
                    torch.set_num_threads(4)
                    torch.set_num_interop_threads(1)
                    cpu_configured = True
                if os.environ.get('CUDA_VISIBLE_DEVICES') and device == 'cpu':
                    raise RuntimeError('所选Qwen GPU不可用，不自动切到CPU')
                target = (kind, str(path), device)
                if identity != target:
                    model = None
                    torch.cuda.empty_cache()
                    kwargs = dict(device_map=device, dtype=torch.bfloat16 if device != 'cpu' else torch.float32,
                                  attn_implementation='sdpa', local_files_only=True)
                    if kind == 'asr':
                        from qwen_asr import Qwen3ASRModel
                        model = Qwen3ASRModel.from_pretrained(str(path), max_inference_batch_size=1, max_new_tokens=256, **kwargs)
                    else:
                        from qwen_tts import Qwen3TTSModel
                        model = Qwen3TTSModel.from_pretrained(str(path), **kwargs)
                    identity = target
                language = request['language']
                if kind == 'asr':
                    import soundfile as sf
                    audio, rate = sf.read(io.BytesIO(base64.b64decode(request['audio'], validate=True)))
                    result = model.transcribe(audio=(audio, rate), context=request.get('context', ''),
                        language={'zh': 'Chinese', 'ja': 'Japanese', 'auto': None}[language])[0]
                    response = {'text': result.text.strip()[:4000]}
                else:
                    import numpy as np
                    import soundfile as sf
                    torch.manual_seed(42)
                    kwargs = dict(text=request['text'], language={'zh': 'Chinese', 'ja': 'Japanese'}[language], max_new_tokens=2048)
                    if language == 'zh':
                        wavs, rate = model.generate_custom_voice(**kwargs, speaker='hsin_zh')
                    else:
                        wavs, rate = model.generate_voice_clone(**kwargs, ref_audio=request['reference_audio'], ref_text=request['reference_text'])
                    audio = np.asarray(wavs[0])
                    if not audio.size or not np.isfinite(audio).all():
                        raise ValueError('Qwen未返回有效音频')
                    buffer = io.BytesIO()
                    sf.write(buffer, audio, rate, format='WAV', subtype='PCM_16')
                    response = {'audio': base64.b64encode(buffer.getvalue()).decode('ascii')}
                response.update(seconds=time.monotonic() - started, device=str(model.model.device),
                    gpu=torch.cuda.get_device_name(0) if model.model.device.type == 'cuda' else 'cpu', threads=torch.get_num_threads())
            response['id'] = request['id']
        except Exception as error:
            import traceback
            traceback.print_exc(file=sys.stderr)
            print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
            response = {'id': request.get('id'), 'error': str(error) if isinstance(error, ValueError) else 'Qwen模型处理失败，请检查本机模型、独立环境与worker.log'}
        print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
