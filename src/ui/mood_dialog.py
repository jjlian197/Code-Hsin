"""心情与好感度面板，独立于角色穿透和可见性。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QLabel, QProgressBar, QVBoxLayout


class MoodDialog(QDialog):
    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Window)
        self.manager = owner.mood
        self.setWindowTitle("心 · 心情与好感度")
        self.setWindowIcon(owner.windowIcon())
        self.setMinimumWidth(380)
        self.setStyleSheet("QDialog { background: #fff7f3; } QLabel,QCheckBox { color: #50373b; }"
                           "QProgressBar { color: #50373b; background: #f3e4de; border: 1px solid #c59da2; border-radius: 6px; text-align: center; min-height: 24px; }"
                           "QProgressBar::chunk { background: #e6b2bc; border-radius: 5px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self.mood_label = QLabel()
        self.mood_label.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(self.mood_label)
        self.tier_label = QLabel()
        layout.addWidget(self.tier_label)
        self.affection_bar = QProgressBar()
        self.affection_bar.setRange(0, 100)
        layout.addWidget(self.affection_bar)
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.unlocked_label = QLabel()
        self.unlocked_label.setWordWrap(True)
        layout.addWidget(self.unlocked_label)
        self.event_label = QLabel()
        layout.addWidget(self.event_label)
        self.auto_expression = QCheckBox("让心情自然影响表情")
        self.auto_expression.clicked.connect(self.configure)
        layout.addWidget(self.auto_expression)
        hint = QLabel("轻触 +1（间隔 15 秒），成功对话 +2（间隔 60 秒），\n完成专注 +3（间隔 60 秒），每天最多增加 20 点。\n离开电脑与退出不会扣好感度；关闭此面板仍会记录。\n手动表情与动作优先，选择“平常”恢复自动情绪。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.manager.changed.connect(self.refresh)
        self.refresh()

    def configure(self, enabled):
        try:
            self.manager.configure(enabled)
        except ValueError:
            self.refresh()

    def refresh(self):
        from src.core.sprite_window import EXPRESSION_LABELS
        value = self.manager.snapshot()
        self.mood_label.setText("此刻的心情 · " + value["label"])
        self.tier_label.setText("与你的关系 · " + value["tier"])
        self.affection_bar.setValue(value["affection"])
        self.affection_bar.setFormat("好感度 %v / 100")
        next_stage = f"距离下一阶段还差 {value['next_threshold'] - value['affection']} 点。" if value["next_threshold"] is not None else "已经心意相通，继续一起积累日常。"
        self.progress_label.setText(f"{next_stage}\n今天已增加 {value['earned_today']} / {value['daily_limit']} 点。")
        self.unlocked_label.setText("已解锁的自动表情：" + "、".join(EXPRESSION_LABELS.get(key, key) for key in value["unlocked_expressions"]))
        self.event_label.setText("最近互动：" + (value["last_event"] or "今天的陪伴刚刚开始"))
        self.auto_expression.setChecked(value["auto_expression"])
        self.error_label.setText(value["error"] or "好感度与设置保存在本项目中，重启后保留。")

    def open_near(self, owner):
        area = owner.screen().availableGeometry()
        self.adjustSize()
        self.move(max(area.left(), min(owner.x() - self.width() - 12, area.right() - self.width() + 1)),
                  max(area.top(), min(owner.y(), area.bottom() - self.height() + 1)))
        self.show()
        self.raise_()
        self.activateWindow()
