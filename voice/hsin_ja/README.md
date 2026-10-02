# 心 · 日语原声

来源：[wuwa.wiki 繁体页面](https://wuwa.wiki/zh-hant/codex/resonators/1311?nav=voices)，使用网站公开的[日文页面](https://wuwa.wiki/ja/codex/resonators/1311?nav=voices)配对日文原文。音频地址格式取自该页面的播放脚本，原格式为 Ogg Opus。

## 文件

- `raw/`：页面提供的日语 Opus 原文件，包含战斗语音。
- `wav32k/`：32 kHz、单声道、PCM 16 位 WAV。
- `selection.json`：原文、事件名、资源地址、文件摘要、时长、筛选与检查结果。
- `hsin_ja.archive.list`：全部成功准备的音频与日文原文，包含战斗语音，仅供归档。
- `hsin_ja.calm.all.list`：个性语音及滑翔、感知；过长条目仍保留完整音频和全文。
- `hsin_ja.list` / `hsin_ja.draft.list`：排除超出本机 S1 模板 54 秒限制及信号检查失败的候选。
- `reference_candidates.json`：3–10 秒的非战斗参考候选，尚未审听。
- `review.html`：可选的本地试听页面。
- `configs/`：按本机 GPT-SoVITS v2ProPlus 模板生成的 S1、S2 与预处理配置，实验名为 `HsinJA`。

按用户要求跳过自动识别与人工审查。页面元数据配对和文件检查已记录；不表示已逐字听音核对。日文 `<ano=读音>基字</ano>` 使用明确标注的读音，完整标记原文仍保存在清单中。超过 54 秒的素材未随意截断，后续需同步切分音频与文字才能纳入训练。

此目录与中文数据独立。已经完成文本、Hubert、SV 和语义特征预处理，GPT 与 SoVITS v2ProPlus 各训练 20 轮。输入清单为 25 条；S2 按安装版长度分桶实际采样 22 条，S1 按音素数和语音密度规则接纳 21 条。各阶段排除文件分别记录。`weights/GPT/HsinJA-e20.ckpt` 与 `weights/SoVITS/HsinJA_e20_s880.pth` 已通过实际 checkpoint 读取、实验名、版本和有限参数检查。

正式参考整句使用“チームに編入・その一”，原文“あら？いいわ――御者の思うがままに。”，时长 5.918 秒。应用正式音色配置统一生成到 `voice/profiles.json`，按需启动心自己的推理服务；操作、训练与真实合成验收见 [中日语音](../../docs/VOICE.md)。

## 复现

在项目根目录运行：

```powershell
python tools/prepare_wuwa_wiki_voice.py --gsv-root 'D:/Workspace/GPT-SoVITS-v2pro-20250604-nvidia50/GPT-SoVITS-v2pro-20250604-nvidia50' --fetch --download --include-combat
```

省略 `--fetch` 可复用保存的页面；省略 `--download` 可离线检查与转换已保存的原文件。已有文件会复用。若来源拒绝访问或返回限流，停止下载，不绕过。

素材仅保留在本机，来源快照、音频、完整台词与清单已由项目 `.gitignore` 排除。

## 本次结果

已完整保存 75 条日语原声，总长 1347.177 秒。36 条非战斗候选中，25 条进入当前训练清单，11 条超过 54 秒完整保留待切分。下载失败为 0，全部文件摘要和 WAV 格式核验通过。
