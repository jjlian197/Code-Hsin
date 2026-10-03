"""导出固定中日台词和已筛选原声；不复制聊天缓存或本机训练配置。"""
import hashlib
import json
from pathlib import Path
import shutil

from src.core.app_config import load_config, project_path
from src.core.preset_voice import preset_key
from src.core.tts_manager import LocalSynthesizer, wave_info
from src.core.voice_phrases import TOUCH_REPLIES, TRUSTED_TOUCH_REPLIES, FOND_TOUCH_REPLIES, PREVIEW_PHRASES


def main():
    config = load_config()
    synth = LocalSynthesizer(project_path(config['voice']['profiles']), project_path(config['runtime']['directory']), config['voice']['port'])
    folder = project_path('voice/presets')
    folder.mkdir(parents=True, exist_ok=True)
    entries = {}
    try:
        for language in ('zh', 'ja'):
            texts = {PREVIEW_PHRASES[language]}
            for replies in (TOUCH_REPLIES, TRUSTED_TOUCH_REPLIES, FOND_TOUCH_REPLIES):
                texts.update(replies[language].values())
            for text in sorted(texts):
                key = preset_key(text, language)
                target = folder / f'{key}.wav'
                source = synth.synthesize(text, language, 1)
                if target.resolve() != source.resolve():
                    shutil.copyfile(source, target)
                payload = target.read_bytes()
                entries[key] = {'text': text, 'language': language, 'file': target.name,
                    'duration': wave_info(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            print('Prepared fixed voices:', language, len(texts), flush=True)
    finally:
        synth.close()
    (folder / 'manifest.json').write_text(json.dumps({'format': 1, 'entries': entries}, ensure_ascii=False, indent=2), encoding='utf8')
    recordings = project_path('voice/recordings')
    recordings.mkdir(parents=True, exist_ok=True)
    originals = []
    for language in ('zh', 'ja'):
        root = project_path(f'voice/hsin_{language}')
        selection = json.loads((root / 'selection.json').read_text(encoding='utf8'))
        output = recordings / language
        output.mkdir(exist_ok=True)
        for entry in selection['selected']:
            filename = entry.get('raw_file', entry['file'])
            source = root / 'raw' / filename
            if not source.is_file():
                raise FileNotFoundError(source)
            shutil.copyfile(source, output / source.name)
            originals.append({'language': language, 'title': entry['title'], 'text': entry['text'],
                'file': f'{language}/{source.name}', 'source': entry['audio_url'],
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    (recordings / 'manifest.json').write_text(json.dumps({'character': 'Hsin', 'copyright': 'KURO GAMES',
        'purpose': '角色原声参考；不含训练权重或私人聊天', 'entries': originals}, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'fixed_voices': len(entries), 'original_recordings': len(originals)}), flush=True)


if __name__ == '__main__':
    main()
