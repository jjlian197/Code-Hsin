# 心 · Hsin Spatial（visionOS 开发原型）

2026-10-08：**AVP 保持 Build 5；Build 6 面部修复已完成，Build 7 新增 Hsin 侧躺／起身；Build 8 补聊天历史与阶段 3 互动，本轮按用户要求不安装**。独立 SwiftUI／RealityKit 体积窗口，支持心一／二阶段与爱弥斯、角色音色、主动录音、文字聊天、PC／智谱 STT 和 Mac 网关。角色默认后端为心 → PC Hermes `default`、爱弥斯 → 参考 OpenClaw `agent:main:main`。

当前主线为阶段 1–3 的实装核查与补缺；面部表现方面，Build 6 已合并相关面部网格以修复睫毛同步，并接入五口型与平滑过渡，开发侧验证完成，AVP 验收待完成。阶段 1、2 的基础实现已交付，仍有 AVP 验收待办；完整进度和完成标准以 [迁移计划](../docs/VISIONOS_PARITY_PLAN.md) 为准。Hsin 转换步骤见 [私有资源转换](../docs/VISIONOS_HSIN_ASSETS.md)，后端说明见 [角色后端](../docs/VISIONOS_CHARACTER_BACKENDS.md)。全景空间与完整 macOS 功能迁移尚未完成。

## 本机资源与构建

原模型与动作不提交 Git、不对外分发。使用只读 Aemeath 工作区提供的私有开发资源：

```sh
.venv/bin/python tools/prepare_visionos_assets.py --reference-root '/你的路径/aemeath-spirit'
xcodebuild -project visionos/HsinVision.xcodeproj -scheme HsinVision \
  -configuration Debug -destination 'generic/platform=visionOS Simulator' \
  -derivedDataPath visionos/.build CODE_SIGNING_ALLOWED=NO build
```

在 Xcode 打开 `HsinVision.xcodeproj`，选择 visionOS 模拟器运行。真机需要用户自己的 Development Team、Xcode 开发者账号与描述文件；签名团队未写入工程。用户登录 Xcode 后，真机签名构建通过，已安装到用户 AVP（`com.hsin.spatial`，版本 0.1）。免费签名名额已满时，经用户明确授权卸载 `com.jjlian.AemeathCompanion` 后完成安装；描述文件于北京时间 2026-10-14 18:37 到期，届时需重新签名安装。

## 语音连接

应用默认地址 `https://bridge.oieasklja.icu`，仅保存这个公开地址；发行包不含访问令牌或聊天 API Key。首次在“桥接设置”填写访问令牌并保存，令牌按地址保存到 Keychain。Mac 私有令牌文件位于 `~/Library/Application Support/Hsin/bridge-token`；请用户自行查看并输入头显，避免发到聊天或截图。

“测试专属音色”先验证桥接身份、协议与当前角色音色指纹，再请求新句 WAV。音频实际开始播放才显示台词；停止会关闭本地播放、取消网络请求，并向 PC 发送请求编号。已运行的 GPU 推理可能继续结束，但旧结果不播放。Build 6 口型使用 PCM 能量门控、文本元音提示和实际播放时钟，平滑混合 `a/i/u/e/o`；属于近似提示，并非逐音素对齐。

PC 域名入口提供 STT/TTS；文字与语音对话经过 Mac 网关，复用 Mac 私有聊天配置、角色设定与智谱密钥。Mac → PC 使用 HTTPS，头显无需 SSH 私钥或聊天 API Key。

## Mac 网关与对话

Build 2 起默认界面仅保留底部操作条与状态；回复显示在侧边，文字输入和连接设置按需展开。visionOS 图标使用 macOS 的同一份 `src/assets/icons/hsin.png`。

以下为历史版本变更；Build 5 的角色默认取代 Build 3 的全局后端开关。

Build 3 对齐 Aemeath visionOS 的聊天通道：默认开启“使用 OpenClaw 对话”，关闭后使用 DeepSeek。Mac 网关只读 Aemeath 的私有 `voice_chat.openclaw` 设置，并按参考实现从现有 OpenClaw 配置补齐地址／令牌；不会修改或启动 Agent。当前参考会话为 `agent:main:main`，人格、模型、工具权限与历史由该 Agent 管理，因此 OpenClaw 的历史与参考应用共享；DeepSeek 历史仍按头显连接／角色隔离。头显仍只保存 Mac 桥接令牌，不保存 OpenClaw 凭据。

本轮已复现并修复录音卡在“正在识别”：原生客户端发送二进制 JSON，旧网关只接受文字帧。网关现在接受两种帧，新客户端统一发送文字 JSON，并在识别完成后显示“正在回复”。识别服务有 90 秒超时，客户端也有等待保护，超时可停止并重试。

