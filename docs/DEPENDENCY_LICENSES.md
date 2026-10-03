# 分发与第三方说明

应用代码随同版本源码公开，采用 GNU GPL v3；第三方代码和媒体保留各自权利。GPL 文本随包提供，源码与构建入口见 https://github.com/jjlian197/Code-Hsin/tree/v1.1.0 。源码包含应用程序与重建工具；模型受独立限制，不随程序许可重新授权。

| 组件 | 使用与来源 |
| --- | --- |
| PyQt6 / PyQt6-WebEngine | GPL v3 开源版本；[Riverbank 许可](https://www.riverbankcomputing.com/software/pyqt/intro) |
| Qt6 / QtWebEngine / Chromium | 对应动态库及第三方条款；[Qt 许可与源码](https://doc.qt.io/qt-6/licensing.html)，Qt 6.10.0 源码 https://download.qt.io/archive/qt/6.10/6.10.0/ |
| Python 3.11 | PSF 许可；https://www.python.org/downloads/source/ |
| PyInstaller 6.19.0 | GPL 与启动器分发例外；https://pyinstaller.org/en/v6.19.0/license.html |
| Three.js / MMD 解析器 / Ammo / fflate | 原有许可证保留于 `_internal/src/assets/pmx_viewer/lib` |
| FFmpeg | Qt 音视频运行库，随 Qt 分发的许可信息保留；https://ffmpeg.org/legal.html |
| aiohttp / websockets / requests / PyYAML / loguru / edge-tts / webrtcvad | 依赖元数据与许可文本保留在 `_internal` 的 dist-info/licenses 目录 |
| 图标、加载插画、角色语音 | 鸣潮 / KURO GAMES 角色素材，保留库洛原署名与原声来源；不是 GPL 资产 |

程序无商业售卖或官方身份声明。原声清单只保留已筛选角色台词，固定回应是本机已训练音色的合成结果，不混入私人聊天。原 PMX 模型说明禁止二次配布，用户须自行取得并导入。Aemeath spirit 提供透明窗口/气泡等参考，复用记录保存在源码 `docs/reference-provenance.json`。

本次 EXE 不包含 Whisper/CTranslate2 识别组件或模型，也不包含 GPT-SoVITS/PyTorch 权重与推理环境；源码版可由用户独立安装这些依赖，遵循各自上游许可。
