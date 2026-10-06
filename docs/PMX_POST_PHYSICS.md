# PMX 物理后与跑步实验

2026-10-06：源码实验版支持骨骼的物理后阶段；v1.3.0 已发布的 EXE 尚未包含本轮修改。

加载器保留 PMX `0x1000` 标记。非共享物理的动画更新分成物理前求解、刚体模拟/回写、物理后求解；每阶段按变形阶层与骨骼索引排序，同阶段 Grant 依赖先求父，跨阶段读取当前姿态，避免重新计算父骨并重复叠加旋转。关闭物理时仍计算两组骨骼；静息冻结姿态在第二阶段之前恢复。

当前沿用 Three.js 的 PMX 求解能力：支持已实现的旋转 Grant 与 IK，局部付与和位移付与仍有上游限制；共享物理模式暂不使用此分阶段路径。模型父子关系和 Grant 仍需正确，标记本身不会修复碰撞参数。

本机心的一阶段副本将181/183/185/187/189改绑124（左胸），182/184/186/188/190改绑123（右胸），十根骨开启物理后。二阶段按同名辅助骨修改175–184。当前源码日常播放器对已验证的心双形态原版哈希，在加载后、构建网格前应用相同修改，并保留现有胸部补偿，作为后续默认效果。原PMX文件和路径不改写；副本和用户FBX不提交或分发，转换后的双形态动作JSON随源码保存。其他模型不自动套用此修改。

## 跑步检测

用户提供 `Treadmill Running.fbx`，Mixamo 动作长7.8667秒、53条轨道。工具以30fps采样为238帧、21条Hsin骨骼轨道，保留上下/左右起伏并移除前后位移。日常动作菜单新增“跑步（半速）”，关键帧时间翻倍至15.7333秒，物理仍按实际帧间隔推进。腿部FK播放时关闭原腿IK，避免被拉回站立；结束或中断恢复待机骨骼、动画备份和IK，侧躺中请求时先起身。尚未提供通用FBX导入菜单或完整脚掌接地/衣物适配。

```powershell
node --loader ./tools/node_three_loader.mjs tools/build_fbx_physics_trial.mjs "D:/Workspace/Treadmill Running.fbx" "你的PMX路径" ".runtime/pmx-physics-trial/running-first.json"
python -m tools.verify_post_physics --verify --running
python -m tools.verify_post_physics --running
```

预览使用本机已有的 `.runtime/pmx-physics-trial/patch-report.json` 及双形态 `running-first.json`、`running-second.json`。下拉选择原版/副本和形态，“原生胸物理”跳过应用既有补偿，取消则使用补偿；“近景”观察胸部跟随，“物理”和“重置物理”便于比较。预览不开聊天、语音或麦克风，不保存日常状态。

用户实际观察认为“改绑副本 + 关闭原生胸物理”效果最好，开启原生胸物理后未观察到乳摇。交互预览默认使用该组合；自动对照验证仍开启原生胸物理，用于检查不依赖补偿的求解顺序。对照窗口跳过日常播放器的自动改骨，确保“原模型”分组仍是原版。关闭“原生胸物理”仍保留胸部动态：使用现有补偿中的受限旋转及回弹，胸部位置跟随骨骼。日常默认已采用这套组合，原生刚体/关节模式继续作为开发对比项；上述观感尚未证明原生模式不明显的具体原因。

两种形态的原版和副本各运行16.4秒以上，约两个完整动作周期；共133次实时采样，贴图错误0、骨骼坐标有限，每种约498–501次物理更新。改绑副本的十根辅助骨与本帧胸骨按原Grant权重计算的四元数误差最大约 `7.3e-8` 弧度。这个指标证明执行顺序生效，不代表裙摆、袖子或身体碰撞已经精修；大幅跑步可见裙摆穿插，需后续校准。

执行顺序回归覆盖物理回写、依赖排序、重复帧、物理/Grant开关、静息冻结恢复与无标记路径；原双形态动作/骨架检查及8项原生比心/X手势与物理开关回归通过。报告和截图在 `.runtime/pmx-physics-trial/`。

默认效果接入后，双形态半速菜单、物理开关、结束复位、手势中断与侧躺起身后排队检查通过，报告在 `.runtime/running-validation.json`。原生手势8项和躺下/起身87项回归再次通过，报告分别为 `.runtime/gesture-validation.json` 与 `.runtime/pose-transition-validation.json`。半速关键帧检查确认总时长和每条轨道时间均翻倍，默认改骨检查确认仅指定十根辅助骨的亲骨骼及标记变化。

```powershell
node --loader ./tools/node_three_loader.mjs tests/test_post_physics.mjs
node --loader ./tools/node_three_loader.mjs tests/test_running.mjs
python -m tools.verify_running
```
