"""独立番茄钟：以截止时间计时，面板与角色可见性不影响进度。"""
import json
import math
import time
from pathlib import Path

from loguru import logger
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

PHASES = {"focus": "专注", "short_break": "短休息", "long_break": "长休息"}
DEFAULTS = {"focus_minutes": 25, "short_break_minutes": 5,
            "long_break_minutes": 15, "long_break_every": 4, "sound": True}


class PomodoroManager(QObject):
    changed = pyqtSignal()
    finished = pyqtSignal(str)

    def __init__(self, settings_path, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.path = Path(settings_path)
        self.clock = clock
        self.settings = dict(DEFAULTS)
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            self.settings.update(self._validate(values))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logger.warning("番茄钟设置无法读取，使用默认值；保留原文件")
        self.phase = "focus"
        self.state = "idle"
        self.completed_focus = 0
        self.deadline = None
        self.remaining = self._duration(self.phase)
        self.next_phase = "focus"
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self._last_snapshot = None

    @staticmethod
    def _validate(values):
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError("未知番茄钟设置")
        for key, value in values.items():
            if key == "sound":
                if type(value) is not bool:
                    raise ValueError("sound 必须是布尔值")
            else:
                upper = 12 if key == "long_break_every" else 180
                if type(value) is not int or not 1 <= value <= upper:
                    raise ValueError(f"{key} 必须是 1–{upper} 的整数")
        return values

    def _duration(self, phase):
        return self.settings[phase + "_minutes"] * 60

    def configure(self, **values):
        proposed = {**self.settings, **self._validate(values)}
        # 先落盘再修改内存，失败不会丢失原设置或改变当前计时。
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(proposed, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        except OSError as exc:
            raise ValueError("番茄钟设置保存失败，请检查目录是否可写") from exc
        self.settings = proposed
        if self.state == "idle":
            self.remaining = self._duration(self.phase)
        self._publish()
        return self.snapshot()

    def snapshot(self):
        seconds = max(0, math.ceil(self.deadline - self.clock())) if self.deadline is not None else math.ceil(self.remaining)
        return {"state": self.state, "phase": self.phase, "label": PHASES[self.phase],
                "remaining_seconds": seconds, "completed_focus": self.completed_focus,
                "next_phase": self.next_phase, "settings": dict(self.settings)}

    def _publish(self):
        value = self.snapshot()
        if value != self._last_snapshot:
            self._last_snapshot = value
            self.changed.emit()

    def start(self, phase=None):
        if phase is not None and phase not in PHASES:
            raise ValueError("phase 需要 focus、short_break 或 long_break")
        self.tick()
        if self.state in {"running", "paused"}:
            raise ValueError("当前已有计时，请先重置或继续")
        self.phase = phase or self.next_phase
        self.next_phase = self.phase
        self.remaining = self._duration(self.phase)
        self.deadline = self.clock() + self.remaining
        self.state = "running"
        self.timer.start()
        self._publish()
        return self.snapshot()

    def pause(self):
        self.tick()
        if self.state != "running":
            raise ValueError("只有正在运行的计时可以暂停")
        self.remaining = max(0, self.deadline - self.clock())
        self.deadline = None
        self.state = "paused"
        self.timer.stop()
        self._publish()
        return self.snapshot()

    def resume(self):
        if self.state != "paused":
            raise ValueError("只有已暂停的计时可以继续")
        self.deadline = self.clock() + self.remaining
        self.state = "running"
        self.timer.start()
        self._publish()
        return self.snapshot()

    def reset(self):
        self.timer.stop()
        self.deadline = None
        self.phase = self.next_phase = "focus"
        self.remaining = self._duration(self.phase)
        self.state = "idle"
        self._publish()
        return self.snapshot()

    def tick(self):
        if self.state == "running" and self.clock() >= self.deadline:
            self.timer.stop()
            self.deadline = None
            self.remaining = 0
            self.state = "completed"
            if self.phase == "focus":
                self.completed_focus += 1
                self.next_phase = "long_break" if self.completed_focus % self.settings["long_break_every"] == 0 else "short_break"
                message = f"御者，专注完成！来休息 {self.settings[self.next_phase + '_minutes']} 分钟吧。"
            else:
                self.next_phase = "focus"
                message = "御者，休息结束了。准备好开始下一轮专注了吗？"
            # 先终结状态再通知，迟到的 tick 不会重复提醒或累计多轮。
            self._publish()
            self.finished.emit(message)
        else:
            self._publish()

    def close(self):
        self.timer.stop()
