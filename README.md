# 心 · Hsin 桌面精灵

以鸣潮角色“心”为主角的独立 Windows 桌面项目，桌面框架适配自本机 `aemeath-spirit`。

后续顺序与验收目标见 [后续计划](docs/ROADMAP.md)。

当前阶段已完成：透明无边框窗口、置顶、托盘与右键菜单、拖动、鼠标穿透与恢复、大小调整、浮动气泡、本机 WebSocket/HTTP 控制，以及独立启动和退出清理。原声数据与 GPT-SoVITS 配置见 [语音准备说明](voice/hsin_zh/README.md)。

**已经直接显示原始 PMX，无需转换 GLB。** 默认一阶段，右键或托盘的“形态”菜单切换二阶段。镜头自动适配窗口尺寸，模型以双臂下放的站立姿势显示；保留原始 toon / sphere 材质与透明贴图。两个形态均通过原生 Windows WebGL 加载和透明画面检查。

已接入 12 种原生表情与右键选择菜单，包括脸红、放松、笑眯眯、星星眼和爱心眼。内置待机、点头、挥手、V 手势、指尖比心和交叉手臂；等待回复时思考，实际朗读时轻微做手势，开麦时倾听，闲置时低频环顾和伸展。右键“陪伴动作”可分别关闭对话姿态和随机动作。读取模型原生刚体和关节，用 Ammo/Bullet 模拟头发、衣摆等部件；右键或托盘可播放动作、开关物理和重置。也支持在配置中加入本地 VMD 动作，见 [动作与物理说明](docs/ANIMATION.md)。自然眨眼、呼吸、视线跟随、触摸和实际音频口型已接入。

已修正测试动作短暂回到手臂平举的问题，挥手掌心朝向正面镜头；两个形态均通过逐帧切换与物理开关检查。

主体保持完全不透明，透明贴图采用正确的叠加方式；已修正毛发覆盖身体 alpha 和环境项造成的发灰。窗口、应用和托盘图标使用用户提供的头像原图。二阶段原 PMX 引用缺失的 `textures/Tail_EX.png`，在配置中映射到一阶段同名耳毛贴图；不改写模型或原贴图。

## 启动

本机直接双击 **`启动心.vbs`**，无需打开终端；**`重启心.vbs`** 会正常退出旧实例并重新启动，**`停止心.bat`** 用于正常退出。重复点击启动会显示已有窗口，不会多开。`start_silent.vbs` 是同样的英文入口，`start.bat` 打开调试控制台。

启动器自动寻找依赖完整的本项目虚拟环境或本机 Python，处理带空格的路径，并检查 PMX。失败时弹窗提示，诊断记录在 `.runtime/launcher.log`，程序启动输出在 `.runtime/launcher.stderr.log`。也可运行 `powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Diagnose` 只检查环境。

新环境推荐先创建项目虚拟环境：

