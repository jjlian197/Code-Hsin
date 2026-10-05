# 第一批本地模型测试

本批仅准备和评估独立后端，不修改桌面精灵的现有配置。

资源放在 `.runtime/local-model-tests/`，被现有忽略规则排除，不提交模型、参考录音或生成音频。

| 资源 | 第一批选择 |
| --- | --- |
| 主模型 | ggml-org/gemma-4-E4B-it-GGUF，Q4_0 |
| 音频投影 | mmproj-gemma-4-E4B-it-BF16.gguf |
| 主模型运行库 | 官方 llama.cpp Windows x64 CUDA 包及匹配 DLL |
| TTS | Qwen/Qwen3-TTS-12Hz-0.6B-Base 完整目录，包含 speech_tokenizer |
| TTS 环境 | 项目内独立 Python 3.11 环境，PyTorch/Torchaudio 2.7.1 CUDA 12.8、qwen-tts 0.1.1 |
| 对照原声 | voice/profiles.json 中已有中日原声及准确文本，只读使用 |

下载入口支持未完成文件续传，记录模型仓库 revision，核对大文件 SHA256。首次安装完成后生成依赖版本记录。断网发行所需 wheel 包收集安排在真实推理通过之后，避免把尚未验证的环境当正式离线依赖包。

```powershell
python tools/prepare_local_models.py
```

首先分别运行，避免两个后端同时挤占8GB显存。默认按显卡UUID选择5060 Laptop；两张显卡的CUDA序号与nvidia-smi显示顺序不同，不能依赖设备0。测试输出必须核实目标显卡，不能把另一张显卡成绩算作8GB验收。需要换机器时可明确设置CUDA_VISIBLE_DEVICES。

```powershell
# 一个终端启动本机服务（18790端口）。关闭该终端内服务后再单独测TTS。
python tools/run_local_model_tests.py server
# 另一终端检查文本、工具参数与现有短录音转写。
python tools/run_local_model_tests.py gemma
# 使用独立环境生成中日试听WAV。
& .runtime/local-model-tests/venv-tts/Scripts/python.exe tools/run_local_model_tests.py tts
```

结果位于 `.runtime/local-model-tests/results/`。TTS使用本机资源并强制离线加载，生成文件而不自动播放；耗时是完整句子合成时间，不能当作流式首包延迟。显存记录为PyTorch分配/保留峰值，尚不包含其他进程，需要后续与nvidia-smi及PMX共同运行测量。

文本用例见 [测试台词](local_model_test_cases.json)。工具测试仅检查请求参数，不执行文件或系统操作。听写先用已有干净短录音初筛；真实真人录音、噪声、混合语言及热词仍需后续专门验收。现有原声没有标注为小狐狸/岁主双阶段，当前只能作为音色基线，不能据此宣布语气切换通过。

通过资源完整性、CUDA初始化及离线单次推理后，再评估用户听感、主模型与TTS共同显存、流式取消、Agent执行和桌面角色集成。Qwen3-ASR、Qwen3.5及CosyVoice备选不在本批下载。

首轮发现默认思考会消耗短回复的输出预算，基础测试入口关闭显式思考，先检查最终回复；这不代表已经比较不同思考预算的复杂推理能力。Gemma与音频投影加载后，一次系统显存采样为7091MiB（含原有桌面占用，不是模型独占或峰值）。8GB上同时常驻TTS的余量较小，后续需比较模型卸载、CPU投影及按需加载。

准备状态：两套模型权重及音频投影下载完成、SHA256校验通过；llama.cpp b11405可启动并识别目标显卡；独立TTS环境通过依赖检查并留存版本记录。Gemma短录音初筛中，“御者”等专名仍有明显误识别；基础工具调用参数正确，推理用例出现先答30分钟再纠正35分钟，人设用例出现猫叫和较通用的助手措辞。原始结果保存在本机，不能据这组小样本给出完整准确率或宣称可替代专用ASR。

Qwen3-TTS在本机使用PyTorch SDPA，不安装FlashAttention。包导入时可能提示缺少SoX；该工具用于另一套25Hz分词器，本批12Hz模型已实际生成音频，未因此阻塞。后续若使用25Hz模型，需要另外准备相应运行库。

已完成首次离线TTS合成检查：6条WAV均生成，音频长5.04–6.48秒。模型加载3.34秒（不含Python及依赖导入），首次合成26.39秒，后续11.65–14.41秒；PyTorch分配峰值2473MiB、保留峰值2740MiB，系统显存一次采样5381MiB。当前完整句子合成尚慢于音频播放，后续先试听音色，再优化参考提示复用和推理速度；尚未验证段内流式首包、GPT-SoVITS同台词对照、取消及与主模型共同运行。报告为本机 `results/tts/report.json`，不能用客观文件检查代替听感。

官方来源：[Gemma GGUF](https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF)、[llama.cpp发布](https://github.com/ggml-org/llama.cpp/releases)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)。
