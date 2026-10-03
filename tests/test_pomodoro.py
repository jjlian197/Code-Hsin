"""验证时间跳跃、暂停余量、阶段轮换和设置落盘失败的边界。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.pomodoro import PomodoroManager


class PomodoroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 100.0
        self.manager = PomodoroManager(Path(self.temp.name) / "pomodoro.json", clock=lambda: self.now)
        self.messages = []
        self.manager.finished.connect(self.messages.append)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_fractional_pause_does_not_lose_seconds(self):
        self.manager.start()
        self.now += 10.4
        self.manager.pause()
        self.assertEqual(self.manager.snapshot()["remaining_seconds"], 1490)
        self.now += 10000
        self.assertEqual(self.manager.snapshot()["remaining_seconds"], 1490)
        self.manager.resume()
        self.now += 1489.59
        self.manager.tick()
        self.assertEqual(self.manager.state, "running")
        self.now += .02
        self.manager.tick()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.manager.completed_focus, 1)

    def test_delayed_tick_finishes_once_and_waits_for_next_stage(self):
        self.manager.start()
        self.now += 100000
        for _ in range(10):
            self.manager.tick()
        self.assertEqual(self.manager.state, "completed")
        self.assertEqual(self.manager.next_phase, "short_break")
        self.assertEqual(self.manager.completed_focus, 1)
        self.assertEqual(len(self.messages), 1)
        self.assertFalse(self.manager.timer.isActive())

    def test_four_focus_sessions_select_long_break_and_break_returns_to_focus(self):
        for round_number in range(1, 5):
            self.manager.start()
            self.now += 1500
            self.manager.tick()
            phase = "long_break" if round_number == 4 else "short_break"
            self.assertEqual(self.manager.next_phase, phase)
            self.manager.start()
            self.assertEqual(self.manager.phase, phase)
            self.now += 900 if round_number == 4 else 300
            self.manager.tick()
            self.assertEqual(self.manager.next_phase, "focus")
        self.assertEqual(self.manager.completed_focus, 4)

    def test_reset_cancels_without_counting_and_disallows_overwriting_active_timer(self):
        self.manager.start()
        with self.assertRaises(ValueError):
            self.manager.start("short_break")
        self.manager.reset()
        self.now += 3000
        self.manager.tick()
        self.assertEqual(self.messages, [])
        self.assertEqual(self.manager.completed_focus, 0)
        self.assertEqual(self.manager.state, "idle")
        with self.assertRaises(ValueError):
            self.manager.resume()

    def test_settings_affect_next_session_and_restart_is_idle(self):
        self.manager.start()
        deadline = self.manager.deadline
        self.manager.configure(focus_minutes=12, sound=False)
        self.assertEqual(self.manager.deadline, deadline)
        other = PomodoroManager(self.manager.path)
        self.assertEqual(other.settings["focus_minutes"], 12)
        self.assertEqual(other.snapshot()["remaining_seconds"], 720)
        self.assertEqual(other.state, "idle")
        other.close()
        self.manager.reset()
        self.assertEqual(self.manager.snapshot()["remaining_seconds"], 720)

    def test_invalid_batch_and_save_failure_preserve_settings(self):
        self.manager.configure(focus_minutes=20)
        original = self.manager.path.read_bytes()
        for values in ({"focus_minutes": 10, "sound": 1}, {"focus_minutes": 0}, {"unknown": 5}, {"long_break_every": True}):
            with self.assertRaises(ValueError):
                self.manager.configure(**values)
            self.assertEqual(self.manager.settings["focus_minutes"], 20)
        with patch.object(Path, "replace", side_effect=OSError("locked")):
            with self.assertRaisesRegex(ValueError, "保存失败"):
                self.manager.configure(focus_minutes=30)
        self.assertEqual(self.manager.path.read_bytes(), original)
        self.assertEqual(self.manager.settings["focus_minutes"], 20)

    def test_corrupt_file_is_preserved(self):
        self.manager.path.write_text("bad json", encoding="utf-8")
        other = PomodoroManager(self.manager.path)
        self.assertEqual(other.settings["focus_minutes"], 25)
        self.assertEqual(self.manager.path.read_text(), "bad json")
        other.close()