```powershell
cd 'D:\Workspace\Code Hsin'
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

随后使用启动文件，或在终端运行：

```powershell
python -m src.main
# 也支持 python src/main.py
```

启动文件优先使用 `.venv`，不存在时使用系统 Python。首次模型准备约需数秒，窗口会显示提示。可以拖动角色；右键或托盘可切换形态、隐藏/显示、置顶、穿透、调整大小、回到屏幕右下角和显示气泡。开启穿透后，从托盘取消即可恢复鼠标操作。位置保存在本项目的 `.runtime/window.json`。

心会自动眨眼、轻微呼吸，眼神和头部跟随鼠标。点击头部、身体、手或尾巴可得到不同反应与气泡，拖动与触摸分开处理。右键可关闭眼神跟随、眨眼或停止语音；本地原声播放会按实际音量同步口型。动作、物理与口型说明见 [自然反应](docs/ANIMATION.md)。

右键或托盘的“语音”可切换中文和日本語、开启或关闭语音、试听当前语言。应用读取心的正式 GPT-SoVITS 权重配置，按需启动独立的本机推理服务；触摸回复跟随语言，生成语音同步口型。首次合成要等待模型加载。训练、缓存和接口说明见 [中日语音](docs/VOICE.md)。

“语音”菜单同时提供心 / Edge 引擎选择、自动翻译和备用音色开关。直接朗读文本可复用已有 DeepSeek 配置翻译到所选语言；合成失败后尝试另一引擎，状态会明确标明备用音色。Edge 使用联网通用女声，缓存与心的音色隔离。

“麦克风识别”菜单或聊天窗口可开启语音对话，说完停顿后自动识别并发送。中文优先使用配置好的智谱，日语使用本地 Whisper；识别语言与回复语言可分别选择。心回复、朗读期间暂停收音，麦克风每次启动默认关闭。设备、密钥和离线模型准备见 [麦克风识别说明](docs/STT.md)。

右键或托盘选择“和心聊天…”。默认连接本地 Hermes 已配置的 Hsin Agent，“对话后端”菜单可切换 OpenClaw 与 DeepSeek 直连，并打开连接设置。回复逐步显示，完成后自动用当前中日音色朗读。三种后端的会话各自独立，停止或切换会取消旧回复。详见 [对话连接说明](docs/CHAT.md)。

## 独立配置与接口

GitHub 仓库只包含代码、渲染组件、图标与说明。本机密钥、运行记录、PMX 模型和贴图、原声数据及训练权重不提交。克隆到其他机器后，在 `config.local.yaml` 配置自行取得的模型路径、Hermes 和 DeepSeek；心的音色需要本机 `voice/profiles.json` 及其对应资源，也可先选择 Edge。模型和贴图须保持原目录结构。当前版本尚无独立 EXE，依赖安装方式见上方。

| 项目 | 位置或地址 |
| --- | --- |
| 主配置 | `config.yaml` |
| 本机覆盖 | `config.local.yaml`，参考 `config.local.example.yaml` |
| WebSocket | `ws://127.0.0.1:18765/sprite` |
| HTTP | `http://127.0.0.1:18766` |
| 日志 | `.runtime/hsin.log` |
| 启动锁 | `.runtime/hsin.lock`，防止本项目重复启动 |
| 当前服务地址 | `.runtime/endpoints.json` |

两个端口均只监听回环地址，与爱弥斯的 8765/8766 分开，可同时运行。JSON 的 `type`、`data` 与成功/失败响应格式沿用参考项目，详情见 [控制接口](docs/API.md)。相对资源路径始终相对于本项目根目录，与启动时的工作目录无关。

没有运行时依赖 `D:\Workspace\aemeath-spirit`。迁移了背景类与气泡组件，适配了窗口标志、托盘、拖动和控制协议；复用来源及原始文件摘要记录在 [迁移说明](docs/ARCHITECTURE.md) 和 `docs/reference-provenance.json`。

## 验证

与参考项目尚未对齐的功能及暂缓项见 [功能差距清单](docs/FEATURE_GAPS.md)。

```powershell
python -m unittest discover -s tests -v
node tests/test_motion_clips.mjs
# 应用运行时手动查询或显示气泡
python tests/test_client.py status
python tests/test_client.py message --text '御者，我在这里。'
```

自动测试运行真实 Qt 控件和本地 HTTP/WS 服务，覆盖透明标志、画板拖动、点击广播、气泡定时与屏幕定位、菜单穿透恢复、参数验证、接口错误，以及退出后端口释放。端口测试使用临时端口。

模型验证与导出预览：

```powershell
python -m tools.verify_pmx
python -m src.main --run-for 25 --snapshot .runtime/pmx-first-preview.png
```

模型验证在原生 Qt/WebGL 窗口中执行双形态加载、背景透明与脸部不透明检查、真实 WebSocket 控制、动作骨骼变化、物理开关与复位、测试 VMD 播放和恢复待机，结束后自动关闭。记录位于 `.runtime/pmx-validation.json`，双形态和挥手预览位于 `.runtime/pmx-*-preview.png`。WebGL 验证需要正常的 Windows 桌面会话；窗口框架测试仍可离屏运行。

渲染器组件已保存在项目内，运行时无需访问网络或参考项目。第三方来源见 [渲染说明](docs/PMX.md)。模型署名为“鸣潮/白泽”，原始 Readme 限制非 MMD 视频用途、商用和二次配布；本地接入不代表获得对外发布授权。
