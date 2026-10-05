"""同一录音与context对照Qwen ASR GPU/CPU，测冷/热等待与驻留内存。"""
import base64
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.app_config import DEFAULT_CONFIG, project_path
from src.core.model_process import ModelProcess
from src.core.speech_recognizer import wav_bytes
from src.core.stt_hotwords import DEFAULT_HOTWORDS
from tools.profile_local_stack import Monitor, OUT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('both', 'cpu', '4080'), default='both')
    args = parser.parse_args()
    folder = OUT / ('asr-cpu-compare-' + time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    audio = {}
    for language in ('zh', 'ja'):
        source = ROOT / f'.runtime/local-model-tests/results/4080-quality/request-{language}.wav'
        pcm = subprocess.check_output([shutil.which('ffmpeg'), '-v', 'error', '-i', str(source), '-ar', '16000', '-ac', '1', '-f', 's16le', 'pipe:1'])
        audio[language] = base64.b64encode(wav_bytes(pcm)).decode('ascii')
    report = {'input': 'same existing synthesized request recordings, no microphone', 'devices': {}}
    settings = DEFAULT_CONFIG['stt']['qwen']
    for device in (('4080', 'cpu') if args.device == 'both' else (args.device,)):
        directory = folder / device
        directory.mkdir()
        monitor = Monitor(directory)
        monitor.thread.start()
        client = ModelProcess(settings['python'], device, directory / 'worker')
        rows = []
        time.sleep(15)
        try:
            for index in range(6):
                language = 'zh' if index % 2 == 0 else 'ja'
                monitor.phase = 'cold' if index == 0 else 'warm'
                started = time.monotonic()
                result = client.request('asr', audio=audio[language], language=language,
                                        model=str(project_path(settings['model'])), context='、'.join(DEFAULT_HOTWORDS))
                rows.append({'index': index, 'language': language, 'wall_seconds': time.monotonic() - started,
                             'cold': index == 0, **{k: v for k, v in result.items() if k != 'id'}})
                assert result['device'] == ('cpu' if device == 'cpu' else 'cuda:0')
                print(device, language, round(rows[-1]['wall_seconds'], 3), result['text'], flush=True)
            monitor.phase = 'resident'
            time.sleep(5)
            old_pid = client.process.pid
            assert client.release_idle()
            assert client.process is None
            report['devices'][device] = {'requests': rows, 'idle_released_pid': old_pid}
        finally:
            client.close()
            monitor.phase = 'after_cleanup'
            time.sleep(5)
            monitor.done.set()
            monitor.thread.join(timeout=20)
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('report', folder, flush=True)


if __name__ == '__main__':
    main()
