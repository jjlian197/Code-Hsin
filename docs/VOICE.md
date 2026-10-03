# 心的中日语音

开发版正常启动后，后台启动本地 GPT-SoVITS 并以当前语言完成一次短句推理，预热音频不播放、不进入聊天气泡，也不阻塞窗口或暂停收音。切换中日语言会后台预热新的音色；仅配置了训练资源的环境才预热。语音菜单显示进度或错误，失败不关闭语音，正式请求仍可重试/使用原有备用引擎。预热尚未完成时立即开口仍需等待，之后每条新句依然有合成耗时。

右键或托盘打开“语音”，选择“中文”或“日本語”。“试听当前语言”生成一条新台词；“开启语音”控制聊天、触摸回复和 `speak`，“停止语音”取消合成与未播放队列并闭合口型。语言、引擎、翻译及备用音色开关保存在本项目 `.runtime/voice.json`，下次启动沿用。

触摸头部、身体、手和尾巴时使用各自的中日台词。任意文本通过 `speak` 交给当前语言的音色。合成期间窗口仍可拖动、播放动作和模拟物理。真实 PCM 音量驱动原有口型，支持心的 WAV 和 Edge 的 MP3。

## 翻译、引擎与备用音色

在“语音 → 朗读文本…”输入文字即可使用；选择日本語并开启自动翻译，可直接输入中文，译文会显示在气泡中。失败原因也会在气泡提示。

