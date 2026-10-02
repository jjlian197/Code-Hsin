"""原生窗口验证中日 TTS 播放、PCM 口型、切换取消和退出清理。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe
from tools.verify_hsin_voices import SAMPLES
from src.core.voice_phrases import TOUCH_REPLIES


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_tts_desktop"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"].update(enabled=True, volume=0)
    window = HsinSpriteWindow(config)
    # 共用经过验证的正式缓存；验证期间静音，但真实解码及口型仍完整执行。
    window.tts.provider.runtime = project_path(".runtime/tts")
    bridge = ControlBridge(window)
    probe = GuiProbe(window)
    window.show_sprite()
    result = {"success": False, "languages": [], "failures": []}
    pool = ThreadPoolExecutor(1)

    async def verify():
        async def command(kind, data=None):
            response = await bridge.execute({"type": kind, "data": data or {}})
            assert response["success"], response
            return response["data"]

        for _ in range(450):
            status = await command("get_status")
            if status["renderer"]["model_loaded"]:
                break
            assert not status["renderer"]["error"], status
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("模型加载超时")
        for language, text in SAMPLES[:2]:
            await command("tts_config", {"language": language})
            queued = await command("speak", {"text": text, "volume": 0})
            assert queued["language"] == language
            peak = 0
            decoded = False
            deadline = time.monotonic() + 200
            while time.monotonic() < deadline:
                status = await command("get_status")
                assert not status["tts"]["error"], status["tts"]
                assert not status["audio"]["error"], status["audio"]
                current_audio = f"cache/{language}/" in (status["audio"]["path"] or "").replace("\\", "/")
                decoded |= current_audio and status["audio"]["buffer_count"] > 0
                state = await probe.state()
                peak = max(peak, state["behavior"]["mouth_open"])
                if decoded and not status["tts"]["synthesizing"] and status["audio"]["state"] == "StoppedState":
                    break
                await asyncio.sleep(0.04)
            assert decoded and peak > 0.15, (status, peak)
            await asyncio.sleep(0.3)
            assert (await probe.state())["behavior"]["mouth_open"] < 0.02
            assert f"cache/{language}/" in status["audio"]["path"].replace("\\", "/")
            result["languages"].append({"language": language, "mouth_peak": peak, "audio": status["audio"]})
            print(f"PASS: {language} TTS playback and PCM mouth", flush=True)
            await probe.click_face()
            touch_seen, touch_audio_seen, touch_peak = False, False, 0
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = await command("get_status")
                last = status["tts"]["last_request"]
                touch_seen |= bool(last and last["id"] > queued["id"] and last["text"] == TOUCH_REPLIES[language]["head"])
                assert not status["tts"]["error"], status["tts"]
                touch_audio_seen |= touch_seen and status["audio"]["state"] == "PlayingState"
                touch_peak = max(touch_peak, (await probe.state())["behavior"]["mouth_open"])
                if touch_audio_seen and status["audio"]["state"] == "StoppedState" and not status["tts"]["synthesizing"]:
                    break
                await asyncio.sleep(0.04)
            assert touch_seen and touch_audio_seen and touch_peak > 0.15, (language, status)
            result["languages"][-1]["touch_speech_verified"] = True
            print(f"PASS: {language} actual face touch speech", flush=True)
        # 立即切换会使已排队的旧请求失效，即使命中缓存也不能重新播放。
        await command("speak", {"text": SAMPLES[1][1], "language": "ja", "volume": 0})
        await command("tts_config", {"language": "zh"})
        await asyncio.sleep(0.5)
        status = await command("get_status")
        assert status["audio"]["state"] == "StoppedState" and not status["tts"]["synthesizing"]
        assert (await probe.state())["behavior"]["mouth_open"] < 0.02
        await command("tts_config", {"enabled": False})
        muted = await bridge.execute({"type": "speak", "data": {"text": "静音"}})
        assert muted["data"]["code"] == "tts_disabled"
        result["switch_cancellation"] = True
        result["success"] = True

    future = pool.submit(lambda: asyncio.run(verify()))
    def watch():
        if future.done():
            try:
                future.result()
            except Exception:
                result["failures"].append(traceback.format_exc())
            app.quit()
        else:
            QTimer.singleShot(40, watch)
    watch()
    QTimer.singleShot(450000, app.quit)
    try:
        app.exec()
    finally:
        bridge.close()
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
    project_path(".runtime/tts-desktop-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
