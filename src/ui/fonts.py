"""离屏环境也加载本机字体，避免中文预览出现方框。"""
import os
from pathlib import Path
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication


def ensure_fonts():
    if not QFontDatabase.families() and os.name == "nt":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "segoeui.ttf"):
            path = fonts / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        if "Microsoft YaHei UI" in QFontDatabase.families():
            QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))
