"""模拟聊天逐句返回，使用本机心的中日音色和真实 Qt 播放器；不开麦、不调用远程后端。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import threading
import time
import traceback
from unittest.mock import patch

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe

PHRASES = {"zh": ["御者，我在这里。", "今天也一起慢慢来吧。", "好吗"],
           "ja": ["御者、ここにいます。", "今日も一緒にゆっくり過ごしましょう。", "どうですか"]}


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["streaming-speech-validation"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"].update(enabled=True, volume=0, provider="gptsovits", fallback=False, auto_translate=False, port=19883)
    window = HsinSpriteWindow(config)
    # 保留验证缓存，避免每次在空临时目录重建整套 PyTorch 导入缓存。
    window.tts.provider.runtime = project_path(".runtime/streaming-tts")
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    release = threading.Event()
    started = []
    window.tts.speech_started.connect(lambda text: started.append({"text": text, "at": time.monotonic(),
        "chat_busy": window.chat.busy, "provider": window.tts.actual_provider}))
    report = {"success": False, "languages": [], "failures": []}

    class Backend:
        async def chat(self, text, language, delta, **kwargs):
            first, second, tail = PHRASES[language]
            await delta(first)
            while not release.is_set():
                await asyncio.sleep(.01)
            await delta(second)
            return first + second + tail

    async def verify():
        for _ in range(500):
            if await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded)):
                break
            await asyncio.sleep(.1)
        else:
            raise AssertionError("模型加载超时")
        for language in ("zh", "ja"):
            release.clear()
            offset = len(started)
            def send(f):
                window.tts.configure(language=language)
                window.send_chat("验证本地分句朗读", language)
                f.set_result(time.monotonic())
            sent = await probe.call(send)
            await asyncio.sleep(.2)
            diagnostics = await probe.call(lambda f: f.set_result({"chat": window.chat.snapshot(), "tts": window.tts.snapshot(), "token": window._speech_token}))
            print("START:", language, json.dumps(diagnostics, ensure_ascii=False), flush=True)
            deadline = time.monotonic() + 185
            while time.monotonic() < deadline:
                status = await probe.call(lambda f: f.set_result({"started": len(started),
                    "buffers": window.voice_player.buffer_count, "peak": window.voice_player.peak_level,
                    "busy": window.chat.busy, "blocked": window.stt.blocked, "error": window.tts.error}))
                if status["error"]:
                    raise AssertionError(status["error"])
                snapshot = await probe.state()
                if status["started"] > offset and status["buffers"] > 0 and snapshot["behavior"]["mouth_open"] > .03:
                    assert status["busy"] and status["blocked"]
                    assert snapshot["behavior"]["activity"]["state"] == "speaking"
                    break
                await asyncio.sleep(.05)
            else:
                report["last_state"] = await probe.call(lambda f: f.set_result({"chat": window.chat.snapshot(), "tts": window.tts.snapshot(), "audio": window.voice_player.snapshot()}))
                raise AssertionError("第一句未在回复完成前开始播放并驱动口型")
            release.set()
            for _ in range(2000):
                done = await probe.call(lambda f: f.set_result(not window.chat.busy and not window.tts.snapshot()["active"]))
                if done:
                    break
                await asyncio.sleep(.05)
            else:
                raise AssertionError("分句语音没有全部播放完毕")
            played = started[offset:]
            assert [s["text"] for s in played] == PHRASES[language], played
            assert played[0]["chat_busy"] and all(s["provider"] == "gptsovits" for s in played)
            assert await probe.call(lambda f: f.set_result(not window.stt.blocked and not window.stt.enabled))
            result = {"language": language, "segments": [s["text"] for s in played],
                "first_started_before_reply_complete": True, "first_start_seconds": round(played[0]["at"] - sent, 3),
                "actual_pcm_and_lips": True, "ordered_without_duplicate": True}
            report["languages"].append(result)
            print("PASS:", language, json.dumps(result, ensure_ascii=False), flush=True)
        report["success"] = True

    with patch("src.core.chat_manager.make_backend", return_value=Backend()):
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
        QTimer.singleShot(360000, app.quit)
        try:
            app.exec()
        finally:
            release.set()
            window.cleanup()
            window.hide()
            pool.shutdown(wait=True)
            temp.cleanup()
    project_path(".runtime/streaming-speech-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
