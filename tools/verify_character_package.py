"""在隔离应用窗口检查角色菜单、爱弥斯表情/口型与切回心；不开麦、不连接服务。"""
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import json
import tempfile
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMenu

from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    output = project_path(".runtime/character-validation")
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["voice"]["enabled"] = False
    config["chat"]["enabled"] = False
    config["sprite"]["animation"]["physics"] = False
    config["sprite"]["animation"]["behavior"] = {key: False for key in (
        "auto_blink", "breathing", "mouse_follow", "touch_reactions", "random_idle", "conversation_actions")}
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["character-package-validation"])
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(config)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "states": {}, "captures": {}, "failures": []}

    async def loaded():
        for _ in range(450):
            ready, error = await probe.call(lambda f: f.set_result((window.sprite_view.model_loaded, window.sprite_view.load_error)))
            if error:
                raise AssertionError(error)
            if ready:
                await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
                await probe.evaluate("window.__characterClock=performance.now();")
                return
            await asyncio.sleep(.1)
        raise AssertionError("角色加载超时")

    async def tick(count):
        return json.loads(await probe.evaluate(f"""(() => {{for(let i=0;i<{count};i++){{window.__characterClock+=1000/30;window.HsinPmx.tick(window.__characterClock);}}return JSON.stringify(window.HsinPmx.snapshot());}})()"""))

    async def capture(label):
        await asyncio.sleep(.1)
        dest = output / (label + ".png")
        def inspect(future):
            pixmap = window.sprite_view.grab()
            assert pixmap.save(str(dest))
            image = pixmap.toImage()
            luminances = []
            for y in range(0, image.height(), 4):
                for x in range(0, image.width(), 4):
                    color = image.pixelColor(x, y)
                    if color.alpha() == 255:
                        luminances.append(.2126 * color.red() + .7152 * color.green() + .0722 * color.blue())
            assert luminances, "模型必须实际可见"
            future.set_result(sum(luminances) / len(luminances))
        luminance = await probe.call(inspect)
        report["captures"][label] = str(dest)
        return luminance

    async def compare_lighting(character):
        await probe.evaluate("window.HsinPmxDebug.lighting(false)")
        before = await capture(character + "-light-before")
        await probe.evaluate("window.HsinPmxDebug.lighting(true)")
        after = await capture(character + "-light-after")
        assert after > before + 2, f"补光应使画面变亮：{before} → {after}"
        report.setdefault("lighting", {})[character] = {"before": before, "after": after}

    async def verify():
        await loaded()
        report["states"]["hsin_before"] = await tick(10)
        await compare_lighting("hsin")
        def select(future):
            menu = QMenu(window)
            window._populate_characters(menu)
            action = next((a for a in menu.actions() if a.text() == "爱弥斯 · 完整配置"), None)
            assert action is not None, "角色菜单应包含爱弥斯完整配置"
            action.trigger()
            menu.deleteLater()
            future.set_result(True)
        await probe.call(select)
        await loaded()
        await tick(10)
        info = await probe.call(lambda f: f.set_result(window.sprite_view.model_info))
        assert info["character"] == "爱弥斯" and info["texture_errors"] == 0
        assert len(info["expressions"]) == 12 and info["motions"] == ["idle", "nod"]
        assert await probe.call(lambda f: f.set_result(not window._motion_actions["side_lying"].isEnabled()))
        await probe.call(lambda f: (window.set_view_mode("head_front"), f.set_result(None)))
        await tick(30)
        await compare_lighting("aemeath")
        for expression in ("normal", "happy", "content", "star_eyes", "heart_eyes"):
            await probe.call(lambda f, e=expression: (window.set_expression(e), f.set_result(None)))
            state = await tick(8)
            report["states"][expression] = state
            await capture(expression)
        await probe.call(lambda f: (window.set_expression("normal"), f.set_result(None)))
        await probe.evaluate("window.HsinPmx.blink();")
        blink = await tick(2)
        assert blink["behavior"]["morphs"]["まばたき"] > .9
        report["states"]["blink"] = blink
        await capture("blink")
        await tick(10)
        for shape, morph in {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}.items():
            await probe.evaluate(f"window.HsinPmx.setLipSync(.8,'{shape}',500);")
            state = await tick(4)
            assert state["behavior"]["morphs"][morph] > .5
            report["states"][shape] = state
            await capture("vowel-" + shape)
        await probe.evaluate("window.HsinPmx.setLipSync(0,'a',0);")
        state = await tick(35)
        assert max(state["behavior"]["morphs"].get(n, 0) for n in ("あ", "い", "う", "え", "お")) < .001
        # 切换时实际恢复 Hsin 原资产、表情和完整动作；旧角色的状态不残留。
        for form in ("first", "second"):
            await probe.call(lambda f, key=form: (window.set_model_form(key), f.set_result(None)))
            await loaded()
            state = await tick(10)
            info = await probe.call(lambda f: f.set_result(window.sprite_view.model_info))
            assert info["character"] is None and "finger_heart" in info["motions"]
            assert state["behavior"]["expression"] == "normal" and state["behavior"]["mouth_open"] < .001
            assert state["rig"]["model_hash"] != report["states"]["normal"]["rig"]["model_hash"]
            report["states"]["hsin_" + form] = state
            await capture("hsin-" + form)
        # 表情映射在真实 PMX 中无效时，恢复切换前的角色，而非留下空窗口。
        package_file = project_path(".runtime/characters/aemeath/character.json")
        invalid = json.loads(package_file.read_text(encoding="utf-8"))
        invalid["rig"] = str(package_file.parent / invalid["rig"])
        morphs = json.loads((package_file.parent / invalid["morphs"]).read_text(encoding="utf-8"))
        morphs["expressions"]["happy"] = {"不存在的表情": .5}
        bad_morphs = project_path(temp.name) / "bad-morphs.json"
        bad_morphs.write_text(json.dumps(morphs), encoding="utf-8")
        invalid["morphs"] = str(bad_morphs)
        bad_package = project_path(temp.name) / "bad-character.json"
        bad_package.write_text(json.dumps(invalid), encoding="utf-8")
        await probe.call(lambda f: (window.sprite_view.load_character(bad_package), f.set_result(None)))
        await loaded()
        restored = await tick(10)
        assert restored["rig"]["model_hash"] == report["states"]["hsin_second"]["rig"]["model_hash"]
        assert await probe.call(lambda f: f.set_result(window.sprite_view.character_package is None))
        report["states"]["failed_package_restored"] = restored
        # 连续加载时，以最后一次选择为准，迟到贴图/模型不会抢回界面。
        await probe.call(lambda f: (window.sprite_view.load_character(package_file), window.set_model_form("first"), f.set_result(None)))
        await loaded()
        latest = await tick(10)
        assert latest["rig"]["model_hash"] == report["states"]["hsin_first"]["rig"]["model_hash"]
        report["states"]["latest_selection"] = latest
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
        window.cleanup()
        window.close()
        pool.shutdown(wait=True)
        temp.cleanup()
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": report["success"], "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
