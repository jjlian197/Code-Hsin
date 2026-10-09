# Hsin 私有空间资源

PMX 与贴图只读，转换产物在 `.runtime/hsin-spatial`，应用私有资源放在 Git 忽略的 `visionos/HsinVision/Resources/Characters/HsinFirst`／`HsinSecond`。需要项目 Node Three.js loader、Python Pillow 和 `usd-core`。

```bash
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_spatial.mjs /path/心.pmx .runtime/hsin-spatial/first.json
.venv/bin/python -m tools.export_hsin_usdz .runtime/hsin-spatial/first.json .runtime/hsin-spatial/first
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_spatial.mjs /path/心_二阶段.pmx .runtime/hsin-spatial/second.json
.venv/bin/python -m tools.export_hsin_usdz .runtime/hsin-spatial/second.json .runtime/hsin-spatial/second --shared-textures /path/心_一阶段
```

将每个输出的 `Hsin.usdz`、`Motions/*.usdz`、`Motions/manifest.json` 复制到对应 Characters 目录。`--shared-textures` 仅在原贴图缺失时使用，明确记录在 provenance.json；当前二阶段原素材缺少 `textures/Tail_EX.png`，一阶段存在同名贴图。转换拒绝仍缺失的贴图或越出指定目录的引用。

骨骼动画采样共用 macOS 的 `createBuiltinClips`，30 fps，提供待机、挥手、点头、比耶、比心、双臂交叉。蒙皮和动作骨架路径一致；RealityKit 将骨骼／表情目标导入为 `Rig`，不能假设所有角色都叫 `Character`。USD 打包独立进程执行，避免资产重定位改写转换阶段内存。

当前线性蒙皮近似 SDEF；MMD toon、描边和实时布料未迁移。构建、资源引用完整或动作加载不代表全套外观和姿态验收已完成。

## Build 6：面部形变绑定

`tools/spatial_face_mesh.py` 将具有非零 `blink/smile/a/i/u/e/o` 偏移、绑定同一骨架且变换一致的面部网格合并为一个。原因是 RealityKit 的骨架权重集合虽然能列出多个面部网格，但实际只驱动首个形变网格。稀疏形变索引随顶点偏移重映射，材质子集保留原睫毛、牙齿等贴图，身体网格不合并。导出会写入私有 `face-binding.json` 供核对。

爱弥斯使用同一修复函数处理私有生成副本，资源准备工具自动执行；需要先安装 `requirements-visionos-assets.txt` 的依赖。也可独立运行：

```sh
.venv/bin/python -m tools.repair_spatial_face /path/Aemeath.usdz .runtime/aemeath-face-fixed
```

输出包含修复后的 USDZ、源文件 SHA-256 和 `face-repair.json`，参考项目及原始 PMX／贴图保持只读。Build 6 原生模拟器已观察三种模型的全闭眼及心一阶段半闭眼；AVP 外观和口型自然度仍需验收。

## Build 7：侧躺与起身

使用与原 PMX 哈希匹配的 macOS 校准 JSON，转换器拒绝与当前几何采样不匹配的模型。先生成上文的几何采样，再追加姿态：

```sh
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_postures.mjs .runtime/hsin-spatial/first.json src/assets/motions/first.json .runtime/hsin-spatial/posture-first.json
.venv/bin/python -m tools.export_hsin_usdz .runtime/hsin-spatial/posture-first.json .runtime/hsin-spatial/posture-export-first
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_postures.mjs .runtime/hsin-spatial/second.json src/assets/motions/second.json .runtime/hsin-spatial/posture-second.json
.venv/bin/python -m tools.export_hsin_usdz .runtime/hsin-spatial/posture-second.json .runtime/hsin-spatial/posture-export-second --shared-textures /path/心_一阶段
```

`src/assets/motions/{first,second}.json` 为本机私有校准资源，不提交 Git。输出九个完整骨架片段，新增独立躺下、起身与稳定侧躺；所有动作恢复全套骨骼，PMX Grant 在转换侧求值，衣发复用 PoseCloth 离线采样。将各输出 `Hsin.usdz`、`Motions/*.usdz`、`manifest.json` 和新增 `posture.json` 复制到对应 Characters 目录。`posture.json` 记录校准文件哈希、PMX 哈希、固定模型空间地面、整条路径包围盒与物理限制；没有此文件的旧资源仍可加载，但不能获得完整路径取景。

