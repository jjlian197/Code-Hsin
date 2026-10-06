"""隔离原生窗口，检查半速跑步菜单、复位和侧躺后的动作排队。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_running"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["sprite"]["animation"]["behavior"] = dict.fromkeys(
        ("auto_blink", "breathing", "mouse_follow", "touch_reactions", "conversation_actions", "random_idle"), False)
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "forms": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda f: f.set_result(fn()))

    async def advance(seconds):
        for start in range(0, round(seconds * 30), 15):
            count = min(15, round(seconds * 30) - start)
            await probe.evaluate(f"for(let i=0;i<{count};i++)window.HsinPmx.tick(window.__runningClock+=1000/30);")
        return await probe.state()

    async def positions():
        return json.loads(await probe.evaluate("JSON.stringify(window.HsinPmxDebug.rigGeometry());"))

    async def verify():
        for form in ("first", "second"):
            await gui(lambda: window.set_model_form(form))
            for _ in range(500):
                if await gui(lambda: window.sprite_view.model_loaded):
                    break
                assert not await gui(lambda: window.sprite_view.load_error)
                await asyncio.sleep(.1)
            else:
                raise AssertionError("模型加载超时")
            info = await gui(lambda: window.sprite_view.model_info)
            assert info["chest_rig_bones"] == 10
            assert info["runtime"]["transition_available"]
            assert await gui(lambda: window._motion_actions["treadmill_running"].isEnabled())
            await gui(lambda: window.sprite_view.frame_timer.stop())
            await probe.evaluate("window.__runningClock=performance.now();window.HsinPmx.tick(window.__runningClock);")
            await advance(1)
            before = await positions()
            captures = []
            for physics in (True, False):
                await probe.evaluate(f"window.HsinPmx.setPhysics({str(physics).lower()});")
                await gui(lambda: window._motion_actions["treadmill_running"].trigger())
                state = await advance(8)
                assert state["motion"] == "treadmill_running", state
                assert abs(state["motion_time"] - 8) < .05, state
                assert (await positions())["finite"]
                captures.append(await probe.capture(f"running-{form}-{physics}"))
                state = await advance(8)
                assert state["motion"] == "idle", state
                after = await positions()
                for name in ("hips", "left_upper_leg", "right_upper_leg"):
                    assert max(abs(a-b) for a,b in zip(before["points"][name], after["points"][name])) < .03, (name, before, after)
                assert abs(state["right_arm_rotation"][2] - .67) < .02
            # 途中转手势和躺下，起身后再执行跑步。
            await probe.evaluate("window.HsinPmx.playMotion('treadmill_running');")
            await advance(2)
            await probe.evaluate("window.HsinPmx.playMotion('finger_heart');")
            assert (await advance(2))["motion"] == "finger_heart"
            await advance(4)
            await gui(lambda: window._motion_actions["side_lying"].trigger())
            assert (await advance(15))["motion"] == "side_lying"
            await gui(lambda: window._motion_actions["treadmill_running"].trigger())
            assert (await probe.state())["queued_motion"] == "treadmill_running"
            assert (await advance(12))["motion"] == "treadmill_running"
            await probe.evaluate("window.HsinPmx.playMotion('idle');")
            assert (await advance(1))["motion"] == "idle"
            assert (await positions())["finite"]
            report["forms"].append({"form": form, "chest_rig_bones": 10, "captures": captures})
            print("PASS:", form, "半速菜单、物理开关、结束复位、中断与起身排队", flush=True)
        report["success"] = True

    future = pool.submit(lambda: asyncio.run(verify()))

    def watch():
        if future.done():
            try:
                future.result()
            except Exception:
                report["failures"].append(traceback.format_exc())
            app.quit()
        else:
            QTimer.singleShot(30, watch)

    watch()
    QTimer.singleShot(180000, app.quit)
    try:
        app.exec()
    finally:
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
    project_path(".runtime/running-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
