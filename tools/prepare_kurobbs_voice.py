#!/usr/bin/env python3
"""库街区角色原声 → 可追溯的 GPT-SoVITS 数据清单与本机版本配置。"""
import argparse
from array import array
import csv
import hashlib
import html
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

import yaml

ENTRY_API = "https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail"
EXPLORATION = {"滑翔", "感知"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request(url, data=None):
    headers = {"User-Agent": "HsinVoiceDataset/1.0", "Referer": "https://wiki.kurobbs.com/"}
    if data is not None:
        headers.update({"source": "h5", "wiki_type": "9", "Content-Type": "application/x-www-form-urlencoded"})
        data = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=60) as response:
        return response.read()


def clean_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value or "")).split())


def extract(payload, entry_id):
    if payload.get("code") != 200 or str(payload["data"]["id"]) != entry_id:
        raise ValueError("角色资料响应不正确")
    content = payload["data"]["content"]
    selected, excluded, missing_text, missing_audio = [], [], [], []
    seen = set()
    for module in content.get("modules", []):
        for component in module.get("components", []):
            if component.get("type") != "audio-component":
                continue
            category = component.get("title", "")
            for tab in component.get("mediaTabs", []):
                if not tab.get("title", "").startswith("中文"):
                    continue
                for media in tab.get("mediaList", []):
                    key = str(media["id"])
                    if not key.isdigit() or key in seen:
                        raise ValueError(f"重复或非法音频 ID: {key}")
                    seen.add(key)
                    title = media.get("audioTitle", "")
                    text = clean_text(media.get("content"))
                    url = media.get("playUrl", "")
                    parsed = urllib.parse.urlparse(url)
                    if url and (parsed.scheme != "https" or parsed.hostname != "web-static.kurobbs.com" or not parsed.path.startswith("/wiki_audio/")):
                        raise ValueError(f"非预期的音频来源: {url}")
                    row = {"key": key, "title": title, "category": category, "language_tab": tab["title"],
                           "text": text, "source_text": media.get("content", ""), "audio_url": url,
                           "source_file_size": media.get("fileSize"), "file": f"Hsin_ZH_{key}.wav",
                           "review_status": "unreviewed"}
                    if not text:
                        missing_text.append(row)
                    if not url:
                        missing_audio.append(row)
                    if category == "个性语音" or (category == "战斗语音" and title in EXPLORATION):
                        row["selection_reason"] = "personality" if category == "个性语音" else "exploration_exception"
                        if text and url:
                            if "|" in text:
                                raise ValueError(f"台词含清单分隔符: {key}")
                            selected.append(row)
                    else:
                        row["exclusion_reason"] = "combat_or_unknown_category"
                        excluded.append(row)
    if not selected:
        raise ValueError("没有找到配对的中文语音；需要检查网页结构")
    return {"character": payload["data"]["name"], "speaker": "Hsin", "language": "zh",
            "source_page": f"https://wiki.kurobbs.com/mc/item/{entry_id}", "api": ENTRY_API,
            "entry_version": payload["data"].get("currentVersion"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "selected": selected, "excluded_combat": excluded,
            "missing_text": missing_text, "missing_audio": missing_audio}


def prepare_audio(manifest, out, download, prepare, ffmpeg, max_sec):
    raw, wavdir = out / "raw", out / "wav32k"
    raw.mkdir(exist_ok=True)
    wavdir.mkdir(exist_ok=True)
    lines, all_lines, failures, candidates = [], [], [], []
    for row in manifest["selected"]:
        source, target = raw / row["file"], wavdir / row["file"]
        try:
            if download and not source.is_file():
                data = request(row["audio_url"])
                # 先核验 WAV 容器，再保存；不把错误页当音频。
                if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                    raise ValueError("下载结果不是 WAV")
                part = source.with_suffix(".part")
                part.write_bytes(data)
                part.replace(source)
                time.sleep(0.35)
            if not source.is_file():
                raise FileNotFoundError(source)
            row["raw_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            if prepare and not target.is_file():
                part = target.with_suffix(".part.wav")
                subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", str(source), "-ac", "1", "-ar", "32000",
                                "-c:a", "pcm_s16le", "-y", str(part)], check=True)
                part.replace(target)
            if not target.is_file():
                continue
            with wave.open(str(target), "rb") as audio:
                if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) != (1, 32000, 2, "NONE"):
                    raise ValueError("WAV 格式不符合训练规范")
                duration = audio.getnframes() / audio.getframerate()
                samples = array("h", audio.readframes(audio.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
                rms = math.sqrt(sum(float(s) * s for s in samples) / max(1, len(samples))) / 32768
                clipped = sum(abs(s) >= 32735 for s in samples) / max(1, len(samples))
            row.update({"wav": target.resolve().as_posix(), "duration_seconds": round(duration, 3),
                        "wav_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
            line = f"{row['wav']}|Hsin|zh|{row['text']}"
            all_lines.append(line)
            # 不只截音频：过长素材保留全文，等待音频和文本同步切分。
            row["signal_checks"] = {"rms": round(rms, 6), "clipped_fraction": round(clipped, 6),
                                    "passed": rms >= 0.001 and clipped <= 0.005}
            row["review_status"] = "source_metadata_paired_and_format_checked"
            row["training_eligible"] = 0 < duration <= max_sec and row["signal_checks"]["passed"]
            if row["training_eligible"]:
                lines.append(line)
            else:
                row["training_exclusion"] = (f"duration_exceeds_template_max_sec_{max_sec}; needs_aligned_segmentation"
                    if duration > max_sec else "signal_check_failed")
            if 3 <= duration <= 10:
                candidates.append({k: row[k] for k in ("key", "title", "wav", "text", "duration_seconds", "review_status")})
            print(f"{row['title']}: {duration:.2f}s", flush=True)
        except urllib.error.HTTPError as exc:
            # 限流、拒绝访问立即停止；不重试绕过。
            failures.append({"key": row["key"], "error": str(exc)})
            if exc.code in (401, 403, 429):
                break
        except Exception as exc:
            failures.append({"key": row["key"], "error": str(exc)})
    (out / "hsin_zh.all.list").write_text("\n".join(all_lines) + ("\n" if all_lines else ""), encoding="utf-8")
    (out / "hsin_zh.draft.list").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (out / "hsin_zh.list").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    manifest["verification_method"] = "source_record_audio_text_pairing_and_pcm_signal_checks"
    manifest["asr_verification"] = "skipped_at_user_request"
    manifest["human_listening_review"] = "not_performed; not_required_by_user"
    write_json(out / "reference_candidates.json", candidates)
    manifest["preparation_failures"] = failures
    manifest["statistics"] = {"selected": len(manifest["selected"]), "excluded_combat": len(manifest["excluded_combat"]),
        "missing_text": len(manifest["missing_text"]), "missing_audio": len(manifest["missing_audio"]),
        "prepared": len(all_lines), "draft_training_rows": len(lines), "reference_candidates": len(candidates),
        "total_duration_seconds": round(sum(r.get("duration_seconds", 0) for r in manifest["selected"]), 3)}
    review = out / "review.csv"
    if not review.exists():
        with review.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["key", "title", "duration_seconds", "wav", "text", "decision", "notes"])
            writer.writeheader()
            for row in manifest["selected"]:
                writer.writerow({**{k: row.get(k, "") for k in ("key", "title", "duration_seconds", "wav", "text")},
                                 "decision": "pending", "notes": ""})


def configs(gsv, out, language="zh"):
    if language not in ("zh", "ja"):
        raise ValueError(f"不支持的素材语言: {language}")
    configdir = out / "configs"
    configdir.mkdir(exist_ok=True)
    pre = gsv / "GPT_SoVITS/pretrained_models"
    s1_template = gsv / "GPT_SoVITS/configs/s1longer-v2.yaml"
    s2_template = gsv / "GPT_SoVITS/configs/s2v2ProPlus.json"
    s1 = yaml.safe_load(s1_template.read_text(encoding="utf-8"))
    s2 = json.loads(s2_template.read_text(encoding="utf-8"))
    exp = (out / "experiment").as_posix()
    name = "Hsin" + language.upper()
    paths = {"pretrained_s1": (pre / "s1v3.ckpt").as_posix(),
             "pretrained_s2G": (pre / "v2Pro/s2Gv2ProPlus.pth").as_posix(),
             "pretrained_s2D": (pre / "v2Pro/s2Dv2ProPlus.pth").as_posix(),
             "bert_pretrained_dir": (pre / "chinese-roberta-wwm-ext-large").as_posix(),
             "cnhubert_base_dir": (pre / "chinese-hubert-base").as_posix(),
             "sv_path": (pre / "sv/pretrained_eres2netv2w24s4ep4.ckpt").as_posix()}
    missing = [v for v in paths.values() if not Path(v).exists()]
    if missing:
        raise FileNotFoundError(f"缺少本机预训练资源: {missing}")
    s1["train"].update({"exp_name": name, "half_weights_save_dir": (out / "weights/GPT").as_posix(),
                        "if_save_latest": True, "if_save_every_weights": True, "if_dpo": False})
    s1.update({"pretrained_s1": paths["pretrained_s1"], "train_semantic_path": exp + "/6-name2semantic.tsv",
               "train_phoneme_path": exp + "/2-name2text.txt", "output_dir": exp + "/logs_s1_v2ProPlus"})
    # 训练超参数沿用本机模板，GPU 选择留给运行参数。
    s2["train"].update({"pretrained_s2G": paths["pretrained_s2G"], "pretrained_s2D": paths["pretrained_s2D"],
                       "if_save_latest": True, "if_save_every_weights": True, "save_every_epoch": 1,
                       "gpu_numbers": ""})
    s2["model"]["version"] = "v2ProPlus"
    s2["data"]["exp_dir"] = exp
    s2.update({"name": name, "version": "v2ProPlus", "s2_ckpt_dir": exp,
               "save_weight_dir": (out / "weights/SoVITS").as_posix()})
    (configdir / "s1_hsin.yaml").write_text(yaml.safe_dump(s1, allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_json(configdir / "s2_hsin.json", s2)
    prep = {"inp_text": (out / f"hsin_{language}.list").as_posix(), "inp_wav_dir": (out / "wav32k").as_posix(),
            "exp_name": name, "opt_dir": exp, "i_part": "0", "all_parts": "1", "version": "v2ProPlus",
            "hz": "25hz", "s2config_path": s2_template.as_posix(), **{k: v for k, v in paths.items() if k != "pretrained_s2D" and k != "pretrained_s1"}}
    write_json(configdir / "preprocess.json", prep)
    write_json(configdir / "installation.json", {"gptsovits_root": gsv.as_posix(), "python": (gsv / "runtime/python.exe").as_posix(),
               "version": "v2ProPlus", "templates": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (s1_template, s2_template)},
               "training_hyperparameters": "inherited_from_local_templates; not_tuned_for_hsin", "resources_missing": missing})
    return s1["data"]["max_sec"]


def review_artifacts(manifest, out, gsv):
    # 审听页面只用本地资源；下载后的音频不会上传。
    template = Path(__file__).with_name("voice_review_template.html").read_text(encoding="utf-8")
    rows = [{**r, "audio": "wav32k/" + r["file"]} for r in manifest["selected"] if "wav" in r]
    template = template.replace("__VOICE_DATA__", json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c"))
    (out / "review.html").write_text(template, encoding="utf-8")
    candidate = next((r for r in rows if r["title"] == "突破1" and 3 <= r["duration_seconds"] <= 10), None)
    if candidate:
        profile = {"tts": {"language": "zh", "gptsovits": {"enabled": False, "api_url": "http://127.0.0.1:9880/tts",
                    "default_profile": "zh", "text_split_method": "cut5", "media_type": "wav", "streaming_mode": False,
                    "profiles": {"zh": {"refer_audio_path": candidate["wav"], "prompt_text": candidate["text"],
                    "prompt_lang": "zh", "top_k": 15, "top_p": 1.0, "temperature": 1.0, "speed_factor": 1.0}}}}}
        (out / "configs/app_voice_profile.draft.yaml").write_text(
            "# 参考候选尚未审听；需训练出 Hsin 权重并加载后再启用。仅更换参考音频不会切换角色权重。\n" +
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        write_json(out / "configs/reference_request.draft.json", {"ref_audio_path": candidate["wav"],
                   "prompt_text": candidate["text"], "prompt_lang": "zh", "text": "御者，今天想一起去哪里走走？",
                   "text_lang": "zh", "text_split_method": "cut5", "media_type": "wav", "streaming_mode": False})
    infer_template = gsv / "GPT_SoVITS/configs/tts_infer.yaml"
    infer = yaml.safe_load(infer_template.read_text(encoding="utf-8"))["v2ProPlus"].copy()
    for key in ("bert_base_path", "cnhuhbert_base_path"):
        infer[key] = (gsv / infer[key]).as_posix()
    infer["t2s_weights_path"] = (out / "weights/GPT/SELECT_TRAINED_HSIN_WEIGHT.ckpt").as_posix()
    infer["vits_weights_path"] = (out / "weights/SoVITS/SELECT_TRAINED_HSIN_WEIGHT.pth").as_posix()
    (out / "configs/tts_infer_hsin.draft.yaml").write_text(
        "# 两个 SELECT_TRAINED_HSIN_WEIGHT 路径是占位符，训练完成后选取真实权重再启动独立服务。\n" +
        yaml.safe_dump({"custom": infer}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-id", default="1543050481616060416")
    parser.add_argument("--out", type=Path, default=Path("voice/hsin_zh"))
    parser.add_argument("--gsv-root", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    out, gsv = args.out.resolve(), args.gsv_root.resolve()
    (out / "source").mkdir(parents=True, exist_ok=True)
    source = out / "source/entry.json"
    if args.fetch:
        payload = json.loads(request(ENTRY_API, {"id": args.entry_id}))
        extract(payload, args.entry_id)  # 先验证再覆盖快照。
        write_json(source, payload)
    manifest = extract(json.loads(source.read_text(encoding="utf-8")), args.entry_id)
    max_sec = configs(gsv, out)
    prepare_audio(manifest, out, args.download, args.prepare, args.ffmpeg, max_sec)
    write_json(out / "selection.json", manifest)
    review_artifacts(manifest, out, gsv)
    print(json.dumps(manifest["statistics"], ensure_ascii=False))
    if manifest["preparation_failures"]:
        raise SystemExit("部分音频未准备成功，请查看 selection.json")


if __name__ == "__main__":
    main()
