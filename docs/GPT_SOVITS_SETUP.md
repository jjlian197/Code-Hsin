# GPT-SoVITS 中日语音部署

感谢 **RVC-Boss 与 GPT-SoVITS 社区**提供语音训练与推理项目：[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)。下载、硬件要求、预训练模型和安装方法请以[上游中文说明](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md)为准。

EXE 已提供中日固定回应与试听音频，不安装 GPT-SoVITS 也能使用这些语音。生成任意新句需要部署下面的环境及音色权重；配置文件本身不包含训练好的模型。Edge 是可选的联网通用音色。

## 1. 安装上游环境

Windows 用户可按照上游说明下载并解压整合包，先用 `go-webui.bat` 验证环境。Hsin 当前独立推理脚本使用 **v2ProPlus、CUDA 和半精度**，请准备兼容的 NVIDIA GPU 环境及对应预训练资源。不要直接将不兼容版本的权重改名替换。

上游目录需要包括 `GPT_SoVITS`、`chinese-roberta-wwm-ext-large`、`chinese-hubert-base` 等资源。运行语音服务使用该环境自己的 Python；EXE 内的 Python 运行库不负责运行 PyTorch/GPT-SoVITS。

## 2. 使用已公开的中日配置

[配置目录](https://github.com/jjlian197/Code-Hsin/tree/v1.1.0/voice/config-templates)包含：

- `profiles.example.json`：Hsin 双语音色接入模板，含中文和日文参考台词。
- `zh/`、`ja/` 下的 `train_gpt.yaml` 与 `train_sovits.json`：本次实际训练参数。两种语言各训练 20 轮；中文 GPT 使用恢复训练的 batch 1 参数，日文 GPT 使用 batch 2。
- `inference.yaml`：上游推理配置模板。
- `reference_request.json`：上游 API 的参考请求示例。

先根据自己的目录替换所有占位符：`<GPT_SOVITS_ROOT>` 是上游项目根目录，`<GPT_SOVITS_PYTHON>` 是其 Python 可执行文件的完整路径，`<HSIN_ROOT>` 是自己的语音工作目录。JSON 中建议使用 `/` 路径分隔符。

训练模板依赖自己的预处理产物（文本/BERT、Hubert、语义特征等），不能跳过上游数据准备流程直接运行。预存原声清单位于 EXE 的 `_internal/voice/recordings/manifest.json`，包含文字、语言和来源；日文原声为 OPUS，训练前需转换为上游接受的音频并按台词切片、审核。中文和日文分别训练，保持参考音频内容与 `prompt_text` 一致。原声版权归 KURO GAMES。

准备好 GPT `.ckpt`、SoVITS `.pth` 和参考 WAV 后，将模板中的 `gpt_weights`、`sovits_weights`、`reference_audio` 改成这些文件的实际绝对路径。示例权重名称记录本机训练结果，仅供对应关系参考；仓库不提供这些权重，用户自己的产物名称可不同。

## 3. 连接桌面精灵

将填好的接入配置保存为自己的 `profiles.json`，在 **右键或托盘 → 设置 → 语音** 中选择它，再开启心的音色。中文和日本語共用此配置，可从语音菜单切换。切换资源后重启应用，程序会后台预热当前语言。

Hsin 自动启动独立的本机服务，默认端口为 `19880`，仅监听 `127.0.0.1`；可在设置中修改。不要在同一端口重复启动上游 API 服务。EXE 的服务脚本位于 `_internal/tools/hsin_voice_server.py`，源码版位于 `tools/hsin_voice_server.py`。

固定预存语音不需要这个服务；新句失败时请检查音色路径、上游 Python、CUDA 和服务日志。日志位于 Hsin 的 `.runtime/voice/`。仅有配置模板、没有权重或预训练资源时，应用不能生成新的心语音。

本机音色配置、训练权重、API Key 和私人对话缓存不随发布上传。公开模板与本地私有配置分开保存，升级时保留自己的 `profiles.json`。
