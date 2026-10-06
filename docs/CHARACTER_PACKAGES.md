# 本地角色包 v1

更新：2026-10-06。v1.3.0 与源码版支持 PMX 角色包加载、设置中的角色管理与完整配置切换，首个样本为爱弥斯。

## 使用

启动程序，打开“设置 → 角色管理”，或“角色 → 角色管理…”。首次列表提供心；检测到本机已生成的爱弥斯角色包时也会列出爱弥斯。爱弥斯初始关闭 AI 和语音，需自行绑定后端与对应音色。

1. 选择已有角色，或点击“新建角色 / 导入模型角色包…”，导入生成好的 `character.json`。
2. 填写名称、人设、聊天后端及其模型/Agent、TTS引擎、回复语言、音量、中日音色配置；Qwen可单独绑定运行环境和中日模型。
3. 点击“保存角色配置”，保存草稿而不切换；再点击“一键启用已保存角色”。草稿有改动时会要求先保存。
4. 之后可从角色菜单选择“角色名 · 完整配置”一键切换；下次启动恢复最后启用的配置。

DeepSeek、Ollama使用填写的人设。Hermes、OpenClaw使用绑定Agent自身的人设和工具，表单人设不改写其外部配置。后端地址、Key和会话凭据沿用全局连接设置；角色文件不复制凭据。音色配置引用中日权重、参考音频与台词，导入PMX不会生成音色。新角色禁用心的预存音频，避免使用错误角色声音。

角色配置保存在用户数据目录的 `.runtime/characters.json`：便携版为 `Hsin/data`，安装版为 `%LOCALAPPDATA%\Hsin`，源码版沿用项目 `.runtime`。模型加载成功后才提交聊天和音色；加载失败保留原配置并恢复原模型。切换取消旧回复/语音、丢弃迟到识别结果，并关闭麦克风，需要时手动重新开启。当前会话的聊天记录及后端会话按角色分开，聊天历史尚不跨重启保存；好感度、番茄钟和窗口偏好仍是全局状态。

本机已生成 `.runtime/characters/aemeath/character.json`。旧的“角色 → 爱弥斯 / 心 · 默认角色 / 导入角色包…”和“形态 → 一/二阶段”仍只切换视觉模型；需要联动人设与声音时使用完整配置入口。角色菜单也扫描 `.runtime/characters/*/character.json`；外部包经设置中的角色管理保存后，路径会跨重启保留。

这是引用式本地包：包含模型/贴图路径、骨架映射、表情映射和能力清单，不复制私有资源。移动或改模后需要更新引用或重新生成。角色管理将此视觉包与本机人设、聊天和音色配置绑定；目前未提供直接拖入PMX并自动生成全部映射的设置界面。

## 生成

```powershell
$samplePmx = "D:/Workspace/aemeath-spirit/src/assets/models/vrm/鸣潮_爱弥斯(绑骨修模后)_by_鸣潮_230143b4780d2dd4d00b41a07dd1c180/鸣潮_爱弥斯1.05.pmx"
node --loader ./tools/node_three_loader.mjs tools/build_character_package.mjs $samplePmx --out .runtime/characters/aemeath --morphs src/assets/character_profiles/aemeath.json --name 爱弥斯
```

输出已存在时需明确加 `--force`；可用 `--overrides 修正.json` 沿用骨架校正。生成器拒绝缺失/冲突的必需骨、缺图、无效表情映射与覆盖输入。其他角色需准备对应的 Morph 映射，不能直接套用爱弥斯文件。

| 文件 | 作用 |
| --- | --- |
| character.json | format=hsin.character、version=1、name、model、rig、morphs、capabilities |
| rig_map.json | 哈希绑定的语义骨映射 |
| morph_map.json | version=1、aliases（行为通道别名，可用 null 禁用）、expressions（原生顶点 Morph 到 0–1 权重） |
| report.json / preview.html | 骨架报告与可校正预览 |

manifest 的模型包含 path、sha256、textures；贴图逐项记录 source 与 path。所有路径支持绝对路径或相对 character.json 所在目录的路径。capabilities 当前接受 motions=[idle] 或 [idle,nod]，physics 为布尔值；表情菜单从已验证的 Morph 映射生成。角色包不能开放未校准的复杂手势、侧躺或默认配置中的 VMD。

加载前检查版本、模型哈希、资源文件与数据结构，渲染端再核对实际骨骼/Morph。异步加载失败会重载切换前的角色并显示原因；连续选择沿用请求代次，最后一次选择生效。切回心会还原默认映射、手势和过渡配置，物理偏好沿用用户选择。

## 爱弥斯与验证

爱弥斯包提供 12 项表情映射，修正左右嘴角、垂眼、眼球方向的名称差异；保留 27 个需要的顶点 Morph。眨眼、微笑/笑眯眯、星星眼、爱心眼和五元音已查看真实网格；各元音能切换并释放，未进行真实音频时序或听感验收。基础动作仍为待机/点头与视线跟随，复杂手势继续待校准。

```powershell
python -m unittest discover -s tests -p test_character_package.py
node --loader ./tools/node_three_loader.mjs tests/test_character_morphs.mjs
python -m tools.verify_character_package
python -m unittest discover -s tests -p test_character_settings.py
python -m tools.verify_character_settings
```

包验证 5 项与 Morph 通道检查通过。隔离原生应用窗口通过角色菜单加载爱弥斯、眨眼/表情/五元音、切回心双形态、无效 Morph 包恢复和连续切换检查；旧表情与口型没有残留，未校准动作菜单禁用。报告与截图为 `.runtime/character-validation/`，测试关闭语音、不开麦、不连接服务，应用状态放入临时目录；Hsin 原行为与骨架回归通过。

角色管理通过7项针对性检查及原有27项设置、聊天和TTS回归。原生窗口验证设置页保存/启用爱弥斯、菜单完整配置切回心、从磁盘恢复爱弥斯配置；验证无效Morph包失败时不提交其人设、音色或启动选择。截图和报告在 `.runtime/character-settings-validation/`。测试关闭语音、不开麦、不连接服务，未做真实新音色合成或Agent人设验收。

本轮 v1.3.0 已重新构建 EXE，冻结版验证心双形态、爱弥斯完整配置切换与返回，模型和贴图仍由用户合法导入。后续完善音色资源导入和试听，再校准爱弥斯挥手/比心/X、扩展 VPD/VMD 与角色包能力。
