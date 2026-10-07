# AGENTS.md — 心 · Hsin 桌面精灵

## 当前架构

本项目为 PyQt6 + QWebEngine + Three.js/MMDLoader + Ammo/Bullet 的桌面精灵，直接加载原始 PMX。入口是 `python -m src.main`，不是 Live2D 项目。平台共用同一源码树，Windows 正式发行基线为 v1.3.0；macOS 源码和开发应用包已在 Apple Silicon 验证，详情见 `docs/MACOS.md`。visionOS 已进入独立 SwiftUI/RealityKit 原型开发阶段，方案见 `docs/VISIONOS_PLAN.md`。

- `src/app.py`：Qt 主线程、启动锁、本机服务与退出。
- `src/core/sprite_window.py`：窗口、共享菜单、角色交互与各管理器。
- `src/core/model_digest.py`：后台读取 PMX 哈希，避免外置盘授权等待阻塞主线程。
- `src/core/pmx_view.py`、`src/assets/pmx_viewer/`：透明 WebEngine、QWebChannel、原始模型、动作与物理。
- `src/core/platform_support.py`：macOS 原生窗口层级和 Spaces 策略。
- `src/core/control_bridge.py`：把 HTTP/WS 请求排队交给 Qt 主线程。
- `src/core/control_services.py`：后台 asyncio 线程及端口释放。
- `src/core/app_config.py`、`src/core/user_settings.py`：配置合并、资源根目录、用户数据与本机设置保存。
- `src/core/remote_voice.py`、`local_synthesizer.py`：SSH 语音客户端与桌面/PC 共用合成逻辑；PC 独立入口 `tools/hsin_pc_voice_server.py`，见 `docs/MACOS_PC_VOICE.md`。
- `src/core/voice_player.py`、`tts_manager.py`、`stt_manager.py`、`chat_manager.py`：音频口型、合成、听写、流式聊天。
- `tools/`：定向原生验证与转换工具；`tests/`：Python/JS 检查。

## 开发原则

- 先读 `docs/MACOS_HANDOFF.md`、`docs/ARCHITECTURE.md` 和涉及模块。真实兼容问题先复现、定位再修复。
- 保留 Windows 行为，仅为真实的平台差异增加适配；原生功能集中在平台模块。
- Python 新增代码使用类型注解；复杂逻辑注释说明原因。逻辑抽取共用函数，变量自解释。
- 配置、模型哈希和动作必须匹配。Hsin 专用手势与物理后处理不宣称适用于任意 PMX。
- 原 PMX 和贴图只读使用；日常加载器按已验证哈希在内存应用十根辅助骨处理。
- 使用仓库内 Three.js/Ammo，保留现有 Grant/物理后修改；不随手覆盖为上游版本。
- 每次改动说明原因，验证真实可观察状态。成功接口响应不代表动作完成或音频实际播放。
- 检查使用隔离状态与端口；默认不开麦，不自动启动/修改用户 Agent，不把开发截图当完整外观验收。

## 环境和启动

macOS：

```bash
./scripts/setup_macos.sh
./启动心.command
./scripts/build_macos.sh
```

默认寻找 Homebrew Python 3.11，其他位置通过 `HSIN_PYTHON` 指定。`requirements-macos.txt` 复用共用依赖的 Qt/WebEngine 6.10.0，另加 Cocoa 原生绑定。用户模型通过 `config.local.yaml` 或设置导入，保留完整贴图目录。

Windows：使用已有 `scripts/install.ps1`、`scripts/start.ps1` 或 `启动心.vbs`。现有发行工具是 `tools/build_windows_release.py`；macOS 构建单独使用 `packaging/Hsin-macos.spec`。

源码数据默认在项目 `.runtime`；macOS 应用包写 `~/Library/Application Support/Hsin`。`HSIN_DATA_DIR`/`--data-dir` 可隔离数据。应用包资源只读，设置写用户覆盖，不改签名包。

本机接口仍是 `ws://127.0.0.1:18765/sprite` 和 `http://127.0.0.1:18766`，JSON 包络为 `type`/`data`。不要使用旧 Sherry 的 8765/8766 命令。

## 定向验证

根据改动选择必要检查，不例行跑全套或连接私人云端服务。

```bash
python -m unittest discover -s tests -p 'test_desktop.py'
python -m unittest discover -s tests -p 'test_settings.py'
python -m unittest discover -s tests -p 'test_macos.py'
python -m unittest discover -s tests -p 'test_model_digest.py'
python -m unittest discover -s tests -p 'test_packaging.py'
python -m tools.verify_macos
python -m tools.verify_macos_app --source
python -m tools.verify_macos_app
python -m tools.verify_pmx
python -m tools.verify_running
node --loader ./tools/node_three_loader.mjs tests/test_running.mjs
node --loader ./tools/node_three_loader.mjs tests/test_post_physics.mjs
```

窗口/模型工具需真实桌面会话及匹配私有资源；离屏测试不能证明 WebGL、桌面透明合成和 Spaces 可用。原生报告在 `.runtime`，记录系统、设备、提交和检查范围。

## 资源和边界

本机配置、密钥、语音权重、原 PMX 与贴图不进入 Git 或发行包。macOS 包默认关闭聊天/语音，麦克风每次启动关闭。Qwen/GPT-SoVITS 的 Apple Silicon 推理仍需独立验证；CPU 设备配置不是推理已可用的结论。MPS 尚未支持。实际 Spaces 切换、外接屏与真人麦克风仍需专门验收。

任何破坏性操作先说明影响并等待用户确认。不得修改 `~/.openclaw/openclaw.json`、SSH 授权或系统关键配置，不向外部发送凭据。任务结束输出变更摘要、原因和验证结果。