- **语音引擎**：默认“心 · GPT-SoVITS”，也可选择“Edge · 通用女声（联网）”。Edge 中文使用 Xiaoxiao、日语使用 Nanami，属于通用音色，不是训练的心。实现依据 [edge-tts 项目](https://github.com/rany2/edge-tts)；依赖已加入 `requirements.txt`。
- **自动翻译文本**：默认开启。直接 `speak` 的中文会在日语模式下先翻译，含日语假名的文本在中文模式下会先翻译；纯英文也会翻译。已判断为目标语言的文本直接朗读。这是文字特征判断，不是语音识别；混合语言或纯汉字日语可能判断不准确，可关闭自动翻译，或单次传 `translate:false`。
- 翻译使用既有 DeepSeek API Key 和模型设置，不改变聊天后端、Agent 会话或对话记忆。缺密钥、连接失败或译文截断会显示错误，不把未翻译的原文冒充译文播放。翻译结果按原文、目标语言、模型和提示版本缓存于 `.runtime/tts/translations/`。调用依据 [DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/)。
- **合成失败使用备用音色**：默认开启。心的合成失败后尝试 Edge；Edge 失败后尝试心。成功回退时，语音菜单状态和 `tts.warning` 明确标明实际音色，首选引擎保持不变；两个引擎都失败则显示错误。Edge 需要联网；本地心音色已经缓存的内容无需联网。关闭此开关可保持只用所选音色。
- 聊天已经让后端按当前语言回答，朗读时不重复翻译。切换语言、引擎或辅助开关会取消旧播放；取消或静音后的旧结果不会重新发声，也不会开始备用合成。

Edge 缓存独立位于 `.runtime/tts/cache/edge/<zh|ja>/`，键包含文字、语言、声音和语速，不与心的权重缓存混用。两类音频经过同一 Qt 播放器和 PCM 口型链路。

聊天默认分句朗读，当前句播放时最多预合成两句，后句不会打断前句。文本接收、合成和播放并行；关闭语音、停止、切换设置或新对话后，旧句不再播放。任一句合成或解码失败会取消剩余语音，聊天全文继续保留。每句按原有策略单独缓存和回退，回退失败不跳句。显式 `speak`、试听和触摸发声仍替换当前语音，之后的旧聊天句子不会重新接管。详见 [聊天说明](CHAT.md)。

## 独立推理

正式音色文件为 `voice/profiles.json`，包含每种语言的 GPT/SoVITS 权重、来源配对的参考原声、原文和 SHA-256。缺少训练权重时不会回退到爱弥斯的音色。

首次生成语音时自动启动本机 GPT-SoVITS 安装内的 Python，加载心的权重。仅监听 `127.0.0.1:19880`，不使用爱弥斯的 9880 服务。仅驻留一套发声模型，切换语言时在同一任务内更换两套权重，再执行合成。推理设置写入 `.runtime/tts/tts_infer.yaml`，不修改安装目录的配置。服务由启动它的应用负责退出清理。

初次合成需要加载模型，比后续慢；已生成的同文台词会复用缓存。缓存包含语言、权重、参考音频、文字和语速信息，位置为 `.runtime/tts/cache/zh` 和 `ja`。日志位于 `.runtime/tts/server.log`，接口状态的 `tts.error` 提供合成失败原因；排队成功不表示合成已经完成。

`config.yaml` 中 `voice.enabled`、`language`、`provider`、`auto_translate`、`fallback`、`volume`、`port`、`profiles` 设置默认行为。更换推理端口后重启应用。早期 `hsin_voice.yaml` 和推理草案保留来源记录，正式应用读取复数 `voice.profiles`。

## 控制接口

```json
{"type":"tts_config","data":{"language":"ja","enabled":true}}
{"type":"tts_config","data":{"provider":"gptsovits","auto_translate":true,"fallback":true}}
{"type":"speak","data":{"text":"御者，早安。","language":"ja"}}
{"type":"speak","data":{"text":"御者、おはようございます。","language":"ja","translate":false}}
{"type":"speak","data":{"text":"御者、今日は一緒に散歩しましょう。"}}
{"type":"speak","data":{"text":"御者，我在这里。","language":"zh","speed":1.0,"volume":0.65}}
{"type":"tts_config","data":{"action":"stop"}}
```

`speak` 返回 `tts_queued` 和请求编号。每个新请求替代旧请求；语言切换、关闭或停止语音也会使旧结果失效。显式 `speak.language` 只作用于这一条请求。`get_status.data.tts` 及 WebSocket `tts_status` 事件包含当前语言、开关、合成中标志、最后请求和错误；播放进度和错误位于 `audio`。`streaming` 标记聊天语音队列，`stream_open` 表示仍接收句子，`queued_segments` 表示未完成合成的句子数，`ready_segments` 表示已合成待播放数，`active` 覆盖合成、待播放和当前播放。`last_request.segment` 是当前队列中的序号，`stream` 区分聊天与直接朗读。

## 训练和验证

原文直接来自库街区中文页与 wuwa.wiki 日文页，按用户要求跳过自动识别和人工审查。中文 34 条、日语 25 条非战斗素材用于本次训练，超过 54 秒的完整素材暂不纳入。参考整句分别为“入队1”和“チームに編入・その一”，未任意裁切或用中文翻译充当日语原文。

以上为输入清单数量。安装版 S1 还按音素数和语音密度筛选，实际接纳中文 29 条、日语 21 条；S2 长度分桶实际采样中文 26 条、日语 22 条。各阶段采用数量与排除文件记录在正式音色配置中，不把重复补齐到约 100 条的训练样本数当作原声数量。

本机 8 GB GPU 使用混合精度，S2 batch 2 并启用梯度检查点，日语 S1 batch 2。中文 S1 恢复后使用 batch 1、单 worker、CPU 2 线程和 75% 显存分配上限，每轮保存，并在优化器更新前释放空闲显存池。中日两种语言均已完成 S1/S2 各 20 轮。来源、模板、训练配置、特征和实际权重位于各自 `voice/hsin_zh` 和 `voice/hsin_ja`，各阶段结果记录在 `.runtime/training-status.json`。

```powershell
python -u tools/train_hsin_voices.py
python tools/finalize_hsin_voices.py
python -m tools.verify_hsin_voices
```

最终发布工具只接受唯一的第 20 轮 GPT 和 SoVITS 权重。合成验证使用未见过的中日文本，连续切换语言并检查缓存、音频长度、非静音、幅度和削波比例，样本与结果保存在 `voice/samples/`。这些客观检查不能代替听感评价，未宣称已人工核验音色、读音或每句自然度。

## 2026-10-02 中断记录

系统在 13:42:51 意外停止，13:45:16 重启，系统事件记录 bugcheck `0x101`，原因尚未从转储确定。当时日语 S1/S2 与中文 S2 已完成 20 轮；中文 S1 在第 2 轮的 24/44 批次中断，尚无可恢复 checkpoint。降低资源占用重训后，每轮保存；在第 3 与第 17 轮分别触及显存上限，进程退出而系统继续运行。最终加入可扩展显存段及优化器更新前释放空闲池，从保存点恢复并完成第 20 轮。

中文 S1 的恢复入口：

```powershell
python tools/hsin_gptsovits.py train-s1 --out voice/hsin_zh --gpu 0 --conservative
```

正式 `voice/profiles.json` 已生成。四条未见过的中日新句子通过实际合成和缓存验证，全部无削波，时长约 5–6 秒；八条触摸回复已预生成。原生 Qt 窗口验证了双语言播放、实际头部触摸发声、PCM 驱动口型、播放完闭嘴、切换取消和静音。报告位于 `voice/samples/validation.json` 和 `.runtime/tts-desktop-validation.json`。恢复成功不表示已确定原系统故障原因。
