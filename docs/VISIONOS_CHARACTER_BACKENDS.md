# visionOS 角色后端

2026-10-07。角色默认值由 Mac 网关明确绑定，不从先前 DeepSeek 测试偏好推断。

| 角色 | 默认聊天途径 | 身份和历史 | 音色 |
| --- | --- | --- | --- |
| 心 | AVP → Mac 网关 → HTTPS PC 桥接 → 已运行 Hermes | PC `default` profile；每个头显连接建立独立会话，按角色续接 | `hsin` |
| 爱弥斯 | AVP → Mac 网关 → 参考 Aemeath 的 OpenClaw | 读取 Aemeath 配置的 `agent:main:main`；沿用原有 Agent 设定 | `aemeath` |

PC 桥接增加 `/v1/hermes`，返回逐行 JSON 流；和 STT/TTS 共用 Bearer 鉴权及现有 `bridge.oieasklja.icu` HTTPS 入口。无需新增公开端口，Hermes 动态端口保持回环。PC 服务从 `C:/Users/lianj/AppData/Local/hermes/spawn-ledger.json` 发现当前登记端口，握手凭据仅在 PC 内存使用。客户端不能指定 Hermes 地址、profile 或凭据，桥接不启动或修改 Hermes Agent。

`bridge.json` 中 `hermes` 配置示例（不包含凭据）：

```json
{"hermes":{"home":"C:/Users/lianj/AppData/Local/hermes","profile":"default","url":""}}
```

角色切换立即取消旧录音、回复及播放。PC `/v1/cancel` 只取消对应请求及本桥接创建的 Hermes 会话，不触碰用户桌面会话；会话缓存限 128 个，闲置超过一小时释放引用。Agent 原生保存的会话仍由 Hermes 管理。失败会显示错误，不自动切换到其他 Agent 或 DeepSeek。

设置里的“角色默认”使用上述绑定；显式后端选择按角色分别保存。DeepSeek 仍是可选择的直连途径，不能替代角色默认 Agent。PC 和智谱两种 STT 保持可选。

验证：`test_vision_gateway.py` 覆盖角色切换与独立历史；`test_remote_hermes.py` 覆盖流式文字、续接、鉴权和取消。真实固定文字已完成两角色 Agent → 各自 TTS WAV 生成；该检查不开麦、不在 AVP 播放，不能替代真人收音和头显听音验收。

## 1.0.0 触摸语音

两角色头、手、胸、身体中日固定短句直接走既有 PC `/health` → `/v1/tts`，按角色选择 `hsin`／`aemeath`，不发给聊天 Agent，不改角色会话。音频通过现有播放器与口型链路播放；仅固定台词写入头显缓存，音色指纹变化后重新合成。需要已保存的 PC 桥接令牌。触摸语音可独立关闭，聊天、收音和持续语音会话期间暂停播报，侧躺回应保持姿态。
