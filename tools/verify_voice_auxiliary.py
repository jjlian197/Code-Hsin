"""实际翻译、Edge 中日播放、双向备用音色和 PCM 口型的原生验证。"""
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


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["voice-auxiliary"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"].update(enabled=True, volume=0)
    window = HsinSpriteWindow(config)
    # 缓存共享，设置与会话记录隔离；不改变正在运行的主应用。
    window.tts.provider.runtime = project_path(".runtime/tts")
    window.tts.edge.cache = project_path(".runtime/tts/cache/edge")
    window.tts.translator.cache = project_path(".runtime/tts/translations")
    bridge = ControlBridge(window)
    probe = GuiProbe(window)
    window.show_sprite()
    pool = ThreadPoolExecutor(1)
    result = {"success": False, "checks": [], "failures": []}

    async def command(kind, data=None):
        response = await bridge.execute({"type": kind, "data": data or {}})
        assert response["success"], response
        return response["data"]

    async def play(text, language, engine, translate=False, fallback=False, actual=None):
        await command("tts_config", {"language": language, "provider": engine,
                                     "auto_translate": translate, "fallback": fallback})
        queued = await command("speak", {"text": text, "volume": 0})
        mouth, decoded = 0, False
        deadline = time.monotonic() + 200
        status = None
        while time.monotonic() < deadline:
            status = await command("get_status")
            assert not status["tts"]["error"], status["tts"]
            assert not status["audio"]["error"], status["audio"]
            decoded |= status["audio"]["buffer_count"] > 0 and status["tts"]["actual_provider"] == (actual or engine)
            mouth = max(mouth, (await probe.state())["behavior"]["mouth_open"])
            if decoded and not status["tts"]["synthesizing"] and status["audio"]["state"] == "StoppedState":
                break
            await asyncio.sleep(0.04)
        assert decoded and mouth > 0.1, (status, mouth)
        await asyncio.sleep(0.35)
        assert (await probe.state())["behavior"]["mouth_open"] < 0.03
        state = status["tts"]
        if translate:
            assert state["last_request"]["spoken_text"] != text, state
        if actual:
            assert state["warning"], state
        result["checks"].append({"language": language, "requested_provider": engine,
            "actual_provider": state["actual_provider"], "text": text,
            "spoken_text": state["last_request"]["spoken_text"], "warning": state["warning"],
            "mouth_peak": mouth, "audio": status["audio"]["path"]})
        print("PASS:", language, engine, "translation" if translate else "speech", "fallback" if actual else "primary", flush=True)

    async def verify():
        for _ in range(500):
            status = await command("get_status")
            if status["renderer"]["model_loaded"]:
                break
            assert not status["renderer"]["error"], status
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("模型加载超时")
        await play("御者，我在这里陪着你。", "zh", "edge")
        await play("御者、ここであなたを待っています。", "ja", "edge")
        primary = window.tts.provider.synthesize
        edge = window.tts.edge.synthesize
        def unavailable(*args): raise RuntimeError("verification: deliberately unavailable")
        try:
            await probe.call(lambda f: (setattr(window.tts.provider, "synthesize", unavailable), f.set_result(None)))
            await play("御者，我在这里陪着你。", "zh", "gptsovits", fallback=True, actual="edge")
        finally:
            await probe.call(lambda f: (setattr(window.tts.provider, "synthesize", primary), f.set_result(None)))
        try:
            await probe.call(lambda f: (setattr(window.tts.edge, "synthesize", unavailable), f.set_result(None)))
            language, text = SAMPLES[0]
            await play(text, language, "edge", fallback=True, actual="gptsovits")
        finally:
            await probe.call(lambda f: (setattr(window.tts.edge, "synthesize", edge), f.set_result(None)))
        await play("御者，今晚也让我陪着你吧。", "ja", "gptsovits", translate=True)
        await play("御者、今日はゆっくり休んでくださいね。", "zh", "gptsovits", translate=True)
        await probe.call(lambda f: (window.tts.configure(provider="edge", auto_translate=True, fallback=True), f.set_result(None)))
        synced = await probe.call(lambda f: f.set_result(window._voice_engine_actions["edge"].isChecked()
            and window._voice_translate_action.isChecked() and window._voice_fallback_action.isChecked()))
        assert synced, "菜单辅助设置必须与接口同步"
        result["menus_synced"] = True
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
            QTimer.singleShot(30, watch)
    watch()
    QTimer.singleShot(600000, app.quit)
    try:
        app.exec()
    finally:
        bridge.close()
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
    project_path(".runtime/voice-auxiliary-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
