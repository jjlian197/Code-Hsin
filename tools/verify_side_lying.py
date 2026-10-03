"""原生双形态侧躺预览与保持/退出检查，使用本机 FBX 和临时状态。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from src.core.control_bridge import ControlBridge
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_side_lying"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    original_size = (window.width(), window.height())
    window.position_bottom_right()
    window.show_sprite()
    probe = GuiProbe(window)
    bridge = ControlBridge(window)
    pool = ThreadPoolExecutor(1)
    result = {"success": False, "forms": [], "failures": []}

    async def gui(function):
        return await probe.call(lambda future: future.set_result(function()))

    async def verify():
        for form in ("first", "second"):
            if form == "second":
                await gui(lambda: window.set_model_form(form))
            for _ in range(500):
                if await gui(lambda: window.sprite_view.model_loaded):
                    break
                await asyncio.sleep(.1)
            else:
                raise AssertionError("模型加载超时")
            initial = await probe.state()
            response = await bridge.execute({"type": "motion", "data": {"group": "side_lying"}})
            assert response["success"] and response["type"] == "motion_loading", response
            for _ in range(150):
                state = await probe.state()
                if state["motion"] == "side_lying":
                    break
                error = await gui(lambda: window.sprite_view.model_info.get("motion_error"))
                assert not error, error
                await asyncio.sleep(.1)
            assert state["motion"] == "side_lying"
            await asyncio.sleep(2)
            await probe.capture("side-lying-" + form)
            held = await probe.state()
            assert held["motion"] == "side_lying", "定格姿势不能一帧后结束"
            assert not held["physics_active"] and held["pose_profile"] == "stable_side"
            assert await gui(lambda: window.width() > window.height()), "侧躺成功后自动加宽窗口"
            await gui(lambda: window.sprite_view.trigger_motion("side_lying"))
            await asyncio.sleep(.5)
            assert (await probe.state())["motion"] == "side_lying", "重复动作保持同一姿势"
            await gui(window.sprite_view.reset_physics)
            await asyncio.sleep(.5)
            assert not (await probe.state())["physics_active"], "重置物理不能扰动定格衣裙"
            frames = []
            for width, height in [(900, 420), (600, 280), (400, 600), (1100, 500)]:
                await gui(lambda w=width, h=height: window.set_size(w, h))
                await asyncio.sleep(.3)
                framing = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))
                assert framing["fully_visible"], framing
                assert min(framing["left"], framing["top"], 1-framing["right"], 1-framing["bottom"]) > .025, framing
                frames.append(framing)
            await gui(lambda: window.set_size(900, 420))
            await asyncio.sleep(.5)
            await probe.click_face()
            await asyncio.sleep(.15)
            assert (await probe.state())["behavior"]["last_touch"]["part"] == "head", "侧躺仍能摸头"
            await gui(lambda: window.sprite_view.set_lip_sync(.8, "a", 1500))
            await asyncio.sleep(.3)
            mouth = (await probe.state())["behavior"]
            assert mouth["morphs"]["あ"] > .5, mouth
            await asyncio.sleep(1.6)
            await probe.capture("side-lying-" + form)
            await asyncio.sleep(15)
            stable = await probe.state()
            assert stable["motion"] == "side_lying"
            assert abs(stable["dynamic_bone_angle"] - held["dynamic_bone_angle"]) < 1e-5
            assert json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))["fully_visible"]
            await gui(window.hide_sprite)
            await asyncio.sleep(.15)
            assert (await probe.state())["paused"]
            await gui(window.show_sprite)
            await asyncio.sleep(.3)
            assert (await probe.state())["motion"] == "side_lying"
            result["forms"].append({"form": form, "state": held, "framing": frames})
            if form == "second":
                await gui(lambda: window.sprite_view.set_physics(False))
            await gui(lambda: window._motion_actions["idle"].trigger())
            await asyncio.sleep(.5)
            standing = await probe.state()
            assert standing["motion"] == "idle" and standing["physics_active"] == (form == "first")
            assert abs(standing["right_arm_rotation"][2] - .67) < .04
            await probe.capture("side-to-idle-" + form)
            assert all(abs(a-b)<1e-4 for a,b in zip(standing["root_rotation"],initial["root_rotation"])), standing
            assert all(abs(a-b)<1e-4 for a,b in zip(standing["root_position"],initial["root_position"])), standing
            assert standing["body_positions"]["head"][1] > max(standing["body_positions"][key][1] for key in ("right_ankle", "left_ankle")) + 15, "待机必须在世界坐标中恢复直立，不能只检查动作名和手臂"
            result["forms"][-1]["restored_standing"] = standing
            assert await gui(lambda: (window.width(), window.height()) == original_size), "退出侧躺恢复原窗口尺寸"
            for _ in range(3):
                await gui(lambda: window._motion_actions["side_lying"].trigger())
                await asyncio.sleep(.3)
                assert (await probe.state())["motion"] == "side_lying"
                await gui(lambda: window._motion_actions["idle"].trigger())
                await asyncio.sleep(.3)
                repeated = await probe.state()
                assert all(abs(a-b)<1e-4 for a,b in zip(repeated["root_rotation"],initial["root_rotation"]))
                assert repeated["body_positions"]["head"][1] > max(repeated["body_positions"][key][1] for key in ("right_ankle", "left_ankle")) + 15
            await gui(lambda: (window.sprite_view.trigger_motion("side_lying"), window.sprite_view.trigger_motion("idle")))
            await asyncio.sleep(.5)
            assert (await probe.state())["motion"] == "idle", "后发动作取消尚在加载的 FBX"
            await gui(lambda: window.sprite_view.set_physics(True))
        await gui(lambda: window.sprite_view.trigger_motion("side_lying"))
        await asyncio.sleep(.5)
        await gui(lambda: window.set_model_form("first"))
        assert await gui(lambda: (window.width(), window.height()) == original_size), "侧躺切换形态立即恢复站立窗口"
        for _ in range(500):
            if await gui(lambda: window.sprite_view.model_loaded):
                break
            await asyncio.sleep(.1)
        assert (await probe.state())["motion"] == "idle"
        result["success"] = True

    async def run():
        try:
            await verify()
        except Exception:
            result["failures"].append(traceback.format_exc())
        finally:
            await gui(app.quit)
    QTimer.singleShot(0, lambda: pool.submit(asyncio.run, run()))
    QTimer.singleShot(180000, app.quit)
    app.exec()
    window.cleanup()
    bridge.close()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/side-lying-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": result["success"], "forms": [v["form"] for v in result["forms"]], "failures": result["failures"]}, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
