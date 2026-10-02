#!/usr/bin/env python3
"""从 wuwa.wiki 公开页面下载心的日语原声，并按日文原文生成清单。"""
import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

try:
    from .prepare_kurobbs_voice import configs, write_json
except ImportError:
    from prepare_kurobbs_voice import configs, write_json

PAGE = "https://wuwa.wiki/ja/codex/resonators/1311?nav=voices"
EXPLORATION = {"play_favor_word_xin_com_fly_01", "play_favor_word_xin_com_scan"}


def request(url):
    # 只使用网站页面公开的地址；遇到拒绝访问或限流不重试。
    req = urllib.request.Request(url, headers={"User-Agent": "HsinVoiceDataset/1.0", "Referer": PAGE})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def decode_page(source):
    match = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', source, re.S)
    if not match:
        raise ValueError("页面缺少公开角色数据")
    values = json.loads(match.group(1))
    cache = {}

    def decode(index):
        if index < 0:
            return None
        if index in cache:
            return cache[index]
        value = values[index]
        if isinstance(value, dict):
            result = {}
            cache[index] = result
            result.update({k: decode(v) for k, v in value.items()})
            return result
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                if value[0] not in {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyShallowRef", "Set"}:
                    raise ValueError(f"未知页面数据类型: {value[0]}")
                return decode(value[1]) if len(value) > 1 else None
            result = []
            cache[index] = result
            result.extend(decode(v) for v in value)
            return result
        return value

    return decode(0)


def clean_japanese(value):
    # 采用页面明确标注的读音，避免把 ruby 基字当作实际发音。
    value = re.sub(r"<ano=([^>]+)>.*?</ano>", lambda m: m[1], value, flags=re.S)
    value = re.sub(r"<br\s*/?>", " ", value)
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def extract(source):
    if not re.search(r'<html\s+[^>]*lang="ja"', source):
        raise ValueError("必须使用日文页面，不能把中文译文配到日语音频")
    payload = decode_page(source)
    responses = [v for v in payload["data"].values() if isinstance(v, dict) and "voices" in v.get("data", {})]
    if len(responses) != 1 or responses[0].get("code") != 1000 or responses[0]["data"]["id"] != 1311:
        raise ValueError("角色资料不匹配")
    base_match = re.search(r'ossPublicBaseURL:"([^"]+)"', source)
    if not base_match:
        raise ValueError("页面缺少公开音频资源地址")
    base = base_match[1]
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".wutheringwaves.wiki"):
        raise ValueError("非预期资源域名")
    role = responses[0]["data"]
    selected, excluded, missing, seen = [], [], [], set()
    for category, records in role["voices"].items():
        if category not in {"personal", "battle"}:
            raise ValueError(f"未知语音分类: {category}")
        for item in records:
            key, event = str(item["id"]), item.get("file", "")
            if not key.isdigit() or key in seen or not re.fullmatch(r"play_favor_word_xin2?_[a-z0-9_]+", event):
                raise ValueError(f"重复或非法音频记录: {key}")
            seen.add(key)
            text = clean_japanese(item.get("content", ""))
            if "|" in text:
                raise ValueError(f"台词包含清单分隔符: {key}")
            row = {"key": key, "title": item["title"], "category": category, "event": event,
                   "text": text, "source_text": item.get("content", ""), "language": "ja", "language_tab": "日本語",
                   "audio_url": base + "/transform/kuro/gameclient/Content/Aki/WwiseAudio_Generated/Event/" + event + "_ja.opus",
                   "raw_file": f"Hsin_JA_{key}.opus", "file": f"Hsin_JA_{key}.wav"}
            if not text:
                missing.append(row)
            if (category == "personal" or event in EXPLORATION) and text:
                row["selection_reason"] = "personality" if category == "personal" else "exploration_exception"
                selected.append(row)
            else:
                row["exclusion_reason"] = "combat_or_missing_original_text"
                excluded.append(row)
    if not selected:
        raise ValueError("未找到可配对的日语语音")
    return {"character": role["name"], "character_id": 1311, "speaker": "Hsin", "language": "ja",
            "source_page": PAGE, "requested_page": "https://wuwa.wiki/zh-hant/codex/resonators/1311?nav=voices",
            "generated_at": datetime.now(timezone.utc).isoformat(), "selected": selected,
            "excluded_combat": excluded, "missing_text": missing, "missing_audio": [],
            "asr_verification": "skipped_at_user_request", "human_listening_review": "not_performed; not_required_by_user",
            "verification_method": "source_record_audio_text_pairing_and_pcm_signal_checks"}


