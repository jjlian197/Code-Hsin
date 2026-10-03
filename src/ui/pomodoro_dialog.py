"""只提供番茄钟，关闭面板不会结束计时。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout,
                            QLabel, QPushButton, QSpinBox, QVBoxLayout)
from src.core.pomodoro import PHASES


class PomodoroDialog(QDialog):
    def __init__(self, owner):
        # 独立顶层窗口，角色穿透/隐藏时仍可操作。
        super().__init__(None, Qt.WindowType.Window)
        self.manager = owner.pomodoro
        self.setWindowTitle("心 · 番茄钟")
        self.setWindowIcon(owner.windowIcon())
        self.setMinimumWidth(360)
        # 显式设置子控件前景，避免 Windows 深色主题白字落在浅色面板上。
        self.setStyleSheet("QDialog { background: #fff7f3; }"
                           "QLabel, QCheckBox { color: #50373b; }"
                           "QPushButton { padding: 8px 12px; color: #50373b; background: #f7e6df; border: 1px solid #c59da2; border-radius: 6px; }"
                           "QPushButton:hover { background: #efd3cb; }"
                           "QPushButton:disabled { color: #a78e91; background: #f0e9e5; border-color: #d7c8c4; }"
                           "QSpinBox { padding: 4px; color: #50373b; background: #ffffff; border: 1px solid #c59da2; border-radius: 4px; }")
        layout = QVBoxLayout(self)
        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.phase_label)
        self.clock_label = QLabel()
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_label.setStyleSheet("font-size: 44px; font-weight: 600; padding: 10px;")
        layout.addWidget(self.clock_label)
        self.round_label = QLabel()
        layout.addWidget(self.round_label)
        row = QHBoxLayout()
        self.start_button = QPushButton()
        self.start_button.clicked.connect(lambda: self._run(self.manager.start))
        row.addWidget(self.start_button)
        self.pause_button = QPushButton()
        self.pause_button.clicked.connect(self._pause)
        row.addWidget(self.pause_button)
        self.reset_button = QPushButton("重置本轮")
        self.reset_button.clicked.connect(self.manager.reset)
        row.addWidget(self.reset_button)
        layout.addLayout(row)
        form = QFormLayout()
        self.inputs = {}
        for key, label, upper in (("focus_minutes", "专注（分钟）", 180),
                                   ("short_break_minutes", "短休息（分钟）", 180),
                                   ("long_break_minutes", "长休息（分钟）", 180),
                                   ("long_break_every", "每几轮专注后长休息", 12)):
            widget = QSpinBox()
            widget.setRange(1, upper)
            self.inputs[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        self.sound = QCheckBox("到时播放提示音")
        layout.addWidget(self.sound)
        save = QPushButton("保存设置（下一轮生效）")
        save.clicked.connect(self._save)
        layout.addWidget(save)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        hint = QLabel("到时提醒后，手动开始下一阶段。\n关闭面板或隐藏心会继续计时；退出程序结束本次计时。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._settings = None
        self.manager.changed.connect(self.refresh)
        self.refresh()

    def _run(self, action):
        try:
            action()
            self.notice.clear()
        except ValueError as exc:
            self.notice.setText(str(exc))

    def _pause(self):
        self._run(self.manager.resume if self.manager.state == "paused" else self.manager.pause)

    def _save(self):
        self._run(lambda: self.manager.configure(**{key: widget.value() for key, widget in self.inputs.items()}, sound=self.sound.isChecked()))
        if not self.notice.text():
            self.notice.setText("设置已保存。正在计时的本轮时长保持不变。")

    def refresh(self):
        value = self.manager.snapshot()
        state = value["state"]
        self.phase_label.setText(value["label"] + {"idle": " · 准备开始", "running": " · 进行中", "paused": " · 已暂停", "completed": " · 已完成"}[state])
        seconds = value["remaining_seconds"]
        self.clock_label.setText(f"{seconds // 60:02d}:{seconds % 60:02d}")
        self.round_label.setText(f"本次启动已完成 {value['completed_focus']} 轮专注")
        self.start_button.setText("开始" + PHASES[value["next_phase"]])
        self.start_button.setEnabled(state in {"idle", "completed"})
        self.pause_button.setText("继续" if state == "paused" else "暂停")
        self.pause_button.setEnabled(state in {"running", "paused"})
        if value["settings"] != self._settings:
            self._settings = value["settings"]
            for key, widget in self.inputs.items():
                widget.setValue(self._settings[key])
            self.sound.setChecked(self._settings["sound"])

    def open_near(self, owner):
        area = owner.screen().availableGeometry()
        self.adjustSize()
        self.move(max(area.left(), min(owner.x() - self.width() - 12, area.right() - self.width() + 1)),
                  max(area.top(), min(owner.y(), area.bottom() - self.height() + 1)))
        self.show()
        self.raise_()
        self.activateWindow()
