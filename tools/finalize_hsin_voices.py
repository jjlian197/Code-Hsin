"""仅在两种语言各有第 20 轮 S1/S2 权重时发布应用音色配置。"""
import hashlib
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    profiles = {}
    for language in ("zh", "ja"):
        out = ROOT / "voice" / ("hsin_" + language)
        candidates = json.loads((out / "reference_candidates.json").read_text(encoding="utf8"))
        ref = next(item for item in candidates if item["title"] in ("入队1", "チームに編入・その一"))
        with wave.open(ref["wav"], "rb") as audio:
            if not 3 <= audio.getnframes() / audio.getframerate() <= 10 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise ValueError(f"{language} 参考原声格式或长度不合适")
        gpt = list((out / "weights/GPT").glob("*-e20.ckpt"))
        sovits = list((out / "weights/SoVITS").glob("*_e20_s*.pth"))
        if len(gpt) != 1 or len(sovits) != 1:
            raise ValueError(f"{language} 尚未生成唯一的第 20 轮 S1/S2 权重")
        weights = {"gpt_weights": str(gpt[0]), "sovits_weights": str(sovits[0])}
        profile = {**weights, "reference_audio": ref["wav"], "prompt_text": ref["text"],
                   "language": language, "epochs_s1": 20, "epochs_s2": 20,
                   "training_rows": len((out / f"hsin_{language}.list").read_text(encoding="utf8").splitlines()),
                   "listening_review": "not_performed_user_requested_direct_execution"}
        # 按当前安装版 S1 的实际限制记录重复补齐前的有效素材数。
        phones = {row.split("\t")[0]: len(row.split("\t")[1].split()) for row in
                  (out / "experiment/2-name2text.txt").read_text(encoding="utf8").splitlines()}
        eligible, filtered = [], []
        for row in (out / "experiment/6-name2semantic.tsv").read_text(encoding="utf8").splitlines()[1:]:
            name, tokens = row.split("\t")
            seconds = len(tokens.split()) / 25
            ratio = phones[name] / seconds
            (eligible if seconds <= 54 and phones[name] <= 540 and 3 <= ratio <= 25 else filtered).append(name)
        profile["s1_eligible_rows"] = len(eligible)
        profile["s1_filtered_files"] = filtered
        s2_eligible, s2_filtered = [], []
        # 安装版 S2 分桶范围为 (32, 1900] 帧，hop 640；超桶样本不参与采样。
        for name in phones:
            size = (out / "experiment/5-wav32k" / name).stat().st_size
            (s2_eligible if 0.6 < size / 64000 < 54 and 32 < size // 1280 <= 1900
             else s2_filtered).append(name)
        profile["s2_eligible_rows"] = len(s2_eligible)
        profile["s2_filtered_files"] = s2_filtered
        validation_path = ROOT / ".runtime" / f"weight-validation-{language}.json"
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf8"))
            if validation.get("success") and Path(validation["gpt"]["path"]) == gpt[0] and Path(validation["sovits"]["path"]) == sovits[0]:
                profile["checkpoint_validation"] = validation
        profile["sha256"] = {key: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                             for key, path in {**weights, "reference_audio": ref["wav"]}.items()}
        profiles[language] = profile
        (out / "configs/trained_voice.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf8")
    prep = json.loads((ROOT / "voice/hsin_zh/configs/preprocess.json").read_text(encoding="utf8"))
    installation = json.loads((ROOT / "voice/hsin_zh/configs/installation.json").read_text(encoding="utf8"))
    data = {"profiles": profiles, "installation": {**installation, **prep}}
    data["profile_id"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    (ROOT / "voice/profiles.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
