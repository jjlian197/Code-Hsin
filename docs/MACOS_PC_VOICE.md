# Mac 使用 PC 语音推理

2026-10-07：已部署并验证。PC 实际设备为 RTX 4080 SUPER 与 RTX 5060 Laptop；用户确认使用 RTX 4080 SUPER，未使用 RTX 5060。Mac 不安装语音模型环境。

## 当前调用链

- STT：Mac 的 Qt 麦克风采集/VAD → SSH 隧道 → PC Qwen3-ASR → Mac 文字处理。
- TTS：Mac 回复分句 → SSH 隧道 → PC GPT-SoVITS 心音色 → 完整 WAV → Mac Qt 播放、PMX 口型。
- 智谱 STT 原接口与配置保留。在“设置 → 麦克风”或独立麦克风设置中选择“智谱”，即从 Mac 调用原有云端接口；密钥沿用本机设置/环境变量。没有将智谱 Key 复制到 PC。

PC 模式不会在失败时自动切到智谱或 Edge。用户可手动切换识别方式。逐句音频返回不等于句内 PCM 流式，也不等于聊天首句延迟已完成测量。

## 已配置本机

源码和应用包的本机覆盖文件已配置 PC provider，TTS 开启、自动翻译与备用音色关闭，麦克风启动仍关闭，聊天仍关闭。改动前配置备份位于源码 `.runtime/pc-voice-config-backup/`。没有设置首次向导已完成标志。

公共发行默认值仍关闭语音，不包含 PC 地址、个人音色配置或权重。新环境可写入下列覆盖，或在设置的语音页填写同样字段：

```yaml
speech_bridge:
  url: http://127.0.0.1:19881
  ssh_host: 192.168.50.230
  ssh_user: lianj
  ssh_key: ~/.ssh/id_ed25519
  ssh_port: 22
  remote_port: 19881
  timeout: 180
stt:
  provider: remote
voice:
  provider: remote
  enabled: true
  auto_translate: false
  fallback: false
```

源码覆盖为项目 `config.local.yaml`；应用包覆盖为 `~/Library/Application Support/Hsin/config.local.yaml`。连接设置变更后需重启。智谱可单独选择 `stt.provider: zhipu`，其凭据字段仍是 `stt.zhipu.api_key`，也支持 `ZHIPU_API_KEY`。

SSH 隧道在第一次语音请求时建立，STT/TTS 共用一个进程；关闭 Mac 应用结束自身隧道，不停止 PC 服务。macOS 使用独立的轻量监护脚本，在应用提前结束、Qt 清理未完成时仍结束本实例 SSH，避免孤儿转发进程。PC 仅监听 `127.0.0.1:19881`，其 GPT-SoVITS 子服务仅监听 `127.0.0.1:19882`，无需开放新的 LAN 端口。私钥由 Mac 上的 SSH 使用，不复制到 PC。

PC 离线会报错，下次请求可重新建立隧道；不自动重放旧请求。停止会立即停播，使旧代次失效，并通知 PC 取消排队任务。已开始的推理目前正常运行到结束、丢弃结果，不能把停止播放理解为 GPU 推理已被中断。

## PC 部署与运行

首次部署：

```bash
python -m tools.deploy_pc_voice --gpu-uuid <确认过的GPU-UUID>
```

工具先检查 19881/19882 端口，已占用时拒绝替换。仅拷贝最小代码到 PC 仓库 `.runtime/pc-voice-bridge/<时间>/`，引用已有 ASR 环境、模型和 `voice/profiles.json`。部署记录在 Mac `.runtime/pc-voice-deployment.json`，记录 PC 目录与服务 PID。

通过 Windows WMI 创建独立进程，使 SSH 会话结束后服务继续运行；普通 `Start-Process` 在此次 SSH 测试中会随会话结束，不能用它证明后台部署成功。未创建开机任务、未修改 PC 工作区源码、现有音色配置、用户 Agent 或防火墙。当前没有开机自动启动，也没有服务端闲置释放模型。

PC 重启后，可在 PC 终端用已有目录直接启动：

```powershell
& 'D:/Workspace/Code Hsin/.runtime/local-model-tests/venv-asr/Scripts/python.exe' -u '<部署目录>/code/tools/hsin_pc_voice_server.py' --config '<部署目录>/bridge.json'
```

