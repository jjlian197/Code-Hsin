"""在真实透明 Qt 窗口检查两形态的部位点击、大头视角、侧躺与站立恢复。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_touch_views"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["sprite"]["animation"]["behavior"] = {"auto_blink": False, "breathing": False,
        "mouse_follow": False, "touch_reactions": True, "conversation_actions": False, "random_idle": False}
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    touches = []
    window.touch_event.connect(lambda action, part: touches.append((action, part)))
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    async def advance(frames):
        return json.loads(await probe.evaluate(f"""(() => {{
          for(let i=0;i<{frames};i++){{window.__touchClock+=1000/30;window.HsinPmx.tick(window.__touchClock);}}
          return JSON.stringify(window.HsinPmx.snapshot());
        }})()"""))

    async def click(x, y):
        def apply(future):
            view = window.sprite_view
            local = QPoint(round(x * view.width()), round(y * view.height()))
            global_pos = view.mapToGlobal(local)
            for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                QApplication.sendEvent(view, QMouseEvent(kind, QPointF(local), QPointF(global_pos),
                    Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
            future.set_result(None)
        await probe.call(apply)
        await probe.state()  # 等触摸回调送回 Qt。
        await asyncio.sleep(.05)

    async def locate(part):
        # 从骨骼附近的小网格寻找真实可见命中，测试仍发送 Qt 鼠标点击。
        value = await probe.evaluate(f"""(() => {{
          const part={json.dumps(part)}, p=window.HsinPmxDebug.geometry().points;
          let c=part==='head'?p['頭'].map((v,i)=>v+[0,.4,1][i]):
            part==='chest'?p['上半身2'].map((v,i)=>v+[0,1.25,2][i]):
            part==='hand'?p['右手首']:p['上半身2'].map((v,i)=>v+[0,-1.5,1][i]);
          const a=window.HsinPmxDebug.projectPoint(c);
          for(const d of [0,.025,-.025,.05,-.05,.075,-.075,.1,-.1])
            for(const e of [0,.025,-.025,.05,-.05,.075,-.075]) {{
              const x=a.x+d,y=a.y+e;
              if(x>.02&&x<.98&&y>.02&&y<.98&&window.HsinPmxDebug.pickTouch(x,y)===part)return JSON.stringify({{x,y}});
            }}
          return null;
        }})()""")
        assert value, f"找不到可见的{part}命中点"
        return json.loads(value)

    async def verify():
        for form in ("first", "second"):
            await probe.call(lambda f: (window.set_model_form(form), f.set_result(None)))
            for _ in range(500):
                if await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded)):
                    break
                error = await probe.call(lambda f: f.set_result(window.sprite_view.load_error))
                assert not error, error
                await asyncio.sleep(.1)
            else:
                raise AssertionError("模型加载超时")
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            await probe.evaluate("window.__touchClock=performance.now();window.HsinPmx.tick(window.__touchClock);")
            for mode in ("full", "head_front", "head_left", "head_right"):
                await probe.call(lambda f: (window._view_actions[mode].trigger(), f.set_result(None)))
                state = await advance(10)
                canvas = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.framing());"))
                assert canvas["width"] == (400 if mode == "full" else 1000) and canvas["height"] == 600, canvas
                assert state["view_mode"] == mode and state["effective_view_mode"] == mode
                if mode != "full":
                    assert 0 < state["interaction"]["head_top"]["y"] < .25, state["interaction"]
                parts = [("head", "finger_heart", "头部"), ("chest", "crossed_arms", "胸部"), ("body", "wave", "身体")]
                if mode == "full":
                    parts.append(("hand", "peace", "手"))
                for part, motion, label in parts:
                    await probe.evaluate("window.HsinPmx.playMotion('idle');")
                    await advance(15)
                    point = await locate(part)
                    before = len(touches)
                    await click(**point)
                    state = await advance(20)
                    assert state["motion"] == motion, (part, state)
                    assert state["behavior"]["last_touch"]["part"] == part
                    assert len(touches) == before + 1 and touches[-1] == ("tap", label), touches
                    if part == "chest":
                        assert state["behavior"]["morphs"]["FaceRed"] > .3
                    state = await advance(40)
                    if mode != "full":
                        framing = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmxDebug.visibleBandFraming());"))
                        if framing["left"] < 0 or framing["right"] > 1:
                            await asyncio.sleep(.2)
                            await probe.capture(f"touch-{form}-{mode}-{part}-clipping")
                        assert framing["left"] >= 0 and framing["right"] <= 1, (mode, motion, framing)
                    report["checks"].append({"form": form, "mode": mode, "part": part, "motion": state["motion"]})
                    if part in ("head", "chest"):
                        await asyncio.sleep(.2)
                        report["captures"].append(await probe.capture(f"touch-{form}-{mode}-{part}"))
                    await advance(150)
                    assert (await probe.state())["motion"] == "idle"
                assert await probe.evaluate("window.HsinPmx.touchAt(.01,.01)") is None
                await probe.evaluate("window.HsinPmx.setBehavior({touch_reactions:false});")
                point = await locate("head")
                before = len(touches)
                await click(**point)
                assert len(touches) == before and (await probe.state())["motion"] == "idle"
                await probe.evaluate("window.HsinPmx.setBehavior({touch_reactions:true});")
            # 大头偏好在躺稳后取上半身，过渡仍完整显示，站立恢复对应近景。
            await probe.call(lambda f: (window._motion_actions["side_lying"].trigger(), f.set_result(None)))
            await asyncio.sleep(.2)
            await advance(240)
            for _ in range(100):
                await asyncio.sleep(.1)
                if (await probe.state())["motion"] == "side_lying":
                    break
            state = await advance(30)
            assert state["motion"] == "side_lying" and state["view_mode"] == "head_right" and state["effective_view_mode"] == "head_right"
            assert json.loads(await probe.evaluate("JSON.stringify(window.HsinPmx.upperBodyFraming());"))["fully_visible"]
            await probe.click_face()
            await advance(30)
            assert (await probe.state())["motion"] == "side_lying"
            await probe.evaluate("window.HsinPmx.playMotion('idle');")
            await advance(270)
            assert (await probe.state())["effective_view_mode"] == "head_right"
            print("PASS:", form, "四种菜单视角、真实部位点击、开关和侧躺恢复", flush=True)
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
    QTimer.singleShot(240000, app.quit)
    try:
        app.exec()
    finally:
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
    if not report["success"] and not report["failures"]:
        report["failures"].append("原生检查超过运行时限，未完成全部步骤")
    project_path(".runtime/touch-view-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"success": report["success"], "checks": len(report["checks"]), "failures": report["failures"]}, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
