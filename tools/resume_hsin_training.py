"""仅恢复中断的中文 S1，保留已完成语言的权重与历史崩溃记录。"""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / ".runtime/training-status.json"
    status = json.loads(path.read_text(encoding="utf8"))
    step = next(item for item in status["steps"] if item["language"] == "zh" and item["stage"] == "train-s1")
    step.update(state="running", recovery_started=datetime.now(timezone.utc).isoformat(),
                recovery_mode="batch1_worker1_cpu2_vram75pct_expandable_segments_release_before_optimizer_save_each_epoch")
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf8")
    log = ROOT / ".runtime/train-zh-train-s1-recovery.log"
    with log.open("ab") as output:
        result = subprocess.run([sys.executable, "-u", str(ROOT / "tools/hsin_gptsovits.py"),
                "train-s1", "--out", str(ROOT / "voice/hsin_zh"), "--gpu", "0", "--conservative"],
                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    step.update(state="complete" if result.returncode == 0 else "failed", exit_code=result.returncode)
    if result.returncode == 0:
        status["completed"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
