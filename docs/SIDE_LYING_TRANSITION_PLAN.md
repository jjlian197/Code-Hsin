# 站立与侧躺过渡

更新：2026-10-03。双形态可用第一版已接入。右键/托盘“动作 → 躺下休息”播放躺下过程并保持撑头侧躺；选择“待机”播放独立起身动作，回到手臂下垂的站立。

## 素材与转换

| 用途 | AMC 动作 | 配套 ASF | 截取与衔接 |
| --- | --- | --- | --- |
| 躺下 | [113_08.amc](https://mocap.cs.cmu.edu/subjects/113/113_08.amc) | [113.asf](https://mocap.cs.cmu.edu/subjects/113/113.asf) | 1845 帧中的 0–600 帧，原始 120 fps；保留蹲下、侧坐、放倒段，0.8 秒接入、1.2 秒末端调整，共 7 秒。 |
| 起身 | [140_03.amc](https://mocap.cs.cmu.edu/subjects/140/140_03.amc) | [140.asf](https://mocap.cs.cmu.edu/subjects/140/140.asf) | 1023 帧中的 150–870 帧；独立侧躺起身，0.8 秒准备、0.9 秒站稳，共 7.7 秒。 |

帧范围使用零起始索引。进入躺下另有 0.35 秒从当前显示姿势接入，避免触摸手势或衣发物理残留导致首帧跳姿。AMC 配套 ASF 决定骨架、轴和自由度，不能直接复制角度或只改骨骼名称。来源见 [CMU 格式说明](https://mocap.cs.cmu.edu/info.php)。四个源文件、SHA-256 和来源 URL 保留在本机转换产物中。

`tools/convert_cmu_motion.py` 按 ASF 层级、轴和稀疏 DOF 还原世界位置/朝向，保留原长度单位。`tools/retarget_cmu_transitions.mjs` 读取双 PMX，按骨长比例、关节方向和掌面坐标重定向，输出 30 fps 关键帧；源帧按 120 fps 取样。

心的腿部网格由 D 骨骼继承驱动，离线落地计算同时应用 Grant。转换按真实皮肤、手套和足部蒙皮求地面高度，加入分阶段脚点、撑地手的位置约束与可达性修正，再平滑局部姿态；首尾保持精确匹配。根部横移修正分配到整个动作段。末端沿用 Female Laying Pose 的撑头轮廓，双腿沿长裙叠放并略抬脚，校正支撑肘部。

## 固定地面与取景

虚拟地面来自站立网格最低点，背景保持透明。全身与过渡共用固定纵向比例，地面位于画布高度的 95% 处；根据完整路径预先求网格包围范围，避免逐帧重新缩放。

过渡/侧躺默认画布 1000×600，全身站立仍为 400×600。加宽保留中心，高度因屏幕限制变化时优先保留地面位置。大头模式在进入过渡时用 0.65 秒平滑拉回全身，躺稳后再平滑进入横躺上半身近景，起身时拉回全身，站稳恢复对应站立大头视角。沿用“显示模式”的正面、左斜侧、右斜侧；侧躺时选择全身可完整查看腿部和衣摆。近景按实际头部、狐耳、肩胸和手臂蒙皮轮廓取景，排除裙尾、尾巴与腿部对镜头的影响，不逐帧缩放。窄屏按上半身横向范围放宽取景。

衣发采用**骨骼布料动态版**：过渡与侧躺暂停站立 IK 和 Ammo，使用独立 PBD 粒子链计算头发、裙摆、袖摆、飘带和尾巴的重力、阻尼与惯性。固定根节点跟随身体，骨长和 PMX 邻接约束维持形状，身体胶囊与地面约束抑制穿入，限制偏移和弯曲幅度；进入渐入，起身最后 0.6 秒渐出，站立后恢复 Ammo。菜单物理开关与重置同样作用于侧躺模拟。衣发边缘保留顶点地面投影作为显示兜底，身体、皮肤、眼睛、手套不投影。取景预留动态余量。这是基于骨骼的近似布料，尚无逐三角形自碰撞或完整衣物层间碰撞。

颈部重定向先扣除 ASF 站立参考的局部旋转，再映射变化量并限制转角，避免采集骨架的固有偏角让脖子在启动时扭曲。起身复位明确写回下垂待机值与 MMDHelper 备份，避免常量轨道缓存跳过写入后留下双臂平举。

## 状态与指令

- `standing`：站立与普通动作。
- `lie_down`：躺下过程。
- `side_lying`：保持撑头侧躺。
- `get_up`：独立起身过程。

重复选择侧躺不重新开始。躺下途中选择待机或手势，先完成当前支撑段，再起身；站稳后执行最后请求的动作。起身中再选侧躺，先站稳再躺下。外部 VMD 同样等待起身，加载失败报告动作错误。隐藏暂停、显示继续；切换形态取消旧过渡，新模型以站立加载。站立后恢复原物理偏好。

眨眼、眼球鼠标跟随、口型和触摸表情继续运行；躯干呼吸、转头和陪伴手势让位给支撑动作。状态见 `renderer.info.runtime` 的 `posture_state`、`motion`、`transition_available`、`transition_duration`、`queued_motion`、`floor_y`、`pose_profile` 与 `physics_active`。生成产物携带 PMX SHA-256，模型更换后拒绝误用旧校准。

## 在新环境重建

v1.2.0按用户要求内置默认FBX及双形态过渡于`src/assets/motions/`，便携版默认配置已指向这些资源。PMX和CMU源文件不分发。默认过渡带原PMX校验；新模型或修改后的模型必须重新生成，不能移除哈希检查强行套用。源码包含转换工具；按配置放好模型和FBX后执行：

```powershell
python -m pip install -r requirements-motion.txt
python -X utf8 -m tools.convert_cmu_motion
node --loader ./tools/node_three_loader.mjs tools/retarget_cmu_transitions.mjs
```

NumPy/SciPy 仅供离线转换，桌面播放器不导入。转换器仅在缺文件时从上述四个地址下载，不覆盖现有文件。输出 `motions/hsin/first.json`、`second.json`，由 `sprite.animation.transitions` 加载；修改 PMX、定格 FBX 或参数后重新生成并验证。没有产物时保留原 FBX 定格回退；已有产物但校验失败时提示错误。

## 验证与后续细化

`tests/test_cmu_motion.py` 验证轴、父子/根旋转和无效通道。`tests/test_pose_transitions.mjs` 在真实双 PMX 上检查首尾匹配、帧间连续、无效产物拒绝、指令排队、MMDHelper 备份和连续往返的缓存释放。

`python -m tools.verify_pose_transitions` 在原生透明 Qt/WebGL 逐阶段截图，检查双形态固定尺度/地面、完整网格边界、恢复直立、重复请求、隐藏/恢复、口型、物理偏好、中途请求、手势排队、大头恢复及形态切换。报告为 `.runtime/pose-transition-validation.json`，截图为 `.runtime/behavior-transition-*.png`。`verify_touch_views` 回归真实点击和四种显示模式；`verify_side_lying` 专门检查旧 FBX 定格回退。

`python -m tools.verify_side_closeup` 检查双形态侧躺三个近景角度、上半身蒙皮范围、衣发持续运动时取景、实际面部点击、全身切换和起身恢复。报告为 `.runtime/side-closeup-validation.json`，截图为 `.runtime/behavior-side-closeup-*.png`。

后续细化手掌、前臂与地面的接触高度、坐起阶段的衣袖接触、叠腿/脚尖的观感，以及衣发贴地形状。当前脚点约束抑制支撑阶段水平滑动；撑地手仍可能局部悬空，不能据此宣布每个支撑点完全贴地。布料自碰撞、衣物层间碰撞和更自然的贴身褶皱继续留在 ROADMAP。验证覆盖 Windows 正面全身与既有大头模式；其他任意镜头角度和平台需单独验收。