Build 4 修复骨骼动作目标选择：RealityKit 顶层包含 `global scene animation`，它不是角色骨骼动作目标；按 `/wave` 骨骼动画定位实际 `Character` 实体后，再播放匹配的 idle／wave 资源。修复前张臂姿态已复现，修复后模拟器已看到双臂下垂待机与抬臂挥手；日志确认挥手结束后切回 idle。动作缺失不再静默忽略。Debug 专用 `--motion-smoke-test` 调用同一个挥手入口并暂停中间帧，便于原生画面检查，不采集音频；普通启动不触发测试。

用户授权自动配置后，可以在安装完成时通过配对设备连接写入一次性配置（不放入安装包）：

```sh
.venv/bin/python -m tools.provision_visionos_connection \
  --device <你的AVP设备ID> --gateway-url http://<Mac局域网IP>:18767
```

脚本读取 Mac 私有 `bridge-token`，不会在日志或命令行输出令牌；临时文件权限为 0600，传输后清除本机临时副本。应用下次启动将 PC 与 Mac 地址对应的令牌存入 Keychain，成功后消费掉设备上的一次性配置，并写入不含令牌的 `Documents/HsinConnectionReceipt.json` 供安装验收。不自动开启麦克风。此脚本只适用于两个服务共用该令牌的当前开发配置。

在仓库根目录启动网关（默认仅监听回环，局域网使用 Mac 的实际 IP）：

```sh
.venv/bin/python -m tools.hsin_vision_gateway --host 192.168.50.189 --port 18767
```

当前开发 Mac 地址为 `http://192.168.50.189:18767`，IP 可能变化。服务不会自动随桌面应用启动。默认读取 `~/Library/Application Support/Hsin/config.local.yaml`、`.runtime/characters.json` 与 `bridge-token`；不将凭据打包。头显“桥接设置”中的 Mac 网关地址及令牌需分别保存；PC 与 Mac 连接凭据均按地址存入 Keychain。

HTTP/WS 只用于可信局域网，界面明确提示未加密；跨网部署使用 `--cert`／`--key` 或 HTTPS 反向代理与 WSS。客户端拒绝公共地址的 HTTP。网关 `/health`、`/ws` 均需 Bearer 鉴权，最多四个并发会话；关闭后清理临时录音，不向桌面角色发送播放命令。OpenClaw 会话历史由上方配置决定。

输入文字并发送，或主动点击“开始录音”，说完后停止。启动不会申请录音权限或开启麦克风；录音最多 25 秒，转换为 16 kHz 单声道 Int16 WAV。STT 可选 PC 桥接或智谱；选择变化会停止旧回合。界面支持心与爱弥斯，网关处理各自的设定、后端与音色。

协议使用 `turn_id` 与句子 `index` 丢弃迟到消息，整句 WAV 顺序播放。`playback_started` 仅在 `AVAudioPlayer.play()` 成功后发送；解码或播放失败发送 `audio_discarded`，释放队列额度但不声称已经播放。最多两段尚未开始的音频可在途；字幕对应正在播放的句子，全文单独展示。停止使旧回合失效并保留聊天连接；地址变化和断线关闭会话。

## 已验证与待验收

- 模拟器与真机目标编译通过；真机签名与 AVP 安装通过，设备应用列表已确认。
- 公网匿名访问已被拒绝，Mac 新客户端携带令牌能实际合成。
- 已在模拟器看到爱弥斯与对话面板。启动时场景角色不匹配的崩溃已复现并修复；待机／挥手动画绑定已调整，调整后的动作画面尚待复验。系统盘接近满载导致桌面截图失败。
- 网关 9 项自动化测试通过，覆盖鉴权、直连会话隔离、句子顺序、录音校验、取消、播放额度、原生二进制录音与 OpenClaw 选择。真实聊天／TTS 返回有效 WAV；同一固定录音经 PC 与智谱均正确识别。验证脚本模拟播放 ACK，不代表头显实际播放。
- Build 2 已更新到用户 AVP；用户打开后，不含令牌的设备回执确认 PC／Mac 两个连接均已保存到 Keychain，一次性配置文件已消费。签名包扫描确认不含访问令牌。
- 尚未验收头显麦克风、实际声音／口型、简化界面的真机外观、空间尺寸和手势；安装成功不代表上述行为已验收。
- Build 5：心 PMX 转 USDZ 与双形态已交付，12 项针对性检查通过；后续由 Build 6 接入睫毛／多口型修复；AVP 收音、播放、动作外观仍待验收。以上较早版本的验证条目保留作历史记录。

