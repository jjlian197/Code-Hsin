"""在原生 Qt/WebGL 中验证双形态自然反应、实际点击和音频驱动口型。"""
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import QObject, QPoint, QPointF, QEvent, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCursor, QMouseEvent
from PyQt6.QtWidgets import QApplication
import websockets

from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow


class GuiProbe(QObject):
    requested = pyqtSignal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.requested.connect(self._apply, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object, object)
    def _apply(self, function, future):
        try:
            function(future)
        except Exception as exc:
            future.set_exception(exc)

    async def call(self, function):
        future = Future()
        self.requested.emit(function, future)
        return await asyncio.wait_for(asyncio.wrap_future(future), 8)

    async def evaluate(self, source):
        return await self.call(lambda future: self.window.sprite_view.web.page().runJavaScript(source, future.set_result))

    async def state(self):
        value = await self.evaluate("JSON.stringify(window.HsinPmx.snapshot());")
        return json.loads(value) if value else None

    async def capture(self, name):
        def capture(future):
            path = project_path(f".runtime/behavior-{name}.png")
            pixmap = self.window.grab()
            assert pixmap.toImage().pixelColor(0, 0).alpha() == 0
            assert pixmap.save(str(path))
            future.set_result(str(path))
        return await self.call(capture)

    async def click_face(self):
        def click(future):
            window = self.window
            anchor = window.sprite_view.model_info["runtime"]["interaction"]["face"]
            view = window.sprite_view
            local = QPoint(round(anchor["x"] * view.width()), round(anchor["y"] * view.height()))
            global_pos = view.mapToGlobal(local)
            for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                event = QMouseEvent(kind, QPointF(local), QPointF(global_pos), Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(view, event)
            future.set_result(None)
        await self.call(click)


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_behavior"])
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
    touches = []
    window.touch_event.connect(lambda action, part: touches.append((action, part)))
    original_cursor = QCursor.pos()
    area = window.screen().availableGeometry()
    window.move(area.center() - QPoint(window.width() // 2, window.height() // 2))
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    result = {"success": False, "forms": [], "failures": []}

    async def verify():
        async with websockets.connect(services.endpoints()["websocket"]) as ws:
            async def command(kind, data=None):
                await ws.send(json.dumps({"type": kind, "data": data or {}}))
                response = json.loads(await ws.recv())
                assert response["success"], response
                return response

            async def wait_loaded():
                for _ in range(450):
                    status = (await command("get_status"))["data"]
                    if status["renderer"]["model_loaded"]:
                        state = await probe.state()
                        if state and state["frames"] > 3:
                            return status
                    if status["renderer"]["error"]:
                        raise AssertionError(status["renderer"]["error"])
                    await asyncio.sleep(0.1)
                raise AssertionError("模型加载超时")

            for form in ("first", "second"):
                if form == "second":
                    await command("model", {"form": form})
                await wait_loaded()
                await command("behavior", {"mouse_follow": False, "breathing": True, "auto_blink": True, "reset_parameters": True})
                peak = 0
                breaths = []
                torso_heights = []
                for _ in range(100):
                    state = await probe.state()
                    peak = max(peak, state["behavior"]["morphs"]["まばたき"])
                    breaths.append(state["behavior"]["breath"])
                    torso_heights.append(state["torso_position"][1])
                    await asyncio.sleep(0.07)
                assert peak > 0.4, "实际窗口没有自然眨眼"
                assert max(breaths) - min(breaths) > 1, "呼吸没有推进"
                assert max(torso_heights)-min(torso_heights)>0.05, "实际上半身没有呼吸起伏"
                await command("behavior", {"auto_blink": False, "breathing": False})
                await command("look_at", {"x": 0.8, "y": 0.6})
                await asyncio.sleep(0.5)
                state = await probe.state()
                assert state["head_rotation"][1] > 0.15, state
                assert state["head_rotation"][0] < -0.03
                assert state["behavior"]["morphs"]["Left"] > 0.3
                await probe.capture(form + "-look-right")
                await command("look_at", {"x": -0.8, "y": 0})
                await asyncio.sleep(0.5)
                assert (await probe.state())["head_rotation"][1] < -0.15

                await command("behavior", {"mouse_follow": True, "reset_parameters": True})
                # 单帧核对实际采样，避免用户同时移动鼠标导致长时间等待指定位置。
                await probe.call(lambda future: (window.sprite_view.frame_timer.stop(), future.set_result(None)))
                await probe.state()  # 等已发送帧完成，再测这一帧。
                for sign in (1, -1):
                    def move_cursor(future, direction=sign):
                        view = window.sprite_view
                        face = view.model_info["runtime"]["interaction"]["face"]
                        point = view.mapToGlobal(QPoint(round(view.width()*face["x"]) + direction*220, round(view.height()*face["y"])))
                        QCursor.setPos(point)
                        actual = view.mapFromGlobal(QCursor.pos())
                        expected = {"x": max(-1, min(1, (actual.x()/view.width()-face["x"])/1.5)),
                                    "y": max(-1, min(1, (face["y"]-actual.y()/view.height())/0.9))}
                        view._advance_frame()
                        future.set_result(expected)
                    expected = await probe.call(move_cursor)
                    state = await probe.state()
                    assert abs(state["behavior"]["pointer"]["x"]-expected["x"]) < 0.02, f"系统鼠标采样未送到视线层：{state}"
                    assert abs(state["behavior"]["pointer"]["y"]-expected["y"]) < 0.02
                await probe.call(lambda future: (window.sprite_view.frame_timer.start(), future.set_result(None)))
                await command("behavior", {"mouse_follow": False, "reset_parameters": True})
                await asyncio.sleep(0.5)
                await command("expression", {"name": "happy"})
                await command("parameter_batch", {"params": {"ParamMouthOpenY": 1, "ParamEyeLOpen": 0, "ParamEyeROpen": 0}})
                await asyncio.sleep(0.4)
                state = await probe.state()
                assert state["behavior"]["morphs"]["あ"] > 0.75
                assert state["behavior"]["morphs"]["まばたき"] > 0.95
                assert state["behavior"]["morphs"]["にこり"] > 0.6, "口型覆盖了开心表情"
                await probe.capture(form + "-blink-mouth")
                await ws.send(json.dumps({"type": "parameter_batch", "data": {"params": {"ParamMouthOpenY": 0, "invalid": 1}}}))
                assert not json.loads(await ws.recv())["success"]
                assert (await probe.state())["behavior"]["parameters"]["ParamMouthOpenY"] == 1, "错误批次不应部分应用"
                await command("behavior", {"reset_parameters": True})
                await command("expression", {"name": "normal"})
                await asyncio.sleep(0.6)
                assert (await probe.state())["behavior"]["mouth_open"] < 0.01
                await probe.capture(form + "-neutral")

                await command("lip_sync", {"value": 0.9, "shape": "o", "duration": 900})
                await asyncio.sleep(0.35)
                assert (await probe.state())["behavior"]["morphs"]["お"] > 0.6
                await asyncio.sleep(1.0)
                assert (await probe.state())["behavior"]["mouth_open"] < 0.01

                before = len(touches)
                await probe.click_face()
                await asyncio.sleep(0.5)
                assert len(touches) == before + 1 and touches[-1] == ("tap", "头部"), touches
                assert (await probe.state())["behavior"]["last_touch"]["part"] == "head"
                await probe.capture(form + "-touch")
                await asyncio.sleep(1.5)
                assert not (await probe.state())["behavior"]["touch_active"]
                # 空白处不能触发触摸。
                assert await probe.evaluate("window.HsinPmx.touchAt(0.01,0.01)") is None

                await command("audio", {"action": "play", "path": "voice/hsin_ja/wav32k/Hsin_JA_1311129.wav", "volume": 0})
                mouth_peak = 0
                for _ in range(65):
                    state = await probe.state()
                    mouth_peak = max(mouth_peak, state["behavior"]["mouth_open"])
                    await asyncio.sleep(0.05)
                audio = (await command("get_status"))["data"]["audio"]
                assert not audio["error"], audio
                assert audio["buffer_count"] > 0 and audio["peak_level"] > 0.1, audio
                assert mouth_peak > 0.1, "真实音频没有驱动实际口型"
                assert (await probe.state())["behavior"]["mouth_open"] < 0.02, "原声结束后嘴应闭合"
                await command("audio", {"action": "stop"})

                await command("physics", {"action": "off"})
                await command("look_at", {"x": 0.6, "y": 0})
                await command("behavior", {"mouse_follow": True})
                await command("look_at", {"x": 0.6, "y": 0})
                await asyncio.sleep(0.5)
                assert (await probe.state())["head_rotation"][1] > 0.1, "关闭物理后头部仍须跟随"
                await command("physics", {"action": "on"})
                await command("behavior", {"auto_blink": True, "breathing": True, "mouse_follow": True, "reset_parameters": True})
                await command("window", {"action": "hide"})
                await asyncio.sleep(0.4)
                frames = (await probe.state())["frames"]
                await asyncio.sleep(0.4)
                assert (await probe.state())["frames"] == frames
                await command("window", {"action": "show"})
                await asyncio.sleep(0.4)
                assert (await probe.state())["frames"] > frames
                result["forms"].append({"form": form, "blink_peak": peak, "mouth_peak_from_audio": mouth_peak,
                    "audio_buffers": audio["buffer_count"], "touch": touches[-1], "final_runtime": await probe.state()})
                print("PASS:", form, "自然反应、系统鼠标、实际触摸与 PCM 口型", flush=True)
        result["success"] = True

    future = pool.submit(lambda: asyncio.run(verify()))
    def watch():
        if future.done():
            try:
                future.result()
            except Exception:
                result["failures"].append(traceback.format_exc())
            app.quit()
        else:
            QTimer.singleShot(30, watch)
    watch()
    QTimer.singleShot(180000, app.quit)
    try:
        app.exec()
    finally:
        bridge.close()
        services.stop()
        window.cleanup()
        window.hide()
        QCursor.setPos(original_cursor)
        pool.shutdown(wait=True)
        temp.cleanup()
    project_path(".runtime/behavior-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": result["success"], "forms_checked": len(result["forms"]), "failures": result["failures"]}, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
