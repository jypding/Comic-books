# Needle Engine Runtime 集成指令（3DComicToolkit → viewer-needle）

> 本目录 `viewer-needle/` 是**新增并行运行时**，与旧 `app.js` 共存，不删除旧 Viewer。
> 严格按阶段顺序验收，上一阶段未通过不得进入下一阶段。

---

## 0. 硬性禁止清单（贯穿全程）

- ❌ 禁止重写 / 修改 `ModernExporter`
- ❌ 禁止修改 Blender 相机导出逻辑、改变 GLB 相机数据结构
- ❌ 禁止一次性删除旧 `app.js`（新旧双运行时并行，`?runtime=legacy` / `?runtime=needle` 切换）
- ❌ 禁止因迁移 Needle 而重新设计漫画页面 / 时序系统
- ❌ 禁止 Rapier / Multiplayer / XR 默认打进主 bundle（必须动态 import，按 page.json 开关加载）
- ❌ 禁止跳过 GLB 相机 & 动画验证直接扩展上层业务
- ❌ 禁止 CDN 作为生产架构（统一 npm + Vite）

---

## 1. 环境准备（Windows 机器，首次一次性）

```bash
# 在仓库根 D:\GitRepos\Comic-books 下
cd viewer-needle
npm install
```

> ⚠️ 依赖说明：
> - `@needle-tools/engine` 为 Needle 官方包，**License: none（需商业授权，Needle Engine Pro 已内置）**。无 license 时本脚手架会自动降级为纯 three 运行（见 `runtime-setup.ts`），不影响漫画业务开发预览。
> - three 使用 Needle fork：`"three": "npm:@needle-tools/three@^0.169.19"`，保证与 engine 内部依赖版本一致，避免双实例冲突。
> - 若 license 缺失导致 `@needle-tools/engine` 安装失败，可临时把 `dependencies` 里的该行移除，纯 three 版本仍可构建运行。

> 📦 体积权衡（重要）：
> `src/runtime-setup.ts` 里 `import('@needle-tools/engine')` 会把 Needle 自带的 MaterialX / WASM（约 4MB）打包进产物，这是 Needle 引擎本身特性，**与第四阶段的"2.5MB GLB 资产"约束无关**（那是模型资产体积，不是 JS 包体积）。
> - 若当前阶段只需纯 three 跑通漫画业务，可把 `initNeedle()` 里那行 `await import('@needle-tools/engine')` 注释掉，产物立即回到约 320KB（three-core + index），漫画逻辑照常运行。
> - 需要真正启用 Needle 引擎能力（Rapier / XR / 高级组件）时再打开该行。

### 开发 / 构建 / 预览命令

```bash
npm run dev        # Vite dev server (日常开发预览), http://localhost:5173/Comic-books/
npm run build      # 生产构建 (离线归档/发布), 输出到 dist/
npm run preview    # 验证打包产物 (静态预览), http://localhost:8000/
npm run typecheck  # TypeScript 类型检查
```

---

## 2. 阶段一：Needle Runtime 基础验证（GLB 相机 + 动画）

### 验收目标（全部通过才进入阶段二）
- [ ] Needle Engine 可以启动（或降级纯 three 后仍正常启动）
- [ ] `scene.glb` 可以加载并显示
- [ ] GLB 内置 Camera 正确读取，参数与 Blender 导出一致（**不修改投影矩阵/aspect**）
- [ ] Camera Animation 正确识别
- [ ] Animation 每帧正确更新（`AnimationPlayer.update()` 驱动原生 AnimationMixer）

### 落地方式
把 ModernExporter 导出的 `scene.glb` 放到 `viewer-needle/assets/scene_optimized.glb`（或修改 `PageManager` 默认路径），然后 `npm run dev` 打开页面，观察状态栏显示 `ready: <page_id>`，镜头动画自动播放。

> 若无可用的 GLB，可先用任意含相机的测试 GLB 验证加载链路。

---

## 3. 阶段二：迁移现有 Viewer 业务逻辑（逐项，新旧并行）

将旧 `app.js` 的功能**逐项**迁移到 `src/comic-runtime/`，每迁移一项做一次新旧对比验证：

| 旧功能 | 迁移目标文件 | 迁移说明 |
|---|---|---|
| GLB Loader | `GlbLoader.ts` | 已迁移，提取 scene/cameras/animations |
| Camera 查找 / 切换 | `CameraController.ts` | 已迁移，按名字查找，不改相机数据 |
| Animation playback / timing | `AnimationPlayer.ts` | 已迁移，原生 AnimationMixer |
| 页面 / 画格切换 | `PageManager.ts` | 已迁移，读 manifest/page.json 驱动翻页 |
| UI / 字幕 / 音频 | `UiController.ts` | 已迁移，含运行时切换按钮 |
| Raycast / 物体选中 | `comic-runtime/RaycastController.ts`（待建） | 用 three Raycaster |
| 移动端控制 | `UiController.ts` + InputController | 触摸/缩放 |