离线采样不等价于实时物理，侧躺使用稳定定格；桌面逐顶点落地投影尚未迁移。原 PMX、贴图、校准 JSON 和参考模型均保持只读。

## Build 8：完整互动资源准备

统一工具依次执行几何、校准姿态、互动采样和 USDZ 导出，只复制模型、动作与 JSON 运行资源到忽略目录，不复制中间层或带私人路径的来源报告：

```sh
.venv/bin/python -m tools.prepare_hsin_visionos \
  --model /path/心.pmx --transitions src/assets/motions/first.json \
  --workspace .runtime/hsin-spatial/build8-first \
  --destination visionos/HsinVision/Resources/Characters/HsinFirst
.venv/bin/python -m tools.prepare_hsin_visionos \
  --model /path/心_二阶段.pmx --transitions src/assets/motions/second.json \
  --workspace .runtime/hsin-spatial/build8-second \
  --destination visionos/HsinVision/Resources/Characters/HsinSecond \
  --shared-textures /path/心_一阶段
```

`bake_hsin_interactions.mjs` 将九片段扩展为十一片段：待机呼吸与半速跑步，使用桌面呼吸参数及按 PMX 哈希选择的双形态跑步 JSON。Grant 求值、全身端点与跑步包围盒均在转换侧处理；跑步原校准文件不含 PMX 哈希，转换器按已验证哈希选择对应形态文件，并另记文件 SHA-256。不宣称任意模型兼容。

`Motions/behavior.json` 包含可用表达与每帧五个触摸区域位置；表达取自 macOS `expressions`，映射到统一的原生通道。两形态当前均支持 12 种表达及四向视线；相关非零面部网格一并合并，保留各材质。触摸采用动画骨骼球形区域近似，尚非实际蒙皮三角形命中。

转换拒绝覆盖输入采样或原模型。打包后逐个检查资产引用确实存在于 USDZ 中；两形态分别核对 47／45 个贴图引用。这只证明资源引用完整，不证明透明材质、表情／跑步或 AVP 外观已验收。

## Build 11：胸辅助骨试验版本与实时衣发

仅 visionOS 的默认两形态资源替换为只读试验 PMX；macOS 模型及配置不变。转换器单独登记已验证 SHA-256，不把任意 PMX 视为兼容：

| 形态 | PMX 版本 | SHA-256 |
| --- | --- | --- |
| 一阶段 | 心_胸辅助骨_物理后试验.pmx | `793b1e9ed92e44154add8616423d5f7932422303966e0541a6c0597a4ae703c3` |
| 二阶段 | 心_二阶段_胸辅助骨_物理后试验.pmx | `247f1f0adb21ad4a6ef6bc51a03ab2293a956a4965ebb63c6a8066af3e7c02cf` |

两份试验版与各自原版的顶点、蒙皮、面片、贴图、材质、形变、刚体及约束一致；仅十根 `ZSpring_Spine_*` 辅助骨的父骨及物理后标记改变。故沿用对应身体动作校准，按新父子层级重新生成 USD 骨架、逆绑定和全部动作；原版动作不能直接混入新版骨架。来源记录同时保存试验版哈希与原版校准哈希。

生成实时资源时，姿态转换使用 `--realtime-cloth`，跳过离线 PoseCloth，原生动画每帧恢复全部模拟骨骼的动画目标：

```sh
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_spatial.mjs /path/心_胸辅助骨_物理后试验.pmx .runtime/trial/first.json
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_postures.mjs .runtime/trial/first.json src/assets/motions/first.json .runtime/trial/posture-first.json --realtime-cloth
node --loader ./tools/node_three_loader.mjs tools/bake_hsin_interactions.mjs .runtime/trial/posture-first.json .runtime/trial/interaction-first.json
.venv/bin/python -m tools.export_hsin_usdz .runtime/trial/interaction-first.json .runtime/trial/export-first
```

