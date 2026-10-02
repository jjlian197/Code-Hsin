"""使用用户提供的心头像作为应用、窗口和托盘图标。"""
from PyQt6.QtGui import QIcon
from src.core.app_config import project_path


def create_icon():
    return QIcon(str(project_path("src/assets/icons/hsin.png")))
