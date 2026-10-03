"""原生 PMX：加速闲置计时，验证自动侧躺、点击起身和过渡中唤醒。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_idle_rest"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    config["voice"]["enabled"] = False
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda future: future.set_result(fn()))

    async def advance(seconds):
        count = round(seconds * 30)
        for start in range(0, count, 15):
            await probe.evaluate(f"for(let i=0;i<{min(15, count-start)};i++)window.HsinPmx.tick(window.__qaTime+=1000/30);")
        await asyncio.sleep(.1)
        return await probe.state()

    async def rest():
        await gui(lambda: setattr(window, "_last_interaction", time.monotonic() - 601))
        await gui(window._tick_rest)
        await asyncio.sleep(.15)
        state = await probe.state()
        assert state["motion"] == "lie_down", state

    async def verify():
        for _ in range(500):
            if await gui(lambda: window.sprite_view.model_loaded):
                break
            await asyncio.sleep(.1)
        else:
            raise AssertionError("模型加载超时")
        await gui(lambda: (window.sprite_view.frame_timer.stop(), window.rest_timer.stop()))
        await probe.evaluate("window.__qaTime=performance.now(); window.HsinPmx.setPaused(false);")
        assert (await probe.state())["transition_available"]
        await rest()
        state = await advance(8)
        assert state["motion"] == "side_lying", state
        assert json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))["fully_visible"]
        report["checks"].append("闲置十分钟自动侧躺，完整取景")
        await probe.click_face()
        await asyncio.sleep(.15)
        assert (await probe.state())["motion"] == "get_up"
        state = await advance(9)
        assert state["motion"] == "idle", state
        assert abs(state["left_arm_rotation"][2] + .67) < .025 and abs(state["right_arm_rotation"][2] - .67) < .025
        report["checks"].append("实际点击立即发起起身，恢复下垂双臂")
        await gui(window._tick_rest)
        assert (await probe.state())["motion"] == "idle"
        report["checks"].append("互动后重新计时，不立即再次躺下")
        await rest()
        await advance(1)
        await gui(window._record_interaction)
        state = await advance(17)
        assert state["motion"] == "idle", state
        report["checks"].append("躺下途中互动，安全支撑后起身")
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
    project_path(".runtime/idle-rest-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
