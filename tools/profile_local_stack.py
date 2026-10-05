"""隔离真实窗口共同负载采样：PMX/Qwen ASR/4B/GPT-SoVITS，不开麦。"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.local_ollama_test_service import test_service
OUT = ROOT / '.runtime/local-model-tests/acceptance'


def renderer_luid():
    """按真实DXGI名称选卡；仅设置本次Qt进程，不修改Windows偏好。"""
    import ctypes as c
    import uuid
    class Luid(c.Structure):
        _fields_ = [('low', c.c_uint32), ('high', c.c_int32)]
    class Desc(c.Structure):
        _fields_ = [('name', c.c_wchar * 128), ('vendor', c.c_uint32), ('device', c.c_uint32),
                    ('subsystem', c.c_uint32), ('revision', c.c_uint32), ('dedicated_video', c.c_size_t),
                    ('dedicated_system', c.c_size_t), ('shared_system', c.c_size_t), ('luid', Luid), ('flags', c.c_uint32)]
    def method(obj, slot, result, *arguments):
        table = c.cast(obj, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(result, c.c_void_p, *arguments)(table[slot])
    factory = c.c_void_p()
    iid = c.create_string_buffer(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    result = c.WinDLL('dxgi').CreateDXGIFactory1(iid, c.byref(factory))
    if result:
        raise RuntimeError('DXGI初始化失败')
    try:
        for index in range(16):
            adapter = c.c_void_p()
            if method(factory, 12, c.c_long, c.c_uint, c.POINTER(c.c_void_p))(factory, index, c.byref(adapter)):
                break
            try:
                desc = Desc()
                if method(adapter, 10, c.c_long, c.POINTER(Desc))(adapter, c.byref(desc)) == 0 and 'RTX 4080 SUPER' in desc.name:
                    os.environ['QT_D3D_ADAPTER_INDEX'] = str(index)
                    os.environ['QSG_RHI_BACKEND'] = 'd3d11'
                    return f'{desc.luid.high},{desc.luid.low}'
            finally:
                method(adapter, 2, c.c_ulong)(adapter)
    finally:
        method(factory, 2, c.c_ulong)(factory)
    raise RuntimeError('DXGI未找到4080S')


class Monitor:
    def __init__(self, folder):
        self.folder = folder
        self.started = time.monotonic()
        self.phase = 'baseline'
        self.samples = []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        with (self.folder / 'samples.jsonl').open('w', encoding='utf-8') as log:
            while not self.done.is_set():
                row = {'seconds': time.monotonic() - self.started, 'phase': self.phase}
                try:
                    output = subprocess.check_output(['nvidia-smi', '--query-gpu=uuid,name,memory.used,utilization.gpu', '--format=csv,noheader,nounits'], text=True)
                    row['gpus'] = [{'uuid': fields[0], 'name': fields[1], 'used_mib': int(fields[2]), 'utilization': int(fields[3])}
                                   for line in output.splitlines() if (fields := [v.strip() for v in line.split(',')])]
                    vm = psutil.virtual_memory()
                    row['system_ram_used_mib'] = vm.used / 1048576
                    processes = []
                    for proc in [psutil.Process(), *psutil.Process().children(recursive=True)]:
                        try:
                            cmd = ' '.join(proc.cmdline())
                            if proc.name().lower() in ('nvidia-smi.exe', 'pwsh.exe', 'powershell.exe'):
                                continue
                            group = ('gpt_sovits' if 'hsin_voice_server.py' in cmd else 'asr' if 'src.core.qwen_worker' in cmd
                                     else 'ollama' if 'ollama' in proc.name().lower() or proc.name().lower() == 'llama-server.exe' else 'pmx_app')
                            memory = proc.memory_info()
                            processes.append({'pid': proc.pid, 'name': proc.name(), 'group': group,
                                'rss_mib': memory.rss / 1048576, 'private_commit_mib': memory.private / 1048576,
                                'private_working_set_mib': proc.memory_full_info().uss / 1048576})
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    row['processes'] = processes
                    row['owned_rss_mib'] = sum(p['rss_mib'] for p in processes)
                    row['owned_private_commit_mib'] = sum(p['private_commit_mib'] for p in processes)
                    row['owned_private_working_set_mib'] = sum(p['private_working_set_mib'] for p in processes)
                    if len(self.samples) % 15 == 0:
                        script = 'Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | Select-Object Name,DedicatedUsage,SharedUsage,TotalCommitted | ConvertTo-Json -Compress'
                        counters = json.loads(subprocess.check_output(['powershell', '-NoProfile', '-Command', script], text=True, timeout=15))
                        pids = {p['pid'] for p in processes}
                        row['owned_gpu_counters'] = [p for p in counters if (m := re.match(r'pid_(\d+)_', p['Name'])) and int(m[1]) in pids]
                except Exception as error:
                    row['sampling_error'] = str(error)
                self.samples.append(row)
                log.write(json.dumps(row, ensure_ascii=False) + '\n')
                log.flush()
                self.done.wait(2)


def verify(service, monitor, folder, args):
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--use-angle=d3d11 --use-adapter-luid=' + renderer_luid()
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import QApplication
    from src.core.app_config import load_config
    from src.core.sprite_window import HsinSpriteWindow
    config = load_config(OUT / 'config.yaml')
    config['runtime']['directory'] = str(folder / 'runtime')
    config['runtime']['model_idle_seconds'] = args.idle_release_seconds
    config['chat'].update(provider='ollama', speech_scope='full', reply_length='short')
    config['chat']['ollama'].update(url=service['url'], model=service['model'], thinking=False, context_length=4096)
    config['stt'].update(provider='qwen', fallback=False)
    config['stt']['qwen']['gpu'] = args.asr_device
    config['voice'].update(provider='gptsovits', enabled=True, port=19885, volume=0, fallback=False, auto_translate=False)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(['local-stack-resource-profile'])
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(config)
    window.show_sprite()
    window.chat.configure('ollama')
    window.tts.configure(provider='gptsovits', enabled=True, language='zh', fallback=False, auto_translate=False)
    window.stt._start_capture = lambda: (_ for _ in ()).throw(RuntimeError('禁止打开物理麦克风'))
    report = {'success': False, 'turns': [], 'input': 'existing synthesized recordings, no physical microphone',
              'context_length': 4096, 'model': service['model'], 'gpu_uuid': service['gpu_uuid'],
              'tts_cache': 'separate cache directory each turn, no prior audio reuse',
              'asr_device': args.asr_device, 'idle_release_seconds': args.idle_release_seconds}
    state = {'phase': 'warmup', 'language': 'zh', 'since': time.monotonic(), 'started': time.monotonic(), 'played': 0, 'buffers': 0, 'reply': '', 'transcript': ''}
    window.stt.transcript.connect(lambda text: state.update(transcript=text))
    window.chat.reply_ready.connect(lambda text, lang: state.update(reply=text))
    window.tts.speech_started.connect(lambda text: state.update(played=state['played'] + 1))
    window.voice_player.buffers.audioBufferReceived.connect(lambda buffer: state.update(buffers=state['buffers'] + int(buffer.isValid() and buffer.byteCount() > 0)))
    renderer_script = "(() => {let c=document.querySelector('canvas');let g=c&&(c.getContext('webgl2')||c.getContext('webgl'));if(!g)return 'unavailable';let e=g.getExtension('WEBGL_debug_renderer_info');return e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):g.getParameter(g.RENDERER);})()"

    def phase(value):
        state.update(phase=value, since=time.monotonic())
        monitor.phase = value + '-' + state['language']

    def feed():
        pcm = subprocess.check_output([shutil.which('ffmpeg'), '-v', 'error', '-i', str(ROOT / f'.runtime/local-model-tests/results/4080-quality/request-{state["language"]}.wav'), '-ar', '16000', '-ac', '1', '-f', 's16le', 'pipe:1'])
        window.stt.enabled = True
        window.stt.blocked = False
        window.stt._cooldown = 0
        window.stt.feed_pcm(pcm + b'\0' * 32000)
        assert window.stt.busy

    def tick():
        try:
            assert window.stt.source is None
            if window.chat.error or window.tts.error or window.stt.error:
                raise RuntimeError(window.chat.error or window.tts.error or window.stt.error)
            if state['phase'] != 'idle' and time.monotonic() - state['since'] > 180:
                raise RuntimeError('阶段超时：' + state['phase'])
            if state['phase'] == 'warmup' and window.tts.warmup_state == 'ready' and window.sprite_view.model_loaded:
                if 'renderer' not in report:
                    def renderer_result(value):
                        report['renderer'] = value
                        if 'RTX 4080 SUPER' not in str(value):
                            report['error'] = 'PMX未绑定4080S：' + str(value)
                            app.quit()
                    window.sprite_view.web.page().runJavaScript(renderer_script, renderer_result)
                phase('turn')
                # 每轮独立缓存，避免删掉播放器仍持有的音频，也保证正式回复真实合成。
                window.tts.provider.runtime = folder / 'runtime' / 'tts' / ('turn-' + str(len(report['turns']) + 1))
                feed()
            elif state['phase'] == 'warmup' and window.tts.warmup_state == 'failed':
                raise RuntimeError(window.tts.warmup_error)
            elif state['phase'] in ('turn', 'reload_turn') and state['reply'] and state['played'] and not window.chat.busy and not window.tts.snapshot()['active']:
                report['turns'].append({'index': len(report['turns']) + 1, 'language': state['language'], 'seconds': time.monotonic() - state['since'],
                    'played': state['played'], 'buffers': state['buffers'], 'reply': state['reply'], 'transcript': state['transcript'],
                    'after_idle_release': state['phase'] == 'reload_turn'})
                print('turn', len(report['turns']), state['language'], round(report['turns'][-1]['seconds'], 2), flush=True)
                (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                state.update(played=0, buffers=0, reply='', transcript='')
                if state['phase'] == 'reload_turn':
                    assert report['turns'][-1]['buffers'] > 0
                    report['idle_release']['reload_asr_pid'] = window.stt._recognizer._qwen.process.pid
                    report['idle_release']['reload_tts_pid'] = window.tts.provider.process.pid
                    assert report['idle_release']['reload_asr_pid'] != report['idle_release']['old_asr_pid']
                    assert report['idle_release']['reload_tts_pid'] != report['idle_release']['old_tts_pid']
                    report['success'] = True
                    app.quit()
                    return
                if len(report['turns']) >= args.turns:
                    if args.verify_idle_release:
                        report['idle_release'] = {'old_asr_pid': window.stt._recognizer._qwen.process.pid,
                                                  'old_tts_pid': window.tts.provider.process.pid}
                    phase('idle')
                else:
                    state['language'] = 'ja' if state['language'] == 'zh' else 'zh'
                    window.stt.configure(language=state['language'], enabled=False)
                    window.tts.configure(language=state['language'])
                    phase('warmup')
            elif state['phase'] == 'idle' and args.verify_idle_release and window.voice_idle.release_count:
                assert window.voice_idle.last_release == {'asr': True, 'gptsovits': True}
                assert window.stt._recognizer._qwen.process is None and window.tts.provider.process is None
                report['idle_release'].update(seconds=time.monotonic() - state['since'], released=window.voice_idle.last_release)
                print('ASR/TTS idle released', flush=True)
                window.config['runtime']['model_idle_seconds'] = 0
                phase('after_release')
            elif state['phase'] == 'after_release' and time.monotonic() - state['since'] >= 10:
                state['language'] = 'zh'
                window.tts._prewarm_enabled = False
                window.stt.configure(language='zh', enabled=False)
                window.tts.configure(language='zh')
                window.tts.provider.runtime = folder / 'runtime' / 'tts' / 'reload'
                phase('reload_turn')
                feed()
            elif state['phase'] == 'idle' and time.monotonic() - state['since'] >= args.idle_seconds:
                assert not args.verify_idle_release, '闲置期限内未释放本次ASR/TTS'
                report['success'] = True
                app.quit()
                return
        except Exception as error:
            report['error'] = str(error)
            app.quit()
            return
        QTimer.singleShot(80, tick)

    phase('warmup')
    window.tts.prewarm()
    QTimer.singleShot(80, tick)
    try:
        app.exec()
    finally:
        report['model_loaded'] = window.sprite_view.model_loaded
        report['duration_seconds'] = time.monotonic() - state['started']
        monitor.phase = 'cleanup'
        window.cleanup()
        window.hide()
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=24)
    parser.add_argument('--idle-seconds', type=int, default=300)
    parser.add_argument('--asr-device', choices=('4080', 'cpu'), default='4080')
    parser.add_argument('--idle-release-seconds', type=int, default=600)
    parser.add_argument('--verify-idle-release', action='store_true')
    args = parser.parse_args()
    folder = OUT / ('stack-profile-' + time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    monitor = Monitor(folder)
    monitor.thread.start()
    # 基线采样先于本次服务启动，保留原有程序。
    time.sleep(15)
    try:
        with test_service() as service:
            os.environ['CUDA_VISIBLE_DEVICES'] = service['gpu_uuid']
            os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
            report = verify(service, monitor, folder, args)
        monitor.phase = 'after_cleanup'
        time.sleep(15)
    finally:
        monitor.done.set()
        monitor.thread.join(timeout=20)
    print(json.dumps({'folder': str(folder), 'success': report['success'], 'turns': len(report['turns']), 'duration': report['duration_seconds']}, ensure_ascii=False), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