前台运行时 Ctrl+C 退出并清理本实例推理子进程。ASR 与 TTS 在两个环境运行，但推理作业共用串行锁；模型载入后保持常驻。后台进程的维护需按部署记录识别实例，不按 `python.exe` 名称批量结束。仅部署了 Hsin 独立服务，不切换 Aemeath 的全局音色。

## 实测与限制

- PC 新句合成得到有效非静音 WAV，首次完整往返约 70.8 秒，包含环境/模型加载。
- 将该音频转为 16kHz 后送 PC 识别，首次往返约 31.8 秒；实际报告 `cuda:0` / `NVIDIA GeForce RTX 4080 SUPER`。主要内容正确，但“心的”识别为“新的”，热词不保证精确识别。
- 热状态实机双句测试：首段实际进入 PlayingState 在验证开始后约 5.38 秒，第二段约 9.75 秒；计时包含桌面模型加载。顺序正确、99 个 PCM 缓冲、PMX mouth_open 峰值约 0.93。
- 验证使用预先给定的两句话和实际 PC 推理，未连接 LLM，因此不是聊天端到端首句性能结论。
- 测试期间麦克风、聊天均关闭，尚未验证真人开麦、麦克风权限、日文推理、长时间运行或 PC 休眠恢复。
- 智谱的请求构造、热词与选项保留经过回归检查；未调用真实智谱 API。

应用包也已验证实际 PC 新句播放、PMX 口型、菜单退出及 SIGTERM 退出、转发进程/端口释放与立即重启。79 项相关回归检查通过，PC 的 ASR/TTS 两个实际 GPU 进程均确认在获准的 RTX 4080 SUPER UUID 上。报告：`.runtime/pc-voice-inference-validation.json`、`pc-voice-playback-validation.json`、`macos-bundle-pc-voice-validation.json`、`macos-bundle-pc-voice-sigterm-validation.json`、`pc-voice-gpu-validation.json`。预览与日志留在 `.runtime`，不进入 Git。

复验实际播放与口型（会发声，不开麦）：

```bash
python -m tools.verify_pc_voice
```

协议/取消/缓存/云端选择回归使用本地模拟后端；这些测试不证明 GPU 性能：

```bash
PYTHONPATH=tests python -m unittest test_settings test_stt test_tts test_remote_voice
```

## HTTPS 域名直连（2026-10-07）

安装版已切换至 `https://bridge.oieasklja.icu`，不启动 SSH 隧道。设置 → 语音可填写 HTTPS 地址及桥接访问令牌；修改后重启。SSH 配置继续保留，切回回环 HTTP 地址即可使用隧道。

PC 当前通过 Cloudflare Tunnel 转发到回环 19881，19882 继续仅本机使用。桥接所有端点校验 Bearer 令牌，匿名请求返回 401。Mac 私有配置与 PC 私有令牌文件保存凭据；公共源码与应用包不含令牌。新部署可使用 `tools.deploy_pc_voice --token-file <PC私有令牌文件>`，文件至少 32 字符且无空白。

41 项回归通过。新 RemoteVoice 实际 HTTPS 合成、STT 与无 SSH 进程均已验证；安装版恢复爱弥斯后通过 HTTPS 实际播放并驱动口型，麦克风保持关闭。证据 `.runtime/https-client-validation.json`、`https-stt-validation.json`、`https-bundle-validation.json`。Cloudflare 匿名验证与携带令牌验证使用相同客户端标识。

### 2026-10-08 公网 502 恢复记录

AVP 聊天报连接失败时，Mac 网关与其鉴权握手正常；PC Cloudflare 转发仍运行，但 Hsin 桥接进程已退出，回环 19881 没有监听，公网返回 502。重新启动现有 `20261007-hermes/run_bridge.py` 后恢复鉴权 200／匿名 401。沿用 RTX 4080 SUPER、私有令牌与音色；没有重启 Hermes Agent、修改全局配置或重新部署代码。

通过现有 Mac 网关验证固定文字 → PC Hermes → 有效 TTS WAV，38.54 秒完成；模拟播放 ACK 仅验证链路，不证明头显播放。具体退出原因尚未确认；恢复进程不等于已建立自动重启／开机恢复保障。后续排查须区分公网转发、19881 桥接及 Agent，不凭 502 修改 AVP 令牌。
