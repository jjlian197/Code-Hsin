"""真实 Hermes → 分句 → 心音色：记录首句时序，不延迟后端来伪造流式效果。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_streaming_live"])
    app.setQuitOnLastWindowClosed(False)
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config = load_config()
    config["runtime"]["directory"] = temp.name
    config["voice"].update(enabled=True, volume=0, fallback=False, auto_translate=False, port=19884)
    config["chat"].update(provider="hermes", enabled=True, reply_length="detailed", speech_scope="full")
    window = HsinSpriteWindow(config)
    window.tts.provider.runtime = project_path(".runtime/streaming-live-tts")
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "turns": [], "failures": []}
    events = []
    started_at = [0.0]
    window.chat.progress.connect(lambda _, text: events.append({"kind": "delta", "seconds": time.monotonic() - started_at[0], "characters": len(text)}))
    window.chat.sentence_ready.connect(lambda *args: events.append({"kind": "sentence", "seconds": time.monotonic() - started_at[0], "characters": len(args[1])}))
    window.chat.reply_ready.connect(lambda *args: events.append({"kind": "complete", "seconds": time.monotonic() - started_at[0]}))
    window.tts.speech_started.connect(lambda text: events.append({"kind": "audio", "seconds": time.monotonic() - started_at[0], "characters": len(text), "chat_busy": window.chat.busy}))

    async def gui(fn):
        return await probe.call(lambda future: future.set_result(fn()))

    async def verify():
        for _ in range(600):
            if await gui(lambda: window.sprite_view.model_loaded):
                break
            await asyncio.sleep(.1)
        else:
            raise AssertionError("模型加载超时")
        for index in range(2):
            events.clear()
            def send():
                window.open_chat()
                started_at[0] = time.monotonic()
                window.send_chat("这是桌面分句时序测试，不要调用工具。请先说一句‘御者，我在这里。’，随后用十到十二个自然短句，约三百字，说明如何轻松地安排一个休息日。")
            await gui(send)
            for _ in range(2400):
                state = await gui(lambda: {"chat_busy": window.chat.busy, "chat_error": window.chat.error,
                    "active": window.tts.snapshot()["active"], "tts_error": window.tts.error,
                    "buffers": window.voice_player.buffer_count, "peak": window.voice_player.peak_level})
                if state["chat_error"] or state["tts_error"]:
                    raise AssertionError(state["chat_error"] or state["tts_error"])
                # 先记录真实首句即可，避免长回复的完整语音耗时掩盖串流时序。
                if any(event["kind"] == "complete" for event in events) and any(event["kind"] == "audio" for event in events) and state["buffers"]:
                    break
                await asyncio.sleep(.1)
            else:
                raise AssertionError("真实回复或首句音频超时")
            first = lambda kind: next(event["seconds"] for event in events if event["kind"] == kind)
            result = {"turn": index + 1, "first_delta": first("delta"), "first_sentence": first("sentence"),
                "reply_complete": first("complete"), "first_audio": first("audio"),
                "sentence_before_complete": first("sentence") < first("complete"),
                "audio_before_complete": first("audio") < first("complete"), "events": list(events)}
            assert result["sentence_before_complete"]
            report["turns"].append(result)
            print(json.dumps({key: value for key, value in result.items() if key != "events"}), flush=True)
            await gui(lambda: window.chat_dialog.grab().save(str(project_path(f".runtime/streaming-live-{index + 1}.png"))))
            await gui(window.stop_chat)
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
            QTimer.singleShot(100, watch)
    watch()
    app.exec()
    window.cleanup()
    window.hide()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/streaming-live-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
