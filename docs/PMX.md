# PMX 显示

`src/core/pmx_view.py` 管理 Qt WebEngine、加载状态和 QWebChannel；`src/assets/pmx_viewer/viewer.js` 负责 PMX、贴图、站立姿势、镜头和基础顶点表情。浏览器页面禁止访问远程资源，所有运行文件都在本机。

Three.js 固定 r165，与参考项目原来的渲染库一致。核心文件取自本地参考项目；MMDLoader、MMDAnimationHelper、CCDIKSolver、MMDPhysics、TGALoader、MMDToonShader、mmdparser.module.js 和 Ammo WASM 来自 [Three.js 官方 r165](https://github.com/mrdoob/three.js/tree/r165/examples/jsm)。第三方文件保持原样，许可证保存在 `lib/three/LICENSE`、`lib/three/addons/libs/LICENSE.mmd-parser` 和 `LICENSE.ammo`。文件摘要见 `pmx-vendor.json`。

## 本地模型

模型：鸣潮/白泽。保留原文件夹及 Readme，不转换、不改写、不对外配布。二阶段的 `Fur_Ear` 材质引用缺失的 `textures/Tail_EX.png`；`config.yaml` 的 `texture_overrides` 将其映射到一阶段同名原贴图。未配置的缺失贴图会明确报错。

| 形态 | 顶点 | 三角形 | 骨骼 | 材质 |
| --- | ---: | ---: | ---: | ---: |
| 一阶段 | 92,521 | 117,580 | 876 | 47 |
| 二阶段 | 80,184 | 101,613 | 924 | 45 |

从骨骼下放两臂后计算包围盒，正交镜头随窗口比例调整。保留原始 MMD toon / sphere 材质，读取贴图 alpha 后设置材质透明标志与标准 source-over 混合，防止透明毛发直接覆盖身体 alpha；环境光项乘以贴图颜色，减少深色衣服发灰。模型切换会释放旧几何、材质、贴图和骨骼纹理；使用请求编号丢弃过期加载结果。

七种基础表情、眨眼、五种元音和视线使用原生顶点 morph，仅构建所需的 22 个 morph，避免为原模型百余个表情全部分配 GPU 纹理。已经接入基础动作、VMD 骨骼动画、模型原生刚体物理、呼吸、鼠标跟随、触摸反应和本地音频口型，详情见 `ANIMATION.md`。MMDLoader 对 SDEF 仅作线性蒙皮近似，大幅度或复杂外部动作需要另外调试碰撞和蒙皮；渲染效果不等同游戏本身。

## 验证

`python -m tools.verify_pmx` 在原生 Windows 桌面运行 Qt/WebGL，以临时端口检查双形态与真实 WebSocket 控制，并验证画面非空、透明背景、表情改变画面及背景层合成。结果与预览保存在 `.runtime/`。`node tools/inspect_pmx.mjs` 另提供 PMX 解析和贴图路径检查，需要本机 Node.js 和项目 Python。
