"""实际窗口中的4B聊天、代次取消与本地翻译验收；默认4080S，不开麦。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.local_ollama_test_service import test_service

OUT = ROOT / '.runtime/local-model-tests/acceptance'


def verify_translation(service):
    from src.core.app_config import load_config
    from src.core.voice_auxiliary import VoiceTranslator
    config = load_config(OUT / 'config.yaml')
    config['chat']['provider'] = 'ollama'
    config['chat']['ollama']['url'] = service['url']
    translator = VoiceTranslator(config, OUT / 'translation-recheck')
    report = {'ja': translator.translate('心月狐Hsin会在御者完成工作后，提醒他休息十分钟。', 'ja'),
        'zh': translator.translate('作業が終わったら、十分ほど休んでから、もう一度確認しましょう。', 'zh')}
    report['time_preserved'] = any(term in report['zh'] for term in ('十分钟', '10分钟')) and any(term in report['ja'] for term in ('十分', '10分'))
    (OUT / 'translation-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['time_preserved'] else 1


def verify(service, gpu):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication
    from src.core.app_config import load_config
    from src.core.sprite_window import HsinSpriteWindow
    from src.core.voice_auxiliary import VoiceTranslator
    config = load_config(OUT / 'config.yaml')
    config['runtime']['directory'] = str(OUT / ('verification-' + gpu))
    config['chat']['provider'] = 'ollama'
    config['chat']['ollama'].update(url=service['url'], model=service['model'], context_length=8192 if gpu == '4080' else 4096, thinking=False)
    config['voice'].update(enabled=False, fallback=False, auto_translate=False)
    config['chat']['speech_scope'] = 'off'
    config['http']['enabled'] = config['websocket']['enabled'] = False
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(['local-chat-acceptance'])
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(config)
    window.chat.configure('ollama')
    window.show_sprite()
    window.open_chat()
    report = {'success': False, 'service': service, 'turns': [], 'events': [], 'scope': 'real window/chat/translation; Qwen ASR and TTS application adapters pending'}
    phase, start, cancelled, translation, done_at = ['zh'], [time.monotonic()], [None], [None], [None]
    pool = ThreadPoolExecutor(1)
    def event(kind, generation):
        report['events'].append({'kind': kind, 'generation': generation, 'seconds': time.monotonic() - start[0], 'phase': phase[0]})
    window.chat.progress.connect(lambda generation, text: event('delta', generation))
    window.chat.reply_ready.connect(lambda text, language: report['turns'].append({'phase': phase[0], 'text': text, 'language': language, 'generation': window.chat.generation}))
    def send(text, language):
        start[0] = time.monotonic()
        window.send_chat(text, language)
    def translated():
        translator = VoiceTranslator(config, OUT / ('translation-' + gpu))
        return {'ja': translator.translate('心月狐Hsin会在御者完成工作后，提醒他休息十分钟。', 'ja'),
                'zh': translator.translate('作業が終わったら、十分ほど休んでから、もう一度確認しましょう。', 'zh')}
    def fail(error):
        report['error'] = str(error)
        app.quit()
    def tick():
        try:
            if window.stt.enabled or window.stt.source is not None:
                raise AssertionError('验收不应开启麦克风')
            if window.chat.error:
                raise AssertionError(window.chat.error)
            if time.monotonic() - start[0] > 90:
                raise AssertionError('验收阶段超时：' + phase[0])
            if phase[0] in ('zh', 'ja') and not window.chat.busy:
                assert report['turns'] and report['turns'][-1]['phase'] == phase[0]
                if phase[0] == 'zh':
                    phase[0] = 'ja'
                    send('一時間働いて少し疲れました。短い休憩の取り方を二文で教えてください。', 'ja')
                else:
                    phase[0] = 'cancel'
                    send('请详细写出一百条日语学习建议，每条二十字以上，按顺序逐条解释。', 'zh')
            elif phase[0] == 'cancel' and window.chat.busy and window.chat.partial:
                cancelled[0] = window.chat.generation
                window.stop_chat()
                event('stop', cancelled[0])
                phase[0] = 'after_cancel'
                send('只回复“收到”。', 'zh')
            elif phase[0] == 'cancel' and not window.chat.busy:
                raise AssertionError('回复在取消前已结束，本次未验证生成中取消')
            elif phase[0] == 'after_cancel' and not window.chat.busy:
                phase[0] = 'translation'
                start[0] = time.monotonic()
                translation[0] = pool.submit(translated)
            elif phase[0] == 'translation' and translation[0].done():
                report['translation'] = translation[0].result()
                phase[0] = 'settle'
                done_at[0] = time.monotonic()
            elif phase[0] == 'settle' and time.monotonic() - done_at[0] > .5:
                assert all(row['generation'] != cancelled[0] for row in report['turns'])
                assert report['turns'][-1]['phase'] == 'after_cancel'
                assert '收到' in report['turns'][-1]['text']
                report['cancelled_generation'] = cancelled[0]
                report['model_loaded'] = getattr(window.sprite_view, 'model_loaded', False)
                window.chat_dialog.grab().save(str(OUT / ('chat-' + gpu + '.png')))
                report['success'] = True
                app.quit()
                return
        except Exception as error:
            fail(error)
            return
        QTimer.singleShot(20, tick)
    send('今天工作有点累，请用两句自然中文陪我说说话。', 'zh')
    QTimer.singleShot(20, tick)
    try:
        app.exec()
    finally:
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        (OUT / ('chat-validation-' + gpu + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'success': report['success'], 'error': report.get('error'), 'turns': report['turns'], 'translation': report.get('translation')}, ensure_ascii=False), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpu', choices=('4080', '8gb'), default='4080')
    parser.add_argument('--translation-only', action='store_true')
    args = parser.parse_args()
    try:
        with test_service(args.gpu) as service:
            raise SystemExit(verify_translation(service) if args.translation_only else verify(service, args.gpu))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
