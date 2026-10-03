# Windows EXE 使用与构建

v1.1.0 为 Windows x64 便携版，无需安装 Python。下载 `Code-Hsin-v1.1.0-windows-x64.zip`，解压整个 `Hsin` 文件夹，双击 `Hsin.exe`。请保留 `_internal`，不要只复制 EXE；可为 EXE 创建桌面快捷方式。配置和运行状态保存在 EXE 同目录，建议放在可写的用户文件夹。

首次启动会打开引导，后续右键/托盘“设置…”修改。先选基础陪伴或连接 Hermes/DeepSeek，再选择自行取得的 PMX 文件；贴图须保留原目录结构，修改资源后关闭并重新打开 EXE。可分别选择两个形态。PMX、FBX、按模型校准的过渡文件不分发，自动侧躺需要导入自己的动作和过渡资源；参见源码文档 `SIDE_LYING_TRANSITION_PLAN.md`。

## 语音与识别

- 内置 28 条中日固定语音（触摸、好感度回应、试听），无需网络、GPU、Key 或 GPT-SoVITS 即可播放并驱动口型。开启语音并选择“心”即可使用。
- 附带 72 条已筛选中日角色原声和现有试听样本，位于 `_internal/voice/recordings`、`_internal/voice/samples`；原声清单保留来源与库洛署名。
- 任意新回复使用心的音色仍需另行配置完整 GPT-SoVITS 环境、训练权重与 `voice/profiles.json`。EXE 不包含这些模型。导入后启动会后台静音预热当前语言。
- 附带 `voice/config-templates` 中日训练/推理模板与 `GPT-SoVITS部署说明.md`；感谢 [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，按其上游文档下载部署后填入自己的路径。
- 可以选择 Edge 联网通用女声；备用音色和翻译默认关闭，可在设置开启。自动翻译需自己的 DeepSeek Key。
- **本版 EXE 暂缓本地 Whisper，不包含其运行组件和识别模型**。只导入模型无法启用离线听写；可配置自己的智谱 Key 使用云识别，或通过源码版使用已安装的本地 Whisper。每次启动麦克风默认关闭。

聊天默认关闭，Hermes、DeepSeek 和 OpenClaw 连接均需用户配置，OpenClaw 保持预留接口。Key 不内置，保存到本地 `config.local.yaml`；不把该文件发给别人。详细说明在对应版本源码的 CHAT、STT、SETTINGS 文档中。

## 从源码构建

在 Windows x64 Python 3.11 环境安装 `requirements.txt`、`requirements-build.txt`。本机已有完整角色音色和筛选原声后运行：

```powershell
python -m tools.prepare_release_voice
python -m tools.build_windows_release --version 1.1.0
```

前一步仅导出固定台词和筛选原声，不复制私人对话缓存。后一步使用 `packaging/Hsin.spec` 的显式清单，生成 `dist/Hsin/Hsin.exe` 与发布 ZIP、SHA256；资源目录、包结构和配置从当前项目加载，解压位置不依赖开发机路径。默认配置来自 `packaging/config.yaml`，从不复制 `config.local.yaml`。

源码目录仍使用原来的启动脚本；EXE 直接运行，不依赖这些脚本。GUI 使用 PyInstaller 无控制台入口，早期启动异常记录在 `.runtime/startup-error.log`。路径按 [PyInstaller 运行时规则](https://pyinstaller.org/en/stable/runtime-information.html) 区分 EXE 旁的配置/状态和内部只读资源；标准流处理参照 [无控制台注意事项](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)。

本发行包未做代码签名；Windows 可能显示未知发布者。macOS 和 visionOS 仍在 ROADMAP。
