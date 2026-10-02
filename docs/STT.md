# 麦克风识别与语音对话

右键心或打开托盘菜单，选择 **麦克风识别 → 开启麦克风对话**。聊天窗口也有开关。说完停顿约 700ms 后，识别文字进入当前 Hermes / DeepSeek 对话，回复用“语音”菜单所选中日语言朗读。听到的文字显示在气泡与聊天记录中。

麦克风每次启动默认关闭。关闭麦克风会释放设备、丢弃未说完的半句和迟到的识别结果。心回复、合成和播放期间暂停收音，结束后等待 700ms 再恢复，避免自己的声音触发循环对话；目前不支持在心说话时用声音打断，可点“停止回复”。

“麦克风设置”可选择设备、识别语言、引擎、停顿时长、底噪门限和智谱密钥。设置保存到本机 `config.local.yaml`，密钥不出现在状态接口中。输入语言和回复语言独立设置，例如说中文并让心用日语回答。

## 识别方式

默认热词为 **心、心月狐、御者、鸣潮、鳴潮、Hsin**。“麦克风设置 → 识别热词”可编辑，每行一项，保存后下一次识别生效；清空即关闭提示。智谱收到 JSON 热词列表，本地 Whisper 收到解码热词提示，按分词长度限制提示大小。热词改善专名识别，但不能保证每次准确；不会把普通词强制替换成角色名。

- **自动**：中文或自动检测时，有智谱密钥则优先 GLM-ASR；无密钥使用本地 Whisper。选择日语时使用本地 Whisper。
- **智谱**：短句以 WAV 上传到官方 `audio/transcriptions` 接口；密钥可填写在设置中，也可使用 `ZHIPU_API_KEY`。云端失败时默认尝试本地识别，状态标明回退；可关闭回退。官方接口支持中日等语言，见 [智谱说明](https://docs.bigmodel.cn/cn/guide/models/sound-and-video/glm-asr-2512)。
- **本地 Whisper**：CPU int8，不占用 GPT-SoVITS 显存，音频留在本机。默认使用已缓存的 `Systran/faster-whisper-base`；可指定其他已下载的 faster-whisper 模型目录。首次加载需要数秒，base 对轻声、专名和噪声的准确率有限。

本地 Whisper 在独立进程中运行，避免原生识别依赖与 Qt 渲染库冲突；退出程序时清理自己的识别进程。不会启动或结束其他应用的 ASR 服务。

录音为 16kHz、单声道、16bit，VAD 与能量门限共同过滤底噪，最短有效语音 300ms、保留开头 300ms、每段最长 25 秒。音频仅放在内存中，不保存现场录音。云端空结果视为没有听清，不会启动一次对话。

## 新机器准备本地识别

桌面依赖安装后，使用同一个 Python 环境安装：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-stt.txt
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base')"
```

模型下载需要访问 Hugging Face。应用不会在开麦时自动下载大文件；若模型不可用，会显示错误并关闭麦克风，准备好后可再次开启。若默认设备不支持 16kHz 或打开失败，在设置中换设备，并检查 Windows 麦克风权限。

## 验证

`python -m unittest discover -s tests -p 'test_*.py'` 覆盖断句、噪音过滤、最长句、云端错误与回退、取消与切换、旧结果丢弃、回复阻止输入及主线程回调。

`python -m tools.verify_stt_desktop` 默认离线：固定中日样本进入 VAD 与真实 CPU Whisper，使用模拟对话回复和本地语音播放验证口型、取消和防回声，不打开麦克风、不联网。报告在 `.runtime/stt-desktop-validation.json`。

加 `--live` 才打开真实麦克风检查设备释放（这段现场声音不上传），随后把固定样本发送到真实识别与 Hermes，并合成回复。需要明确授权云端测试后再运行。真人麦克风听写准确率仍需实际说话检查。
