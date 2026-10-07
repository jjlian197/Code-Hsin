"""真实 Cocoa 桌面窗口检查；不开语音、聊天、麦克风，不保存日常状态。"""
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback
from typing import Any

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication

from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("此检查需要 macOS 桌面会话")
    import Cocoa
    import objc

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_macos"])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName() != "cocoa":
        raise SystemExit("此检查必须使用真实 Cocoa 窗口，不能离屏运行")
    report: dict[str, Any] = {"success": False, "platform": platform.platform(), "checks": [], "failures": []}
    output = project_path(".runtime/macos-window-validation.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    def settle() -> None:
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    def native_window(window: HsinSpriteWindow) -> Any:
        return objc.objc_object(c_void_p=int(window.winId())).window()

    with tempfile.TemporaryDirectory() as runtime_dir:
        config = load_config()
        config["runtime"]["directory"] = runtime_dir
        config["_settings_path"] = str(Path(runtime_dir) / "config.local.yaml")
        config["sprite"]["renderer"] = "placeholder"
        config["voice"]["enabled"] = False
        config["chat"]["enabled"] = False
        window = HsinSpriteWindow(config)
        try:
            window.show_sprite()
            settle()
            assert window.tray_icon is not None and window.tray_icon.isVisible(), "菜单栏恢复入口不可用"
            assert not window.stt.snapshot()["enabled"], "检查不应开启麦克风"
            report["checks"].append("菜单栏入口存在，麦克风默认关闭")
            policy = native_window(window)
            assert not policy.hidesOnDeactivate(), "切换应用会隐藏角色"
            expected_spaces = (Cocoa.NSWindowCollectionBehaviorCanJoinAllSpaces
                               | Cocoa.NSWindowCollectionBehaviorFullScreenAuxiliary)
            assert policy.collectionBehavior() & expected_spaces == expected_spaces
            report["checks"].append("切换应用不隐藏，已设置跨 Spaces/全屏辅助策略")
            window.position_bottom_right()
            settle()
            original_position = QPoint(window.pos())
            for enabled in (True, False, True, False):
                window._click_through_action.trigger()
                settle()
                assert window.is_click_through is enabled
                assert native_window(window).ignoresMouseEvents() is enabled
                assert window.isVisible() and window.pos() == original_position
                assert not native_window(window).hidesOnDeactivate()
            report["checks"].append("共享菜单穿透开关与原生事件透传同步，重复恢复保持位置")
            for enabled in (False, True):
                window.set_always_on_top(enabled)
                settle()
                expected_level = Cocoa.NSFloatingWindowLevel if enabled else Cocoa.NSNormalWindowLevel
                assert native_window(window).level() == expected_level
                assert window.pos() == original_position
            report["checks"].append("置顶开关正确改变原生层级并保持位置")
            window.hide_sprite()
            window.set_click_through(True)
            settle()
            assert not window.isVisible(), "隐藏期间切换穿透不能意外显示"
            window._tray_menu.actions()[0].trigger()
            window.set_click_through(False)
            settle()
            assert window.isVisible()
            assert window.screen().availableGeometry().contains(window.geometry())
            report["checks"].append("菜单栏显示恢复和可用屏幕定位")
            report["device_pixel_ratio"] = window.devicePixelRatioF()
            report["success"] = True
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            window.cleanup()
            window.hide()
            window.deleteLater()
            app.processEvents()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
