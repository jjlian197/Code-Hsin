"""真实双 PMX 侧躺上半身近景：三个角度、动态衣发、菜单切换与起身恢复。"""
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
    app = QApplication(["verify_side_closeup"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["sprite"]["animation"]["behavior"] = {"mouse_follow": False, "random_idle": False}
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda f: f.set_result(fn()))

    async def advance(seconds):
        frames = round(seconds*30)
        for start in range(0, frames, 15):
            await probe.evaluate(f"for(let i=0;i<{min(15,frames-start)};i++)window.HsinPmx.tick(window.__sideClock+=1000/30);")
        await asyncio.sleep(.1)
        return await probe.state()

    def check(name, condition, details=None):
        assert condition, (name, details)
        report["checks"].append(name)

    async def capture(form, mode):
        await asyncio.sleep(.15)
        report["captures"].append({"form": form, "mode": mode, "path": await probe.capture(f"side-closeup-{form}-{mode}"), "state": await probe.state()})

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
            await probe.evaluate("window.__sideClock=performance.now();window.HsinPmx.setPaused(false);")
            await gui(lambda: window.set_view_mode("head_front", persist=False))
            await gui(lambda: window.sprite_view.trigger_motion("side_lying"))
            await asyncio.sleep(.1)
            transition = await advance(2)
            check(form+":躺下保留全身", transition["effective_view_mode"] == "full", transition)
            await advance(6.5)
            for mode in ("head_front", "head_left", "head_right"):
                await gui(lambda: window._view_actions[mode].trigger())
                state = await advance(1)
                check(form+mode+":侧躺近景", state["motion"] == "side_lying" and state["effective_view_mode"] == mode, state)
                frame = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.upperBodyFraming());"))
                check(form+mode+":上半身完整", frame["fully_visible"] and min(frame["left"],frame["top"],1-frame["right"],1-frame["bottom"])>.025, frame)
                check(form+mode+":放大上半身", state["camera_frame"]["height"] < transition["camera_frame"]["height"]*.7, state["camera_frame"])
                check(form+mode+":头部可见", .1<state["interaction"]["face"]["x"]<.9 and .05<state["interaction"]["face"]["y"]<.8, state["interaction"])
                await capture(form, mode)
                await advance(2)
                check(form+mode+":衣发活动无裁切", json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.upperBodyFraming());"))["fully_visible"])
                await probe.click_face()
                state = await advance(.5)
                check(form+mode+":近景触摸保持侧躺", state["motion"] == "side_lying" and state["behavior"]["last_touch"]["part"] == "head", state)
            await gui(lambda: window.set_view_mode("full", persist=False))
            state = await advance(1)
            check(form+":切回完整侧躺", state["effective_view_mode"] == "full" and json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))["fully_visible"])
            await capture(form, "full")
            await gui(lambda: window.set_view_mode("head_right", persist=False))
            await advance(1)
            await gui(lambda: window.sprite_view.trigger_motion("idle"))
            state = await advance(1)
            check(form+":起身保留全身", state["motion"] == "get_up" and state["effective_view_mode"] == "full", state)
            state = await advance(8)
            check(form+":站立恢复斜侧大头", state["motion"] == "idle" and state["effective_view_mode"] == "head_right", state)
            await capture(form, "standing")
            print("PASS:", form, flush=True)
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
    project_path(".runtime/side-closeup-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"success": report["success"], "checks": len(report["checks"]), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
