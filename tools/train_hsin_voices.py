"""串行训练心的两种语言，断点由安装版训练器恢复，记录每步真实结果。"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    status = {"started": datetime.now(timezone.utc).isoformat(), "steps": []}
    report = ROOT / ".runtime/training-status.json"
    for language in ("ja", "zh"):
        out = ROOT / "voice" / ("hsin_" + language)
        # 固定本次 8 GB GPU 配方，避免重新准备素材后又退回安装模板的 batch 32。
        s2_path = out / "configs/s2_hsin.json"
        s2 = json.loads(s2_path.read_text(encoding="utf8"))
        s2["train"].update(batch_size=2, epochs=20, grad_ckpt=True, save_every_epoch=5)
        s2_path.write_text(json.dumps(s2, ensure_ascii=False, indent=2), encoding="utf8")
        s1_path = out / "configs/s1_hsin.yaml"
        s1 = yaml.safe_load(s1_path.read_text(encoding="utf8"))
        s1["train"].update(batch_size=2, epochs=20, save_every_n_epoch=5)
        # 安装版 DataLoader 固定 persistent_workers=True，不能使用 0。
        s1["data"]["num_workers"] = 2
        s1_path.write_text(yaml.safe_dump(s1, allow_unicode=True, sort_keys=False), encoding="utf8")
        for stage in ("preprocess", "train-s2", "train-s1"):
            step = {"language": language, "stage": stage, "state": "running"}
            status["steps"].append(step)
            report.write_text(json.dumps(status, indent=2), encoding="utf8")
            log = ROOT / ".runtime" / f"train-{language}-{stage}.log"
            with log.open("w", encoding="utf8") as stream:
                result = subprocess.run([sys.executable, "-u", str(ROOT / "tools/hsin_gptsovits.py"),
                                         stage, "--out", str(out), "--gpu", "0"],
                                        cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            step.update(state="complete" if result.returncode == 0 else "failed", exit_code=result.returncode)
            report.write_text(json.dumps(status, indent=2), encoding="utf8")
            if result.returncode:
                return result.returncode
    status["completed"] = datetime.now(timezone.utc).isoformat()
    report.write_text(json.dumps(status, indent=2), encoding="utf8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
