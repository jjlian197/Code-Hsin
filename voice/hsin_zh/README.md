# 心 Hsin · 库街区中配 → GPT-SoVITS v2ProPlus

已完成原声采集、官方台词配对、格式与信号检查、神经特征预处理，GPT 与 SoVITS v2ProPlus 各完成 20 轮训练。两套实际 checkpoint 已通过实验名、版本、轮次和有限参数检查。按用户要求跳过自动识别和人工审查。实际阶段结果记录在项目 `.runtime/training-status.json`。

来源：[库街区·心](https://wiki.kurobbs.com/mc/item/1543050481616060416)。读取公开接口的角色语音组件，同一记录中的 `playUrl` 和 `content` 直接配对，保留音频 ID、来源网址、原始台词和文件 SHA-256；没有猜测音频排列顺序。

## 数据结果

- 页面中配 74 条：34 条个性语音、40 条战斗语音；其他语言标签暂无音频。
- 保留 36 条：全部个性语音，以及技能规则中的“滑翔”“感知”；排除其他 38 条战斗语音。
- 已下载并转换 36 条，总时长 933.952 秒，约 15 分 34 秒。缺失台词 0，缺失音频 0。
- 可用训练清单 34 条，共 809.288 秒。
- 音频格式：32 kHz、单声道、PCM 16-bit WAV。检查完整解码、时长、RMS 静音、削波比例和文件校验和。
- 未做 ASR 或人工试听；台词来自网页，格式/信号检查不能证明逐字发声吻合，也不能证明完全没有背景音效或其他说话者。

完整原声仍保留。以下素材暂不进入训练清单，长音频如需加入，应同步切分文字和音频：

- 心声2：54.418 秒；duration_exceeds_template_max_sec_54; needs_aligned_segmentation。
- 心声3：70.246 秒；duration_exceeds_template_max_sec_54; needs_aligned_segmentation。

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

本机 8 GB GPU 使用混合精度，S2 batch 2、梯度检查点，每 5 轮保存。中文 S1 中断后使用 `s1_hsin.recovery.yaml`：batch 1、单 worker、CPU 2 线程、75% 显存上限、可扩展段、优化器更新前清理空闲池，每轮保存。输入清单为 34 条，S1 实际接纳 29 条，S2 实际采样 26 条。最终权重为 `HsinZH-e20.ckpt` 与 `HsinZH_e20_s520.pth`。恢复过程见 [中日语音](../../docs/VOICE.md)。

早期草案参考为“突破1”，正式应用参考选用“入队1”，原文“嗯？但凭御者差遣。”，时长 3.992 秒，使用完整原声。prompt 来自同一条网页记录。`prompt_lang=zh` 描述参考音频，`text_lang=zh` 描述生成文本。

早期 `hsin_voice.yaml` 和推理草案保留准备记录，其中占位路径不会被正式应用使用。正式配置读取 `voice/profiles.json`，由完整的第 20 轮 GPT/SoVITS 权重生成；中日切换、自动启动服务与口型说明见 [中日语音](../../docs/VOICE.md)。没有修改或切换现有爱弥斯服务。

## 重现

在 `D:\Workspace\Code Hsin` 执行（系统 Python 需安装 PyYAML）：

```powershell
$gsvRoot = 'D:\Workspace\GPT-SoVITS-v2pro-20250604-nvidia50\GPT-SoVITS-v2pro-20250604-nvidia50'
# 不加 --fetch 使用已有页面快照；已有原声会跳过下载。
python tools/prepare_kurobbs_voice.py --gsv-root $gsvRoot --download --prepare
python tools/build_hsin_voice_report.py
python tools/validate_hsin_voice.py
```

分阶段执行时提供实际 GPU 编号：

```powershell
python tools/hsin_gptsovits.py preprocess --gpu <实际GPU编号>
python tools/hsin_gptsovits.py train-s2 --gpu <实际GPU编号>
python tools/hsin_gptsovits.py train-s1 --gpu <实际GPU编号>
```

辅助工具按本机源码执行 1-get-text、2-get-hubert-wav32k、2-get-sv、3-get-semantic；检查每步退出码和逐条产物，并统一语义 TSV 表头。预处理缺文件或条目不匹配时会停止。训练阶段要求完整特征。

原声、全文台词、预处理产物和训练权重保留在本机，已加入项目忽略规则。
