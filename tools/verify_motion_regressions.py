"""双形态逐帧检查动作切换不回平举姿态，以及挥手掌心的镜头方向。"""
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
    app = QApplication(["motion-regressions"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"]["enabled"] = False
    config["sprite"]["animation"]["behavior"] = dict.fromkeys(
        ("auto_blink", "breathing", "mouse_follow", "touch_reactions"), False)
    window = HsinSpriteWindow(config)
    probe = GuiProbe(window)
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "failures": []}

    async def verify():
        for form in ("first", "second"):
            await probe.call(lambda f: (window.set_model_form(form), f.set_result(None)))
            for _ in range(500):
                loaded = await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded))
                if loaded:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("模型加载超时")
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            await probe.evaluate("window.__motionClock=performance.now();window.HsinPmx.tick(window.__motionClock);")
            for physics in (True, False):
                await probe.evaluate(f"window.HsinPmx.setPhysics({str(physics).lower()});")
                for motion in ("nod", "wave"):
                    frames = json.loads(await probe.evaluate(f"""(() => {{
                        const api=window.HsinPmx, frames=[];
                        api.playMotion('idle'); api.playMotion({json.dumps(motion)});
                        frames.push(api.snapshot());
                        for(let i=0;i<100;i++) {{ window.__motionClock+=1000/30;
                            api.tick(window.__motionClock);frames.push(api.snapshot()); }}
                        return JSON.stringify(frames);
                    }})()"""))
                    left = [f["left_arm_rotation"][2] for f in frames]
                    assert all(abs(z + 0.67) < 0.035 for z in left), (form, physics, motion, min(left), max(left))
                    if motion == "nod":
                        assert all(abs(f["right_arm_rotation"][2] - 0.67) < 0.035 for f in frames), "点头不能重置手臂"
                    palms = [f["right_palm_normal"][2] for f in frames if motion == "wave" and 0.85 < f["motion_time"] < 2.15]
                    if motion == "wave":
                        assert palms and min(palms) > 0.92, (form, physics, "掌心方向", palms)
                    assert frames[-1]["motion"] == "idle"
                    assert abs(frames[-1]["right_arm_rotation"][2] - 0.67) < 0.035
                    report["checks"].append({"form": form, "physics": physics, "motion": motion,
                        "frames": len(frames), "left_arm_range": [min(left), max(left)],
                        "minimum_palm_camera_dot": min(palms) if palms else None})
                # 在挥手中途切回点头：不能残留抬手或手腕姿态。
                state = json.loads(await probe.evaluate("""(() => {
                    const api=window.HsinPmx;api.playMotion('wave');
                    for(let i=0;i<30;i++){window.__motionClock+=1000/30;api.tick(window.__motionClock);}
                    api.playMotion('nod');return JSON.stringify(api.snapshot());
                })()"""))
                assert abs(state["right_arm_rotation"][2]-0.67)<0.035, "中断动作必须立即恢复下垂手臂"
            await probe.evaluate("window.HsinPmx.playMotion('wave');for(let i=0;i<35;i++){window.__motionClock+=1000/30;window.HsinPmx.tick(window.__motionClock);}")
            await probe.capture("wave-fixed-" + form)
            print("PASS:", form, "逐帧动作连续、镜头朝向、物理开关与中途切换", flush=True)
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
    project_path(".runtime/motion-regression-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
