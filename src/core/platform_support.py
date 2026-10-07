"""macOS 原生窗口策略；其他平台仍由 Qt 管理。"""
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


def configure_desktop_window(widget: "QWidget", *, always_on_top: bool) -> None:
    if sys.platform != "darwin":
        return
    from PyQt6.QtWidgets import QApplication

    if QApplication.platformName() != "cocoa":
        return
    import Cocoa
    import objc

    native_view = objc.objc_object(c_void_p=int(widget.winId()))
    native_window = native_view.window()
    if native_window is None:
        return
    # Qt 更改穿透/置顶标志时可重建 NSWindow，因此每次显示都重施策略。
    native_window.setHidesOnDeactivate_(False)
    native_window.setLevel_(Cocoa.NSFloatingWindowLevel if always_on_top else Cocoa.NSNormalWindowLevel)
    native_window.setCollectionBehavior_(
        Cocoa.NSWindowCollectionBehaviorCanJoinAllSpaces
        | Cocoa.NSWindowCollectionBehaviorFullScreenAuxiliary
    )
