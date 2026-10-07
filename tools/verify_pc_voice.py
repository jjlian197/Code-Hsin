"""真实 PC 合成 → Mac 双句播放与 PMX 口型；不用麦克风、不连接聊天后端。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.50.230")
    parser.add_argument("--voice-id", choices=("hsin", "aemeath"), default="hsin")
    parser.add_argument("--language", choices=("zh", "ja"), default="zh")
    parser.add_argument("--character-package", type=Path)
    parser.add_argument("--existing-tunnel", action="store_true", help="复用运行中应用的本机 SSH 转发")
    options = parser.parse_args()
    config = load_config()
    report_root = project_path(".runtime")
    report_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hsin-pc-voice-") as directory:
        config["runtime"]["directory"] = directory
        config["chat"]["enabled"] = False
        config["speech_bridge"].update(url="http://127.0.0.1:19881", ssh_host="" if options.existing_tunnel else options.host)
        config["voice"].update(enabled=True, provider="remote", remote_voice=options.voice_id,
                               language=options.language, auto_translate=False, fallback=False)
        config["stt"]["provider"] = "remote"
        application = QApplication(["hsin-pc-voice-verification"])
        window = HsinSpriteWindow(config)
        if options.character_package:
            window.sprite_view.load_character(options.character_package)
        window.show_sprite()
        sentences = ["御者，我已经连接电脑上的语音服务。", "这是第二句，声音会按顺序播放，嘴巴也会跟着动。"]
        if options.voice_id == "aemeath":
            sentences = (["父亲，我是爱弥斯，现在可以用自己的声音陪伴你了。", "今天也让爱弥斯陪你度过吧。"]
                         if options.language == "zh" else ["父さん、私はエイメス。そばにいるよ。", "今日も一緒に過ごしましょう。"])
        report_name = "pc-voice" if options.voice_id == "hsin" else f"pc-voice-{options.voice_id}-{options.language}"
        report: dict[str, Any] = {"success": False, "scope": "真实 PC 推理与播放队列；未连接 LLM、未开麦",
                                  "played_sentences": [], "mouth_peak": 0.0, "pcm_peak": 0.0, "pcm_buffers": 0,
                                  "failures": []}
        started = time.monotonic()
        phase = "loading"
        timer = QTimer()
        timer.setInterval(50)

        def playing(text: str) -> None:
            report["played_sentences"].append({"text": text, "at_seconds": time.monotonic() - started,
                                               "state": window.voice_player.player.playbackState().name})
            print("Playing: " + text, flush=True)

        window.tts.speech_started.connect(playing)

        def finish() -> None:
            timer.stop()
            report["success"] = not report["failures"]
            report["health"] = window.tts.remote.client.last_health
            report["mic_enabled"] = window.stt.enabled
            report["chat_enabled"] = window.chat.config.get("enabled", True)
            window.grab().save(str(report_root / (report_name + "-preview.png")))
            (report_root / (report_name + "-playback-validation.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2))
            window.cleanup()
            window.close()
            application.quit()

        def tick() -> None:
            nonlocal phase
            try:
                if time.monotonic() - started > 180:
                    raise TimeoutError("PC 合成/播放验证超时")
                assert not window.stt.enabled, "验证不得开启麦克风"
                if window.sprite_view.load_error:
                    raise RuntimeError(window.sprite_view.load_error)
                if window.tts.error:
                    raise RuntimeError(window.tts.error)
                if phase == "loading" and window.sprite_view.model_loaded:
                    stream = window.tts.begin_stream(options.language, source="verification")
                    for sentence in sentences:
                        assert window.tts.enqueue_sentence(stream, sentence, options.language)
                    window.tts.finish_stream(stream)
                    phase = "playing"
                if phase == "playing":
                    playback = window.voice_player.snapshot()
                    report["pcm_peak"] = max(report["pcm_peak"], playback["peak_level"])
                    report["pcm_buffers"] = max(report["pcm_buffers"], playback["buffer_count"])
                    runtime = window.sprite_view.model_info.get("runtime", {})
                    behavior = runtime.get("behavior", {})
                    report["mouth_peak"] = max(report["mouth_peak"], behavior.get("mouth_open", 0))
                    state = window.tts.snapshot()
                    if len(report["played_sentences"]) == 2 and state["stage"] == "idle":
                        assert [event["text"] for event in report["played_sentences"]] == sentences
                        assert all(event["state"] == QMediaPlayer.PlaybackState.PlayingState.name for event in report["played_sentences"])
                        assert report["pcm_peak"] > 0.05 and report["pcm_buffers"] > 2
                        assert report["mouth_peak"] > 0.05, "PMX 口型未响应真实音频"
                        finish()
            except Exception as exc:
                report["failures"].append(str(exc))
                finish()

        timer.timeout.connect(tick)
        timer.start()
        application.exec()
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
