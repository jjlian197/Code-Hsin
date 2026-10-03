# 和心聊天

右键或托盘选择“和心聊天…”，输入文字后回车或点击发送。默认使用本地 **Hermes · Hsin**。右键的“对话后端”可选择 Hermes、OpenClaw 或 DeepSeek 直连；选择保存在 `.runtime/chat.json`。回复逐步显示，完整短句到达后立即排入当前中文或日本語音色的合成队列，播放当前句时继续接收文字和预合成后句。切换语言会取消旧回复；“停止回复”同时停止等待结果、当前播放与未播放的语音，全文收到后此按钮仍可停止朗读。

关闭聊天窗口后，当前回复继续完成。文字记录保留在本次应用运行的窗口中；每个后端维护自己的上下文。DeepSeek 保留最近六轮成功对话，Hermes 通过自己的已保存会话恢复上下文，OpenClaw 使用本客户端独立的 `agent:hsin:desktop-…` 会话。聊天期间拖动、自然动画和物理继续运行。

## 本地 Hermes

本机 Hermes 数据目录为 `C:/Users/lianj/AppData/Local/hermes`，现有 default profile 的身份为 Hsin。空 `chat.hermes.url` 会从 `spawn-ledger.json` 发现桌面服务的动态端口，通过安装版桌面客户端同样的握手连接 `/api/ws`。服务重启后，下次请求重新发现端口。

请先打开 Hermes 桌面应用。另一套本地服务可在“连接设置”填写地址、数据目录与 Agent profile 名称。`default` 在本机对应已经设置好的心。会话凭据通常留空，由握手在内存中获取。

协议来自安装版 `tui_gateway/contracts`：`session.create` / `session.resume`、`prompt.submit` 和 `message.delta` / `message.complete`。只读取本客户端会话的回复，不朗读 reasoning 或其他会话消息。取消后关闭自己创建的活动会话，后续不自动续跑已停止的任务。

## OpenClaw

按当前要求，OpenClaw 仅保留连接接口和设置入口，实际服务联调暂缓。预留地址为 `ws://127.0.0.1:18789/ws`，Agent 名称为 `hsin`。协议沿用参考项目的 connect、会话订阅与 chat.send，使用本客户端独立的会话。

应用不自动启动或管理 OpenClaw、WSL 或网关服务。默认后端仍为 Hermes；以后启用 OpenClaw 时可在“连接设置”填写地址与凭据。

此前已通过安装版 [OpenClaw agents 命令](https://docs.openclaw.ai/cli/agents)准备 `hsin` Agent，工作目录为 `/home/lianj/.openclaw/workspace-hsin`，初始化人设副本在项目 `agents/hsin/`。这些准备工作保留，但尚未验证实际对话。

## DeepSeek 直连

使用官方 `https://api.deepseek.com/chat/completions`，默认 `deepseek-v4-flash`，关闭思考模式，流式读取最终文字。调用字段依据 [DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/)。直连人设为心，称呼御者，只进行文字聊天。

优先读取 `DEEPSEEK_API_KEY`，其次使用项目 `config.local.yaml` 的 `chat.deepseek.api_key`。本机已有密钥和 OpenClaw 凭据复制到本项目未跟踪的配置，不打印到验证报告。可以在“连接设置”更新；保存会合并已有配置。

## 验证与限制

实际中日连续对话记录位于 `.runtime/chat-backend-validation.json`，原生桌面聊天→Hermes→中日合成→播放→PCM 口型报告位于 `.runtime/chat-desktop-validation.json`。首次朗读仍需要加载本地模型，分句只能减少等待完整文字回复的时间；后续同文短句使用缓存。

分句支持中文/日文句号、问号、叹号、换行和英文句点；无标点长句最多约 160 字一段，优先在逗号或空格处切分。思考标签、代码块、行内代码、图片和链接地址不朗读，链接保留文字。尚未闭合的结构先等待，回复结束后不朗读残缺结构。长回复累计最多朗读 500 字，聊天窗口保留全文；朗读范围选择仍在计划中。

最终回复用于补齐没有通过 delta 传来的尾句，不会重读已排队的前缀。若后端修改了已朗读的前缀，保留最终聊天文字并取消剩余语音，不再播放修订全文。停止语音、静音、切换后端/语言/引擎、发送新消息或任一句失败都会清空队列并使迟到结果失效；当前正在执行的本地推理可能继续完成，但结果不会播放。

播放当前句时最多预合成两句；即使后续合成更快，也要等前句播放结束。每句继续使用原有缓存、备用音色与 PCM 口型。语音回复期间暂停收音，覆盖合成、预备队列和实际播放；麦克风设置见 [STT](STT.md)。后端失败在聊天窗口和 `chat.error` 显示，不自动转向另一个后端。

```powershell
python -m tools.verify_chat_backends hermes deepseek
python -m tools.verify_chat_desktop
python -m tools.verify_streaming_speech
```

分句原生检查使用模拟聊天与本机已训练音色，静音播放、不开麦、不调用远程后端。检查中日首句在最终回复前播放、顺序、无重复、真实音频口型和收音阻塞恢复；报告为 `.runtime/streaming-speech-validation.json`，验证语音缓存为 `.runtime/streaming-tts/`。
