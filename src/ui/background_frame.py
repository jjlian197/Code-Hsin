"""从 aemeath-spirit 提取的透明窗口背景层，保留原有绘制方式。"""
from pathlib import Path
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPainterPath, QLinearGradient, QColor, QPixmap


class BackgroundFrame(QFrame):
    """Custom-painted background frame to avoid QSS/GL composition issues."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_type = "transparent"
        self._image_path = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)

    def set_background(self, bg_type: str):
        self._bg_type = bg_type
        self._image_path = None
        if bg_type.startswith("image:"):
            p = Path(bg_type[6:]).expanduser().resolve()
            if p.exists():
                self._image_path = str(p)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect.adjusted(0, 0, -1, -1)), 20, 20)
        painter.setClipPath(path)

        if self._bg_type == "transparent":
            return

        if self._bg_type == "purple":
            grad = QLinearGradient(0, 0, rect.width(), rect.height())
            grad.setColorAt(0.0, QColor("#667eea"))
            grad.setColorAt(1.0, QColor("#764ba2"))
            painter.fillRect(rect, grad)
            return

        if self._image_path:
            pix = QPixmap(self._image_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    rect.size(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawPixmap(rect.topLeft(), scaled)
                return

        color = QColor(self._bg_type)
        if color.isValid():
            painter.fillRect(rect, color)
