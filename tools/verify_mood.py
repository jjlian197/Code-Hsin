"""原生双形态情绪检查；临时好感度、模拟对话与时间，不联网也不录音。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QApplication
from aiohttp import ClientSession

from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_mood"])
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
    now, wall = [100.0], [time.time()]
    window.mood.clock = lambda: now[0]
    window.mood.wall_clock = lambda: wall[0]
    window.mood.last_interaction = now[0]
    window.mood._save({**window.mood.data, "affection": 59})
    window._sync_mood()
    window.move(window.screen().availableGeometry().center() - QPoint(window.width() // 2, window.height() // 2))
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    result = {"success": False, "forms": [], "failures": []}

    async def gui(function):
        return await probe.call(lambda future: future.set_result(function()))

    async def wait_face(name, threshold=.2):
        for _ in range(100):
            state = await probe.state()
            if state["behavior"]["morphs"].get(name, 0) > threshold:
                return state
            await asyncio.sleep(.05)
        raise AssertionError(f"没有观察到情绪表情：{name}")

    async def advance(seconds):
        await gui(lambda: (now.__setitem__(0, now[0] + seconds), wall.__setitem__(0, wall[0] + seconds)))

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
                    loaded = await gui(lambda: window.sprite_view.model_loaded and "face" in window.sprite_view.model_info.get("runtime", {}).get("interaction", {}))
                    if loaded:
                        break
                    await asyncio.sleep(.1)
                assert loaded, "模型加载超时"
                await command("behavior", {"mouse_follow": False, "random_idle": False})
                await advance(16)
                await probe.click_face()
                state = await wait_face("FaceRed", .45)
                mood = await command("mood", {"action": "status"})
                assert mood["tier_index"] >= 2 and mood["mood"] == "shy"
                face = state["behavior"]["morphs"]["FaceRed"]
                await probe.capture("mood-" + form)
                await command("expression", {"name": "angry"})
                await asyncio.sleep(.3)
                manual = await probe.state()
                assert manual["behavior"]["morphs"]["FaceRed"] == 0
                assert manual["behavior"]["morphs"]["怒り"] > .6
                await command("expression", {"name": "normal"})
                await command("motion", {"group": "wave", "index": 0})
                await asyncio.sleep(.3)
                moving = await probe.state()
                assert moving["behavior"]["manual_motion"]
                assert moving["behavior"]["morphs"]["FaceRed"] == 0
                await command("motion", {"group": "idle", "index": 0})
                await wait_face("FaceRed", .4)
                await command("mood", {"action": "configure", "auto_expression": False})
                await asyncio.sleep(1.5)
                disabled = await probe.state()
                assert disabled["behavior"]["morphs"]["FaceRed"] < .01
                await command("mood", {"action": "configure", "auto_expression": True})
                result["forms"].append({"form": form, "affection": mood["affection"], "blush": face,
                                        "manual_priority": True, "disable_release": True})

            await gui(lambda: window.mood._save({**window.mood.data, "affection": 79}))
            await advance(16)
            await gui(lambda: window.touch_event.emit("tap", "手"))
            await wait_face("はぁと", .5)
            await gui(lambda: window.pomodoro.configure(sound=False))
            await command("mood", {"action": "open"})
            await gui(lambda: window.mood_dialog.grab().save(str(project_path(".runtime/mood-panel.png"))))
            await command("window", {"action": "click_through", "enabled": True})
            await command("window", {"action": "hide"})
            assert await gui(lambda: window.mood_dialog.isVisible())
            await gui(window.mood_dialog.close)
            await advance(3601)
            idle = await command("mood", {"action": "status"})
            assert idle["mood"] == "tired" and idle["affection"] == 80
            await command("pomodoro", {"action": "start"})
            active = await command("mood", {"action": "status"})
            assert active["mood"] == "calm" and active["affection"] == 80
            from src.core.mood import MoodManager
            def restore():
                restored = MoodManager(window.mood.path)
                value = restored.snapshot()
                restored.close()
                return value
            saved = await gui(restore)
            assert saved["affection"] == 80 and "heart_eyes" in saved["unlocked_expressions"]
            result.update(success=True, heart_unlock=True, persisted_affection=saved["affection"],
                          idle_without_penalty=True, focus_not_idle=True, independent_panel=True)

    async def run():
        try:
            await verify()
        except Exception:
            result["failures"].append(traceback.format_exc())
        finally:
            await gui(app.quit)

    QTimer.singleShot(0, lambda: pool.submit(asyncio.run, run()))
    QTimer.singleShot(120000, app.quit)
    app.exec()
    bridge.close()
    services.stop()
    window.cleanup()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/mood-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
