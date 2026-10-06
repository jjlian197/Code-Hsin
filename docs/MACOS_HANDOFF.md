# 心 · Hsin macOS 开发交接

更新：2026-10-06。接收环境：用户的 Mac mini。本文根据当前 Windows 工作区的代码和文档整理；macOS 尚未运行或验收。Mac mini 的芯片、内存、macOS 版本及已有 Python 环境需在接手时记录。

## 1. 接手时首先确认

当前项目是 **心 · Hsin 桌面精灵**，实际架构为 **PyQt6 + QWebEngine + Three.js/MMDLoader + Ammo/Bullet，直接加载 PMX**，不是 Live2D。入口为 `python -m src.main`。

根目录 `AGENTS.md` 仍是 Sherry/Live2D 旧架构说明，其中双平台目录、8765/8766 端口、`start_sherry.sh` 和 Live2D 初始化步骤不对应当前仓库。开发原则继续遵守，架构、路径和命令以当前源码及本文为准。本次只编写交接文档，未修改该文件或应用代码。

目标是在同一仓库适配 macOS，尽量共用角色、渲染、动作、聊天和控制协议，仅为真实的平台差异增加适配。先完成 Mac mini 上的源码运行，再处理发行；visionOS 不在本次开发范围。

## 2. 源码基线与提交状态

- 仓库：<https://github.com/jjlian197/Code-Hsin>；当前分支 `main`。
- 本文提交前的源码 HEAD：`c806654`（`Add half-speed running and default post-physics chest rig`）。
- Windows 正式发行基线：v1.3.0；安装包和便携版已经发布。
- 下一版跑步与 PMX 物理后阶段改动已纳入 `c806654`，包括关联 Python/JS、双形态动作 JSON、测试工具及 `docs/PMX_POST_PHYSICS.md`。这些改动仍不包含在 v1.3.0 已发布 EXE 中。

编写本文时这些源码改动尚未提交；提交交接文档前已确认它们全部纳入上述提交，工作区仅剩本文未跟踪。Mac 接手时获取包含 `c806654` 及本交接文档的最新源码，不要仅下载 v1.3.0 标签。私有模型、语音、权重与本机配置仍需按第 4 节单独搬运。Windows 开发环境继续保留为对照基线。

建议在 Mac 上确认交接文件齐全后创建 `codex/macos-port` 分支。先核对 `git status --short` 和 `git log -5 --oneline`，记录实际接手的提交，避免把不同版本的 Python、JS 和动作资源拼在一起。

## 3. 已有功能和迁移边界

Windows 当前已有：透明无边框置顶窗口、拖动、穿透恢复、托盘与右键菜单、大小/位置/近景保存、双形态 PMX 与原生表情、头发衣摆物理、眨眼呼吸和视线、触摸与手势、侧躺/起身与闲置休息、分句气泡及实际音频口型、聊天、STT/TTS、角色配置切换、心情好感度、番茄钟、本机 HTTP/WS 服务和退出清理。

下一版工作区新增双形态“跑步（半速）”，约 15.73 秒后恢复待机；侧躺时先起身再执行。对已验证原模型在内存中应用十根胸部辅助骨改绑及物理后标记，保留既有胸部补偿，不改写原 PMX。其他模型不自动套用。详见 [物理后与跑步说明](PMX_POST_PHYSICS.md)。其中验证结论来自既有 Windows 记录，本次没有重跑；脚掌接地、掌面、首尾过渡及裙摆/袖摆穿插仍待精修。

仍需保持的功能边界：

- 复杂动作只开放已匹配、已校准模型的能力，不宣称任意 PMX 通用。
- OpenClaw 仅保留接口，实际服务联调与自动启动继续暂缓。
- 4B 本地聊天尚未开放工具执行；日语质量、真人收音、首音频延迟、长时间与完整断网验收未完成。
- Windows 的 NVIDIA 显存和延迟结果不能用作 Mac mini 性能结论。
- 自主切换形态与 visionOS 属于后续计划，本轮不顺带实现。

## 4. 需要随开发环境私下搬运的资源

Git 不包含完整运行资源。查看 `.gitignore`，按实际需求挑选，不要直接把整个 Windows 虚拟环境复制到 Mac。

