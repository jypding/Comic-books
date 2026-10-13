# VoiceBook 可视化排版模块 — 实施计划

## 上下文

基于现有 `add-on-image-editor-tools-v0.3.9` Blender 插件（Blender 4.2+，使用 `blender_manifest.toml` + `bl_info` 双格式注册），在其**不修改任何源码**的前提下，独立开发 VoiceBook 可视化排版功能模块。模块需注册到 Blender 图像编辑器（IMAGE_EDITOR）空间，与原插件功能共存，完全复用原生画布的缩放、平移、抓手等交互能力。

## 核心约束

1. **零侵入**：不修改 `add-on-image-editor-tools-v0.3.9` 目录下任何文件
2. **独立注册**：VoiceBook 为自带 `bl_info`/`blender_manifest.toml` 的独立插件
3. **共存不冲突**：`bl_idname` 前缀 `voicebook.`，`Scene` 属性名 `voicebook_layout`，面板分类 `VoiceBook排版`
4. **GPU 安全**：POST_PIXEL 绘制回调内**禁止离屏渲染**（`GPUOffScreen`），只允许直接画屏 + `blf`
5. **坐标冻结**：画布基准永久 1920×1080，所有坐标整数，JSON 格式严格对齐 V1 规范

## 模块架构

```
Texpile 可视化 TikZ 编辑器/
├── add-on-image-editor-tools-v0.3.9/      # 原插件，绝不修改
└── voicebook_layout/                      # 独立新插件
    ├── blender_manifest.toml
    ├── __init__.py                        # bl_info / register / unregister / Scene 指针挂载
    ├── vb_props.py                        # PropertyGroup 层级（版式/文字区/文本框/声音按钮）
    ├── vb_coords.py                       # 1920×1080 逻辑 ↔ 屏幕像素换算（纯函数，唯一入口）
    ├── vb_draw.py                         # GPU 绘制：底图/分割线/虚线框/文本框/声音按钮/blf 文字
    ├── vb_engine.py                       # VoiceBookEngine：draw_handler 持有者 + 命中测试 + 拖拽状态机
    ├── vb_modal.py                        # VOICEBOOK_OT_layout_start/stop：模态事件分发 + timer 重绘
    ├── vb_panels.py                       # 1 个根 Panel + 4 个 bl_parent_id 子面板
    └── vb_json.py                         # JSON 序列化/反序列化/校验 + 导入导出操作符
```

## 关键技术决策

### 1. 注册机制（与原插件共存）

- VoiceBook 独立 `register()`/`unregister()`，类名前缀 `VOICEBOOK_`，`bl_idname` 前缀 `voicebook.`
- `bpy.types.Scene.voicebook_layout = PointerProperty(type=VOICEBOOK_PG_Properties)` —— 属性名与对方的 `image_editor_tools` 无交集
- 反注册时先 `engine.cleanup()` 移除 draw_handler，再逆序 `unregister_class`
- 不读写对方的 `state.current_tool`，但启动前通过 `bpy.ops.image_editor_tools.tool_cancel()`（跨插件 ops 调用）让位，避免双模态冲突

### 2. 坐标系统（逻辑与屏幕分离）

- **逻辑坐标**：左上角原点，x 向右，y 向下，范围 [0,1920]×[0,1080]，整数
- **屏幕映射**：通过 `region.view2d.view_to_region(0.0, 0.0, clip=False)` + `space_data.zoom` 获取当前图像显示矩形，再按图像尺寸→1920×1080 的比例映射
- 映射公式：`sx = ox + lx / img_w * disp_w`，`sy = oy + (1 - ly / img_h) * disp_h`（y 翻转）
- 若当前图像不是 1920×1080：以 letterbox 方式居中内切，画布外区域画半透明遮罩提示

### 3. 绘制机制（GPU 安全）

- `SpaceImageEditor.draw_handler_add(draw_callback, (), 'WINDOW', 'POST_PIXEL')`
- 底图：`bpy.data.images.load()` → `gpu.texture.from_image()` → display shader 直接画满画布矩形（单 pass，零离屏）
- 分割线/虚线框/手柄：`gpu.shader.from_builtin('UNIFORM_COLOR')` + `batch_for_shader('LINES'/'TRI_FAN')`
- 文本：`blf` 屏幕直绘，字号按画布缩放系数 `s = disp_w / 1920` 动态调整，正文自动换行按 `blf.dimensions` 逐词断行
- 所有绘制包 `try/except`，错误只 print 不抛，避免炸栈导致 Blender 白屏

### 4. 交互机制（模态 + 事件谦让）

- `VOICEBOOK_OT_layout_start`：`bl_options={'REGISTER','UNDO'}`，`invoke` 中 `modal_handler_add`
- 左键 PRESS → `engine.handle_mouse_press()` 做命中测试，命中则 `RUNNING_MODAL`，未命中 → `PASS_THROUGH`（不拦截原生平移缩放）
- MOUSEMOVE → 仅 `_drag_mode != 'NONE'` 时处理，否则 `PASS_THROUGH`
- TIMER → 每 0.1s 对所有 `IMAGE_EDITOR` area `tag_redraw()`，保证面板改值即时刷新画布
- ESC → `_finish()`：移除 handler、timer、恢复 `ui_mode`、清空状态栏
- 拖拽对象：分割线（改 `divider_position`）、文本框移动（改 x/y）、文本框宽度（改 w）、文字区（改内边距）

