# macOS 补光与爱弥斯测试（2026-10-07）

## 补光

新增 `lighting.js`，环境光略增强，主光与侧面柔光增加，并加入正面白光。保留 MMD toon、贴图环境项、原有透明材质处理；不修改模型或贴图。开发检查可用 `HsinPmxDebug.lighting(false/true)` 比较旧灯光与新灯光。

原生窗口在同一姿态下比较不透明像素平均亮度：心 137.20 → 166.48，爱弥斯 163.47 → 199.66。数值是截图的像素指标，不是物理照度。对比图和表情、口型、切回双形态检查见 `.runtime/character-validation/validation.json`，该检查通过。

## 角色与设定

引用本机 Aemeath spirit 原始 PMX 1.05，使用已有爱弥斯表情映射及自动标准骨架匹配，生成数据角色包。人设参考该项目 `src/brain/soul.py` 的 VOICE_SYSTEM_PROMPT：电子幽灵女儿、称呼用户“父亲”、温柔活泼、自然表达。移除对某个聊天后端或固定短回答的硬编码，遵守当前对话后端能力。

安装版角色包：`~/Library/Application Support/Hsin/.runtime/characters/aemeath/character.json`。
角色列表：`~/Library/Application Support/Hsin/.runtime/characters.json`。
人设源：`src/assets/character_profiles/aemeath.persona.txt`。

复用当前全局聊天连接，凭据不复制到角色文件。爱弥斯现已绑定原项目的专用 GPT-SoVITS 音色并启用 PC 桥接 TTS，详见 `MACOS_AEMEATH_TTS.md`。当前支持待机、点头、12 种表情与五种口型，未开放心专用全身手势/侧躺。

右键 → 角色 → “爱弥斯 · 完整配置”启用；“心 · 完整配置”切回。设置 → 角色管理可编辑人设和聊天后端。

## 模型存放与验证

新应用包打开外置盘模型时出现文件打开等待。为验证安装版，复制模型到应用数据目录 `models/hsin` 与 `models/aemeath`，原模型只读保留；更新安装版资源路径前已备份配置。两套模型约 216MB，资源不进入 Git 或 `.app`。

12 项角色包与角色设置单元测试通过。真实安装版切换爱弥斯成功、贴图错误 0、人设已绑定、麦克风保持关闭。报告 `.runtime/aemeath-bundle-validation.json`。额外的损坏角色包回退检查未完成，未标记为通过。

工具 `python -m tools.register_character --package <角色包> --persona <文本> --data-dir <数据目录>` 可注册模型与人设，保留当前角色及已有配置；重复安装不覆盖用户编辑的人设。

真实 DeepSeek 人设测试：返回爱弥斯身份与“父亲”称呼，报告 `.runtime/aemeath-persona-validation.json`。安装版重启后恢复爱弥斯及模型，麦克风保持关闭。
