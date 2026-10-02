"""在原生 Qt/WebGL 中加载双形态，验证透明画面、表情、切换和真实 WS 控制。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import math
import struct
import traceback
from pathlib import Path

import websockets
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage

from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow


def main():
    print("开始原生 PMX 验证", flush=True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_pmx"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["sprite"]["renderer"] = "pmx"
    # 透明像素与 VMD 关键帧检查固定中性姿态；自然反应另有原生验证。
    config["sprite"]["animation"]["behavior"] = {"auto_blink": False, "breathing": False, "mouse_follow": False, "touch_reactions": True}
    config["websocket"]["port"] = 0
    config["http"]["port"] = 0
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    # 三帧头部旋转的测试 VMD，验证真实文件解析，不依赖外部舞蹈素材。
    vmd = project_path(".runtime/test-nod.vmd")
    vmd.parent.mkdir(exist_ok=True)
    raw = bytearray(b"Vocaloid Motion Data 0002".ljust(30, b"\0") + b"Hsin".ljust(20, b"\0"))
    raw += struct.pack("<I", 3)
    for frame, angle in ((0, 0), (15, 0.20), (30, 0)):
        raw += "頭".encode("shift_jis").ljust(15, b"\0")
        raw += struct.pack("<I3f4f", frame, 0, 0, 0, math.sin(angle/2), 0, 0, math.cos(angle/2))
        raw += bytes(([20] * 8 + [107] * 8) * 4)
    raw += struct.pack("<6I", 0, 0, 0, 0, 0, 0)
    vmd.write_bytes(raw)
    config["sprite"]["animation"]["vmd"] = {"test_vmd": [str(vmd)]}
    window = HsinSpriteWindow(config)
    print("验证窗口已创建", flush=True)
    bridge = ControlBridge(window)
    services = ControlServices(bridge, config)
    services.start()
    window.show_sprite()
    output = project_path(".runtime")
    output.mkdir(exist_ok=True)
    failures, results = [], []
    pool = ThreadPoolExecutor(1)
    phase = "first"

    def check_frame(name):
        pixmap = window.grab()
        pixmap.save(str(output / f"pmx-{name}-preview.png"))
        image = pixmap.toImage()
        assert image.pixelColor(0, 0).alpha() == 0, "背景必须真实透明"
        visible = sum(image.pixelColor(x, y).alpha() > 100
                      for x in range(0, image.width(), 8) for y in range(0, image.height(), 8))
        assert visible > image.width() * image.height() / 64 * 0.15, "画面不能为空"
        colors = {image.pixelColor(x, y).rgba() for x in range(0, image.width(), 16)
                  for y in range(0, image.height(), 16)}
        assert len(colors) > 100, "必须实际绘制贴图模型"
        assert image.pixelColor(image.width()//2, round(image.height()*0.22)).alpha() == 255, "脸部不能透出桌面背景"

    async def switch_over_ws():
        async with websockets.connect(services.endpoints()["websocket"]) as ws:
            async def command(kind, data=None):
                await ws.send(json.dumps({"type":kind,"data":data or {}}))
                return json.loads(await ws.recv())
            status = (await command("get_status"))["data"]
            assert status["renderer"]["model_loaded"]
            assert status["renderer"]["info"]["texture_errors"] == 0
            info = status["renderer"]["info"]
            assert info["runtime"]["physics_steps"] > 0
            assert info["runtime"]["dynamic_bone_angle"] > 0.0001, "物理必须真正更新骨骼"
            assert all(m["opacity"] == 1 and not m["transparent"] for m in info["material_alpha"]["body_opacity"])
            assert (await command("expression", {"name":"happy"}))["success"]
            await asyncio.sleep(1)
            assert (await command("motion", {"group":"wave"}))["success"]
            await asyncio.sleep(1.0)
            state = (await command("get_status"))["data"]["renderer"]["info"]["runtime"]
            assert state["motion"] == "wave" and abs(state["right_arm_rotation"][2] - 0.67) > 0.2, f"挥手未更新骨骼：{state}"
            await asyncio.sleep(3.0)
            assert (await command("get_status"))["data"]["renderer"]["info"]["runtime"]["motion"] == "idle"
            assert (await command("motion", {"group":"nod"}))["success"]
            await asyncio.sleep(0.7)
            state = (await command("get_status"))["data"]["renderer"]["info"]["runtime"]
            assert state["motion"] == "nod" and abs(state["head_rotation"][0]) > 0.01
            assert (await command("motion", {"group":"idle"}))["success"]
            assert (await command("physics", {"action":"off"}))["success"]
            await asyncio.sleep(0.8)
            state = (await command("get_status"))["data"]["renderer"]["info"]["runtime"]
            steps = state["physics_steps"]
            assert state["physics_enabled"] is False
            await asyncio.sleep(0.8)
            assert (await command("get_status"))["data"]["renderer"]["info"]["runtime"]["physics_steps"] == steps
            assert (await command("physics", {"action":"on"}))["success"]
            assert (await command("physics", {"action":"reset"}))["success"]
            assert (await command("motion", {"group":"test_vmd"}))["success"]
            for attempt in range(30):
                await asyncio.sleep(0.1)
                info = (await command("get_status"))["data"]["renderer"]["info"]
                assert "motion_error" not in info, info.get("motion_error")
                if info["runtime"]["motion"] == "test_vmd" and abs(info["runtime"]["head_rotation"][0]) > 0.01:
                    break
            else:
                raise AssertionError(f"VMD 未推进：{info['runtime']}")
            await asyncio.sleep(1.2)
            assert (await command("get_status"))["data"]["renderer"]["info"]["runtime"]["motion"] == "idle"
            assert (await command("motion", {"group":"not_a_motion"}))["success"] is False
            assert (await command("model", {"form":"second"}))["type"] == "model_loading"

    def capture_and_continue():
        try:
            nonlocal phase
            check_frame(phase)
            results.append(bridge.dispatch({"type":"get_status"})["data"]["renderer"])
            if phase == "first":
                phase = "second"
                future = pool.submit(lambda: asyncio.run(switch_over_ws()))
                def capture_expression():
                    try:
                        assert window.sprite_view.current_expression == "happy"
                        check_frame("happy")
                        assert window.grab().toImage() != QImage(str(output / "pmx-first-preview.png")), "表情应改变实际画面"
                    except Exception as exc:
                        failures.append(str(exc))
                        app.quit()
                QTimer.singleShot(600, capture_expression)
                QTimer.singleShot(2400, lambda: window.grab().save(str(output / "pmx-wave-preview.png")))
                def watch_network():
                    if future.done():
                        try:
                            future.result()
                        except Exception as exc:
                            failures.append(traceback.format_exc())
                            app.quit()
                    else:
                        QTimer.singleShot(30, watch_network)
                watch_network()
            else:
                # 切换后表情重新归零，避免沿用另一形态的 morph 索引。
                assert window.sprite_view.current_expression == "normal"
                assert window.sprite_view.model_path.name == "心_二阶段.pmx"
                assert window.sprite_view.model_info["runtime"]["rigid_bodies"] > 0
                assert window.sprite_view.model_info["runtime"]["physics_steps"] > 0
                window.set_background("#462535")
                def check_background():
                    try:
                        pixmap = window.grab()
                        # 背景层原本就是圆角；在圆角内侧的空白区验证背景合成。
                        assert pixmap.toImage().pixelColor(60, 60).alpha() == 255, "背景控制必须在 WebGL 后生效"
                    except Exception as exc:
                        failures.append(str(exc))
                    app.quit()
                QTimer.singleShot(400, check_background)
        except Exception as exc:
            failures.append(str(exc))
            app.quit()

    def loaded(success):
        if not success:
            failures.append(window.sprite_view.load_error)
            app.quit()
        else:
            QTimer.singleShot(800, capture_and_continue)

    window.sprite_view.load_finished.connect(loaded)
    def timeout():
        failures.append("双形态验证超时")
        app.quit()
    QTimer.singleShot(90000, timeout)
    try:
        app.exec()
    finally:
        bridge.close()
        services.stop()
        window.cleanup()
        window.hide()
        window.deleteLater()
        app.processEvents()
        pool.shutdown(wait=True)
        temp.cleanup()
    (output / "pmx-validation.json").write_text(json.dumps({"success":not failures,
        "models":results,"failures":failures},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"success":not failures,"forms_checked":len(results),"failures":failures},ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
