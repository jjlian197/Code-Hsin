#!/usr/bin/env python3
"""独立核验本地原声、正式训练清单及 GPT-SoVITS 配置路径。"""
import hashlib
import json
import wave
from pathlib import Path
import yaml


def main():
    out = Path("voice/hsin_zh").resolve()
    manifest = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    by_wav = {r["wav"]: r for r in manifest["selected"]}
    assert len(by_wav) == len(manifest["selected"]), "音频路径重复"
    for row in manifest["selected"]:
        raw, wav = out / "raw" / row["file"], Path(row["wav"])
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == row["raw_sha256"]
        assert hashlib.sha256(wav.read_bytes()).hexdigest() == row["wav_sha256"]
        with wave.open(str(wav), "rb") as stream:
            assert (stream.getnchannels(), stream.getframerate(), stream.getsampwidth()) == (1, 32000, 2)
            assert abs(stream.getnframes() / stream.getframerate() - row["duration_seconds"]) <= 0.001
    approved = {r["wav"] for r in manifest["selected"] if r["training_eligible"] and r["signal_checks"]["passed"]}
    lines = (out / "hsin_zh.list").read_text(encoding="utf-8").splitlines()
    assert lines and len(lines) == len(approved)
    for line in lines:
        wav, speaker, lang, text = line.split("|")
        assert wav in approved and speaker == "Hsin" and lang == "zh"
        assert text == by_wav[wav]["text"]
    configdir = out / "configs"
    s1 = yaml.safe_load((configdir / "s1_hsin.yaml").read_text(encoding="utf-8"))
    s2 = json.loads((configdir / "s2_hsin.json").read_text(encoding="utf-8"))
    prep = json.loads((configdir / "preprocess.json").read_text(encoding="utf-8"))
    assert Path(prep["inp_text"]) == out / "hsin_zh.list"
    assert s1["train"]["exp_name"] == s2["name"] == prep["exp_name"] == "HsinZH"
    assert s2["version"] == s2["model"]["version"] == prep["version"] == "v2ProPlus"
    for path in [s1["pretrained_s1"], s2["train"]["pretrained_s2G"], s2["train"]["pretrained_s2D"],
                 prep["bert_pretrained_dir"], prep["cnhubert_base_dir"], prep["sv_path"]]:
        assert Path(path).exists(), path
    for path in [s1["train"]["half_weights_save_dir"], s1["train_semantic_path"], s1["train_phoneme_path"],
                 s1["output_dir"], s2["data"]["exp_dir"], s2["save_weight_dir"], prep["opt_dir"]]:
        assert Path(path).is_relative_to(out), "输出路径越界"
    assert all(by_wav[wav]["duration_seconds"] <= s1["data"]["max_sec"] for wav in approved)
    installation = json.loads((configdir / "installation.json").read_text(encoding="utf-8"))
    root = Path(installation["gptsovits_root"])
    s1_template = yaml.safe_load((root / "GPT_SoVITS/configs/s1longer-v2.yaml").read_text(encoding="utf-8"))
    s2_template = json.loads((root / "GPT_SoVITS/configs/s2v2ProPlus.json").read_text(encoding="utf-8"))
    for key in ("optimizer", "data", "model", "inference"):
        assert s1[key] == s1_template[key], f"S1 模板字段被意外修改: {key}"
    for key in s2_template["train"]:
        assert s2["train"][key] == s2_template["train"][key], f"S2 模板字段被意外修改: {key}"
    assert manifest["asr_verification"] == "skipped_at_user_request"
    print(f"通过：{len(by_wav)} 条原声及 WAV、{len(lines)} 条来源配对训练数据、预训练资源及配置输出路径（未做 ASR）")


if __name__ == "__main__":
    main()
