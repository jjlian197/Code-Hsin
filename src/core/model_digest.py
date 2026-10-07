"""在后台读取 PMX，避免外置盘授权或慢盘阻塞 Qt 界面。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event, Thread

from PyQt6.QtCore import QObject, pyqtSignal


def read_model_digest(model_path: Path, cancelled: Event) -> str:
    fingerprint = hashlib.sha256()
    with model_path.open("rb") as model_file:
        while not cancelled.is_set():
            chunk = model_file.read(1024 * 1024)
            if not chunk:
                return fingerprint.hexdigest()
            fingerprint.update(chunk)
    return ""


class ModelDigestLoader(QObject):
    finished = pyqtSignal(int, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancelled = Event()

    def request(self, request_id: int, model_path: Path) -> None:
        self._cancelled.set()
        self._cancelled = Event()
        # OS 的文件授权等待无法由 Python 中断；daemon 允许用户立即退出应用。
        Thread(target=self._read, args=(request_id, model_path, self._cancelled), daemon=True).start()

    def _read(self, request_id: int, model_path: Path, cancelled: Event) -> None:
        fingerprint = ""
        error_message = ""
        try:
            fingerprint = read_model_digest(model_path, cancelled)
        except OSError as exc:
            error_message = f"模型无法读取：{exc}"
        if not cancelled.is_set():
            try:
                self.finished.emit(request_id, fingerprint, error_message)
            except RuntimeError:
                # 关闭窗口可能已销毁 Qt 对象，此时丢弃晚到的文件读取结果。
                pass

    def close(self) -> None:
        self._cancelled.set()
