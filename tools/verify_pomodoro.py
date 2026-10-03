"""原生窗口验证番茄钟双形态与独立面板；模拟时间，不联网、不开麦。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication
from aiohttp import ClientSession

from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_pomodoro"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["websocket"]["port"] = config["http"]["port"] = 0
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    bridge = ControlBridge(window)
    services = ControlServices(bridge, config)
    services.start()
    probe = GuiProbe(window)
    now = [100.0]
    window.pomodoro.clock = lambda: now[0]
    window.pomodoro.configure(sound=False)
    notices = []
    window.pomodoro.finished.connect(notices.append)
    area = window.screen().availableGeometry()
    window.move(area.center() - QPoint(window.width() // 2, window.height() // 2))
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    result = {"success": False, "forms": [], "failures": []}

    async def gui(function):
        return await probe.call(lambda future: future.set_result(function()))

    async def verify():
        async with ClientSession() as session:
            async def command(kind, data):
                async with session.post(services.endpoints()["http"] + "/api/" + kind, json=data) as response:
                    value = await response.json()
                    assert value["success"], value
                    return value["data"]

            for form in ("first", "second"):
                if form == "second":
                    await command("model", {"form": form})
                for _ in range(500):
                    loaded = await gui(lambda: window.sprite_view.model_loaded and "head_top" in window.sprite_view.model_info.get("runtime", {}).get("interaction", {}))
                    if loaded:
                        break
                    await asyncio.sleep(.1)
                assert loaded, "模型或头部投影加载超时"
                await command("pomodoro", {"action": "reset"})
                await command("pomodoro", {"action": "start"})
                await asyncio.sleep(.3)

                def capture():
                    overlay = window.pomodoro_overlay
                    assert overlay.isVisible()
                    assert area.contains(overlay.geometry())
                    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
                    bounds = window.geometry().united(overlay.geometry())
                    image = QPixmap(bounds.size())
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    painter.drawPixmap(window.pos() - bounds.topLeft(), window.grab())
                    painter.drawPixmap(overlay.pos() - bounds.topLeft(), overlay.grab())
                    painter.end()
                    path = project_path(f".runtime/pomodoro-{form}.png")
                    assert image.save(str(path))
                    return {"form": form, "preview": str(path), "badge": overlay.text(),
                            "head_top": window.sprite_view.model_info["runtime"]["interaction"]["head_top"]}
                result["forms"].append(await gui(capture))

            await command("pomodoro", {"action": "open"})
            await command("pomodoro", {"action": "pause"})
            await asyncio.sleep(.1)
            await gui(lambda: window.pomodoro_dialog.grab().save(str(project_path(".runtime/pomodoro-panel.png"))))
            await gui(window.pomodoro_dialog.close)
            await command("window", {"action": "click_through", "enabled": True})
            await command("window", {"action": "hide"})
            await command("pomodoro", {"action": "open"})
            assert await gui(lambda: window.pomodoro_dialog.isVisible() and not window.pomodoro_overlay.isVisible())
            await gui(lambda: now.__setitem__(0, now[0] + 10000))
            state = await command("pomodoro", {"action": "status"})
            assert state["state"] == "paused" and state["remaining_seconds"] == 1500
            await command("pomodoro", {"action": "resume"})
            await gui(window.pomodoro_dialog.close)
            await gui(lambda: now.__setitem__(0, now[0] + 1500))
            state = await command("pomodoro", {"action": "status"})
            assert state["state"] == "completed" and state["completed_focus"] == 1
            assert await gui(lambda: len(notices) == 1 and not window.bubble_widget.isVisible())
            await command("pomodoro", {"action": "status"})
            assert len(notices) == 1
            await command("window", {"action": "show"})
            await command("pomodoro", {"action": "start"})
            await gui(lambda: now.__setitem__(0, now[0] + 300))
            state = await command("pomodoro", {"action": "status"})
            assert state["phase"] == "short_break" and state["next_phase"] == "focus"
            assert await gui(lambda: window.bubble_widget.isVisible() and len(notices) == 2)
            result.update(success=True, completed_focus=state["completed_focus"], notifications=len(notices),
                          paused_time_preserved=True, hidden_completion=True, panel_click_through=True)

    async def run():
        try:
            await verify()
        except Exception:
            result["failures"].append(traceback.format_exc())
        finally:
            await gui(app.quit)

    def launch():
        pool.submit(asyncio.run, run())
    QTimer.singleShot(0, launch)
    QTimer.singleShot(120000, app.quit)
    app.exec()
    bridge.close()
    services.stop()
    window.cleanup()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/pomodoro-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
