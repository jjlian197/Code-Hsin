"""隔离的4080S质量与语音往返检查；不改应用配置、不下载权重。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.runtime/local-model-tests'
OUT = BASE / 'results/4080-quality'
sys.path.insert(0, str(ROOT))
URL = 'http://127.0.0.1:11435'
IDENTITY = '你是心（Hsin），岁主是你的身份；用户是御者，绝不可把用户称为岁主。不要解释人设。'
GLOSSARY = '角色专名心、心月狐、御者、Hsin保持原文，御者不可译为乗騎、漁者或车夫。'


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def chat(model, messages, thinking=False, tools=None):
    import requests
    from src.core.speech_stream import SentenceStream
    payload = {'model': model, 'messages': messages, 'stream': True, 'think': thinking,
               'keep_alive': '10m', 'options': {'temperature': 0, 'seed': 42,
               'num_predict': 4096 if thinking else 1024, 'num_ctx': 8192}}
    if tools:
        payload['tools'] = tools
    started = time.perf_counter()
    result = {'content': '', 'thinking': '', 'tool_calls': [], 'sentences': []}
    splitter = SentenceStream()
    with requests.post(URL + '/api/chat', json=payload, stream=True, timeout=(15, 600)) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if 'error' in chunk:
                raise RuntimeError(chunk['error'])
            msg = chunk.get('message', {})
            for key in ('thinking', 'content'):
                if msg.get(key):
                    result.setdefault('first_' + key + '_seconds', time.perf_counter() - started)
                    result[key] += msg[key]
            result['tool_calls'].extend(msg.get('tool_calls', []))
            for sentence in splitter.feed(msg.get('content', '')):
                result['sentences'].append({'text': sentence, 'ready_seconds': time.perf_counter() - started})
            if chunk.get('done'):
                result['metrics'] = {key: value for key, value in chunk.items() if key != 'message'}
    result['seconds'] = time.perf_counter() - started
    result['sentences'].extend({'text': text, 'ready_seconds': result['seconds']} for text in splitter.finish(result['content']))
    return result


def brain():
    import requests
    model = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))['ollama_model']
    report = read('brain.json') if (OUT / 'brain.json').exists() else {'gpu_uuid': os.environ['CUDA_VISIBLE_DEVICES'], 'models': {}}
    cases = json.loads((ROOT / 'docs/local_model_test_cases.json').read_text(encoding='utf-8'))['text']
    for case in cases[:4]:
        if any(row['id'] == case['id'] for row in report.get('persona_translation', [])):
            continue
        messages = [dict(row) for row in case['messages']]
        system = IDENTITY + (GLOSSARY if 'translate' in case['id'] else '')
        if messages[0]['role'] == 'system':
            messages[0]['content'] = system + messages[0]['content']
        else:
            messages.insert(0, {'role': 'system', 'content': system})
        result = chat(model, messages)
        report.setdefault('persona_translation', []).append({'id': case['id'], 'messages': messages, **result})
        save('brain.json', report)
        print(case['id'], result['content'], round(result['seconds'], 2), flush=True)
    # 同一题分别关闭/开启思考，并与用户已经安装的9B比较。
    for current in (model, 'huihui_ai/qwen3.5-abliterated:9b'):
        rows = report['models'].setdefault(current, [])
        reasoning = [('dependency', cases[4]['messages']),
            ('long-parallel', [{'role': 'user', 'content': 'A要12分钟，B在A完成后做，要8分钟。C由自动程序从0分钟开始做30分钟，D必须等B和C都完成后做5分钟。最快何时完成D？简短解释。'}]),
            ('discount', [{'role': 'user', 'content': '200元商品先打八折，再使用满150元减20元的优惠券（门槛按打折后金额计算）。最终付多少元？简短解释。'}])]
        for case_id, prompt in reasoning:
            for thinking in (False, True):
                if any(row['id'] == case_id and row['thinking_enabled'] == thinking for row in rows):
                    continue
                messages = [{'role': 'system', 'content': '请核验依赖关系和算术，最终用两句话回答。'}, *prompt]
                result = chat(current, messages, thinking)
                rows.append({'id': case_id, 'thinking_enabled': thinking, 'messages': messages, **result})
                save('brain.json', report)
                print(current, case_id, 'thinking', thinking, result['content'], round(result['seconds'], 2), flush=True)
        tools = [{'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': list(properties)}}}
            for name, description, properties in (
                ('write_note', '写入测试便笺。成功后要调用read_note核验。', {'text': {'type': 'string'}}),
                ('read_note', '读取实际写入的便笺note.txt。', {'name': {'type': 'string', 'enum': ['note.txt']}}))]
        messages = [{'role': 'system', 'content': IDENTITY + '使用工具完成请求，写入后必须读取核验，再根据工具结果回复。'},
                    {'role': 'user', 'content': '请把“日语练习25分钟，然后休息10分钟”存入便笺，读回来确认，并告诉我总共多少分钟。'}]
        turns = []
        workspace = OUT / ('tool-' + current.rsplit(':', 1)[-1])
        workspace.mkdir(exist_ok=True)
        for _ in range(5):
            try:
                result = chat(current, messages, thinking=current == model, tools=tools)
            except (requests.RequestException, RuntimeError) as error:
                response = getattr(error, 'response', None)
                turns.append({'error': str(error), 'server_response': response.text if response is not None else None})
                break
            turns.append(result)
            messages.append({'role': 'assistant', 'content': result['content'], 'tool_calls': result['tool_calls']})
            if not result['tool_calls']:
                break
            for call in result['tool_calls']:
                function = call['function']
                args = function['arguments']
                if function['name'] == 'write_note' and set(args) == {'text'} and isinstance(args['text'], str):
                    (workspace / 'note.txt').write_text(args['text'], encoding='utf-8')
                    value = {'success': True, 'characters': len(args['text'])}
                elif function['name'] == 'read_note' and args == {'name': 'note.txt'}:
                    value = {'text': (workspace / 'note.txt').read_text(encoding='utf-8')}
                else:
                    raise ValueError('不允许的工具或参数')
                messages.append({'role': 'tool', 'tool_name': function['name'], 'content': json.dumps(value, ensure_ascii=False)})
        if current in report.get('tools', {}):
            report.setdefault('tools_previous', []).append({'model': current, **report['tools'][current]})
        report.setdefault('tools', {})[current] = {'schema': 'read_note requires fixed filename', 'thinking_enabled': current == model, 'turns': turns, 'messages': messages,
            'note': (workspace / 'note.txt').read_text(encoding='utf-8') if (workspace / 'note.txt').exists() else None}
        save('brain.json', report)
        print(current, 'tools', turns[-1].get('content', turns[-1].get('error')), flush=True)
        role_prompt = '你扮演心，她是岁主。用户扮演御者。称呼用户时只能用“御者”，禁止称用户为“岁主”。你的说话方式正式、端庄、从容温柔，用现代汉语。请直接给出工作安排，不介绍身份。安排用相对分钟表示，不虚构绝对时刻。先核算总时间，三项时间之和必须等于用户给定的一小时即60分钟。用三条简短建议回答，不堆砌古语。'
        result = chat(current, [{'role': 'system', 'content': role_prompt}, cases[1]['messages'][-1]])
        if current in report.get('explicit_roles', {}):
            report.setdefault('explicit_roles_previous', []).append({'model': current, **report['explicit_roles'][current]})
        report.setdefault('explicit_roles', {})[current] = {'system': role_prompt, **result}
        save('brain.json', report)
        print(current, 'explicit-roles', result['content'], flush=True)
        if current == model:
            ja_prompt = 'あなたは心（Hsin）という親しみやすく少し茶目っ気のある女性です。ユーザーは御者です。自然な日本語の短い文をちょうど二文だけ返してください。自分の名前や身分を名乗らないでください。箇条書きは使わず、疲れたユーザーに具体的な短い休憩を提案してください。'
            result = chat(current, [{'role': 'system', 'content': ja_prompt},
                {'role': 'user', 'content': '一時間働いて少し疲れました。休み方をにむんで教えてください。'}])
            save('explicit-japanese.json', {'system': ja_prompt, **result})
            started = time.perf_counter()
            with requests.post(URL + '/api/chat', json={'model': current, 'stream': True, 'think': True,
                'messages': [{'role': 'user', 'content': '请深入分析一个复杂项目应该如何安排。'}],
                'options': {'num_predict': 4096, 'num_ctx': 8192}}, stream=True, timeout=60) as response:
                response.raise_for_status()
                received = False
                for line in response.iter_lines():
                    if line and json.loads(line).get('message', {}).get('thinking'):
                        received = True
                        break
            following = chat(current, [{'role': 'user', 'content': '只回复“收到”。'}])
            save('generation-cancel.json', {'received_thinking_before_close': received,
                'seconds_through_following_request': time.perf_counter() - started,
                'following_request': following, 'scope': '关闭真实流式HTTP连接后发送新请求；应用代次和TTS取消尚未接入'})
        requests.post(URL + '/api/generate', json={'model': current, 'keep_alive': 0}, timeout=30).raise_for_status()


def tts(inputs):
    import torch
    import soundfile as sf
    import numpy as np
    from qwen_tts import Qwen3TTSModel
    profiles = json.loads((ROOT / 'voice/profiles.json').read_text(encoding='utf-8'))['profiles']
    rows = read('requests.json') if inputs else read('replies.json')
    report = []
    for language in ('zh', 'ja'):
        path = ROOT / '.runtime/qwen3-tts-training/zh/checkpoint-epoch-3' if language == 'zh' else BASE / 'models/qwen3-tts'
        model = Qwen3TTSModel.from_pretrained(str(path), device_map='cuda:0', dtype=torch.bfloat16,
            attn_implementation='sdpa', local_files_only=True)
        for row in [row for row in rows if row['language'] == language]:
            torch.manual_seed(42)
            started = time.perf_counter()
            kwargs = {'text': row['text'], 'language': 'Chinese' if language == 'zh' else 'Japanese', 'max_new_tokens': 1024}
            if language == 'zh':
                wavs, rate = model.generate_custom_voice(**kwargs, speaker='hsin_zh')
            else:
                wavs, rate = model.generate_voice_clone(**kwargs, ref_audio=profiles[language]['reference_audio'], ref_text=profiles[language]['prompt_text'])
            audio = np.asarray(wavs[0])
            assert audio.size and np.isfinite(audio).all()
            target = OUT / (row['id'] + '.wav')
            sf.write(str(target), audio, rate)
            report.append({**row, 'audio': str(target), 'synthesis_seconds': time.perf_counter() - started,
                'audio_seconds': audio.size / rate, 'gpu': torch.cuda.get_device_name(0)})
            save('inputs.json' if inputs else 'audio.json', report)
            print(row['id'], round(report[-1]['synthesis_seconds'], 2), flush=True)
        del model
        torch.cuda.empty_cache()


def asr():
    import torch
    from qwen_asr import Qwen3ASRModel
    model = Qwen3ASRModel.from_pretrained(str(BASE / 'models/qwen3-asr'), device_map='cuda:0', dtype=torch.bfloat16,
        attn_implementation='sdpa', max_inference_batch_size=1, max_new_tokens=256, local_files_only=True)
    rows = []
    for row in read('inputs.json'):
        started = time.perf_counter()
        result = model.transcribe(audio=row['audio'], context='心、御者、心月狐、Hsin',
            language='Chinese' if row['language'] == 'zh' else 'Japanese')[0]
        rows.append({**row, 'transcript': result.text, 'asr_seconds': time.perf_counter() - started})
        save('transcripts.json', rows)
        print(row['id'], result.text, flush=True)


def replies():
    model = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))['ollama_model']
    rows = []
    for row in read('transcripts.json'):
        result = chat(model, [{'role': 'system', 'content': IDENTITY + GLOSSARY + '温柔俏皮，用输入语言回答，两句简短自然的口语，不用列表。'},
                             {'role': 'user', 'content': row['transcript']}])
        save('reply-' + row['language'] + '.json', result)
        rows.extend({'id': 'reply-' + row['language'] + '-' + str(index), 'language': row['language'],
            'text': sentence['text'], 'ready_seconds': sentence['ready_seconds']} for index, sentence in enumerate(result['sentences']))
    save('replies.json', rows)


def playback():
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtMultimedia import QMediaPlayer
    from src.core.voice_player import LocalVoicePlayer
    app = QApplication(['qwen-audio-validation'])
    player = LocalVoicePlayer()
    rows, events = read('audio.json'), []
    index, started = [0], time.perf_counter()
    def event(kind):
        events.append({'kind': kind, 'id': rows[index[0]]['id'], 'seconds': time.perf_counter() - started, **player.snapshot()})
    def next_audio():
        index[0] += 1
        if index[0] == len(rows):
            # 真实停止播放后观察旧解码回调，不以睡眠模拟播放成功。
            index[0] = 0
            player.play(Path(rows[0]['audio']), volume=0)
            QTimer.singleShot(300, cancel)
        else:
            player.play(Path(rows[index[0]]['audio']), volume=0)
    def cancel():
        player.stop()
        event('cancel')
        QTimer.singleShot(500, finish)
    def finish():
        event('after_cancel')
        save('playback.json', {'events': events, 'cancel_stopped': player.snapshot()['state'] == 'StoppedState' and player.last_level == 0})
        app.quit()
    def status(value):
        if value == QMediaPlayer.MediaStatus.EndOfMedia:
            event('end')
            QTimer.singleShot(0, next_audio)
    player.player.mediaStatusChanged.connect(status)
    player.player.playbackStateChanged.connect(lambda value: event('playing') if value == QMediaPlayer.PlaybackState.PlayingState else None)
    player.player.errorOccurred.connect(lambda *_: (event('error'), finish()))
    player.play(Path(rows[0]['audio']), volume=0)
    QTimer.singleShot(180000, finish)
    app.exec()
    player.cleanup()


def prompts():
    report = read('brain.json')
    model = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))['ollama_model']
    for current in (model, 'huihui_ai/qwen3.5-abliterated:9b'):
        system = '你扮演心，她是岁主。用户是御者，称呼用户只能用御者。语气正式端庄、从容温柔，用现代汉语。工作安排用相对分钟，不虚构绝对时刻。三项时间之和必须等于60分钟，先核算总时间。用三条简短建议回答，不堆砌古语。'
        result = chat(current, [{'role': 'system', 'content': system}, {'role': 'user', 'content': '我今晚只有一个小时，需要整理会议记录、完成一份报告并练习日语。请帮我安排。'}])
        report.setdefault('budgeted_roles', {})[current] = {'system': system, **result}
        save('brain.json', report)
        print(current, 'budgeted-roles', result['content'], flush=True)
    result = chat(model, [{'role': 'system', 'content': '你是心，用户是御者。请用自然日语回答用户的问题，提供具体的休息建议。不要复述或翻译用户的问题，不自报身份。输出两句简短日语。'},
        {'role': 'user', 'content': '一時間働いて少し疲れました。休み方をにむんで教えてください。'}])
    save('japanese-response-prompt.json', result)
    print('japanese-response-prompt', result['content'], flush=True)


def suite(only_prompts=False, cleanup_only=False):
    import requests
    # 端口被占用就停止，不复用或结束非本测试服务。
    import socket
    with socket.socket() as check:
        assert check.connect_ex(('127.0.0.1', 11435)) != 0, '隔离端口已占用'
    env = os.environ.copy()
    env.update(OLLAMA_HOST='127.0.0.1:11435', OLLAMA_MODELS='D:/ollama/models', OLLAMA_CONTEXT_LENGTH='8192',
        OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1', OLLAMA_NO_CLOUD='true')
    OUT.mkdir(parents=True, exist_ok=True)
    log = (OUT / 'ollama.log').open('a', encoding='utf-8')
    server = subprocess.Popen([shutil.which('ollama'), 'serve'], env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(100):
            try:
                requests.get(URL + '/api/version', timeout=1).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(.2)
        else:
            raise RuntimeError('测试服务启动失败')
        def worker(python, mode):
            subprocess.run([str(python), str(Path(__file__)), mode], check=True, env=os.environ.copy())
        if cleanup_only:
            model = json.loads((BASE / 'qwen-brain.json').read_text(encoding='utf-8'))['ollama_model']
            save('cleanup-check.json', chat(model, [{'role': 'user', 'content': '只回复收到。'}]))
            return
        if only_prompts:
            worker(sys.executable, 'prompts')
            return
        worker(sys.executable, 'brain')
        save('requests.json', [{'id': 'request-zh', 'language': 'zh', 'text': '我工作了一个小时，有点累了。请用两句话建议我怎么休息。'},
            {'id': 'request-ja', 'language': 'ja', 'text': '一時間働いて、少し疲れました。休み方を二文で教えてください。'}])
        if not (OUT / 'playback.json').exists():
            worker(BASE / 'venv-tts/Scripts/python.exe', 'inputs')
            worker(BASE / 'venv-asr/Scripts/python.exe', 'asr')
            worker(sys.executable, 'replies')
            worker(BASE / 'venv-tts/Scripts/python.exe', 'tts')
            worker(sys.executable, 'playback')
    finally:
        if server.poll() is None:
            try:
                resident = requests.get(URL + '/api/ps', timeout=5).json().get('models', [])
                for row in resident:
                    requests.post(URL + '/api/generate', json={'model': row['name'], 'keep_alive': 0}, timeout=15).raise_for_status()
            except requests.RequestException:
                pass
            # Windows强制终止服务不会自动结束模型子进程，按本次Popen的PID清理整棵树。
            subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        server.wait(timeout=20)
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['suite', 'prompt-suite', 'cleanup-suite', 'prompts', 'brain', 'inputs', 'asr', 'replies', 'tts', 'playback'])
    mode = parser.parse_args().mode
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
    os.environ['CUDA_VISIBLE_DEVICES'] = next(line.rsplit(',', 1)[1].strip() for line in inventory.splitlines() if 'RTX 4080 SUPER' in line)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_DEVICE_ORDER='PCI_BUS_ID')
    {'suite': suite, 'prompt-suite': lambda: suite(True), 'cleanup-suite': lambda: suite(cleanup_only=True), 'prompts': prompts, 'brain': brain, 'inputs': lambda: tts(True), 'asr': asr,
     'replies': replies, 'tts': lambda: tts(False), 'playback': playback}[mode]()
