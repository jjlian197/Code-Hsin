# macOS 麦克风排查与修复（2026-10-07）

## 本次复现

用户选择智谱、主动开麦并说话后，旧应用的 STT 状态持续为 listening=true、level=0、speech_active=false，未进入 recognizing。问题位于 PC 与智谱共用的音频采集阶段，不能用已通过的 WAV 文件识别测试替代真人收音验证。

另外，启动时 PC SSH 曾出现 No route to host；本次检查 SSH 和桥接健康端点已经恢复。运行中的配置一度是本机 qwen，且本机模型未安装；首次引导选择基础陪伴会改写 STT provider，现已去掉这项改写。

权限检查版在真人测试中显示 granted，仍然未收到 PCM，因此权限并非已确认的根因；改为设备原生 44.1kHz Float 采集并转换到 ASR 所需格式后，已收到音频并成功识别。设备声明支持 16kHz 不能作为实际收音成功的证据。

## 改动原因

- 开麦时检查 QMicrophonePermission；未决定时异步请求，拒绝时明确给出系统设置位置。回调遵守用户关麦和退出状态，不会擅自重开。
- macOS 使用设备原生格式采集，标准库转换为 16kHz 单声道 int16；分块间保留采样位置，避免时长漂移。
- 在既有 Qt 定时器内排空录音 IO，补充 readyRead 通知；两条路径读取同一缓冲区，不重复提交音频。
- 五秒没有收到任何 PCM 时关闭此次采集并显示错误，避免把空收音误报为正常监听。
- 状态提供 permission、received_bytes，设置页显示音量与接收字节；日志只记录设备、短句时长、后端和错误，不记录音频、转录内容或凭据。
- 基础陪伴引导保留既有 STT 后端选择。

权限调用参考 [Qt Application Permissions](https://doc.qt.io/qt-6/permissions.html)。仅 Info.plist 中声明用途不等于应用已获得授权；麦克风请求应在用户主动录音时发起。

## 验证

35 项设置、STT 与原生 PCM 转换测试通过，覆盖权限拒绝、只请求一次、关麦后迟到授权、无 readyRead 通知时定时收音、无输入报错与设置保留。修复包已构建并通过 codesign 深度验证，安装到 dist/Hsin.app；旧包保留为 dist/Hsin-before-microphone-fix-20261007-120523.app。私人设置未改写。

真人验收需用户主动开麦：检查系统授权、输入音量与字节是否增加，再检查短句识别和回复。PC 与智谱应分别验证；本机 Qwen 需要独立安装模型，不能替代 PC 桥接。

## 真人验证结果

智谱：用户主动开麦，原生采集 44100Hz/1ch/Float；日志显示提交 2.48 秒短句，状态 last_text 非空，用户确认“听到了”。最小证据记录在 `.runtime/microphone-zhipu-validation.json`，不保存录音或转录原文。

PC 桥接：用户完成真人测试，确认“桥接效果也很好”。两个后端均已通过真人验证。
