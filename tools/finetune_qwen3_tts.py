"""用现有完整日常语音在4080S上微调Qwen3-TTS；原训练成果只读。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime/qwen3-tts-training'
MODEL = ROOT / '.runtime/local-model-tests/models/qwen3-tts'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def prepare(language):
    import soundfile as sf
    import librosa
    directory = BASE / language
    directory.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'voice' / f'hsin_{language}' / (
        'hsin_zh.all.list' if language == 'zh' else 'hsin_ja.calm.all.list')
    profile = json.loads((ROOT / 'voice/profiles.json').read_text(encoding='utf-8'))['profiles'][language]
    # 官方Dataset只接受24kHz参考音频，转换副本不改原声。
    ref = directory / 'reference.wav'
    data, rate = librosa.load(profile['reference_audio'], sr=24000, mono=True)
    sf.write(str(ref), data, rate, subtype='PCM_16')
    rows = []
    for line in source.read_text(encoding='utf-8').splitlines():
        audio, speaker, lang, text = line.split('|', 3)
        if lang != language or not text.strip():
            raise ValueError(f'清单语言或文本异常：{audio}')
        info = sf.info(audio)
        if info.frames == 0 or info.channels != 1:
            raise ValueError(f'音频格式异常：{audio}')
        rows.append({'audio': audio, 'text': text, 'ref_audio': str(ref),
                     'language': {'zh': 'Chinese', 'ja': 'Japanese'}[lang],
                     'seconds': info.duration})
    candidates = [i for i, row in enumerate(rows) if Path(row['audio']) != Path(profile['reference_audio'])]
    random.Random(42).shuffle(candidates)
    held_out = set(candidates[:2])
    train = [row for i, row in enumerate(rows) if i not in held_out]
    validation = [row for i, row in enumerate(rows) if i in held_out]
    jsonl(directory / 'train_raw.jsonl', train)
    jsonl(directory / 'validation_raw.jsonl', validation)
    write_json(directory / 'data-report.json', {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'total': len(rows), 'train': len(train), 'validation': len(validation),
        'total_seconds': sum(row['seconds'] for row in rows), 'maximum_seconds': max(row['seconds'] for row in rows),
        'speaker_name': 'hsin_' + language, 'reference_text': profile['prompt_text'],
        'transcripts': 'source_paired_not_listening_reviewed', 'combat': 'excluded_by_existing_selection'})
    return train, validation


def encode(language, rows, validation):
    from qwen_tts import Qwen3TTSTokenizer
    directory = BASE / language
    tokenizer = Qwen3TTSTokenizer.from_pretrained(str(MODEL / 'speech_tokenizer'), device_map='cuda:0', local_files_only=True)
    for label, selected in (('train', rows), ('validation', validation)):
        output = directory / (label + '_codes.jsonl')
        cached = {}
        if output.exists():
            cached = {row['audio']: row for row in map(json.loads, output.read_text(encoding='utf-8').splitlines())}
        records = []
        for index, row in enumerate(selected):
            if row['audio'] in cached:
                result = {**row, 'audio_codes': cached[row['audio']]['audio_codes']}
            else:
                codes = tokenizer.encode(row['audio']).audio_codes[0].cpu().tolist()
                result = {**row, 'audio_codes': codes}
            records.append(result)
            jsonl(output, records)
            print(f'{language} {label} encode {index + 1}/{len(selected)}', flush=True)
    del tokenizer
    import torch
    torch.cuda.empty_cache()


def fit(language, epochs, lr):
    import torch
    from torch.utils.data import DataLoader
    from qwen_tts import Qwen3TTSModel
    from safetensors.torch import save_file
    spec = importlib.util.spec_from_file_location('qwen_official_dataset', BASE / 'upstream/dataset.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    directory = BASE / language
    torch.manual_seed(42)
    model_wrapper = Qwen3TTSModel.from_pretrained(str(MODEL), device_map='cuda:0',
        dtype=torch.bfloat16, attn_implementation='sdpa', local_files_only=True)
    model = model_wrapper.model
    model.speaker_encoder.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.config.use_cache = False
    rows = list(map(json.loads, (directory / 'train_codes.jsonl').read_text(encoding='utf-8').splitlines()))
    validation = list(map(json.loads, (directory / 'validation_codes.jsonl').read_text(encoding='utf-8').splitlines()))
    dataset = module.TTSDataset(rows, model_wrapper.processor, model.config)
    valid_dataset = module.TTSDataset(validation, model_wrapper.processor, model.config)
    loader = DataLoader(dataset, batch_size=1, shuffle=True, collate_fn=dataset.collate_fn, num_workers=0)
    valid_loader = DataLoader(valid_dataset, batch_size=1, collate_fn=valid_dataset.collate_fn, num_workers=0)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=lr, weight_decay=0.01)
    accumulation = 4
    speaker_embedding = None

    def loss_for(batch):
        nonlocal speaker_embedding
        batch = {key: value.to('cuda:0') for key, value in batch.items()}
        with torch.no_grad():
            embedding = model.speaker_encoder(batch['ref_mels'].to(model.dtype)).detach()
            if speaker_embedding is None:
                speaker_embedding = embedding[:1]
        input_ids = batch['input_ids']
        embeds = model.talker.text_projection(model.talker.model.text_embedding(input_ids[:, :, 0])) * batch['text_embedding_mask']
        codec = model.talker.model.codec_embedding(input_ids[:, :, 1]) * batch['codec_embedding_mask']
        codec[:, 6, :] = embedding
        embeds = embeds + codec
        for i in range(1, 16):
            embeds = embeds + model.talker.code_predictor.get_input_embeddings()[i - 1](batch['codec_ids'][:, :, i]) * batch['codec_mask'].unsqueeze(-1)
        outputs = model.talker(inputs_embeds=embeds[:, :-1, :], attention_mask=batch['attention_mask'][:, :-1],
            labels=batch['codec_0_labels'][:, 1:], output_hidden_states=True, use_cache=False)
        mask = batch['codec_mask'][:, :-1]
        hidden = outputs.hidden_states[0][-1][mask]
        codes = batch['codec_ids'][batch['codec_mask']]
        _, sub_loss = model.talker.forward_sub_talker_finetune(codes, hidden)
        return outputs.loss + 0.3 * sub_loss

    metrics = []
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        losses = []
        for step, batch in enumerate(loader):
            group_size = min(accumulation, len(loader) - (step // accumulation) * accumulation)
            loss = loss_for(batch)
            if not torch.isfinite(loss):
                raise RuntimeError(f'{language} loss不是有限值，停止训练')
            (loss / group_size).backward()
            value = loss.detach().item()
            losses.append(value)
            if (step + 1) % accumulation == 0 or step + 1 == len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            print(f'{language} epoch {epoch + 1}/{epochs} step {step + 1}/{len(loader)} loss {value:.4f}', flush=True)
        model.eval()
        with torch.no_grad():
            validation_loss = sum(loss_for(batch).item() for batch in valid_loader) / len(valid_loader)
        checkpoint = directory / f'checkpoint-epoch-{epoch + 1}'
        checkpoint.mkdir(exist_ok=False)
        for item in MODEL.iterdir():
            if item.is_file() and item.suffix != '.safetensors':
                shutil.copy2(item, checkpoint / item.name)
        # 保留完整本机分词器，检查点可以独立离线加载。
        shutil.copytree(MODEL / 'speech_tokenizer', checkpoint / 'speech_tokenizer')
        # 保留官方JSON结构；to_dict会为说话人配置加入其构造器不接受的dtype字段。
        config = json.loads((MODEL / 'config.json').read_text(encoding='utf-8'))
        config['tts_model_type'] = 'custom_voice'
        config['talker_config']['spk_id'] = {'hsin_' + language: 3000}
        config['talker_config']['spk_is_dialect'] = {'hsin_' + language: False}
        write_json(checkpoint / 'config.json', config)
        state = {key: value.detach().cpu().contiguous() for key, value in model.state_dict().items() if not key.startswith('speaker_encoder')}
        state['talker.model.codec_embedding.weight'][3000] = speaker_embedding[0].detach().cpu()
        save_file(state, str(checkpoint / 'model.safetensors'))
        del state
        metrics.append({'epoch': epoch + 1, 'train_loss': sum(losses) / len(losses), 'validation_loss': validation_loss,
            'elapsed_seconds': time.perf_counter() - started, 'checkpoint': str(checkpoint),
            'peak_allocated_mib': torch.cuda.max_memory_allocated() / 2**20,
            'peak_reserved_mib': torch.cuda.max_memory_reserved() / 2**20})
        write_json(directory / 'training-report.json', {'gpu': torch.cuda.get_device_name(0), 'epochs': metrics,
            'learning_rate': lr, 'batch_size': 1, 'gradient_accumulation': accumulation,
            'best_epoch': min(metrics, key=lambda item: item['validation_loss'])['epoch']})
        print(f'{language} epoch {epoch + 1} saved; validation={validation_loss:.4f}', flush=True)
    del optimizer, model, model_wrapper
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--languages', nargs='+', choices=('zh', 'ja'), default=['zh', 'ja'])
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--lr', type=float, default=2e-6)
    args = parser.parse_args()
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
    uuid = next(line.rsplit(',', 1)[1].strip() for line in inventory.splitlines() if 'RTX 4080 SUPER' in line)
    os.environ['CUDA_VISIBLE_DEVICES'] = uuid
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    if '4080 SUPER' not in torch.cuda.get_device_name(0):
        raise RuntimeError('训练显卡不符合4080S要求')
    print('Training GPU:', torch.cuda.get_device_name(0), flush=True)
    write_json(BASE / 'run-config.json', {'gpu_uuid': uuid, 'gpu': torch.cuda.get_device_name(0),
        'model': str(MODEL), 'languages': args.languages, 'epochs': args.epochs, 'lr': args.lr,
        'official_source': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (BASE / 'upstream').glob('*') if path.is_file()}})
    for language in args.languages:
        if list((BASE / language).glob('checkpoint-epoch-*')):
            raise RuntimeError(f'{language}已有检查点；请为新实验安排独立目录，不覆盖本次成果')
        rows, validation = prepare(language)
        encode(language, rows, validation)
        fit(language, args.epochs, args.lr)


if __name__ == '__main__':
    main()
