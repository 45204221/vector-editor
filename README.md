# Vector Editor — Qt/OpenGL 图形学实验型矢量编辑器

Vector Editor 是一个以 PyQt5 `QGraphicsView/QGraphicsScene` 为交互基础、同时提供 C++17 数值内核与桌面 OpenGL 实验后端的矢量图形编辑器。项目目标不是替代完整游戏引擎，而是把编辑器工程问题与经典图形学算法放在同一个可运行程序中，形成“可视、可用、可讲、可验证”的技术展示。

当前代码同时保留稳定的 QPainter 编辑路径和实验性 GPU 路径。OpenGL、C++ 扩展或驱动能力不可用时，基础编辑器仍可运行；实验功能会回退到 Python reference 或显示可解释的 unavailable 状态。

## 主要能力

### 矢量编辑与游戏引擎基础

- 矩形、椭圆、直线、多边形、折线、连接线、文字及流程图/电路图图元；选择、框选、复制粘贴、对齐分布和几何变换。
- 基于命令对象的撤销/重做；JSON 文档序列化不保存 GPU 句柄、实验参数或绝对图片路径。
- 图层 Z-order、锁定、隐藏与活动图层变换；变换后约束图元留在画布范围内。
- AABB/圆形碰撞体、实时碰撞高亮、连接线避障、刚体速度/质量、边界反弹和弹簧约束。

### 图形学与渲染管线实验

- 三种画布后端：传统 QPainter、命令缓冲 QPainter、实验性 OpenGL。
- 2D GPU 描边：C++ tessellation、miter/bevel/round join、butt/square/round cap、coverage AA，以及按整条路径弧长连续的 dash/dot/dash-dot。
- 3D Forward/Deferred 对照：MVP、裁剪、深度、背面剔除、光照、Shadow Map、G-buffer 与附件检查。
- 共享线性 HDR 契约：RGBA16F、Linear/Reinhard/ACES、曝光、亮度热力图和过曝遮罩。
- 五级 Bloom 金字塔，以及 10 Hz 的 32×32 GPU 亮度归约、C++ 对数直方图曝光估计和非对称时间适应。
- 纹理采样实验：Nearest/Bilinear/Trilinear、LOD、mipmap、footprint、各向异性采样，本地 PNG/JPEG，以及 Linear/`GL_SRGB8_ALPHA8`/错误 gamma mip 对照。
- SDF 实验：C++17 精确欧氏距离变换、动态字形/程序 mask、OpenGL `fwidth + smoothstep` 抗锯齿、描边、发光和 0.25×..8× bitmap/SDF 对照。
- GPU 资源、draw call、上传次数、附件尺寸、CPU/GPU 时间和 framebuffer signature 用于验证，而不是仅报告 FPS。

## 架构与数据流

```text
用户输入
  ↓
GraphicsView / Tool / 属性与图层面板
  ↓
Canvas + Shape + Layer + History（文档事实来源）
  ↓ create_render_snapshot / RenderDelta
GeometryCompiler → GeometryCache → GpuBufferBuilder / GpuArena
  ├─ QPainterBackend
  └─ OpenGLBackend → Shader / FBO / Atlas / HDR postprocess

引擎实验室（运行时配置，不写入文档）
  ├─ 3D Pipeline / HDR / Bloom / Exposure
  ├─ Texture Sampling / sRGB / LOD
  └─ SDF / Instancing / Lighting / Profiling

Python reference ↔ native/python_bindings ↔ C++17 kernels
```

关键边界：`Canvas/Shape` 拥有可保存和可撤销的编辑状态；renderer 只消费不可变快照与增量；每个 OpenGL context 独立拥有资源；C++ 内核不拥有 Qt 对象、文档对象或 GPU context。

## 目录

```text
src/main.py                  程序入口与 OpenGL surface format
src/core/                    文档模型、算法 reference、渲染快照与后端
src/ui/                      主窗口和分页式引擎实验室
src/widgets/graphics_view.py 编辑交互及后端切换
native/include, native/src   C++17 数值/几何内核
native/python_bindings       CPython 3.9 扩展边界
tests/                       单元、集成和真实 OpenGL smoke
benchmarks/                  100/1000 图元及算法基准
PROJECT_PLAN.md              结构决策、阶段门槛和实施记录
```

## 环境与运行

已验证开发环境为 Windows、Python 3.9、PyQt5。安装依赖并启动：

```powershell
python -m pip install -r requirements.txt
python src\main.py
```

程序默认可不构建 C++ 扩展运行。构建原生模块需要 Visual Studio C++、CMake、Ninja 和与运行解释器 ABI 一致的 CPython 开发文件：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File native\build_native.ps1
```

产物为 `native/bin/vector_engine_native.pyd`。设置 `$env:VECTOR_EDITOR_NATIVE="0"` 可强制 Python reference 路径进行对照。详见 [native/README.md](native/README.md)。

## 测试与可复现实验

完整自动化：

```powershell
python -m unittest discover -s tests
```

真实 OpenGL 测试会创建窗口和 context，不应与纯 offscreen 单元测试混淆：

```powershell
python tests\opengl_pipeline3d_hdr_smoke.py
python tests\opengl_texture_sampling_smoke.py
python tests\opengl_sdf_smoke.py
```

性能证据：

```powershell
python benchmarks\benchmark_native_geometry.py --counts 100 1000
python benchmarks\benchmark_pipeline.py
python benchmarks\benchmark_dash_pipeline.py
```

合格标准包括：数学 golden case、C++/Python parity、History/文档中立性、完整回归、真实 framebuffer signature、上传/重建计数稳定，以及能力不足时安全降级。GUI 的视觉与工作流手感仍需人工验收。

## 实验限制

- 这是教学/作品集取向的桌面图形学工程，不是通用游戏引擎、完整 PBR 材质系统或通用纹理容器库。
- PNG/JPEG 实验导入有文件和像素预算；BC1/BC3 当前仅报告驱动能力，未宣称实现 DDS 直传。
- 索引描边和 MultiDraw 只有在端到端基准达到约 25% 收益且驱动矩阵验证后才会启用；当前保持可移植路径。
- 自动曝光使用受控的小尺寸 GPU 归约与有界 readback，而不是每帧读取完整 framebuffer。

## 文档

- [项目分析与优化总结](PROJECT_ANALYSIS_AND_OPTIMIZATION.md)
- [持续开发计划与实施记录](PROJECT_PLAN.md)
- [原生模块构建说明](native/README.md)

## License

MIT License
