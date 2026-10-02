"""用训练清单之外的文本验证两种语言的真实合成，并导出可试听样本。"""
import array
import json
from pathlib import Path
import shutil
import time
import wave
import unicodedata

from src.core.tts_manager import LocalSynthesizer
from src.core.voice_phrases import TOUCH_REPLIES

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    ("zh", "御者，我在这里。今天也一起去散步吧。"),
    ("ja", "御者、ここにいるわ。今日は一緒に散歩しましょう。"),
    ("zh", "夜已经深了，记得早点休息。明天再来找我说话吧。"),
    ("ja", "もう夜も遅いわ。ゆっくり休んで、また明日お話しましょう。"),
]


def main():
    target = ROOT / "voice/samples"
    target.mkdir(exist_ok=True)
    provider = LocalSynthesizer(ROOT / "voice/profiles.json", ROOT / ".runtime", 19880)
    report = {"listening_review": "not_performed", "samples": []}
    try:
        for index, (language, text) in enumerate(SAMPLES):
            source = ROOT / "voice" / ("hsin_" + language) / f"hsin_{language}.list"
            original_texts = {unicodedata.normalize("NFKC", row.split("|", 3)[3]).strip()
                              for row in source.read_text(encoding="utf8").splitlines()}
            assert unicodedata.normalize("NFKC", text).strip() not in original_texts, "验收文本不能直接复述训练清单"
            start = time.monotonic()
            path = provider.synthesize(text, language, 1)
            elapsed = time.monotonic() - start
            destination = target / f"hsin_{language}_{index // 2 + 1}.wav"
            shutil.copy2(path, destination)
            with wave.open(str(path), "rb") as audio:
                samples = array.array("h", audio.readframes(audio.getnframes()))
                duration = len(samples) / audio.getframerate()
            peak = max(abs(value) for value in samples) / 32768
            rms = (sum(value * value for value in samples) / len(samples)) ** 0.5 / 32768
            clipped = sum(abs(value) >= 32760 for value in samples) / len(samples)
            if not 1 <= duration <= 30 or not 0.01 <= rms <= 0.4 or clipped > 0.01:
                raise ValueError(f"{language} 音频长度/幅度异常: {duration}, {rms}, {clipped}")
            cached = provider.synthesize(text, language, 1)
            assert cached == path
            report["samples"].append({"language": language, "text": text, "path": str(destination),
                "duration_seconds": duration, "synthesis_seconds": elapsed, "peak": peak,
                "rms": rms, "clipped_fraction": clipped, "cache_verified": True})
            report["samples"][-1]["unseen_text_verified"] = True
            (target / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
            print(f"Validated {language} sample {index // 2 + 1}: {duration:.2f}s", flush=True)
        report["success"] = True
        # 常用触摸台词预生成到正式缓存，日常点击无需再次等待推理。
        report["touch_cache"] = []
        for language, replies in TOUCH_REPLIES.items():
            for part, text in replies.items():
                path = provider.synthesize(text, language, 1)
                report["touch_cache"].append({"language": language, "part": part, "path": str(path)})
                print(f"Cached {language} touch {part}", flush=True)
        (target / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    finally:
        provider.close()


if __name__ == "__main__":
    main()