| 资源 | 搬运方式与注意事项 |
| --- | --- |
| 心的双形态 PMX、完整贴图目录和模型说明 | 私下转移自行取得的原模型；保留目录层级。来源见 README。二阶段缺失的 `textures/Tail_EX.png` 通过配置映射到一阶段同名贴图 |
| 本地动作 | `motions/hsin/first.json`、`second.json` 和本地侧躺 FBX 若当前配置仍引用它们，需一起转移；Git 已包含 `src/assets/motions/first.json`、`second.json`、`side_lying.fbx`，也可显式改用这些同版本资源 |
| 新跑步资源 | 使用 c806654 中已提交的双形态 JSON 及关联源码。日常播放使用生成后的 JSON；原 `Treadmill Running.fbx` 仅重建/校准时需要，私下另存 |
| 固定语音与原声 | `voice/presets/`、`voice/samples/`、中日 `selection.json` 及其引用音频可能被 Git 忽略；按配置实际引用转移 |
| GPT-SoVITS | `voice/profiles.json`、中日 GPT/SoVITS 权重、参考音频和文字、对应模型资源；在 Mac 重建 Python 环境，重写安装位置和所有 Windows 路径 |
| Qwen | 可转移 ASR/TTS 本地模型、中文微调权重和日语参考音频；推理环境在 Mac 重建，先独立验证兼容性 |
| 个人配置与状态 | `config.local.yaml`、`.runtime/characters.json`、`.runtime/characters/`、`mood.json`、`pomodoro.json` 等按需备份；先用新状态调通，再导入并检查资源路径 |
| 开发诊断 | 可选择保存已有 `.runtime/*validation.json`、截图和物理实验报告作 Windows 对照；物理对照预览依赖本地 `patch-report.json` 与模型副本，不属于日常启动必需项 |

密钥和个人语音配置只私下转移，不进入 Git。不要搬运旧 `hsin.lock`、`endpoints.json`、进程状态或 Windows `.venv`。模型和角色素材继续遵循各自许可，迁移开发环境不代表取得对外分发许可。

## 5. Mac mini 第一轮启动

以下是待在 Mac 执行的准备步骤，不是已验证的 macOS 安装器。现有 `.vbs`、`.bat`、`scripts/start.ps1`、`scripts/install.ps1` 都是 Windows 入口；仓库目前没有已验证的 Mac 启动脚本。

记录 `sw_vers`、`uname -m`、`python3 --version` 和 `node --version`。Apple Silicon 优先保持 Python/Qt 的架构一致；Intel 则按实际架构准备。依赖先尝试当前锁定版本，失败时记录具体 wheel/架构问题，再做最小的 macOS 依赖调整，避免顺手升级 Windows 依赖。

在已完整转移的项目根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.local.example.yaml config.local.yaml
```

`cp` 仅适用于尚无 `config.local.yaml` 的首次准备；已有配置先备份，勿覆盖。基础依赖为 PyQt6/Qt6/WebEngine 6.10.0、websockets 12.0、aiohttp、PyYAML、loguru、Edge TTS、requests 和 webrtcvad-wheels，完整版本以 `requirements.txt` 为准。Node 用于开发转换和 JS 检查，日常 Qt 应用不是 Node 服务；渲染库已在仓库内。

先在 `config.local.yaml` 合并以下覆盖，避免首轮启动依赖旧语音/聊天环境：

```yaml
voice:
  enabled: false
chat:
  enabled: false
```

麦克风每次启动默认关闭，保持关闭。先设置 `sprite.renderer: placeholder` 验证窗口与服务，再改回 `pmx` 并配置双形态模型、贴图覆盖及动作路径。可通过设置界面或本机覆盖文件指定 Mac 上的绝对路径；相对资源路径按项目根目录解析。

特别检查 `config.yaml` 当前引用的是本地 `motions/hsin/` 和 `Female Laying Pose (1).fbx`。若不转移这些资源，在本机覆盖中显式设置：

```yaml
sprite:
  animation:
    side_lying: src/assets/motions/side_lying.fbx
    transitions:
      first: src/assets/motions/first.json
      second: src/assets/motions/second.json
