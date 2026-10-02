# Hsin 本地控制接口

WebSocket：`ws://127.0.0.1:18765/sprite`。HTTP：`http://127.0.0.1:18766`。修改 `config.yaml` 或本机覆盖文件可调整端口，监听地址只允许本机回环地址。

请求保留 aemeath-spirit 的结构：

```json
{"type":"message","data":{"text":"御者，我在这里。","duration":5000}}
```

成功响应：

```json
{"type":"message_shown","data":{"text":"御者，我在这里。","duration":5000},"success":true}
```

失败响应：

```json
{"type":"error","success":false,"data":{"message":"错误说明","code":"invalid_command"}}
```

可选顶层 `id` 会在响应中原样返回。WebSocket 每个命令都有响应；触摸事件会广播给所有 `/sprite` 客户端。

## 可用命令

| type | data | 行为 |
| --- | --- | --- |
| `get_status` | `{}` | 窗口、渲染入口、模型文件存在情况、可用能力、连接数量 |
| `message` | `text`, `duration` | 显示气泡；文本 1–2000 字符，duration 为毫秒，0 持续显示 |
| `window` | `action: move`, `x`, `y` | 移动窗口，保留参考项目语义 |
| `window` | `action: resize`, `width`, `height` | 大小范围 160–1600 |
| `window` | `action: opacity`, `opacity` | 透明度 0.1–1 |
| `window` | `action: hide/show/reset` | 隐藏（含气泡）、显示、回到右下角 |
| `window` | `action: quit` | 先返回响应，再正常清理并退出 |
| `window` | `action: click_through`, `enabled` | 鼠标穿透；可由托盘恢复 |
| `window` | `action: always_on_top`, `enabled` | 调整置顶 |
| `background` | `type: transparent/purple/有效颜色` | 透明、渐变或纯色背景 |
| `background` | `type: image`, `path` | 本地图片背景；相对路径以项目根目录为基准 |
| `model` | `form: first/second` | 异步切换形态，返回 `model_loading`；查询状态确认完成 |
| `expression` | `name` | normal、happy、sad、angry、surprised、wink、sleepy |
| `motion` | `group`, `index: 0` | idle、nod、wave；tap 为 wave 的兼容别名；外部 VMD 按配置组与索引播放 |
| `physics` | `action: on/off/reset` | 开关或复位原生 MMD 刚体物理 |
| `look_at` | `x`, `y`，范围 -1–1 | 固定注视方向；x 正值向屏幕右，y 正值向上 |
| `parameter` | `id`, `value` | 设置单个受支持参数，兼容 `param_id` |
| `parameter_batch` | `params` | 一次设置多个参数；先完整验证，错误批次不部分应用 |
| `behavior` | `auto_blink`, `breathing`, `mouse_follow`, `touch_reactions` | 按需修改布尔开关；可用 `reset_parameters: true` 清除手动参数和固定视线 |
| `blink` | `{}` | 立即眨眼一次 |
| `lip_sync` | `value: 0–1`, `shape: a/i/u/e/o`, `duration: 50–2000` | 临时口型，duration 为毫秒，默认 250；超时闭合 |
| `audio` | `action: play`, `path`, `volume: 0–1` | 播放本地原声，以实际 PCM 音量驱动口型；默认音量 0.65 |
| `audio` | `action: stop` | 停止播放并释放音频口型控制 |
| `speak` | `text`, 可选 `language: zh/ja`, `speed: 0.5–2`, `volume: 0–1`, `translate: true/false` | 后台翻译与合成，返回请求编号；文本 1–500 字符 |
| `tts_config` | `language: zh/ja`, `enabled`, `provider: gptsovits/edge`, `auto_translate`, `fallback` | 布尔开关、语言和引擎持久化；支持 action: set/status/on/off/toggle/stop |
| `stt_config` | `action: set/status/devices/on/off/toggle`, `enabled`, `language: zh/ja/auto`, `provider: auto/zhipu/whisper`, `device` | 麦克风识别、设备枚举与状态；设备 ID 来自 devices，空字符串为系统默认。可选 silence_ms、energy_threshold、fallback；设置仅本次生效，持久设置在界面保存 |

窗口变更响应为 `window_updated`，背景响应为 `background_set`，表情响应为 `expression_set`，状态响应为 `status`。加载中 `renderer.model_loaded=false`、`state=model_pending`；贴图完整加载且实际绘制后为 true / idle。失败时为 model_error，`renderer.error` 提供原因。`renderer.info` 包含顶点、三角形、骨骼、材质、表情与贴图补全数量。

