"""透明的渲染接入口；当前仅显示心的项目标记，不冒充已加载的 PMX 模型。"""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class SpriteView(QWidget):
    """后续 PMX 视图只需实现同样的状态和控制方法即可接入窗口。"""
    renderer_name = "placeholder"
    model_loaded = False
    current_expression = "normal"

    def __init__(self, model_path=None, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def get_available_expressions(self):
        return []

    def set_expression(self, name):
        raise NotImplementedError("PMX 表情控制尚未接入")

    def trigger_motion(self, group, index=0):
        raise NotImplementedError("PMX 动作控制尚未接入")

    def set_parameter(self, param_id, value):
        raise NotImplementedError("PMX 参数控制尚未接入")

    def look_at(self, x, y):
        raise NotImplementedError("PMX 视线控制尚未接入")

    def cleanup(self):
        pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width() * 0.48, self.height() * 0.35, 180)
        cx, cy = self.width() / 2, self.height() * 0.62
        circle = QRectF(cx - size / 2, cy - size / 2, size, size)
        painter.setPen(QPen(QColor("#dfbf89"), 2))
        painter.setBrush(QColor(70, 37, 53, 235))
        painter.drawEllipse(circle)
        painter.setPen(QColor("#f6e9ce"))
        painter.setFont(QFont("Microsoft YaHei", max(20, int(size / 3))))
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "心")
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(QRectF(cx - size, cy + size / 2 + 14, size * 2, 28), Qt.AlignmentFlag.AlignCenter, "H S I N")
