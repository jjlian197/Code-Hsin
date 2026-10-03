"""心的情绪与长期好感度：互动驱动，离线不扣分，增长节流并本地保存。"""
from datetime import date, datetime
import json
import math
from pathlib import Path
import time
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MOODS = {"calm": ("从容", "normal"), "happy": ("开心", "happy"),
         "content": ("欢欣", "content"),
         "relaxed": ("安心", "relaxed"), "shy": ("害羞", "blush"),
         "fond": ("亲近", "heart_eyes"), "surprised": ("惊讶", "surprised"),
         "lonely": ("想念", "sad"), "tired": ("困倦", "sleepy")}
TIERS = ((0, "相识", ("normal", "relaxed", "surprised", "sad", "sleepy")),
         (30, "相伴", ("happy",)), (60, "信赖", ("blush", "content")),
         (80, "心意相通", ("heart_eyes",)))
REWARDS = {"touch": (1, 15), "chat": (2, 60), "focus": (3, 60)}
EVENT_LABELS = {"head": "轻触头部", "chest": "轻触胸部", "body": "轻触身体", "hand": "轻触手部", "tail": "轻触尾巴",
                "chat": "完成对话", "focus": "完成专注"}
DAILY_LIMIT = 20


class MoodManager(QObject):
    changed = pyqtSignal()

    def __init__(self, state_path, parent=None, clock=time.monotonic, wall_clock=time.time):
        super().__init__(parent)
        self.path = Path(state_path)
        self.clock, self.wall_clock = clock, wall_clock
        self.data = {"version": 1, "affection": 30, "auto_expression": True,
                     "reward_day": self._today(), "earned_today": 0, "last_rewards": {}}
        self.error = None
        self._invalid_file = False
        try:
            self.data = self._validate(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self._invalid_file = True
            self.error = "状态文件无法读取，暂用初始值；下次保存会先保留原文件备份。"
        self.mood = "calm"
        self.until = 0
        self.last_interaction = self.clock()
        self.last_event = None
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        # 活动状态由窗口采样，避免专注/对话时误判成长期闲置。

    def _today(self):
        return datetime.fromtimestamp(self.wall_clock()).date().isoformat()

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1:
            raise ValueError("状态版本无效")
        for key, low, high in (("affection", 0, 100), ("earned_today", 0, DAILY_LIMIT)):
            if type(value.get(key)) is not int or not low <= value[key] <= high:
                raise ValueError("状态数值无效")
        if type(value.get("auto_expression")) is not bool:
            raise ValueError("设置无效")
        if not isinstance(value.get("reward_day"), str):
            raise ValueError("日期无效")
        date.fromisoformat(value["reward_day"])
        rewards = value.get("last_rewards")
        if not isinstance(rewards, dict) or set(rewards) - set(REWARDS):
            raise ValueError("奖励记录无效")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rewards.values()):
            raise ValueError("奖励时间无效")
        return {key: value[key] for key in ("version", "affection", "auto_expression", "reward_day", "earned_today", "last_rewards")}

    def _save(self, proposed):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self._invalid_file and self.path.exists():
                backup = self.path.with_name(f"mood-invalid-{uuid.uuid4().hex}.json")
                backup.write_bytes(self.path.read_bytes())
                self._invalid_file = False
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(proposed, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        except OSError as exc:
            self.error = "好感度保存失败，原记录保留；请检查状态目录是否可写。"
            self.changed.emit()
            raise ValueError(self.error) from exc
        self.data = proposed
        self.error = None

    def snapshot(self):
        tier_index = max(i for i, (threshold, _, _) in enumerate(TIERS) if self.data["affection"] >= threshold)
        unlocks = [expression for _, _, values in TIERS[:tier_index + 1] for expression in values]
        next_threshold = TIERS[tier_index + 1][0] if tier_index < len(TIERS) - 1 else None
        return {"mood": self.mood, "label": MOODS[self.mood][0], "expression": MOODS[self.mood][1],
                "affection": self.data["affection"], "tier": TIERS[tier_index][1], "tier_index": tier_index,
                "next_threshold": next_threshold, "unlocked_expressions": unlocks,
                "auto_expression": self.data["auto_expression"], "daily_limit": DAILY_LIMIT,
                "earned_today": 0 if self._today() > self.data["reward_day"] else self.data["earned_today"],
                "last_event": EVENT_LABELS.get(self.last_event), "error": self.error}

    def configure(self, auto_expression):
        if type(auto_expression) is not bool:
            raise ValueError("auto_expression 必须是布尔值")
        self._save({**self.data, "auto_expression": auto_expression})
        self.changed.emit()
        return self.snapshot()

    def interact(self, event, part=None):
        if event not in REWARDS or (event == "touch" and part not in {"head", "chest", "body", "hand", "tail"}):
            raise ValueError("未知互动")
        now = self.clock()
        self.last_interaction = now
        self.last_event = part if event == "touch" else event
        amount, interval = REWARDS[event]
        proposed = {**self.data, "last_rewards": dict(self.data["last_rewards"])}
        today = self._today()
        if today > proposed["reward_day"]:
            proposed.update(reward_day=today, earned_today=0)
        wall = self.wall_clock()
        if wall - proposed["last_rewards"].get(event, -interval) >= interval:
            gain = min(amount, DAILY_LIMIT - proposed["earned_today"], 100 - proposed["affection"])
            if gain > 0:
                proposed["affection"] += gain
                proposed["earned_today"] += gain
                proposed["last_rewards"][event] = wall
        if proposed != self.data:
            try:
                self._save(proposed)
            except ValueError:
                pass  # 保存错误可在菜单/面板查看，触摸或聊天继续正常工作。
        tier = self.snapshot()["tier_index"]
        if event == "touch":
            self.mood = "shy" if part == "chest" else "surprised" if part == "tail" else ("fond" if tier >= 3 and part == "hand" else "shy" if tier >= 2 and part == "head" else "relaxed")
        else:
            self.mood = "content" if event == "chat" and tier >= 2 else "happy" if event == "chat" and tier >= 1 else "relaxed"
        self.until = now + (12 if self.mood == "surprised" else 45)
        self.changed.emit()
        return self.snapshot()

    def tick(self, engaged=False):
        now = self.clock()
        if self._today() > self.data["reward_day"]:
            try:
                self._save({**self.data, "reward_day": self._today(), "earned_today": 0})
                self.changed.emit()
            except ValueError:
                pass
        if engaged:
            self.last_interaction = now
        idle = max(0, now - self.last_interaction)
        desired = "tired" if idle >= 3600 else "lonely" if idle >= 1800 else "calm"
        if now >= self.until and desired != self.mood:
            self.mood = desired
            self.changed.emit()

    def close(self):
        self.timer.stop()
