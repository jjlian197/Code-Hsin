#!/usr/bin/env python3
"""
心的浮动气泡，迁移自 aemeath-spirit 的 BubbleWidget。
"""

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor


class BubbleWidget(QWidget):
    """Floating message bubble"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_ui()
        self._setup_style()
        
        # Timer for auto-hide
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
    
    def _setup_ui(self):
        """Setup UI components"""
        
        # Frameless, transparent window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 25)
        layout.setSpacing(0)
        
        # Message label
        self.message_label = QLabel(self)
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_label)
        
        # Default size
        self.setMinimumWidth(200)
        self.setMaximumWidth(350)
    
    def _setup_style(self):
        """Setup visual style"""
        
        # 保留参考项目的气泡绘制，使用心的暖色配色。
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(90, 51, 66, 245),
                    stop: 1 rgba(112, 70, 79, 245)
                );
                border-radius: 20px;
                border: 2px solid rgba(255, 255, 255, 200);
            }
            QLabel {
                background: transparent;
                border: none;
                color: white;
                font-size: 14px;
                font-weight: 500;
                padding: 5px;
            }
        """)
        
        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(70, 37, 53, 120))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
    
    def show_message(self, text: str, duration: int = 5000):
        """Show message bubble"""
        
        self.message_label.setText(text)
        self.adjustSize()
        
        # Position above the sprite window
        self.reposition()
        
        self.show()
        self.raise_()
        
        # Auto-hide after duration
        if duration > 0:
            self.hide_timer.start(duration)
        else:
            self.hide_timer.stop()
    
    def reposition(self):
        """随精灵移动，并约束在当前屏幕的可用区域内。"""
        if not self.parent():
            return
        parent_rect = self.parent().frameGeometry()
        area = self.parent().screen().availableGeometry()
        x = parent_rect.center().x() - self.width() // 2
        y = parent_rect.top() - self.height() + 8
        if y < area.top():
            y = parent_rect.top() + 8
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(x, y)
