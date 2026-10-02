"""使用安装版 checkpoint 读取器验证实际训练权重，而不只检查文件名。"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("zh", "ja"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "voice" / ("hsin_" + args.language)
    installation = json.loads((out / "configs/installation.json").read_text(encoding="utf8"))
    installed = Path(installation["gptsovits_root"])
    sys.path[:0] = [str(installed), str(installed / "GPT_SoVITS")]
    import torch
    from process_ckpt import get_sovits_version_from_path_fast, load_sovits_new
    torch.set_num_threads(2)
    gpt_path, = (out / "weights/GPT").glob("*-e20.ckpt")
    sovits_path, = (out / "weights/SoVITS").glob("*_e20_s*.pth")
    gpt = torch.load(gpt_path, map_location="cpu", weights_only=False)
    sovits = load_sovits_new(str(sovits_path))
    assert gpt["info"] == "GPT-e20", gpt["info"]
    assert sovits["info"].startswith("20epoch_"), sovits["info"]
    name = "Hsin" + args.language.upper()
    assert gpt["config"]["train"]["exp_name"] == name
    assert sovits["config"]["name"] == name
    version = get_sovits_version_from_path_fast(str(sovits_path))[1]
    assert version == "v2ProPlus", version
    report = {"success": True, "language": args.language, "experiment": name, "version": version}
    for label, checkpoint, path in (("gpt", gpt, gpt_path), ("sovits", sovits, sovits_path)):
        weights = checkpoint["weight"]
        assert weights
        assert all(torch.isfinite(value).all().item() for value in weights.values())
        report[label] = {"path": str(path), "info": checkpoint["info"],
                         "tensors": len(weights), "parameters": sum(value.numel() for value in weights.values())}
    report["gpt"]["training"] = {"batch_size": gpt["config"]["train"]["batch_size"],
        "epochs": gpt["config"]["train"]["epochs"], "workers": gpt["config"]["data"]["num_workers"],
        "save_every_epoch": gpt["config"]["train"]["save_every_n_epoch"]}
    (root / ".runtime" / f"weight-validation-{args.language}.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
