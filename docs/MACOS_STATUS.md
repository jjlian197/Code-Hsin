# macOS 当前开发状态

更新：2026-10-07。分支：`codex/macos-port`。这是当前开发快照，尚非正式公证发行版。

## 已交付与验证

- Apple Silicon 源码运行、arm64 应用打包、原生窗口策略与后台模型哈希读取已接入；基础模型与桌面功能已有实测记录。
- PC 承担 STT／TTS 推理，使用已确认的 RTX 4080 SUPER；HTTPS 入口为 `bridge.oieasklja.icu`，访问令牌留在用户私有配置，不打包、不提交。SSH 保留为可选传输。
- 麦克风已改用设备原生格式采集并转换 PCM；用户确认智谱可识别，PC 桥接识别效果良好。启动默认关麦。
- 爱弥斯模型、设定与 PC 中日音色已接入测试；心／爱弥斯各自音色的真实合成及 Mac 播放已有专项记录。
- Hermes、OpenClaw 与 DeepSeek 入口保留；用户本机选择不写入源码默认配置，不将临时 DeepSeek 测试选择作为 Hsin Agent 的身份定义。

## 尚未完成

- Developer ID 签名／Apple 公证与正式发布流程。
- 完整 Finder 授权、Spaces、外接屏及长时间连接稳定性验收。
- Apple Silicon 本地 STT／TTS 推理；当前 PC 链路可用不代表 MPS 已支持。
- 其余限制以专项实测记录为准，接口成功不代表原生渲染、真人收音或实际播放已验收。

## 接手入口

[使用与构建](MACOS.md)、[麦克风排查](MACOS_MICROPHONE.md)、[PC 语音](MACOS_PC_VOICE.md)、[爱弥斯测试](MACOS_AEMEATH_TEST.md)、[爱弥斯音色](MACOS_AEMEATH_TTS.md)。私有模型、语音权重、配置、录音与构建产物保留本机。
