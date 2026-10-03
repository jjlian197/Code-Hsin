# 心的双手比心与 X 手势

更新：2026-10-03。右键或托盘“动作 → 双手比心 / 双手交叉（X 手势）”。保留接口组名 `finger_heart`、`crossed_arms`；前者现在是双手组成心形，不再是原来的单手小心，后者不再是抱臂。

## 适配方式

参考本机 aemeath-spirit 的 `aimisi_heart.js`、`aimisi_cross.js` 与 `docs/REACTION_HEART_01.md`。比心使用同一 heartmark001 VPD 的 42 根头颈、手臂、手指旋转作为起点，再按心的真实 PMX 骨长求解。心直接使用 MMDLoader 的右手坐标，无需转换 GLB，不复制爱弥斯的绑定帧或模型单位。

- 双手比心：将手放到胸前，按指长扩大掌距，重建食指上方弧线和中央凹口；中指、无名指、小指保持三段共线，正面左右各向内下方倾斜 45°，形成 90° 下沿。相邻指按深度分开，拇指随掌保留局部姿态，不强迫所有指尖挤到同一点。
- X 手势：两只手腕跨过身体中心，前臂向上交叉，双掌朝向 +Z 镜头，前臂前后错开深度；按手指实际绑定方向伸直，保留自然张开。
- 播放：比心 3.7 秒，先抬手再形成手型、轻微歪头，之后松手回待机；X 为 4.8 秒。五次缓动采样为加法动画，首尾为单位增量，不改变骨长和局部位置。
- 隔离：不写中心、腰、腿、脚或 IK。待机手臂底层固定，呼吸仍由行为层负责，避免细小摆臂破坏接触点。动作拥有的头颈让视线骨骼叠加让位，眼神、眨眼和口型继续可用。
- 中断：相同手势重复触发不重新计时；切换到待机或其他基础动作时，当前手势增量在 0.3 秒内淡出，结束后释放手指、手臂捩骨和行为占用。切换到侧躺/VMD 仍沿用各自的加载与姿态管理，不表示两个全身动作可以同时播放。

## 源数据与维护

`src/assets/pmx_viewer/heart_pose.js` 为源 VPD 的旋转提取结果，保留 SHA-256：`d1bbeb4e375b718f3d70ed20cfe659bed47fe656e2da692484d564cf65bb5aba`。程序只依赖生成结果与本机配置的心 PMX，不依赖 aemeath-spirit 路径或原始 VPD 文件。提取工具排除肩部控制骨与全身平移，避免在 PMX 的肩部 Grant 上重复套用 GLB 方案。

需要重建时：

```powershell
python -X utf8 tools/convert_heart_pose.py D:/Workspace/aemeath-spirit/src/assets/animations/heart/heartmark001.vpd src/assets/pmx_viewer/heart_pose.js
```

`calibrated_gestures.js` 构建目标姿势；`animation_runtime.js` 管理重复触发、骨骼占用与中断释放。调试接口 `window.HsinPmxDebug.geometry()` 导出真实骨骼坐标，`view(angle)` 只切换近景镜头，`resetView()` 恢复产品取景；正常窗口不自动进入调试镜头。

## 验证与边界

已通过两个真实 PMX 的几何与运行检查：食指端点间距约 0.0505 模型单位、掌距约 2.899（校准前约 2.160），后三指正面夹角约 90°、中间/末端弯曲约 0°；X 双掌朝前，前臂留有深度间隔。数值以最后求值的骨骼位置测量，不只检查配置常数。

原生 Qt 检查覆盖两个形态、物理开关、真实菜单、保持/结束，并已查看正面与左右斜侧面网格近景。报告与截图在 `.runtime/gesture-validation.json`、`.runtime/behavior-gestures-*.png`。骨骼点接合不等于指甲/手套网格精确接触，也不是完整衣物自碰撞证明；极端视角、衣袖摆动与指尖轮廓仍可按反馈微调。

```powershell
node tests/test_motion_clips.mjs
node --loader ./tools/node_three_loader.mjs tests/test_gesture_runtime.mjs
node --loader ./tools/node_three_loader.mjs tests/test_behavior.mjs
node --loader ./tools/node_three_loader.mjs tests/test_side_lying.mjs
python -X utf8 -m tools.verify_gestures
python -X utf8 -m unittest discover -s tests -p 'test_*.py'
```

运行回归另覆盖有限/连续关键帧、重复触发计时、中途切换首帧连续、短暂释放与清理、手指复位和下半身隔离。既有侧躺退出站立的 helper 缓存修复继续通过。