```

启动及最小检查：

```bash
python -m src.main
# 另开终端，激活同一环境后查询
python tests/test_client.py status
python tests/test_client.py message --text '御者，我已经来到 Mac 了。'
```

也可用 `python -m src.main --run-for 25 --snapshot .runtime/macos-first-preview.png` 做一次自动退出预览；需真实桌面会话，截图本身不替代检查桌面透明合成。`--headless` 只适合部分框架检查，不能证明 PMX/WebGL 在 Mac 可用。

## 6. 已确认的平台适配入口

| 文件/入口 | 当前事实与 Mac 下一步 |
| --- | --- |
| `src/main.py`、`src/app.py` | 共用启动入口，Qt 主线程创建窗口；后台服务退出后释放锁和端口。先保持架构，验证 Mac 上关闭、重复启动与渲染子进程清理 |
| `src/core/app_config.py` | 源码默认写项目 `.runtime`；安装版默认 `%LOCALAPPDATA%/Hsin`，非 Windows 回退仍是 `~/AppData/Local/Hsin`。`.app` 发行时需要适配资源根目录及用户数据路径，建议目标为 `~/Library/Application Support/Hsin`；现有 `HSIN_DATA_DIR`/`--data-dir` 可用于隔离开发数据 |
| `src/core/sprite_window.py` | 使用 Qt 的 Tool、无焦点、置顶和输入穿透标志，未看到专门 macOS 窗口分支。实测菜单栏恢复入口、焦点、Dock、全屏/Spaces、隐藏显示及切换标志后的位置；先验证 Qt，必要时才增加 AppKit 适配 |
| `src/core/pmx_view.py` | 本地 QWebEngine 页面 + QWebChannel；Qt 每约 33ms 推帧，上一帧未完成不堆积，隐藏暂停。检查 Mac 的透明背景、WebGL、WASM、中文路径、Retina 与外接屏，不替换整套渲染器 |
| `src/assets/pmx_viewer/` | Three.js r165、MMDLoader、Ammo 与定制动作/物理代码本地提供。需完整转移，不能用上游原版覆盖本轮 Grant/物理后改动 |
| `src/core/voice_player.py` | Qt Multimedia 播放，`QAudioBufferOutput` 提供实际音频口型；验证 Mac 音频格式、设备切换、暂停/停止和口型回零 |
| `src/core/stt_manager.py`、`src/ui/microphone_dialog.py` | 使用 `QAudioSource` 录音；权限/默认设备提示目前含 Windows 文案。补 macOS 权限流程和准确提示，保留启动默认不开麦、回复期间暂停收音 |
| `src/core/hermes_bridge.py`、`app_config.py` | 默认 Hermes home 为 `~/AppData/Local/hermes`；自动发现读服务登记。Mac 上先确定实际登记位置或填写现有本机服务地址，不猜路径、不替用户启动/修改 Agent |
| `src/core/model_process.py` | Qwen 设备选择仅 CPU/NVIDIA 路线；非 CPU/UUID 分支调用 `nvidia-smi`。Mac 首轮只能将已有设备字段设为 `cpu` 做独立可行性检查；`mps` 当前不是可用选项 |
| `src/core/qwen_worker.py` | worker 只选择 CPU/CUDA，无 MPS；默认 CUDA 清理也需在 CPU-only 环境检查。Apple Silicon 推理需单独适配并验证包、算子、精度和性能，不能只替换设备字符串 |
| `tools/hsin_voice_server.py`、`src/core/tts_manager.py` | 服务生成 GPT-SoVITS 配置时写死 `device: cuda`、`is_half: true`；须先独立验证 Mac 后端，再调整设备/精度与音色安装配置。Windows 打包 DLL 修复已有平台条件，不应无差别删除 |
| `src/ui/fonts.py` | Windows 字体补载已用 `os.name == nt` 隔离；Mac 先检查中日字体和字号，实际出现问题才调整 |
| `tools/build_windows_release.py`、`packaging/` | 现有 EXE/安装器流程只覆盖 Windows；macOS `.app`、图标、资源、签名与分发另做，不复用 Windows 可执行文件 |

建议按 **窗口/渲染 → 动作/物理 → 固定音频/口型 → 聊天 → 录音/STT → 本地新句 TTS → 打包** 推进。固定音频或 Edge 可用于先验证播放链路；Edge 是联网通用音色，不作为“心的本地音色迁移成功”的验收。Mac 本地推理路线根据硬件与实测选择，保留既有权重，不在移植时重训。

## 7. 最小验收与记录

每完成一个阶段才运行对应检查，文档交接本身不需要跑全套测试。

1. **框架**：能启动、拖动、右键、隐藏/恢复、置顶、穿透/从菜单栏恢复；聊天窗口正常输入且角色不抢焦点；Retina 和多屏位置合理；退出后可立即重新启动，端口与模型子进程释放。
2. **渲染**：双形态贴图齐全，透明区域显示真实桌面、脸和主体不透明；物理开关/复位有效，隐藏恢复不跳帧失控；无持续 JS/贴图/WASM 错误。
3. **动作**：待机、挥手、V、比心、X、侧躺/起身、跑步；首尾复位、手势中断、侧躺排队及物理开关不破坏原行为。新跑步仍记录穿插等已知限制。
4. **服务与状态**：HTTP/WS 本机接口返回实际状态；气泡与番茄钟可见；重启保留位置/角色/好感度；缺资源给出可操作提示。
5. **声音与聊天**：先单独验证中日音频播放和口型，再接一个已配置聊天后端，验证流式文字、分句音频/气泡、停止取消、不串旧回复。Hermes 与 DeepSeek 分别记录结果；OpenClaw 暂缓。
6. **麦克风与推理**：主动开麦才申请/使用权限，拒绝后可恢复；验证真人中日收音、设备切换、回复期间暂停、停止取消。记录 CPU/其他实际后端、冷启动、首音频、内存、持续负载与内容质量。

可选定向命令（根据本轮改动选择）：

```bash
python -m unittest discover -s tests -p 'test_desktop.py'
python -m unittest discover -s tests -p 'test_settings.py'
node tests/test_motion_clips.mjs
node --loader ./tools/node_three_loader.mjs tests/test_post_physics.mjs
node --loader ./tools/node_three_loader.mjs tests/test_running.mjs
python -m tools.verify_pmx
python -m tools.verify_gestures
python -m tools.verify_pose_transitions
python -m tools.verify_running
```

原生验证工具在 Windows 编写，Mac 首次执行可能需要修正平台假设；先读所用工具，再执行。模型检查需要匹配资源和真实桌面，不将“脚本成功退出”当作全部外观验收。检查使用隔离状态，避免覆盖日常位置/配置；部分语音检查会读取私有音色或访问云服务，按当前验收需要选择。

在 Mac 新建本地验收记录，逐项写明设备/系统/提交、资源版本、成功或失败、日志/截图路径与下一步。历史 Windows 报告保留平台标签。

## 8. macOS 发行阶段

源码版稳定后再制作 `.app`，验证从 Finder 启动、资源定位、独立用户数据目录、菜单栏、音频/麦克风权限、子进程退出和升级保留配置。不要在源码启动阶段提前引入后台自启动；如确实需要，再单独设计登录项或 LaunchAgent。

Qt WebEngine 的 macOS 部署包含辅助进程、框架与资源的处理，打包及签名时按官方步骤核对，不能只复制主程序。参见 [Qt WebEngine 部署说明](https://doc.qt.io/qt-6/qtwebengine-deploying.html)。

麦克风 `.app` 必须提供 `NSMicrophoneUsageDescription`，并结合实际分发/沙盒方式核对权限与签名配置。当前录音走 Qt Multimedia，不是网页录音，需验证实际应用的权限请求；拒绝权限应有明确恢复指引。参见 [Apple macOS 媒体采集授权说明](https://developer.apple.com/documentation/bundleresources/requesting-authorization-for-media-capture-on-macos)。

当前 Qt/Python 锁定版本在该 Mac mini 上的安装与打包兼容性尚待验证；这些官方链接是实现参考，不代表当前仓库已经完成对应设置。

## 9. 后续开发应先读的资料

- [README](../README.md)、[当前架构](ARCHITECTURE.md)、[路线图](ROADMAP.md)、[设置](SETTINGS.md)。
- [PMX](PMX.md)、[动作](ANIMATION.md)、[手势](GESTURES.md)、[侧躺过渡](SIDE_LYING_TRANSITION_PLAN.md)、[物理后与跑步](PMX_POST_PHYSICS.md)。
- [角色包](CHARACTER_PACKAGES.md)、[骨架导入](RIG_IMPORT.md)、[控制 API](API.md)。
- [聊天](CHAT.md)、[语音](VOICE.md)、[GPT-SoVITS](GPT_SOVITS_SETUP.md)、[麦克风](STT.md)、[本地部署](LOCAL_SETUP.md)。
- [Windows 发行](WINDOWS_EXE.md)用于理解现有数据分离；[第三方许可](DEPENDENCY_LICENSES.md)用于资源分发核对。
- 仓库内 `skills/desktop-spirit-engineering/SKILL.md` 可作工程经验参考，但 Windows 专用步骤需按平台判断。

## 10. 给 Mac 上下一次开发的接手提示

> 请先阅读 `docs/MACOS_HANDOFF.md`，继续开发心 · Hsin 的 macOS 版。我在 Mac mini 上工作，先检查实际芯片、内存、系统、Python/Qt 环境、Git 状态及私有模型资源是否完整。当前项目是 PyQt6 + QWebEngine + Three.js/PMX，根目录 AGENTS.md 的 Live2D 架构内容已过时。保留 Windows v1.3.0 功能和 c806654 中已提交的跑步/物理后改动，在同一仓库做最小平台适配。第一轮先关闭语音和聊天、不开麦，跑通透明窗口、菜单栏恢复、双形态 PMX、动作/物理、本机接口和退出清理，再逐项接音频、聊天、麦克风与 Mac 本地推理。不要直接搬 Windows 虚拟环境、使用 NVIDIA 默认配置或宣称 MPS 已支持；不要顺带重训音色、重构渲染器、开启工具执行或开发 visionOS。遇到真实兼容问题先给出代码证据，再做针对性修改；只执行与本轮修改相关的必要检查，并记录 Mac 实测结果。