### 5. N 面板（4 个子面板）

根面板 `VOICEBOOK_PT_Panel`：`bl_category="VoiceBook排版"`，`bl_space_type='IMAGE_EDITOR'`，`bl_region_type='UI'`

| 子面板 | bl_parent_id | bl_options | 内容 |
|--------|-------------|------------|------|
| 版式设置 | VOICEBOOK_PT_Panel | 默认展开 | `layout_type` 枚举（全屏/左文右图/上文下图）、`divider_position` 滑杆 ±1% ±5% 步进按钮、`base_image_path` + 加载按钮、新建 1920×1080 画布 |
| 文字区域 | VOICEBOOK_PT_Panel | DEFAULT_CLOSED | `padding_top/bottom/left/right` 数值行、文字区虚线框 visible 开关 |
| 文本框参数 | VOICEBOOK_PT_Panel | DEFAULT_CLOSED | `title_x/y/w/h/text`、`body_x/y/w/h/text`、行高、字号、对齐方式 |
| 导入导出 | VOICEBOOK_PT_Panel | DEFAULT_CLOSED | `page_id`、导出 JSON、导入 JSON、获取页面截图按钮 |

所有数值输入框带 `update` 回调触发 `tag_redraw()`，实现面板→画布单向驱动。

### 6. JSON 格式（V1 冻结）

导出时从 PropertyGroup 显式字段映射，剔除运行时字段（selection、viewport、is_editing）：

```json
{
  "pageId": "p.0000.w1h1",
  "canvas": {"width": 1920, "height": 1080},
  "layout": {
    "type": "left-right",
    "textArea": {"x": 73, "y": 14, "w": 710, "h": 1052},
    "sceneArea": {"x": 783, "y": 14, "w": 1137, "h": 1052},
    "dividerPosition": 760
  },
  "textBoxes": {
    "title": {"x": 0, "y": 40, "w": 710, "h": 80, "text": ""},
    "body": {"x": 0, "y": 140, "w": 710, "h": 800, "text": ""}
  },
  "audioButton": {
    "x": 646, "y": 992, "w": 48, "h": 48, "align": "text-bottom-right"
  }
}
```

导入时校验顶层字段、类型、范围，非法则拒绝且 state 不变。`textArea`/`sceneArea`/`audioButton` 由 `layout_type` + `divider_position` + `padding_*` 动态计算，不存储。

### 7. 底图加载 PNG

- `VOICEBOOK_OT_load_base_image`（`ImportHelper`，`filter_glob="*.png"`）
- `bpy.data.images.load(filepath, check_existing=True)` → 路径写入 `layout.base_image_path`
- 引擎绘制时惰性创建 `gpu.texture.from_image(img)`，以 `(img, img.name)` 为缓存键
- 图像被删或路径变更时丢弃重建
- 不 `bpy.data.images.remove()` 用户数据块，只放弃引用

## 潜在冲突与规避

| 冲突点 | 规避方案 |
|--------|---------|
| 双 draw_handler 同挂 POST_PIXEL | VoiceBook handler 生命周期绑定模态，退出即 remove；后注册者绘在上层，符合排版层在最上语义 |
| 双模态 operator 并存 | 启动前 `bpy.ops.image_editor_tools.tool_cancel()` 让对方退出；运行中检测到对方激活则自退 |
| Scene 属性名撞车 | `voicebook_layout` ≠ `image_editor_tools` |
| bl_idname 撞车 | 前缀 `voicebook.` 与对方 `image_editor_tools.`/`IMAGE_` 无交集 |
| N 面板 Tab 混乱 | 独立 `bl_category="VoiceBook排版"`，与对方 `Tool` 分 Tab |
| ui_mode / status_text 残留 | 各自保存/恢复 `_prev_ui_mode`；状态栏只清自己设置的 |
| 底图图像数据块混淆 | 底图用用户文件名，不建隐藏临时图；卸载不 remove 数据块 |

## 实施步骤

1. `vb_props.py` — PropertyGroup 设计（版式/内边距/文本框/声音按钮/选中状态）
2. `vb_coords.py` — 坐标换算纯函数（逻辑↔屏幕，命中测试）
3. `vb_draw.py` — GPU 绘制原语（虚线矩形、圆角、blf 换行文本）
4. `vb_engine.py` — 引擎：draw_handler 注册/移除、五层绘制、命中测试、拖拽状态机
5. `vb_modal.py` — 模态操作符：事件分发、timer、让位逻辑、清理
6. `vb_panels.py` — 根面板 + 4 个子面板，与画布双向同步
7. `vb_json.py` — 导入导出 + 校验
8. `__init__.py` + `blender_manifest.toml` — 注册入口
9. 回归验证：与原插件共存、不破坏原生功能、JSON 格式一致性

## 验证方式

- Blender 4.2+ 中安装 `voicebook_layout` 插件，确认 N 面板出现「VoiceBook排版」Tab
- 点击「开始排版」，确认画布上显示分割线、虚线文字区、文本框、声音按钮
- 拖拽分割线、文本框，确认数值实时同步到右侧面板
- 修改面板数值，确认画布实时刷新
- 导出 JSON，确认字段/层级/类型与 V1 规范一致
- 导入同格式 JSON，确认状态完全还原
- 同时启用原插件，确认双方面板互不干扰、模态操作可正常切换
