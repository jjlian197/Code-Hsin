#!/usr/bin/env python3
"""按本机 GPT-SoVITS 脚本使用来源配对清单进行预处理或训练。"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checked_list(out):
    prep = load_json(out / "configs/preprocess.json")
    path = Path(prep["inp_text"])
    language = "ja" if path.stem == "hsin_ja" else "zh"
    if not path.exists():
        raise ValueError("请先运行 prepare_kurobbs_voice.py，生成语音清单")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("清单为空")
    names = set()
    for line in lines:
        audio, speaker, lang, text = line.split("|")
        if not Path(audio).is_file() or speaker != "Hsin" or lang != language or not text:
            raise ValueError(f"无效清单行: {audio}")
        if Path(audio).name in names:
            raise ValueError("音频文件名重复")
        names.add(Path(audio).name)
    return names


def table(path, names, width, header=None):
    if not path.is_file():
        raise ValueError(f"预处理产物缺失: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if header and lines and lines[0] == header:
        lines = lines[1:]
    result = []
    seen = set()
    for line in lines:
        parts = line.split("\t")
        if len(parts) != width or parts[0] in seen:
            raise ValueError(f"预处理表格式错误: {path}")
        seen.add(parts[0])
        result.append(line)
    if seen != names:
        raise ValueError(f"预处理表与清单不一致: {path}")
    return result


def verify_features(out, names):
    exp = out / "experiment"
    table(exp / "2-name2text.txt", names, 4)
    table(exp / "6-name2semantic.tsv", names, 2, "item_name\tsemantic_audio")
    for name in names:
        features = [("4-cnhubert", name + ".pt"),
                    ("5-wav32k", name), ("7-sv_cn", name + ".pt")]
        # 日语预处理使用零 BERT 张量；安装版只为中文保存 BERT 文件。
        if Path(load_json(out / "configs/preprocess.json")["inp_text"]).stem == "hsin_zh":
            features.append(("3-bert", name + ".pt"))
        for sub, filename in features:
            path = exp / sub / filename
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f"预处理特征缺失: {path}")


def run_stage(out, stage, gpu, conservative=False):
    if conservative and stage != "train-s1":
        raise ValueError("--conservative 只用于 S1 恢复训练")
    if gpu is None or not re.fullmatch(r"\d+(?:-\d+)*", gpu):
        raise ValueError("预处理/训练需明确提供 --gpu（例如 --gpu 0）；不会沿用爱弥斯的 GPU 编号")
    names = checked_list(out)
    install = load_json(out / "configs/installation.json")
    root = Path(install["gptsovits_root"])
    env = os.environ.copy()
    prep = load_json(out / "configs/preprocess.json")
    env.update({k: str(v) for k, v in prep.items()})
    env.update({"_CUDA_VISIBLE_DEVICES": gpu.replace("-", ","), "CUDA_VISIBLE_DEVICES": gpu.replace("-", ","),
                "is_half": "True", "PYTHONIOENCODING": "utf-8"})
    # 隔离临时文件和编译缓存，避免覆盖原项目与安装目录。
    tmp = out / "temp"
    tmp.mkdir(exist_ok=True)
    env.update({"TEMP": str(tmp), "TMP": str(tmp), "PYTHONPYCACHEPREFIX": str(tmp / "pycache"),
                "HF_HOME": str(tmp / "hf"), "TORCH_HOME": str(tmp / "torch"),
                "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"})
    (out / "experiment").mkdir(exist_ok=True)
    def run(script, *args):
        subprocess.run([install["python"], "-s", script, *map(str, args)], cwd=root, env=env, check=True)
    if stage == "preprocess":
        exp = out / "experiment"
        # 中间脚本可能逐条吞掉异常；每步都核验实际文件与条目数。
        run("GPT_SoVITS/prepare_datasets/1-get-text.py")
        text = table(exp / "2-name2text-0.txt", names, 4)
        (exp / "2-name2text.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
        if Path(prep["inp_text"]).stem == "hsin_zh":
            for name in names:
                if not (exp / "3-bert" / (name + ".pt")).is_file():
                    raise ValueError(f"BERT 特征缺失: {name}")
        run("GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py")
        for name in names:
            for path in (exp / "4-cnhubert" / (name + ".pt"), exp / "5-wav32k" / name):
                if not path.is_file():
                    raise ValueError(f"Hubert/WAV 产物缺失: {path}")
        run("GPT_SoVITS/prepare_datasets/2-get-sv.py")
        for name in names:
            if not (exp / "7-sv_cn" / (name + ".pt")).is_file():
                raise ValueError(f"SV 特征缺失: {name}")
        run("GPT_SoVITS/prepare_datasets/3-get-semantic.py")
        semantic = table(exp / "6-name2semantic-0.tsv", names, 2, "item_name\tsemantic_audio")
        (exp / "6-name2semantic.tsv").write_text("item_name\tsemantic_audio\n" + "\n".join(semantic) + "\n", encoding="utf-8")
        verify_features(out, names)
    else:
        verify_features(out, names)
        # 只有显式调用 train-s1 / train-s2 才训练。
        if stage == "train-s2":
            config = load_json(out / "configs/s2_hsin.json")
            config["train"]["gpu_numbers"] = gpu
            runtime_config = out / "configs/s2_hsin.runtime.json"
            runtime_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            (out / "weights/SoVITS").mkdir(parents=True, exist_ok=True)
            (out / "experiment/logs_s2_v2ProPlus").mkdir(exist_ok=True)
            run("GPT_SoVITS/s2_train.py", "--config", runtime_config)
        elif stage == "train-s1":
            (out / "weights/GPT").mkdir(parents=True, exist_ok=True)
            config_path = out / "configs/s1_hsin.yaml"
            if conservative:
                import yaml
                config = yaml.safe_load(config_path.read_text(encoding="utf8"))
                config["train"].update(batch_size=1, save_every_n_epoch=1)
                config["data"]["num_workers"] = 1
                config_path = out / "configs/s1_hsin.recovery.yaml"
                config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf8")
                env.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
                run(str(Path(__file__).with_name("gsv_conservative_entry.py").resolve()),
                    "--config_file", config_path)
            else:
                run("GPT_SoVITS/s1_train.py", "--config_file", config_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["preprocess", "train-s1", "train-s2"])
    parser.add_argument("--out", type=Path, default=Path("voice/hsin_zh"))
    parser.add_argument("--gpu")
    parser.add_argument("--conservative", action="store_true", help="S1 使用 batch 1、单 worker、CPU 线程限制与 75%% 显存上限")
    args = parser.parse_args()
    out = args.out.resolve()
    run_stage(out, args.stage, args.gpu, args.conservative)


if __name__ == "__main__":
    main()
