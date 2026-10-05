"""隔离模型运行环境；单进程串行请求，取消终止本实例并唤醒等待者。"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

from src.core.app_config import project_path, PROJECT_ROOT


class ModelProcess:
    def __init__(self, python, gpu, runtime):
        self.python, self.gpu, self.runtime = project_path(python), gpu, Path(runtime)
        self.lock, self.serial = threading.Lock(), threading.Lock()
        self.process = self.responses = None
        self.closed = False
        self.active = threading.Event()

    def _start(self):
        if self.closed:
            raise RuntimeError('本地模型进程已关闭')
        if self.process is not None and self.process.poll() is None:
            return
        if not self.python.is_file():
            raise ValueError('未找到Qwen独立Python环境，请选择已准备的Python程序')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   TOKENIZERS_PARALLELISM='false', CUDA_DEVICE_ORDER='PCI_BUS_ID')
        if self.gpu == 'cpu':
            env['CUDA_VISIBLE_DEVICES'] = ''
            env.update(OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
        elif self.gpu.startswith('GPU-'):
            env['CUDA_VISIBLE_DEVICES'] = self.gpu
        else:
            inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
            name = {'4080': 'RTX 4080 SUPER', '8gb': 'RTX 5060 Laptop'}.get(self.gpu)
            matches = [line for line in inventory.splitlines() if name and name in line]
            if len(matches) != 1:
                raise ValueError('请为Qwen选择cpu、4080、8gb或准确的GPU UUID')
            env['CUDA_VISIBLE_DEVICES'] = matches[0].rsplit(',', 1)[1].strip()
        self.runtime.mkdir(parents=True, exist_ok=True)
        frozen_windows = os.name == 'nt' and getattr(sys, 'frozen', False)
        command = [str(self.python), '-u', str(project_path('src/core/qwen_worker.py'))]
        if frozen_windows:
            import ctypes
            bundle = Path(sys._MEIPASS).resolve()
            env['PATH'] = os.pathsep.join(item for item in env.get('PATH', '').split(os.pathsep)
                if item and not Path(item).resolve().is_relative_to(bundle))
        with (self.runtime / 'worker.log').open('ab') as log:
            if frozen_windows:
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                process = subprocess.Popen(command, cwd=str(PROJECT_ROOT),
                    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            finally:
                if frozen_windows:
                    ctypes.windll.kernel32.SetDllDirectoryW(str(bundle))
        responses = queue.Queue()
        self.process, self.responses = process, responses
        def read():
            try:
                for line in process.stdout:
                    try:
                        responses.put(json.loads(line))
                    except (ValueError, UnicodeError):
                        continue
            finally:
                responses.put({'error': 'Qwen进程已结束或已取消'})
        threading.Thread(target=read, name='QwenResponses', daemon=True).start()

    def request(self, operation, timeout=180, **params):
        with self.serial:
            self.active.set()
            try:
                return self._request(operation, timeout, params)
            finally:
                self.active.clear()

    def _request(self, operation, timeout, params):
        with self.lock:
            self._start()
            process, responses = self.process, self.responses
        request_id = uuid.uuid4().hex
        try:
            process.stdin.write((json.dumps({'id': request_id, 'operation': operation, **params}) + '\n').encode())
            process.stdin.flush()
            response = responses.get(timeout=timeout)
            if response.get('error'):
                raise RuntimeError(response['error'])
            if response.get('id') != request_id:
                raise RuntimeError('Qwen返回了不匹配的请求结果')
            with self.lock:
                if self.process is not process:
                    raise RuntimeError('Qwen请求已取消')
            return response
        except queue.Empty:
            self.cancel()
            raise RuntimeError('Qwen本地处理超时，请重试') from None
        except (OSError, ValueError):
            raise RuntimeError('Qwen进程已取消或连接失败') from None

    def cancel(self):
        with self.lock:
            process, self.process = self.process, None
            responses, self.responses = self.responses, None
        if responses is not None:
            responses.put({'error': 'Qwen请求已取消'})
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

    def close(self):
        with self.lock:
            self.closed = True
        self.cancel()

    def release_idle(self):
        # 与真实请求串行，不能因界面已取消就中断仍在运行的识别。
        if not self.serial.acquire(blocking=False):
            return False
        try:
            with self.lock:
                resident = self.process is not None
            if resident:
                self.cancel()
            return resident
        finally:
            self.serial.release()
