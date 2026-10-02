"""默认离线验收；--live 另行打开麦克风并调用智谱/Hermes/TTS。"""
import argparse
import asyncio
import audioop
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback
import wave
from unittest.mock import patch
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def fixture(language):
    with wave.open(str(project_path(f"voice/samples/hsin_{language}_1.wav")), "rb") as audio:
        pcm = audio.readframes(audio.getnframes())
        rate, width, channels = audio.getframerate(), audio.getsampwidth(), audio.getnchannels()
    if channels == 2:
        pcm = audioop.tomono(pcm, width, .5, .5)
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    return audioop.ratecv(pcm, 2, 1, rate, 16000, None)[0] + bytes(64000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="打开麦克风并将固定样本发送到真实云端识别和对话后端")
    live = parser.parse_args().live
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_stt_desktop"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    temp = tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"] = temp.name
    config["voice"].update(enabled=True, volume=0)
    config["chat"]["provider"] = "hermes"
    if not live:
        config["stt"].update(provider="whisper", fallback=False)
    class OfflineBackend:
        async def chat(self, text, language, on_delta):
            await asyncio.sleep(.2)
            reply = "御者，我在这里。" if language == "zh" else "御者、ここにいるわ。"
            await on_delta(reply)
            return reply
    mocked_chat = patch("src.core.chat_manager.make_backend", return_value=OfflineBackend()) if not live else None
    if mocked_chat:
        mocked_chat.start()
    window = HsinSpriteWindow(config)
    if not live:
        # 离线检查不打开麦克风、不联网；真实录音另外由 --live 验证。
        window.stt._start_capture = lambda: None
        window.tts.provider.synthesize = lambda text, language, *args: project_path(f"voice/samples/hsin_{language}_1.wav")
    window.tts.provider.runtime = project_path(".runtime/tts")
    probe = GuiProbe(window)
    window.show_sprite()
    result = {"success": False, "mode": "live" if live else "offline", "chat_and_tts_mocked": not live, "checks": [], "failures": []}
    pool = ThreadPoolExecutor(1)

    async def gui(function):
        def invoke(future):
            try:
                future.set_result(function())
            except Exception as exc:
                future.set_exception(exc)
        return await probe.call(invoke)

    async def until(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await gui(predicate):
                return
            await asyncio.sleep(.05)
        raise AssertionError("验收等待超时")

    async def verify():
        await until(lambda: window.sprite_view.model_loaded, 60)
        assert not await gui(lambda: window.stt.enabled)
        # 硬件检查时替换提交入口，保证现场声音绝不送到 ASR。
        original = await gui(lambda: window.stt._submit)
        await gui(lambda: setattr(window.stt, "_submit", lambda pcm: window.stt._segmenter.reset()))
        await gui(lambda: window.stt.configure(enabled=True))
        await asyncio.sleep(1.5)
        mic = await gui(window.stt.snapshot)
        assert (mic["listening"] if live else not mic["listening"]) and not mic["error"], mic
        await gui(lambda: window.stt.configure(enabled=False))
        assert await gui(lambda: window.stt.source is None and not window.stt.timer.isActive())
        await gui(lambda: setattr(window.stt, "_submit", original))
        result["checks"].append({"microphone_open_and_release": True if live else "not tested", "devices": await gui(window.stt.devices)})
        print("PASS capture lifecycle" + (" with native microphone" if live else " (hardware unopened in offline mode)"), flush=True)

        for language in ("zh", "ja"):
            pcm = fixture(language)
            def inject():
                window.tts.configure(language=language)
                window.open_chat()
                # 合成测试样本的标点停顿较长，验收使用 1.6 秒断句。
                window.stt.configure(enabled=True, language=language, silence_ms=1600)
                window.stt.timer.stop()
                window.stt._stop_capture()
                window.stt._cooldown = 0
                window.stt.feed_pcm(pcm)
                return window.stt.snapshot()
            state = await gui(inject)
            assert state["recognizing"], state
            await until(lambda: not window.stt.busy, 70)
            state = await gui(window.stt.snapshot)
            assert state["last_text"] and not state["error"], state
            words = ("这里", "散步") if language == "zh" else ("ここ", "散歩")
            assert any(word in state["last_text"] for word in words), state
            assert await gui(lambda: window.chat.busy and window.stt.blocked and window.stt.source is None)
            # 心回复期间注入同一语音，不能再识别或提交下一轮。
            await gui(lambda: window.stt.feed_pcm(pcm))
            assert await gui(lambda: not window.stt.busy and len(window.stt._buffer) == 0)
            await until(lambda: not window.chat.busy, 100)
            chat = await gui(window.chat.snapshot)
            assert not chat["error"] and chat["reply"], chat
            peak = 0.0
            playing = False
            deadline = time.monotonic() + 200
            while time.monotonic() < deadline:
                tts = await gui(window.tts.snapshot)
                audio = await gui(window.voice_player.snapshot)
                assert not tts["error"] and not audio["error"], (tts, audio)
                if audio["state"] == "PlayingState":
                    playing = True
                    assert await gui(lambda: window.stt.blocked and window.stt.source is None)
                peak = max(peak, (await probe.state())["behavior"]["mouth_open"])
                if playing and not tts["synthesizing"] and audio["state"] == "StoppedState":
                    break
                await asyncio.sleep(.04)
            assert playing and peak > .15, (tts, audio, peak)
            await gui(lambda: window.stt.configure(enabled=False))
            result["checks"].append({"language": language, "recognized": state["last_text"],
                "provider": state["actual_provider"], "warning": state["warning"], "reply": chat["reply"],
                "mouth_peak": peak, "reply_blocks_input": True})
            print(f"PASS {language}: VAD -> real STT -> {'Hermes/TTS' if live else 'mock chat/TTS fixture'} -> PCM mouth, echo blocked", flush=True)
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
    QTimer.singleShot(600000, app.quit)
    try:
        app.exec()
    finally:
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
        if mocked_chat:
            mocked_chat.stop()
    project_path(".runtime/stt-desktop-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": result["success"], "failures": result["failures"]}), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
