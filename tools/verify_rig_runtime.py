"""隔离原生窗口检查 Hsin 或指定 PMX 的基础动作与原生物理；不启语音或控制服务。"""
import argparse
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import json
import subprocess
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout

from src.core.app_config import load_config, project_path
from src.core.pmx_view import PmxView
from tools.verify_behavior import GuiProbe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="指定完整 PMX，沿用同目录原始贴图")
    parser.add_argument("--out", default=".runtime/rig-native", help="报告与截图目录")
    parser.add_argument("--physics", action="store_true", help="附加原生物理开关/复位检查")
    args = parser.parse_args()
    output = project_path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    paths = {"sample": project_path(args.model)} if args.model else {
        form: project_path(p) for form, p in config["sprite"]["model"]["forms"].items()}
    rig_maps = {}
    for form, path in paths.items():
        folder = output / form
        subprocess.run(["node", str(project_path("tools/analyze_pmx_rig.mjs")), str(path),
                        "--out", str(folder), "--force"], check=True, capture_output=True)
        rig_maps[str(path)] = str(folder / "rig_map.json")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["rig-runtime-validation"])
    app.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.setWindowTitle("Hsin 骨架映射开发检查")
    window.resize(500, 700)
    textures = {} if args.model else {str(paths[form]): mapping for form, mapping in config["sprite"]["model"].get("texture_overrides", {}).items()}
    window.sprite_view = PmxView(next(iter(paths.values())), window, texture_overrides=textures,
        animation_config={"physics": False, "rig_maps": rig_maps, "behavior": {
            "auto_blink": False, "breathing": False, "mouse_follow": False,
            "touch_reactions": False, "random_idle": False, "conversation_actions": False}})
    layout = QVBoxLayout(window)
    layout.addWidget(window.sprite_view)
    probe = GuiProbe(window)
    report = {"success": False, "models": [], "failures": []}
    pool = ThreadPoolExecutor(1)
    window.show()

    async def tick(frames):
        result = await probe.evaluate(f"""(() => {{
            for(let i=0;i<{frames};i++){{window.__rigClock+=1000/30;window.HsinPmx.tick(window.__rigClock);}}
            return JSON.stringify(window.HsinPmx.snapshot());
        }})()""")
        return json.loads(result)

    async def geometry():
        value = json.loads(await probe.evaluate("JSON.stringify(window.HsinPmxDebug.rigGeometry());"))
        assert value["finite"], "骨骼出现非有限变换"
        assert all(abs(n) < 1000 for v in value["bounds"].values() for n in v), "网格边界异常"
        return value

    async def capture(form, label):
        await asyncio.sleep(.15)
        def save(future):
            image = window.sprite_view.grab().toImage()
            colors = {image.pixelColor(x, y).rgba() for x in range(0, image.width(), 10) for y in range(0, image.height(), 10)}
            assert len(colors) > 100, "实际网格/贴图画面为空"
            dest = output / f"{form}-{label}.png"
            assert image.save(str(dest))
            future.set_result(str(dest))
        return await probe.call(save)

    async def verify():
        for index, (form, path) in enumerate(paths.items()):
            if index:
                await probe.call(lambda f: (window.sprite_view.load_model(path), f.set_result(None)))
            for _ in range(450):
                loaded, error = await probe.call(lambda f: f.set_result((window.sprite_view.model_loaded, window.sprite_view.load_error)))
                if error:
                    raise AssertionError(error)
                if loaded:
                    break
                await asyncio.sleep(.1)
            else:
                raise AssertionError("PMX 加载超时")
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            await probe.evaluate("window.__rigClock=performance.now();window.HsinPmx.tick(window.__rigClock);")
            idle = await tick(10)
            assert not idle["rig"]["summary"]["requiredUnresolved"]
            assert abs(idle["right_arm_rotation"][2] - .67) < .01
            info = await probe.call(lambda f: f.set_result(window.sprite_view.model_info))
            if args.model:
                assert info["motions"] == ["idle", "nod"], "未校准角色不应开放复杂手势"
            idle_geometry = await geometry()
            captures = {"idle": await capture(form, "idle")}
            for side in ("left", "right"):
                assert idle_geometry["points"][side + "_hand"][1] < idle_geometry["points"][side + "_upper_arm"][1] - 1, "手腕未下垂"
            await probe.evaluate("window.HsinPmx.playMotion('nod');")
            nod = await tick(10)
            assert abs(nod["head_rotation"][0]) > .1
            nod_geometry = await geometry()
            captures["nod"] = await capture(form, "nod")
            await tick(60)
            await probe.evaluate("window.HsinPmx.setLookAt(.8,0);")
            gaze = await tick(60)
            assert gaze["head_rotation"][1] > .15
            captures["gaze"] = await capture(form, "gaze")
            await probe.evaluate("window.HsinPmx.setLookAt(0,0);")
            reset = await tick(90)
            assert abs(reset["head_rotation"][1]) < .01
            reset_geometry = await geometry()
            for side in ("left", "right"):
                key = side + "_foot"
                assert max(abs(a-b) for a, b in zip(idle_geometry["points"][key], reset_geometry["points"][key])) < .001, "基础动作改变脚点"
            captures["reset"] = await capture(form, "reset")
            # 产品近景会切换到宽画布；隔离窗口也使用相同宽高，避免窄屏保全动作时缩小角色。
            await probe.call(lambda f: (window.resize(1000, 600), f.set_result(None)))
            await probe.evaluate("window.HsinPmx.setViewMode('head_front');")
            await tick(25)
            assert (await probe.state())["view_mode"] == "head_front"
            captures["head"] = await capture(form, "head")
            await probe.evaluate("window.HsinPmx.setViewMode('head_left');")
            await tick(10)
            captures["head-left"] = await capture(form, "head-left")
            await probe.evaluate("window.HsinPmx.setViewMode('head_right');")
            await tick(10)
            captures["head-right"] = await capture(form, "head-right")
            await probe.evaluate("window.HsinPmx.setViewMode('full');")
            await probe.call(lambda f: (window.resize(500, 700), f.set_result(None)))
            await tick(25)
            physics = None
            if args.physics:
                await probe.evaluate("window.HsinPmx.setPhysics(true);")
                physics = await tick(180)
                assert physics["physics_steps"] > 0
                physics_geometry = await geometry()
                captures["physics"] = await capture(form, "physics")
                await probe.evaluate("window.HsinPmx.setLookAt(-.8,.2);")
                await tick(60)
                captures["physics-gaze"] = await capture(form, "physics-gaze")
                await probe.evaluate("window.HsinPmx.setLookAt(0,0);window.HsinPmx.resetPhysics();")
                await tick(90)
                await geometry()
                captures["physics-reset"] = await capture(form, "physics-reset")
                await probe.evaluate("window.HsinPmx.setPhysics(false);")
                await tick(10)
                assert not (await probe.state())["physics_active"]
                physics = {"snapshot": physics, "geometry": physics_geometry}
            report["models"].append({"form": form, "model": str(path), "info": info,
                "idle": idle, "nod": nod, "gaze": gaze, "reset": reset, "captures": captures,
                "geometry": {"idle": idle_geometry, "nod": nod_geometry, "reset": reset_geometry},
                "physics": physics})
            print(f"PASS 原生映射动作：{form}", flush=True)
        report["success"] = True

    def run():
        try:
            asyncio.run(verify())
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            probe.requested.emit(lambda f: (app.quit(), f.set_result(None)), Future())

    QTimer.singleShot(1000, lambda: pool.submit(run))
    QTimer.singleShot(120000, app.quit)
    try:
        app.exec()
    finally:
        window.sprite_view.cleanup()
        window.close()
        pool.shutdown(wait=True)
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": report["success"], "forms": len(report["models"]), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
