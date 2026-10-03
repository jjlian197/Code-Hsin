"""原生双 PMX 过渡回归：实际播放器、固定地面、网格取景和中途指令。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_pose_transitions"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "captures": [], "checks": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda f: f.set_result(fn()))

    async def advance(seconds):
        count = round(seconds * 30)
        # QTimer 停止后用确定的 30 fps 时间驱动真实 helper，避免机器负载影响测试时长。
        for start in range(0, count, 15):
            await probe.evaluate(f"window.__qaTime ??= performance.now(); for(let i=0;i<{min(15,count-start)};i++)window.HsinPmx.tick(window.__qaTime+=1000/30);")
        await asyncio.sleep(.07)
        return await probe.state()

    async def motion(name):
        await gui(lambda: window.sprite_view.trigger_motion(name))
        await asyncio.sleep(.12)
        return await probe.state()

    async def check(name, condition, details=None):
        assert condition, (name, details)
        report["checks"].append(name)

    async def capture(form, name, time):
        state = await probe.state()
        framing = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))
        await check(f"{form}/{name}/{time}:完整取景", framing["fully_visible"], framing)
        path = await probe.capture(f"transition-{form}-{name}-{time}")
        report["captures"].append({"form": form, "motion": name, "time": time, "path": path, "state": state, "framing": framing})
        return state

    async def verify():
        for form in ("first", "second"):
            await gui(lambda: window.set_model_form(form))
            for _ in range(500):
                if await gui(lambda: window.sprite_view.model_loaded):
                    break
                await asyncio.sleep(.1)
            else:
                raise AssertionError("模型加载超时")
            await gui(lambda: window.sprite_view.frame_timer.stop())
            await probe.evaluate("window.__qaTime=performance.now(); window.HsinPmx.setPaused(false);")
            initial = await probe.state()
            await check(form+":动作资产匹配", initial["transition_available"], initial)
            await gui(lambda: window.sprite_view.set_physics(True))
            await advance(.3)
            # 首轮从全身进入，随后另测大头模式。
            await gui(lambda: window.set_view_mode("full", persist=False))
            original_size = await gui(lambda: (window.width(), window.height()))
            start = await motion("side_lying")
            await check(form+":真实躺下状态", start["motion"] == "lie_down" and start["physics_active"], start)
            await advance(.8)
            entry = await capture(form, "entry", .8)
            await check(form+":颈部起点无异常扭转", max(abs(x) for x in entry["head_rotation"]) < .15, entry)
            await advance(.2)
            frames = []
            for time in range(1, 8):
                if time > 1:
                    await advance(1)
                frames.append(await capture(form, "lie_down", time))
            await advance(.5)
            held = await capture(form, "held", 7.5)
            await check(form+":侧躺保持", held["motion"] == "side_lying", held)
            await check(form+":衣发模拟已运行", held["cloth"]["active"] and held["cloth"]["steps"] > 180 and held["cloth"]["max_displacement"] > .03, held["cloth"])
            await check(form+":衣发粒子不穿地", held["cloth"]["min_free_y"] >= held["floor_y"]+.06, held["cloth"])
            await advance(2)
            await capture(form, "cloth_settled", 9.5)
            await gui(lambda: window.sprite_view.set_physics(False))
            off = await advance(.2)
            await check(form+":侧躺物理开关关闭", not off["physics_active"] and not off["cloth"]["active"], off)
            await gui(lambda: window.sprite_view.set_physics(True))
            await advance(1)
            await check(form+":固定尺度", max(s["camera_frame"]["height"] for s in frames)-min(s["camera_frame"]["height"] for s in frames)<.001)
            await check(form+":固定地面", max(s["camera_frame"]["floor_y"] for s in frames)-min(s["camera_frame"]["floor_y"] for s in frames)<.01)
            before = held["root_position"]
            await motion("side_lying")
            repeated = await advance(.3)
            await check(form+":重复选择保持", repeated["motion"] == "side_lying" and max(abs(a-b) for a,b in zip(before,repeated["root_position"]))<1e-5)
            await gui(window.sprite_view.reset_physics)
            await gui(lambda: window.hide_sprite())
            paused = await probe.state()
            await advance(.5)
            await check(form+":隐藏冻结", paused["paused"] and (await probe.state())["motion_time"] == paused["motion_time"])
            await gui(window.show_sprite)
            await gui(lambda: window.sprite_view.frame_timer.stop())
            await probe.evaluate("window.__qaTime=performance.now();")
            await gui(lambda: window.sprite_view.set_lip_sync(.8, "a", 1000))
            lip = await advance(.2)
            await check(form+":侧躺口型", lip["behavior"]["morphs"]["あ"]>.5, lip["behavior"])
            up = await motion("idle")
            await check(form+":独立起身状态", up["motion"] == "get_up", up)
            for time in range(1, 8):
                await advance(1)
                await capture(form, "get_up", time)
            standing = await advance(1.4)
            await check(form+":恢复直立与偏好", standing["motion"] == "idle" and standing["physics_active"] and
                        standing["body_positions"]["head"][1] > max(standing["body_positions"][k][1] for k in ("right_ankle", "left_ankle"))+15, standing)
            await check(form+":恢复窗口", original_size == await gui(lambda: (window.width(), window.height())))
            await check(form+":双臂恢复下垂", abs(standing["right_arm_rotation"][2]-.67)<.025 and abs(standing["left_arm_rotation"][2]+.67)<.025, standing)
            after = await advance(2)
            await check(form+":下垂姿势持续保持", abs(after["right_arm_rotation"][2]-.67)<.025 and abs(after["left_arm_rotation"][2]+.67)<.025, after)
            await capture(form, "standing", 0)
            # 大头模式、中途待机、排队手势：身体走完支撑过程，最后一个指令生效。
            await gui(lambda: window.set_view_mode("head_right", persist=False))
            await motion("side_lying")
            await advance(2)
            await motion("wave")
            await check(form+":动作排队", (await probe.state())["queued_motion"] == "wave")
            await motion("idle")
            await advance(6)
            await check(form+":躺下后安全起身", (await probe.state())["motion"] == "get_up")
            await advance(8.5)
            await check(form+":大头模式恢复", (await probe.state())["motion"] == "idle" and (await probe.state())["effective_view_mode"] == "head_right")
            await motion("side_lying")
            await advance(8)
            await motion("wave")
            await advance(8)
            await check(form+":起身后执行手势", (await probe.state())["motion"] == "wave")
            await advance(5)
            await motion("side_lying")
            await advance(8)
            await motion("idle")
            await advance(1)
            await motion("side_lying")
            await advance(7.5)
            await check(form+":起身中再请求侧躺", (await probe.state())["motion"] == "lie_down")
            await motion("idle")
            await advance(16)
            await check(form+":连续切换最终直立", (await probe.state())["motion"] == "idle")
            await gui(lambda: window.sprite_view.set_physics(False))
            await motion("side_lying")
            await advance(8)
            await check(form+":关闭物理仍能侧躺", (await probe.state())["motion"] == "side_lying" and not (await probe.state())["physics_active"])
            await motion("idle")
            off_standing = await advance(8.5)
            await check(form+":关闭物理仍恢复下垂", off_standing["motion"] == "idle" and not off_standing["physics_active"] and
                        abs(off_standing["right_arm_rotation"][2]-.67)<.025 and abs(off_standing["left_arm_rotation"][2]+.67)<.025, off_standing)
            print("PASS:", form, flush=True)
        # 模型切换取消旧控制器，并恢复新模型的站立与显示模式。
        await motion("side_lying")
        await advance(2)
        await gui(lambda: window.set_model_form("first"))
        for _ in range(500):
            if await gui(lambda: window.sprite_view.model_loaded):
                break
            await asyncio.sleep(.1)
        await check("切换形态取消过渡", (await probe.state())["motion"] == "idle")
        report["success"] = True

    async def run():
        try:
            await verify()
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            await gui(app.quit)
    QTimer.singleShot(0, lambda: pool.submit(asyncio.run, run()))
    app.exec()
    window.cleanup()
    window.hide()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/pose-transition-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"success": report["success"], "checks": len(report["checks"]), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