二阶段同理，使用对应 PMX、`second.json` 校准及必要的 `--shared-textures`。部署复制 `Hsin.usdz`、`provenance.json` 及全部 `Motions`（含 `physics.json`）。不要只替换模型或只复制动作。爱弥斯完整转换调用 `tools/prepare_aemeath_interactions.py --realtime-cloth`；旧离线模式拒绝覆盖已有实时配置，避免残留配置与错误动画叠加。

`physics.json` 包含经过校验的骨骼路径、粒子／链／接缝、模型地面、身体胶囊和十根胸辅助骨的旋转付与。运行时在 [Apple 骨架更新完成事件](https://developer.apple.com/documentation/realitykit/animationevents/skeletalposeupdatecomplete) 后读取动画姿态，经固定 120 Hz 骨骼 PBD 求解后写回 `SkeletalPosesComponent`。这是实时骨骼衣发，身体由既有动画控制；不等同于 MMD Bullet、逐顶点布料、自碰撞或真实房间碰撞。AVP 外观、穿插和性能仍需验收。

## Build 12 胸骨动态与渲染写回

- 两份试验 PMX／全部 USDZ 动作与 Build 11 相同，原文件只读。重新准备资源时，公共 `spatial_cloth_config.mjs` 会为已验证心辅助骨配置生成两条 `chestSprings`；末端偏移来自对应左右“胸先”骨，限幅 0.22 rad。旧的 version 1 衣发配置允许缺少该字段；爱弥斯字段为空。
- 胸骨动态单独求解，不混入衣发粒子；旋转写回后再执行十根辅助骨付与。衣发与胸部共用设置开关。没有迁移完整 Bullet 刚体／关节参数。
- 默认 USD 动画骨架直接写 `ModelEntity.jointTransforms`；仅姿态组件求解计数不能作为可见蒙皮证据。开发探针核对默认渲染关节调色板回读，并用真实资源蒙皮权重计算变形范围；AVP 外观验收单独记录。

## Build 13 衣料材料与接触体积

原模型及动作不变，重新生成私有 `physics.json`：节点标记 `hair`／`garment`，三种角色均含 15 个骨架胶囊体（增加胸部与髋部）。旧 version 1 无材料字段时按骨名兼容推断。衣料降低姿态恢复与跨链接缝强度，父子链长保留；头发和心胸部动态沿用原参数。碰撞半径保持固定，接触去除向内速度并保留滑动；不属于逐顶点／自碰撞求解。

静止 `side_lying` 动画事件不逐帧触发，因此场景时钟持续写回缓存中立目标的求解结果。关闭／开启物理保留静止目标，关闭时恢复中立渲染姿态，切换动作后清理；躺下端点预置目标避免静止片段开始时的事件延迟。Build 13 已安装至 AVP，实际接触外观待验收。

## Build 14 脚部校准

`bake_hsin_postures.mjs` 在 visionOS 私有姿态采样时，根据小腿方向和窗口前向 +Z 建立脚部坐标框，使脚背朝前、脚尖顺腿延伸；躺下／起身按支撑阶段平滑混入，与静止侧躺保持完整骨架端点一致。原 PMX 和 macOS `src/assets/motions/{first,second}.json` 只读；只重新部署三段姿态 USDZ 及对应姿态／互动元数据，角色几何、其他动作和物理配置保持原版本。定向姿态检查覆盖脚部前向及端点连续性，真实线性蒙皮核对足部未穿入原地面。

## Build 15 爱弥斯附加腰背补片

参考导出器生成的 `TorsoLiner` 是额外深色矩形，超出原服装轮廓。`repair_spatial_face.py` 的资源修复流程仅移除已识别的 `/Aemeath/Character/TorsoLiner` 网格，报告 `removed_reference_torso_liner`；校验对应网格与材质路径，缺少补片时安全跳过。原 GLB、原服装、参考项目导出器及动作／物理参数不变。当前角色 USDZ 同步修复，需在 AVP 验收腰背轮廓及填补网格移除后是否存在可见空隙。
