# 爱弥斯 PC TTS 接入（2026-10-07）

## 音色来源

复用本机 Aemeath spirit `config.yaml` 的 GPT-SoVITS 音色档案，以及 PC 现有 `tts_infer.yaml` 指定的 AemeathZH-e15.ckpt / AemeathZH_e15_s375.pth。中文参考音频为 `Aemeath_ZH_Ideals.wav`，日文为 `_ref_selfintro_cut.wav`；提示词、采样参数和日文 0.95 语速因子均沿用原配置。

中日输出当前使用原项目配置的同一套 AemeathZH 权重，分别绑定中日参考音频。日文可实际合成，但不宣称已有独立日文微调权重。原项目配置、权重和参考音频均只读。

## 接入方式

- `voice.remote_voice` 选择 `hsin` 或 `aemeath`，属于每个角色的语音绑定；语音页和角色管理均可选择。
- PC 桥接健康状态提供各音色的语言与资源指纹。请求携带 voice_id 和指纹；不存在的音色报错，不转用其他角色。
- Mac 缓存键包含角色音色 ID、资源指纹、语言、语速和文本。PC 使用各音色的权重及参考音频生成缓存身份。
- GPT-SoVITS 在一把锁内切换权重和参考音频，复用同一推理进程；角色切换取消旧任务，迟到音频不可进入新角色播放队列。
- 音色选择契约单独放在无 Qt 的 `voice_catalog.py`，兼容 GPT-SoVITS 自带 Python 3.9。
- PC 继续使用 RTX 4080 SUPER UUID；服务只监听 PC 回环地址，Mac 通过 SSH 转发，智谱 STT 选项保留。

安装版爱弥斯角色已绑定 PC / aemeath，启用语音并关闭自动翻译与备用音色。心保留 PC / hsin。麦克风启动仍默认关闭。

## 验证

39 项设置、角色、TTS 和桥接回归通过，覆盖角色切换后更换远端音色、同文本不同角色缓存隔离、音色缺失不回退。

真实 PC → Mac 两句播放与 PMX 口型：

| 输出语言 | 实际播放 | PCM 峰值 | 口型峰值 |
| --- | --- | --- | --- |
| 中文 | 两句按序播放 | 0.924 | 0.681 |
| 日文 | 两句按序播放 | 1.000 | 0.588 |

证据 `.runtime/pc-voice-aemeath-zh-playback-validation.json` 和 `.runtime/pc-voice-aemeath-ja-playback-validation.json`。验证不启用麦克风、不连接聊天服务；模拟测试不作为推理性能证据。新包已通过深度签名检查并安装到 `dist/Hsin.app`，旧包与角色配置保留备份。

PC 部署收据 `.runtime/pc-voice-deployment.json`；爱弥斯资源配置收据 `.runtime/aemeath-pc-profiles.json`。多音色部署可通过 `tools.deploy_pc_voice --aemeath-profiles <PC JSON路径>` 配置；已有服务端口占用时部署工具拒绝覆盖。

安装后的最终启动验收尚未完成：桌面工具检测到 Mac 锁定，未能启动新包。上表是源码运行的真实合成、播放和口型验证；解锁后需确认安装版恢复爱弥斯角色与音色绑定。