def prepare_audio(manifest, out, ffmpeg, download, include_combat, max_sec):
    raw, wavdir = out / "raw", out / "wav32k"
    raw.mkdir(exist_ok=True)
    wavdir.mkdir(exist_ok=True)
    training, calm, all_lines, candidates, failures = [], [], [], [], []
    selected = {row["key"] for row in manifest["selected"]}
    records = manifest["selected"] + (manifest["excluded_combat"] if include_combat else [])
    for index, row in enumerate(records, 1):
        source, target = raw / row["raw_file"], wavdir / row["file"]
        try:
            if download and not source.is_file():
                data = request(row["audio_url"])
                if not data.startswith(b"OggS") or b"OpusHead" not in data[:512]:
                    raise ValueError("下载结果不是 Ogg Opus 音频")
                part = source.with_suffix(".part")
                part.write_bytes(data)
                part.replace(source)
                time.sleep(0.35)
            data = source.read_bytes()
            if not data.startswith(b"OggS") or b"OpusHead" not in data[:512]:
                raise ValueError("原声格式错误")
            if not target.is_file():
                part = target.with_suffix(".part.wav")
                subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(source), "-ac", "1", "-ar", "32000",
                                "-c:a", "pcm_s16le", "-y", str(part)], check=True)
                part.replace(target)
            with wave.open(str(target), "rb") as audio:
                if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) != (1, 32000, 2, "NONE"):
                    raise ValueError("WAV 格式错误")
                duration = audio.getnframes() / audio.getframerate()
                samples = array("h", audio.readframes(audio.getnframes()))
            if sys.byteorder != "little":
                samples.byteswap()
            rms = math.sqrt(sum(float(s) * s for s in samples) / max(1, len(samples))) / 32768
            clipped = sum(abs(s) >= 32735 for s in samples) / max(1, len(samples))
            passed = rms >= 0.001 and clipped <= 0.005
            row.update({"wav": target.resolve().as_posix(), "raw": source.resolve().as_posix(),
                        "raw_sha256": hashlib.sha256(data).hexdigest(), "wav_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        "duration_seconds": round(duration, 3), "signal_checks": {"rms": round(rms, 6), "clipped_fraction": round(clipped, 6), "passed": passed},
                        "review_status": "source_metadata_paired_and_format_checked", "training_eligible": False})
            line = f"{row['wav']}|Hsin|ja|{row['text']}"
            if row["text"]:
                all_lines.append(line)
            if row["key"] in selected:
                calm.append(line)
                if 0 < duration <= max_sec and passed:
                    row["training_eligible"] = True
                    training.append(line)
                else:
                    row["training_exclusion"] = (f"duration_exceeds_template_max_sec_{max_sec}; needs_aligned_segmentation"
                                                 if duration > max_sec else "signal_check_failed")
                if passed and 3 <= duration <= 10:
                    candidates.append({k: row[k] for k in ("key", "title", "wav", "text", "duration_seconds", "review_status")})
            print(f"{index}/{len(records)} {row['title']}: {duration:.2f}s", flush=True)
        except Exception as exc:
            failures.append({"key": row["key"], "error": str(exc)})
            print(f"FAILED {row['key']}: {exc}", flush=True)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429):
                break
    for name, lines in (("hsin_ja.list", training), ("hsin_ja.draft.list", training),
                        ("hsin_ja.calm.all.list", calm), ("hsin_ja.archive.list", all_lines)):
        (out / name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    write_json(out / "reference_candidates.json", candidates)
    manifest["preparation_failures"] = failures
    manifest["statistics"] = {"source_records": len(selected) + len(manifest["excluded_combat"]),
        "selected": len(selected), "excluded_combat": len(manifest["excluded_combat"]), "prepared": len(all_lines),
        "draft_training_rows": len(training), "reference_candidates": len(candidates), "missing_text": len(manifest["missing_text"]),
        "total_duration_seconds": round(sum(r.get("duration_seconds", 0) for r in records), 3),
        "selected_duration_seconds": round(sum(r.get("duration_seconds", 0) for r in manifest["selected"]), 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("voice/hsin_ja"))
    parser.add_argument("--gsv-root", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--include-combat", action="store_true", help="战斗语音一并归档，但不进入训练清单")
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    out, gsv = args.out.resolve(), args.gsv_root.resolve()
    (out / "source").mkdir(parents=True, exist_ok=True)
    page = out / "source/page_ja.html"
    if args.fetch:
        source = request(PAGE).decode("utf-8-sig")
        extract(source)
        page.write_text(source, encoding="utf-8")
    manifest = extract(page.read_text(encoding="utf-8-sig"))
    max_sec = configs(gsv, out, language="ja")
    prepare_audio(manifest, out, args.ffmpeg or gsv / "ffmpeg.exe", args.download, args.include_combat, max_sec)
    write_json(out / "selection.json", manifest)
    template = Path(__file__).with_name("voice_review_template.html").read_text(encoding="utf-8")
    template = template.replace("中配原声审听", "日配原声试听")
    rows = [{**r, "audio": "wav32k/" + r["file"]} for r in manifest["selected"] if "wav" in r]
    (out / "review.html").write_text(template.replace("__VOICE_DATA__", json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")), encoding="utf-8")
    print(json.dumps(manifest["statistics"], ensure_ascii=False))
    if manifest["preparation_failures"]:
        raise SystemExit("部分音频未准备成功，请查看 selection.json")


if __name__ == "__main__":
    main()