> 迁移时保留 `?runtime=legacy` 旧入口随时回退；禁止一次性整体重写。

### 验收目标
- [ ] 漫画画格 / 翻页逻辑与旧版行为一致
- [ ] UI、字幕、音频时序正常
- [ ] 移动端触摸、缩放、交互正常
- [ ] 相机切换、动画时序与旧 Viewer 输出对齐

---

## 4. 阶段三：Rapier 物理（Needle 内置，隔离加载）

- 已提供接口占位：`src/extensions/rapier-stub.ts` + `rapier-impl.ts`
- 触发条件：`page.json` 标记 `enable_physics: true` 才动态 `import()` 加载，默认 `false` 完全不加载 WASM
- 物理独立 update 循环，**绝不干预 GLB AnimationMixer 相机动画**
- 现阶段只实现基础外壳（刚体/碰撞体/射线/角色控制器），后续接入 Needle 内置 Rapier 绑定替换 `rapier-impl.ts`

### 验收目标
- [ ] `enable_physics:false` 时 Rapier WASM 完全不加载，主包体积不膨胀
- [ ] `enable_physics:true` 时刚体/碰撞/射线可工作
- [ ] 相机动画、时序系统不受物理模块干扰

---

## 5. 阶段四：资产优化 Pipeline（解决单镜头体积过大）

> 原始 Blender 场景保持不变，优化只作用于 Web 发布资产。复用现有 `scripts/build_project.ps1` + `validate_assets.py` 扩展。

优化项（调查并落地）：Mesh Decimation / Meshopt / Draco / KTX2 / WebP / Texture resize / LOD / Progressive loading。

构建时输出**优化报告**（每页一份 JSON）：
- GLB size、triangle count、texture size/count、预估 loading time、GPU memory、visual quality 标记

### 验收目标
- [ ] 流水线可批量执行优化
- [ ] 生成完整优化报告
- [ ] 运行时可在 high(dist/KTX2) / low(原始Draco) 两套资产间自动降级
- [ ] 2.5MB 硬上限校验生效，超标构建告警

---

## 6. 阶段五：Multiplayer（仅定义接口，不实现）

- 已提供接口占位：`src/extensions/multiplayer-stub.ts` + `multiplayer-impl.ts`
- 接口：`SyncedRoom` / `SyncedTransform` / `SyncedCamera` / `SyncField` / `VoIP`
- 触发：`page.json` 标记 `enable_multiplayer: true`；单机模式完全不加载多人代码

### 验收目标
- [ ] 单机模式不加载任何多人代码
- [ ] 接口类型完备，未来可接入 Needle 多人组件而无需大规模重构业务代码

---

## 7. 阶段六：XR（仅架构预留，不实现）

- 已提供接口占位：`src/extensions/xr-stub.ts` + `xr-impl.ts`
- 接口：`requestSession('AR'|'VR')` / `endSession()`
- 触发：`page.json` 标记 `enable_xr: true`
- **不修改现有 Desktop 相机系统**

### 验收目标
- [ ] 桌面模式完全不加载 XR 代码
- [ ] Runtime 扩展点就绪，不侵入现有相机与叙事系统

---

## 8. 最终目录结构

```
viewer-needle/
├─ package.json
├─ vite.config.js
├─ tsconfig.json
├─ index.html
├─ assets/                    # 测试/生产 GLB（放 ModernExporter 产物）
├─ src/
│   ├─ main.ts                # 入口
│   ├─ runtime-setup.ts       # Needle/three 运行时底座（降级策略）
│   ├─ comic-runtime/         # 漫画业务（迁移自旧 app.js）
│   │   ├─ GlbLoader.ts
│   │   ├─ CameraController.ts
│   │   ├─ AnimationPlayer.ts
│   │   ├─ PageManager.ts
│   │   └─ UiController.ts
│   └─ extensions/            # 隔离扩展占位
│       ├─ rapier-stub.ts / rapier-impl.ts
│       ├─ xr-stub.ts / xr-impl.ts
│       └─ multiplayer-stub.ts / multiplayer-impl.ts
└─ INSTRUCTIONS.md
```

---

## 9. 最终目标

```
Blender 5.2 → 3DComicToolkit → ModernExporter → scene.glb
      → Needle Engine(+Three.js) → Comic Runtime → Web / Mobile / XR(预留)
```

优先保证现有功能不回归，再逐步用 Needle Engine 能力替换旧 Runtime。
