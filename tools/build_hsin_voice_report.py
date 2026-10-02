#!/usr/bin/env python3
"""汇总来源配对与格式校验结果；不运行识别、预处理或训练。"""
import json
from pathlib import Path
import yaml


def main():
    out = Path("voice/hsin_zh").resolve()
    manifest = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    stats = manifest["statistics"]
    training_rows = [r for r in manifest["selected"] if r["training_eligible"]]
    candidates = [r for r in training_rows if 3 <= r["duration_seconds"] <= 10]
    preferred = [r for r in candidates if r["title"] == "突破1"]
    if not candidates:
        raise ValueError("没有满足 3–10 秒条件的参考候选")
    ref = preferred[0] if preferred else max(candidates, key=lambda r: r["duration_seconds"])
    profile = yaml.safe_load((out / "configs/app_voice_profile.draft.yaml").read_text(encoding="utf-8"))
    profile["tts"]["gptsovits"]["profiles"]["zh"].update(
        {"refer_audio_path": ref["wav"], "prompt_text": ref["text"], "prompt_lang": "zh"})
    (out / "configs/hsin_voice.yaml").write_text(
        "# 根据库街区原声和对应台词生成；未做 ASR 或人工试听。训练并加载 Hsin 权重后再启用。\n" +
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    request = json.loads((out / "configs/reference_request.draft.json").read_text(encoding="utf-8"))
    request.update({"ref_audio_path": ref["wav"], "prompt_text": ref["text"], "prompt_lang": "zh"})
    (out / "configs/reference_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    excluded = [r for r in manifest["selected"] if not r["training_eligible"]]
    train_seconds = sum(r["duration_seconds"] for r in training_rows)
    readme = f"""# 心 Hsin · 库街区中配 → GPT-SoVITS v2ProPlus

已完成原声采集、官方台词配对、格式与信号检查、训练清单及配置生成。按用户要求跳过自动识别，无需人工逐条审查。未启动 GPT-SoVITS 神经特征预处理或训练，尚未生成心的训练权重。

来源：[库街区·心]({manifest['source_page']})。读取公开接口的角色语音组件，同一记录中的 `playUrl` 和 `content` 直接配对，保留音频 ID、来源网址、原始台词和文件 SHA-256；没有猜测音频排列顺序。

## 数据结果

- 页面中配 74 条：34 条个性语音、40 条战斗语音；其他语言标签暂无音频。
- 保留 {stats['selected']} 条：全部个性语音，以及技能规则中的“滑翔”“感知”；排除其他 {stats['excluded_combat']} 条战斗语音。
- 已下载并转换 {stats['prepared']} 条，总时长 {stats['total_duration_seconds']:.3f} 秒，约 15 分 34 秒。缺失台词 {stats['missing_text']}，缺失音频 {stats['missing_audio']}。
- 可用训练清单 {len(training_rows)} 条，共 {train_seconds:.3f} 秒。
- 音频格式：32 kHz、单声道、PCM 16-bit WAV。检查完整解码、时长、RMS 静音、削波比例和文件校验和。
- 未做 ASR 或人工试听；台词来自网页，格式/信号检查不能证明逐字发声吻合，也不能证明完全没有背景音效或其他说话者。

完整原声仍保留。以下素材暂不进入训练清单，长音频如需加入，应同步切分文字和音频：

"""
    readme += "\n".join(f"- {r['title']}：{r['duration_seconds']} 秒；{r['training_exclusion']}。" for r in excluded)
    readme += f"""

## 配置与产物

| 文件 | 用途 |
| --- | --- |
| `raw/`、`wav32k/` | 原始 WAV、训练格式 WAV |
| `source/entry.json`、`selection.json` | 页面快照、筛选规则、配对文字、文件校验及格式/信号检查 |
| `hsin_zh.list` | 正式来源配对训练清单：绝对路径\|Hsin\|zh\|台词 |
| `hsin_zh.all.list` | 所有 36 条音频与完整台词，包括暂不训练的长素材 |
| `configs/preprocess.json` | 文本/BERT、Hubert、SV、语义特征的输入与输出配置 |
| `configs/s1_hsin.yaml` | GPT 训练配置 |
| `configs/s2_hsin.json` | SoVITS v2ProPlus 训练配置 |
| `configs/hsin_voice.yaml` | 桌面精灵参考音色配置片段 |
| `configs/reference_request.json` | GPT-SoVITS API 请求示例 |
| `configs/tts_infer_hsin.draft.yaml` | 独立推理服务配置草案；权重路径尚待训练结果 |
| `reference_candidates.json`、`review.html` | 3–10 秒参考候选与可选本地播放器，无需操作审听页面 |

训练配置从本机安装的 `s1longer-v2.yaml` 和 `s2v2ProPlus.json` 派生。实验名 `HsinZH`，BERT/Hubert/SV 与预训练 S1/S2 模型路径已核验存在。训练数据、预处理输出、日志与权重目录配置在本项目 `voice/hsin_zh/` 中。模板摘要保存在 `configs/installation.json`。

学习率、训练轮数和批大小沿用安装模板，尚未根据数据量、显存和效果调优：S1 20 轮、batch 8；S2 100 轮、batch 32。GPU 由后续运行的 `--gpu` 明确指定；S2 的空 `gpu_numbers` 会在辅助工具生成的运行配置中填入。不要直接复用爱弥斯的设备编号。

参考候选选为 **{ref['title']}**，时长 {ref['duration_seconds']} 秒，使用整句原声。配置中的 prompt 来自同一条网页记录。`prompt_lang=zh` 描述参考音频，API 示例中的 `text_lang=zh` 描述生成文本。

音色档案的 `enabled` 暂为 `false`。只有参考音频不能替代心的训练权重；推理草案中的两个 `SELECT_TRAINED_HSIN_WEIGHT` 路径是占位符，训练后需选取实际 GPT `.ckpt`、SoVITS `.pth` 再启动服务。未修改或切换现有爱弥斯服务。

## 重现

在 `D:\\Workspace\\Code Hsin` 执行（系统 Python 需安装 PyYAML）：

```powershell
$gsvRoot = 'D:\\Workspace\\GPT-SoVITS-v2pro-20250604-nvidia50\\GPT-SoVITS-v2pro-20250604-nvidia50'
# 不加 --fetch 使用已有页面快照；已有原声会跳过下载。
python tools/prepare_kurobbs_voice.py --gsv-root $gsvRoot --download --prepare
python tools/build_hsin_voice_report.py
python tools/validate_hsin_voice.py
```

神经特征预处理和训练是后续操作，本次未运行。执行时将占位参数替换为实际 GPU 编号：

```powershell
python tools/hsin_gptsovits.py preprocess --gpu <实际GPU编号>
python tools/hsin_gptsovits.py train-s2 --gpu <实际GPU编号>
python tools/hsin_gptsovits.py train-s1 --gpu <实际GPU编号>
```

辅助工具按本机源码执行 1-get-text、2-get-hubert-wav32k、2-get-sv、3-get-semantic；检查每步退出码和逐条产物，并统一语义 TSV 表头。预处理缺文件或条目不匹配时会停止。训练阶段要求完整特征。

原声、全文台词、预处理产物和训练权重保留在本机，已加入项目忽略规则。
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    print(f"配置说明完成；参考候选：{ref['title']}；训练清单：{len(training_rows)} 条；未做 ASR")


if __name__ == "__main__":
    main()
