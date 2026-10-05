"""真实窗口VAD→Qwen ASR→4B→Qwen TTS→播放，并验证合成/识别取消；不开麦。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.local_ollama_test_service import test_service
OUT = ROOT / '.runtime/local-model-tests/acceptance'


def verify(service):
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import QApplication
    from src.core.app_config import load_config
    from src.core.sprite_window import HsinSpriteWindow
    config = load_config(OUT / 'config.yaml')
    runtime = OUT / ('voice-' + time.strftime('%Y%m%d-%H%M%S'))
    config['runtime']['directory'] = str(runtime)
    config['chat'].update(provider='ollama', speech_scope='full', reply_length='short')
    config['chat']['ollama'].update(url=service['url'], model=service['model'], thinking=False)
    config['stt'].update(provider='qwen', fallback=False)
    config['stt']['qwen']['gpu'] = '4080'
    config['voice'].update(provider='qwen', enabled=True, volume=0, fallback=False, auto_translate=False)
    config['voice']['qwen']['gpu'] = '4080'
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(['qwen-voice-acceptance'])
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(config)
    window.show_sprite()
    window.chat.configure('ollama')
    window.tts.configure(provider='qwen', enabled=True, language='zh', fallback=False, auto_translate=False)
    window.chat.configure_preferences(reply_length='short', speech_scope='full')
    report = {'success': False, 'microphone_opened': False, 'input_kind': 'existing synthesized request recordings, not human microphone',
              'events': [], 'turns': [], 'cancellation': {}, 'runtime': str(runtime)}
    phase, language, started, phase_started = ['warmup'], ['zh'], [time.monotonic()], [time.monotonic()]
    def forbid_capture():
        report['error'] = '虚拟录音验收不允许启动物理麦克风'
        window.stt.enabled = False
        app.quit()
    window.stt._start_capture = forbid_capture
    played, replies, recognized = [], [], []
    buffers = [0]
    def event(kind, **value):
        report['events'].append({'kind': kind, 'phase': phase[0], 'language': language[0], 'seconds': time.monotonic() - started[0], **value})
    window.stt.transcript.connect(lambda text: (recognized.append(text), event('transcript', text=text)))
    window.chat.progress.connect(lambda generation, text: event('delta', generation=generation))
    window.chat.sentence_ready.connect(lambda generation, text, lang: event('sentence', generation=generation, text=text))
    window.chat.reply_ready.connect(lambda text, lang: (replies.append(text), event('reply_complete', text=text)))
    window.tts.speech_started.connect(lambda text: (played.append(text), event('playing', text=text, file=str(window.voice_player.path))))
    window.voice_player.buffers.audioBufferReceived.connect(lambda buffer: buffers.__setitem__(0, buffers[0] + int(buffer.isValid() and buffer.byteCount() > 0)))
    def change_phase(value):
        phase[0], phase_started[0] = value, time.monotonic()
        event('phase')
    def feed():
        source = ROOT / f'.runtime/local-model-tests/results/4080-quality/request-{language[0]}.wav'
        if not source.is_file():
            raise ValueError('缺少已准备的中日测试录音')
        pcm = subprocess.check_output([shutil.which('ffmpeg'), '-v', 'error', '-i', str(source), '-ar', '16000', '-ac', '1', '-f', 's16le', 'pipe:1'])
        # 虚拟录音入口启用VAD，计时器不启动，绝不打开物理麦克风。
        window.stt.enabled = True
        window.stt.blocked = False
        window.stt._cooldown = 0
        window.stt.feed_pcm(pcm + b'\0' * 32000)
        assert window.stt.busy, 'VAD没有提交测试录音'
    def finish():
        app.quit()
    def tick():
        try:
            if window.stt.source is not None:
                report['microphone_opened'] = True
                raise AssertionError('验收不应打开物理麦克风')
            if time.monotonic() - phase_started[0] > 180:
                raise AssertionError('阶段超时：' + phase[0])
            if window.chat.error or window.tts.error or window.stt.error:
                raise AssertionError(window.chat.error or window.tts.error or window.stt.error)
            if phase[0] == 'warmup' and window.tts.warmup_state == 'ready':
                change_phase('turn')
                started[0] = time.monotonic()
                feed()
            elif phase[0] == 'warmup' and window.tts.warmup_state == 'failed':
                raise AssertionError(window.tts.warmup_error)
            elif phase[0] == 'turn' and recognized and replies and played and not window.chat.busy and not window.tts.snapshot()['active']:
                report['turns'].append({'language': language[0], 'transcript': recognized[-1], 'reply': replies[-1], 'played': list(played),
                    'seconds': time.monotonic() - started[0], 'decoded_buffers': buffers[0]})
                (OUT / 'voice-validation-4080.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                assert buffers[0] > 0
                print(language[0], 'voice turn completed', round(report['turns'][-1]['seconds'], 2), flush=True)
                recognized.clear(); replies.clear(); played.clear(); buffers[0] = 0
                if language[0] == 'zh':
                    language[0] = 'ja'
                    window.stt.configure(language='ja', enabled=False)
                    window.tts.configure(language='ja')
                    change_phase('warmup')
                else:
                    change_phase('cancel_tts')
                    window.tts.speak('御者、これは途中で停止する音声合成の確認です。ゆっくり落ち着いて、今日の出来事を一つずつ振り返りましょう。' * 3, 'ja', translate=False)
            elif phase[0] == 'cancel_tts' and window.tts.qwen.worker.active.is_set() and window.tts.stage == 'synthesizing':
                worker = window.tts.qwen.worker
                if worker.process and worker.process.poll() is None and time.monotonic() - phase_started[0] > 1:
                    pid = worker.process.pid
                    window.tts.stop()
                    assert worker.process is None
                    report['cancellation']['tts'] = {'pid': pid, 'worker_stopped': True}
                    change_phase('cancel_asr')
                    window.stt._cooldown = 0
                    window.stt.blocked = False
                    window.stt.enabled = True
                    window.stt._submit(b'\0' * 16000 * 2 * 20)
            elif phase[0] == 'cancel_asr' and window.stt._recognizer._qwen and window.stt._recognizer._qwen.active.is_set():
                if time.monotonic() - phase_started[0] > 0:
                    worker = window.stt._recognizer._qwen
                    pid = worker.process.pid if worker.process else None
                    window.stt.configure(enabled=False)
                    assert worker.process is None
                    report['cancellation']['asr'] = {'pid': pid, 'worker_stopped': True}
                    change_phase('settle')
            elif phase[0] == 'settle' and time.monotonic() - phase_started[0] > .7:
                assert not played and not recognized and not window.tts.snapshot()['active']
                assert window.voice_player.last_level == 0
                assert not window.stt.busy
                report['success'] = True
                finish()
                return
        except Exception as error:
            report['error'] = str(error)
            finish()
            return
        QTimer.singleShot(40, tick)
    window.tts.prewarm()
    QTimer.singleShot(40, tick)
    try:
        app.exec()
    finally:
        window.cleanup()
        window.hide()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'voice-validation-4080.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'events'}, ensure_ascii=False), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    with test_service() as service:
        raise SystemExit(verify(service))