上述模型控制要求 PMX 已加载，加载中返回 `renderer_unavailable`。`speak` 在所选引擎与备用引擎均未就绪时返回 `tts_unavailable`，关闭语音时返回 `tts_disabled`。正常接收后返回 `tts_queued`，合成完成自动播放；实际进展与错误查询 `tts` / `audio` 状态或订阅 `tts_status`。`tts.provider` 是首选引擎，`actual_provider` 是实际音色；`warning` 标明备用音色，`stage` 包含 queued/translating/synthesizing/fallback/idle。语言或引擎切换和停止会取消旧请求的播放。本地原声播放使用 `audio`，无需训练权重。详见 [中日语音](VOICE.md)。

支持参数与范围可从 `available_parameters` 查询：角度 ParamAngleX (-30–30)、ParamAngleY (-20–20)、ParamAngleZ (-15–15)；上半身 ParamBodyAngleX/Y (-10–10)；眼球 ParamEyeBallX/Y (-1–1)；眼睛开放度 ParamEyeLOpen/ROpen (0–1)；张嘴 ParamMouthOpenY (0–1)；嘴角 ParamMouthForm (-1–1)。参数持续有效，直到设置新值、清除手动参数或切换模型。

`look_at` 持续保持目标，手动注视不受自动鼠标开关限制。发送 `behavior` 中的 `mouse_follow: true` 或 `reset_parameters: true` 可清除固定注视，恢复鼠标采样。`renderer.info.runtime.behavior` 提供实际眼神、眨眼、口型、呼吸、表情权重与最后一次触摸；`audio` 状态提供解码错误、实际音频缓冲数量和播放进度。

基础动作返回 `motion_set`，外部 VMD 返回 `motion_loading`，物理控制返回 `physics_updated`。查询 `renderer.info.runtime` 可得到实际动作、物理开关、步数、刚体/关节数量和骨骼变化；VMD 加载错误位于 `renderer.info.motion_error`。`available_motions` 包含基础动作和已配置的外部动作组。JSON 成功响应说明指令已交给渲染器，异步 VMD 需查询状态确认。

拖动与点击分开处理。单击实际模型后按命中位置广播头部、身体、手或尾巴；透明空白处不广播。示例：

```json
{"type":"touch_event","data":{"action":"tap","part":"身体"}}
```

## 对话后端

```json
{"type":"chat_config","data":{"provider":"hermes"}}
{"type":"chat","data":{"text":"今天想和你聊聊天。"}}
{"type":"chat_config","data":{"action":"stop"}}
```

`provider` 可选 `hermes`、`openclaw`、`deepseek`。`chat` 返回 `chat_queued`、编号和语言，完成结果在 `get_status.data.chat.reply`；错误在 `chat.error`。`chat_status` 广播开始、停止、后端变化和完成状态。显式 `chat.language` 可选 zh/ja，默认跟随语音菜单。切换语音语言会取消当前回复。凭据不通过控制接口设置或返回。

## HTTP

`get_status.data.stt` 和 `stt_status` 广播提供 enabled、listening、recognizing、blocked、speech_active、level、last_text、error、warning 与实际引擎，不返回密钥。`POST /api/stt_config` 接受上表字段。麦克风开关不自动开启 TTS；声音回复需开启“语音”。心回复、合成和播放时关闭录音设备，结束后延迟恢复。详见 [麦克风识别](STT.md)。

| 方法和路由 | 请求 |
| --- | --- |
| `GET /health`、`GET /api/status` | 无请求体，返回 `status` 包络 |
| `POST /api/command` | 与 WebSocket 完全相同的 type/data 包络 |
| `POST /api/window`、`POST /api/message`、`POST /api/background` | 对应命令的 data 对象 |
| `POST /api/expression` | 基础表情 |
| `POST /api/motion`、`POST /api/physics`、`POST /api/model` | 对应命令的 data 对象 |
| `POST /api/speak`、`POST /api/tts_config` | 文本合成、语音语言和开关设置 |
| `POST /api/chat`、`POST /api/chat_config` | 提交对话、选择后端、停止回复或查询状态 |
| `POST /api/look_at`、`POST /api/parameter`、`POST /api/parameter_batch` | 视线与模型参数 |
| `POST /api/behavior`、`POST /api/blink`、`POST /api/lip_sync`、`POST /api/audio` | 自然反应与本地原声口型 |

有效操作 HTTP 200，非法请求 400，未接入功能 501，界面超时或退出中 503。单次 JSON 最大 64 KiB，不接受 NaN/Infinity。所有界面读写经同一 Qt 主线程队列执行；形态切换异步完成，表情通过 Qt 交给渲染页面。

```json
{"type":"model","data":{"form":"second"}}
```

```powershell
Invoke-RestMethod 'http://127.0.0.1:18766/api/status'
Invoke-RestMethod 'http://127.0.0.1:18766/api/command' -Method Post -ContentType 'application/json' -Body '{"type":"window","data":{"action":"move","x":100,"y":150}}'
Invoke-RestMethod 'http://127.0.0.1:18766/api/audio' -Method Post -ContentType 'application/json' -Body '{"action":"play","path":"voice/hsin_ja/wav32k/Hsin_JA_1311127.wav"}'
```
