# macOS 使用与开发

2026-10-07：已在 Mac mini M4、16 GB、macOS 27.0、Python 3.11.15、Qt/WebEngine 6.10.0 上验证源码和 arm64 开发应用包。使用 `b3d78fe` 加本轮 `codex/macos-port` 改动，保留双形态原版 PMX、跑步与物理后处理。参考本机 Aemeath spirit 的 `macos-port` 提交 `5aef205`；未修改其现有工作区。

当前开发状态见 [MACOS_STATUS](MACOS_STATUS.md)。以下保留基础桌面阶段的实测记录；后续真人收音、HTTPS 桥接和角色音色接入以进度文档及对应专项记录为准。

这是基础桌面版本的实测记录。聊天后端、真人麦克风和 Apple Silicon 本地语音推理还未联调。PC 合成、识别、Mac 播放与口型已单独验证。本机现已接入 PC 语音桥接，开启 TTS、保留关闭聊天与启动关麦；见 [PC 语音指南](MACOS_PC_VOICE.md)。公共应用包默认关闭语音。

## 启动

本机已配置资源后，可双击 `启动心.command` 运行源码，或双击 `dist/Hsin.app`。源码启动器使用项目 `.venv`，不依赖终端当前目录；应用包包含 Python、Qt 与本地渲染组件。开发包已做 ad-hoc 签名，未做 Developer ID 签名或 Apple 公证，尚非正式 macOS Release。

模型位于外置盘时，Finder 启动会触发 macOS 的“访问可移动宗卷”授权，需在系统弹窗点“允许”；若等待超过加载时限，授权后重新启动。已实测确认该授权请求，尚未完成允许后的 Finder 验收。当前应用包验证是从命令行直接执行包内程序。PMX 哈希读取已移到后台，以便等待授权时界面仍能响应并退出。

拖动角色移动窗口，右键打开动作和设置。菜单栏图标提供显示/隐藏、置顶、鼠标穿透开关和退出。穿透开启后可从菜单栏取消。窗口切换到其他应用时继续显示；置顶和穿透改变后重新施加原生窗口策略。应用包不显示 Dock 图标。

## 新环境

准备 Python 3.11 后运行：

```bash
./scripts/setup_macos.sh
# 自定义解释器位置：HSIN_PYTHON=/绝对路径/python3.11 ./scripts/setup_macos.sh
./启动心.command
```

依赖沿用 `requirements.txt` 的 Qt/WebEngine 锁定版本，macOS 仅追加 `pyobjc-framework-Cocoa`。此项目录音使用 Qt Multimedia，基础安装无需 Aemeath 的 PortAudio/PyAudio。

源码本机覆盖文件为根目录 `config.local.yaml`；应用包覆盖文件为 `~/Library/Application Support/Hsin/config.local.yaml`。源码 `.runtime` 与应用包用户数据分别保存；可用 `--data-dir` 指定隔离目录。只在文件尚不存在时创建配置，不覆盖已有设置。

模型包可留在仓库旁边，通过设置或本机覆盖填入两形态 PMX 的绝对路径。需要原版 `心_一阶段/心.pmx` 和 `心_二阶段/心_二阶段.pmx`，保留模型旁的 `textures` 与 `spa`。二阶段 `textures/Tail_EX.png` 缺失是已知原始资源问题，将它映射到一阶段同名贴图即可。不要把物理试验副本当作日常原版，现有动作与默认物理后处理按原版哈希匹配。

如果不用 Windows 私有动作路径，本机覆盖使用：

```yaml
sprite:
  animation:
    side_lying: src/assets/motions/side_lying.fbx
    transitions:
      first: src/assets/motions/first.json
      second: src/assets/motions/second.json
voice:
  enabled: false
chat:
  enabled: false
```

模型与个人配置不会装入开发包；初次使用应用包时在设置中导入自己的模型。源码和应用包共享 Hsin 的 18765/18766 默认端口，同时运行时需要配置不同端口。

## 构建

```bash
./scripts/build_macos.sh
codesign --verify --deep --strict dist/Hsin.app
```

输出为当前架构的 `dist/Hsin.app`，本机产物约 473 MB。构建从 `packaging/config.yaml` 生成 macOS 基础配置，显式包含图标、加载图、动作和 PMX 渲染组件；不读取 `config.local.yaml`，不包含原模型、权重或运行记录。应用包资源通过打包资源目录定位，设置与运行状态写用户数据目录，可替换应用而保留设置。

## 已验证内容

| 范围 | 实测结果与证据 |
| --- | --- |
| 原生窗口 | 菜单栏入口、穿透/恢复、置顶切换、隐藏后恢复、位置保持通过；Retina 比例为 2。`macos-window-validation.json` |
| macOS 原生策略 | 窗口不再随应用失焦隐藏；已设置所有 Spaces 与全屏辅助策略。真正的全屏/Spaces 切换尚待手动验收 |
| 双形态 PMX | 两形态贴图错误均为 0，透明像素和主体不透明检查通过；表情、点头、挥手、VMD、物理开关和复位通过。`pmx-validation.json` |
| 半速跑步与过渡 | 两形态辅助骨处理、跑步结束复位、手势中断、侧躺/起身后排队和物理开关通过。`running-validation.json` |
| 源码/应用生命周期 | 从临时目录启动、HTTP/WS、中文模型路径、重复启动、退出释放端口/子进程及立即重启。`macos-source-validation.json` / `macos-bundle-validation.json` |
| 设置与配置 | 30 项窗口、11 项设置、2 项 macOS 配置、4 项发行行为检查通过；Windows DLL 检查在 macOS 跳过 |
| 模型后台读取 | Qt 响应、文件哈希/错误、取消/关闭、过期请求与超时保护 4 项检查通过 |
| JS 回归 | 半速动作/哈希保护和物理后执行顺序通过 |

报告、日志和 PNG 均保存在源码目录 `.runtime/`，不提交 Git。预览图证明实际模型绘制，不能代替真实桌面透明合成、外接屏或长时间性能验收。跑步时裙摆/袖摆穿插等 Windows 已知限制继续保留，见 `PMX_POST_PHYSICS.md`。

## 复验

在 `.venv` 中按改动选择检查：

```bash
python -m tools.verify_macos
python -m tools.verify_macos_app --source
python -m tools.verify_macos_app
python -m tools.verify_pmx
python -m tools.verify_running
```

`verify_macos_app` 在临时数据目录与独立端口下运行，关闭聊天/语音，不打开麦克风。它检查真实双形态、HTTP/WS、启动锁、子进程清理和立即重启；端口检查使用与服务相同的地址复用语义，避免把 TCP `TIME_WAIT` 误判成残留监听。

## 下一阶段

下一步接入一个已配置聊天后端并验证真人录音/STT。PC 新句 TTS、ASR、播放与口型已验证，详见 PC 语音指南。Qwen/GPT-SoVITS 当前推理代码仍是 CPU/CUDA 路线，MPS 未适配。应用包已包含麦克风用途说明，实际授权、拒绝后恢复和设备切换需要专门联调。

Qt WebEngine 的框架和辅助进程由 PyInstaller 处理，参见 [Qt 部署说明](https://doc.qt.io/qt-6/qtwebengine-deploying.html)。正式分发还需 Developer ID 签名/公证、新 Mac 验收及各资源许可核对。
