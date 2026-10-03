"""原生双形态陪伴动作检查；不联网、不打开麦克风。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback
import wave
from unittest.mock import patch

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["companion-validation"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"]["enabled"] = False
    audio_path = project_path(temp.name) / "silence.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 16000 * 3)
    config["sprite"]["animation"]["behavior"] = {
        "auto_blink": False, "breathing": False, "mouse_follow": False,
        "touch_reactions": True, "conversation_actions": True, "random_idle": False}
    window = HsinSpriteWindow(config)
    probe = GuiProbe(window)
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    async def tick(frames=60):
        return json.loads(await probe.evaluate(f"""(() => {{
            for(let i=0;i<{frames};i++){{window.__companionClock+=1000/30;window.HsinPmx.tick(window.__companionClock);}}
            return JSON.stringify(window.HsinPmx.snapshot());
        }})()"""))

    async def capture(name):
        # WebEngine 绘制完成后还需等待 Qt 合成，否则截图可能仍是上一帧。
        await asyncio.sleep(.25)
        return await probe.capture(name)

    async def verify():
        for form in ("first", "second"):
            await probe.call(lambda f: (window.set_model_form(form), f.set_result(None)))
            for _ in range(500):
                if await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded)):
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("模型加载超时")
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            await probe.evaluate("window.__companionClock=performance.now();window.HsinPmx.tick(window.__companionClock);")
            menu = await probe.call(lambda f: f.set_result({
                "motions": [n for n, a in window._motion_actions.items() if a.isEnabled()],
                "expressions": [n for n, a in window._expression_actions.items() if a.isEnabled()]}))
            assert len(menu["motions"]) == 6 and len(menu["expressions"]) == 12, menu
            for physics in (True, False):
                await probe.evaluate(f"window.HsinPmx.setPhysics({str(physics).lower()});")
                for state in ("thinking", "speaking", "listening", "idle"):
                    def change(f):
                        window.chat.busy = state == "thinking"
                        stt = {"enabled": state == "listening", "listening": state == "listening", "blocked": False, "recognizing": False}
                        playback = QMediaPlayer.PlaybackState.PlayingState if state == "speaking" else QMediaPlayer.PlaybackState.StoppedState
                        with patch.object(window.stt, "snapshot", return_value=stt), patch.object(window.voice_player.player, "playbackState", return_value=playback):
                            window._sync_companion()
                        window.chat.busy = False
                        f.set_result(None)
                    await probe.call(change)
                    snapshot = await tick()
                    assert snapshot["behavior"]["activity"]["state"] == state
                    weights = snapshot["behavior"]["activity_weights"]
                    assert weights.get(state, 1) > .99
                    if state == "idle":
                        assert max(weights.values()) < .001
                    else:
                        report["captures"].append(await capture(f"{form}-{state}-{physics}"))
                for motion in ("peace", "finger_heart", "crossed_arms"):
                    await probe.evaluate(f"window.HsinPmx.playMotion({json.dumps(motion)});")
                    snapshot = await tick(35)
                    assert snapshot["motion"] == motion and snapshot["behavior"]["manual_motion"]
                    if motion != "crossed_arms":
                        assert snapshot["right_palm_normal"][2] > .95
                    report["captures"].append(await capture(f"{form}-{motion}-{physics}"))
                    snapshot = await tick(90)
                    assert snapshot["motion"] == "idle" and not snapshot["behavior"]["manual_motion"]
                    assert abs(snapshot["right_arm_rotation"][2] - .67) < .02
                    assert abs(snapshot["left_arm_rotation"][2] + .67) < .02
                report["checks"].append({"form": form, "physics": physics, "states": 4, "gestures": 3})
            for expression in menu["expressions"]:
                await probe.call(lambda f: (window.set_expression(expression), f.set_result(None)))
                await tick(2)
                assert await probe.call(lambda f: f.set_result(window._expression_actions[expression].isChecked()))
                if expression in ("blush", "content", "star_eyes", "heart_eyes"):
                    report["captures"].append(await capture(f"{form}-{expression}"))
            await probe.call(lambda f: (window.set_expression("normal"), f.set_result(None)))
            # 验证真实播放器信号，不能只根据合成请求就进入说话姿态。
            await probe.call(lambda f: (window.voice_player.play(audio_path, volume=0), f.set_result(None)))
            for _ in range(60):
                if (await probe.state())["behavior"]["activity"]["state"] == "speaking":
                    break
                await asyncio.sleep(.05)
            else:
                raise AssertionError("实际音频没有触发说话姿态")
            await tick(45)
            assert (await probe.state())["behavior"]["activity_weights"]["speaking"] > .99
            await probe.call(lambda f: (window.voice_player.stop(), f.set_result(None)))
            snapshot = await tick(60)
            assert snapshot["behavior"]["activity"]["state"] == "idle"
            assert snapshot["behavior"]["activity_weights"]["speaking"] < .001
            await probe.evaluate("window.HsinPmx.setBehavior({random_idle:true});")
            snapshot = await tick(1500)
            assert snapshot["behavior"]["next_idle"] > 0
            await probe.evaluate("window.HsinPmx.setActivity({state:'thinking'});")
            snapshot = await tick(2)
            assert snapshot["behavior"]["idle_action"] is None
            await probe.evaluate("window.HsinPmx.setActivity({state:'idle'});window.HsinPmx.setBehavior({random_idle:false});")
            print("PASS:", form, "对话状态、手势、12 表情、菜单和物理开关", flush=True)
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
    project_path(".runtime/companion-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
