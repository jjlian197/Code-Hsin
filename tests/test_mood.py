"""验证好感度节流、跨日/重启、保存失败与闲置情绪。"""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from src.core.mood import MoodManager


class MoodTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 100.0
        self.wall = datetime(2026, 10, 3, 12).timestamp()
        self.path = Path(self.temp.name) / "mood.json"
        self.manager = self.make_manager()

    def make_manager(self):
        return MoodManager(self.path, clock=lambda: self.now, wall_clock=lambda: self.wall)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_touch_cooldown_is_shared_by_parts_and_survives_restart(self):
        self.manager.interact("touch", "head")
        self.manager.interact("touch", "tail")
        self.assertEqual(self.manager.snapshot()["affection"], 31)
        restored = self.make_manager()
        restored.interact("touch", "hand")
        self.assertEqual(restored.snapshot()["affection"], 31)
        self.advance(15)
        restored.interact("touch", "hand")
        self.assertEqual(restored.snapshot()["affection"], 32)
        restored.close()

    def test_daily_cap_rollover_and_backward_clock(self):
        for _ in range(15):
            self.manager.interact("chat")
            self.advance(60)
        self.assertEqual(self.manager.snapshot()["affection"], 50)
        self.assertEqual(self.manager.snapshot()["earned_today"], 20)
        self.advance(86400)
        self.manager.tick()
        self.assertEqual(self.manager.snapshot()["earned_today"], 0)
        self.manager.interact("focus")
        self.assertEqual(self.manager.snapshot()["affection"], 53)
        self.wall -= 86400
        self.manager.interact("focus")
        self.assertEqual(self.manager.snapshot()["affection"], 53, "时钟倒退不重置额度或绕过冷却")

    def test_idle_changes_mood_without_affection_loss_and_active_focus_is_not_idle(self):
        self.manager.interact("touch", "head")
        self.advance(46)
        self.manager.tick()
        self.assertEqual(self.manager.mood, "calm")
        self.advance(1800)
        self.manager.tick()
        self.assertEqual(self.manager.mood, "lonely")
        self.advance(3600)
        self.manager.tick()
        self.assertEqual(self.manager.mood, "tired")
        self.assertEqual(self.manager.snapshot()["affection"], 31)
        self.manager.tick(engaged=True)
        self.assertEqual(self.manager.mood, "calm")
        self.manager.interact("chat")
        self.assertEqual(self.manager.mood, "happy")

    def test_tiers_unlock_responses_and_no_score_above_100(self):
        proposed = {**self.manager.data, "affection": 59}
        self.manager._save(proposed)
        self.manager.interact("touch", "head")
        self.assertEqual(self.manager.snapshot()["tier"], "信赖")
        self.assertEqual(self.manager.mood, "shy")
        self.assertIn("blush", self.manager.snapshot()["unlocked_expressions"])
        self.assertNotIn("heart_eyes", self.manager.snapshot()["unlocked_expressions"])
        self.advance(15)
        self.manager._save({**self.manager.data, "affection": 99})
        self.manager.interact("touch", "hand")
        self.assertEqual(self.manager.snapshot()["affection"], 100)
        self.assertEqual(self.manager.mood, "fond")
        self.manager.interact("chat")
        self.assertEqual(self.manager.snapshot()["affection"], 100)

    def test_save_failure_preserves_disk_and_memory_and_does_not_break_interaction(self):
        self.manager.configure(False)
        original = self.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("locked")):
            self.manager.interact("chat")
            with self.assertRaises(ValueError):
                self.manager.configure(True)
        self.assertEqual(self.manager.snapshot()["affection"], 30)
        self.assertFalse(self.manager.snapshot()["auto_expression"])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn("保存失败", self.manager.error)
        self.manager.configure(True)
        self.assertIsNone(self.manager.error)

    def test_corrupt_file_backup_and_invalid_values(self):
        for value in ("invalid json", json.dumps({"version": 1}), json.dumps({**self.manager.data, "affection": 999})):
            self.path.write_text(value, encoding="utf-8")
            restored = self.make_manager()
            self.assertEqual(self.path.read_text(encoding="utf-8"), value)
            self.assertIsNotNone(restored.error)
            restored.interact("chat")
            backups = list(self.path.parent.glob("mood-invalid-*.json"))
            self.assertTrue(any(p.read_text(encoding="utf-8") == value for p in backups))
            restored.close()
        original = dict(self.manager.data)
        with self.assertRaises(ValueError):
            self.manager.configure(1)
        with self.assertRaises(ValueError):
            self.manager.interact("touch", "unknown")
        self.assertEqual(self.manager.data, original)
