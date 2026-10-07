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