- Build 6：心双形态与爱弥斯面部网格修复，原生模拟器已观察睫毛同步；中日真实 WAV 的口型检查与静音原生播放通过，日语实际产生五口型并在结束时归零。模拟器和真机签名构建通过；AVP 离线，尚未更新。

## Build 7：侧躺与站立

心双形态“动作”菜单新增“侧躺休息／站起来”，只在匹配的三个姿态资源均加载后开放。使用 macOS 校准的独立躺下、起身片段，中途反向请求完成当前支撑段后再执行；重复请求保持进度。侧躺时请求手势先起身，新的姿态请求覆盖先前排队手势。切换模型清空队列，使旧加载与播放控制器失效。

状态依赖实际动画完成事件／控制器状态，模型按整条路径适配一次取景；过渡中位置、尺寸及模型空间地面不变。所有片段写入完整骨架，起身后恢复根节点、腿部和衣发辅助骨。衣发为桌面 PoseCloth 离线采样，侧躺稳定定格；实时物理、逐顶点地面投影和 AVP 接触／穿模验收仍未完成。爱弥斯未开放未经其骨架校准的姿态。

资源制作见 [私有资源转换](../docs/VISIONOS_HSIN_ASSETS.md)。Debug 模拟器与 Release 真机目标（无签名）构建通过；双形态实际往返及一阶段途中反向／排队手势检查通过。一阶段躺下、侧躺、起身画面已观察；Mac 锁定后的二阶段姿态及最终站姿画面复验保留为待办。本轮没有更新 AVP。

Debug 原生姿态检查不启用麦克风：

```sh
xcrun simctl launch <模拟器ID> com.hsin.spatial \
  --character-hsin --form-first --posture-probe --posture-probe-roundtrip
```

仅 `--posture-probe` 会躺下并保持；`--posture-probe-phase=0.5` 检查躺下中段，`--posture-probe-getup-phase=0.5` 检查起身中段，`--posture-probe-reverse` 在躺下途中请求站立。私有 `Documents/PostureProbe.json` 记录进程与真实状态顺序，检查者须等对应进程回执；启动／加载耗时不能计入动作完成时间。Release 不包含测试入口。

## Build 8：聊天历史与互动补缺

“互动”菜单整合 Hsin 姿态、半速跑步、12 种表情和方向视线；设置中的互动开关按需展开。STT 和语言保存，麦克风每次启动关闭。聊天记录按角色／后端在本机保存，包含中断标记，两种 Hsin 形态共享历史；不将显示记录回灌 Agent。

待机呼吸使用桌面骨骼参数，动作／侧躺独占骨骼。十分钟无实际互动可自动休息，忙碌／加载／隐藏重新计时，输入／对话或自动休息时的触摸安全唤醒。随机环顾不会算作互动。触摸目标随当前片段更新到五个骨骼区域，并提供两秒冷却；这是球形区域近似，精确蒙皮命中与遮挡仍有差距。手动侧躺时触摸不强迫起身。

跑步复用匹配形态的 macOS 校准，半速约 15.73 秒，首尾完整站姿衔接；实际结束后恢复呼吸待机，途中排队姿态／手势。转换扩展固定路径取景。视线目前为手动方向／随机环顾，没有头显视线跟随；跑步没有实时衣发物理，爱弥斯未经校准的全身动作不开放。

双形态原生控制器的跑步复位、自动休息／程序触摸唤醒检查通过，未开启麦克风。Debug 模拟器及 Release 真机目标无签名构建通过，AVP 未更新；完整外观和真实空间点击仍由用户验收。

```sh
xcrun simctl launch <模拟器ID> com.hsin.spatial \
  --character-hsin --form-first --interaction-probe --interaction-probe-running
```

改用 `--interaction-probe-rest` 会调整闲置基准，待真实侧躺完成后程序调用同一触摸入口并等待实际起身；不会采集音频。私有 `Documents/InteractionProbe.json` 记录进程、实际状态、面部权重与触摸区域坐标，Release 不含入口。这种程序调用不能替代用户的空间手势验收。

## 参考来源

参考本机 Aemeath spirit HEAD `68ce5e0` 的 `visionos/`；工程骨架来自其 Xcode 项目，体积窗口、模型摆放与面部权重映射参考 `App/CompanionStore.swift`，面部网格合并依据 `Tools/export_usdz.py` 的睫毛导入问题记录；本项目扩展到眼白和口腔网格，并保留材质。Hsin 的 HTTPS 协议与音色选择为本项目实现。未修改参考项目，迁移来源不代表取得对外分发私有模型的许可。
