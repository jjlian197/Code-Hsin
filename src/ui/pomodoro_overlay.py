"""无焦点、可穿透的倒计时徽标，沿用 Aemeath 的头顶浮层交互。"""
from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QLabel


class PomodoroOverlay(QLabel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("QLabel { color: #fff8f4; padding: 8px 14px; font-weight: 600; }")
        self.poll = QTimer(self)
        self.poll.setInterval(150)
        self.poll.timeout.connect(self.reposition)
        self.owner.installEventFilter(self)
        self.owner.pomodoro.changed.connect(self.refresh)
        self.refresh()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#704650"))
        painter.setPen(QPen(QColor("#ebbd9c"), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.end()
        super().paintEvent(event)

    def refresh(self):
        value = self.owner.pomodoro.snapshot()
        active = value["state"] in {"running", "paused"}
        if not active:
            self.poll.stop()
            self.hide()
            return
        seconds = value["remaining_seconds"]
        text = f"{value['label']}{' · 已暂停' if value['state'] == 'paused' else ''}  {seconds // 60:02d}:{seconds % 60:02d}"
        if text != self.text():
            self.setText(text)
            self.adjustSize()
        self.poll.start()
        self.reposition()

    def reposition(self):
        if not self.poll.isActive() or not self.owner.isVisible() or self.owner.isMinimized():
            self.hide()
            return
        view = self.owner.sprite_view
        anchor = getattr(view, "model_info", {}).get("runtime", {}).get("interaction", {}).get("head_top", {"x": .5, "y": .08})
        point = view.mapToGlobal(QPoint(round(anchor["x"] * view.width()), round(anchor["y"] * view.height())))
        area = self.owner.screen().availableGeometry()
        x = max(area.left(), min(point.x() - self.width() // 2, area.right() - self.width() + 1))
        y = max(area.top(), min(point.y() - self.height() - 8, area.bottom() - self.height() + 1))
        # 气泡优先；提示出现时暂时隐藏徽标，计时仍在服务层继续。
        if self.owner.bubble_widget.isVisible() and self.owner.bubble_widget.geometry().intersects(self.geometry().translated(x - self.x(), y - self.y())):
            self.hide()
            return
        self.move(x, y)
        self.setWindowOpacity(self.owner.windowOpacity())
        flags = self.windowFlags()
        top = bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if top != self.owner._always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.owner._always_on_top)
        self.show()

    def eventFilter(self, watched, event):
        if watched is self.owner:
            if event.type() in {QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.WindowStateChange}:
                self.reposition()
            elif event.type() == QEvent.Type.Hide:
                self.hide()
        return super().eventFilter(watched, event)

    def cleanup(self):
        self.poll.stop()
        self.owner.removeEventFilter(self)
        self.close()
