"""真实 Qt/PMX 双形态手势检查与正面/侧面近景；不联网、不开麦。"""
import asyncio
import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--character', help='检查指定PMX角色包，不修改日常角色设置')
    args = parser.parse_args()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_gestures"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    config["sprite"]["animation"]["behavior"] = {"auto_blink": False, "breathing": False,
        "mouse_follow": False, "touch_reactions": False, "conversation_actions": False, "random_idle": False}
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.set_size(650, 800)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    async def advance(frames):
        return json.loads(await probe.evaluate(f"""(() => {{
          for(let i=0;i<{frames};i++){{window.__gestureClock+=1000/30;window.HsinPmx.tick(window.__gestureClock);}}
          return JSON.stringify(window.HsinPmx.snapshot());
        }})()"""))

    async def verify():
        for form in (("aemeath",) if args.character else ("first", "second")):
            await probe.call(lambda f: (window.sprite_view.load_character(project_path(args.character)) if args.character else window.set_model_form(form), f.set_result(None)))
            for _ in range(500):
                if await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded)):
                    break
                error = await probe.call(lambda f: f.set_result(window.sprite_view.load_error))
                assert not error, error
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("模型加载超时")
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            await probe.evaluate("window.__gestureClock=performance.now();window.HsinPmx.tick(window.__gestureClock);")
            for physics in (False, True):
                await probe.evaluate(f"window.HsinPmx.setPhysics({str(physics).lower()});")
                if args.character:
                    for name in ('nod', 'wave', 'peace'):
                        await probe.call(lambda f, n=name: (window._motion_actions[n].trigger(), f.set_result(None)))
                        state = await advance(45)
                        assert state['motion'] == name, state
                        if name != 'nod':
                            assert state['right_palm_normal'][2] > .95, state
                        assert json.loads(await probe.evaluate('JSON.stringify(window.HsinPmxDebug.rigGeometry());'))['finite']
                        report['captures'].append(await probe.capture(f'gestures-{form}-{name}-{physics}-full'))
                        assert (await advance(90))['motion'] == 'idle'
                    assert not await probe.call(lambda f: f.set_result(window._motion_actions['side_lying'].isEnabled()))
                for name in ("finger_heart", "crossed_arms"):
                    await probe.call(lambda f: (window._motion_actions[name].trigger(), f.set_result(None)))
                    state = await advance(60)
                    assert state["motion"] == name, state
                    geometry = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmxDebug.geometry());"))
                    if name == "finger_heart":
                        assert geometry["indexGap"] < .08, "食指上沿未接合"
                        assert all(abs(x["corner"]-90)<.05 and max(sum(x["bends"], []))<.05 for x in geometry["lower"]), "真实骨架的下沿或直指偏离目标"
                    else:
                        left, right = geometry["points"]["左手首"], geometry["points"]["右手首"]
                        span, depth = (.5, .4) if args.character else (1, .7)
                        assert left[0]<-span and right[0]>span and abs(left[2]-right[2])>depth, "X 手势位置或深度错误"
                        assert state["right_palm_normal"][2]>.98, "X 手势掌面未朝前"
                    report["checks"].append({"form": form, "physics": physics, "motion": name, "geometry": geometry})
                    await asyncio.sleep(.3)
                    report["captures"].append(await probe.capture(f"gestures-{form}-{name}-{physics}-full"))
                    for angle, label in ((0, "front"), (-.55, "left"), (.55, "right")):
                        await probe.evaluate(f"window.HsinPmxDebug.view({angle});")
                        await asyncio.sleep(.3)
                        report["captures"].append(await probe.capture(f"gestures-{form}-{name}-{physics}-{label}"))
                    await probe.evaluate("window.HsinPmxDebug.resetView();")
                    state = await advance(100)
                    assert state["motion"] == "idle", state
                    assert abs(state["right_arm_rotation"][2]-.67)<.02
                    assert abs(state["left_arm_rotation"][2]+.67)<.02
                    # 真实 helper/物理路径上的重复触发与中断，不能只靠离线骨架通过。
                    await probe.evaluate(f"window.HsinPmx.playMotion({json.dumps(name)});")
                    state = await advance(60)
                    await probe.evaluate(f"window.HsinPmx.playMotion({json.dumps(name)});")
                    assert abs((await probe.state())["motion_time"]-state["motion_time"])<1e-6
                    interrupted = json.loads(await probe.evaluate("""(() => {
                      const before=window.HsinPmxDebug.geometry().points;
                      window.HsinPmx.playMotion('idle');
                      return JSON.stringify({before,after:window.HsinPmxDebug.geometry().points});
                    })()"""))
                    for bone in ("左手首", "右手首"):
                        assert max(abs(a-b) for a,b in zip(interrupted["before"][bone], interrupted["after"][bone]))<.002, "中断时手腕跳变"
                    state = await advance(20)
                    assert not state["behavior"]["manual_motion"]
                    assert abs(state["right_arm_rotation"][2]-.67)<.02 and abs(state["left_arm_rotation"][2]+.67)<.02
            print("PASS:", form, "真实菜单、手势保持/结束、物理开关、正面和斜侧面截图", flush=True)
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
    project_path(".runtime/aemeath-gesture-validation.json" if args.character else ".runtime/gesture-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"success": report["success"], "checks": len(report["checks"]), "failures": report["failures"]}, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
