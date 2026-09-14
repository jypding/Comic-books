# 天门书 Web Reader 样板项目

本样板项目复刻了 `andrewwoan/blender-to-threejs-sketchy-shader` 的核心交互与展示框架，并结合了天门书 Web Reader 的特定需求。

## 特性
- **页面切换 (Page Navigation):** 通过读取 `manifest.json` 驱动，动态更新相机构图、文本内容与布局配置。
- **布局系统 (Layout Modes):**
  - 上图下文 (Top-Bottom)
  - 左图右文 (Left-Right)
  - 全屏悬浮 (Fullscreen)
- **极简渲染管线:** 不依赖外部后处理 shader，使用原生 Three.js `EdgesGeometry` 配合基础 PBR 材质模拟轻量级的结构轮廓效果。
- **动态控制 (OrbitControls):** 带有平滑阻尼，仅通过 `position` 与 `target` 约束状态，保证切换平滑。
- **HUD 数据面板:** 实时提供 FPS 统计与相机空间参数。

## 运行方式
本项目纯前端驱动，可通过任意 HTTP Server (如 Live Server、`python -m http.server`) 本地打开 `index.html` 运行预览。