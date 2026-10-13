# VoiceBook Blender 预览 WYSIWYG 对齐 8765 实施计划

## 目标（本阶段唯一命题）
让 Blender 排版预览在视觉上等于 8765 对同一份 V1 JSON 的渲染：
`Blender 预览 = V1 JSON = 8765 网页`。
本阶段只做 **Blender 预览绘制对齐**；8765 是否 1:1 消费 JSON 留到下一阶段，本阶段不碰任何 8765 文件。

## Repository Research（已核实的真值）

### 8765 渲染端真值（voicebook_v1_renderer.js + voice.css，只读核实）
- 画布 `#vb-v1-canvas`：白底 `#FFFFFF`，1920×1080 等比缩放；层级 bg < scene < paint < text < widget。
- **Skin 实色底画在每个文本框自身**（`.vb-textbox`），不是整块 textArea：
  - Sit：bg `#F3EDDF`，border 1px `#E5DFD0`。
  - Dark（body.theme-dark）：bg `#2C7A66`，border 1px `#246453`。
- 文本框：绝对定位 `box.x/y/w/h`，`fontSize`、`lineHeight`（px），`white-space:pre-wrap`、`word-break:break-word`、`overflow:hidden`、border-box，正文/标题文本取 `textBoxes.*.text`。渲染器文字色默认 `#1E1E24`（Dark 文字色 `#F3EDDF` 属设计规格，8765 文字色在后续阶段处理）。
- 正文视觉上是**单个 div 连续文本流**：Blender 导出时 `body.text = "\n".join(blocks[].text)`；8765 不渲染分段底色、分隔线、B01 编号/类型标签。
- **音频按钮**：红底圆形 `borderRadius:50%`、bg `#C73E3A`、白 `♪`（24px），定位取 `audioButton.x/y/w/h`；`align` 字段渲染器不使用。
- **Divider 不画线**：分割只是 skin 文本框与 sceneArea 图像之间的隐含边界。

### Blender 现状（vb_engine.py）
- `_draw_text_area`：上一轮改成整块 textArea 铺 skin 底（与 8765 不符，本轮按确认意见撤销）。
- `_draw_single_text_box`：标题/正文画常驻灰/青矩形框；文字色固定近白；正文 `_draw_body_blocks` 画分段半透明底、灰分隔线、`B01 Narration` 标签；正文每段高度 `(行数+1)*行高`，与 CSS 单流不一致。
- `_draw_divider`：常驻红线 + 两端方块手柄。
- `_draw_audio_button`：绿色方块 + ♪（48/16 魔法数）；`vb_json.export_data` 另有同样 48/16；`handle_mouse_press` 命中处第三份 48/16（三处重复，易漂移）。
- 交互命中全部在 vb_engine.py 内部；`vb_modal.py` 只转发事件，不引用 selection/命中内部。保留 `_hit_body_block(props,mx,my,sx0,sy0,sx1,sy1)->int` 与 selection 字符串（TITLE/BODY/DIVIDER/AUDIO）即可不碰 modal。
- `vb_draw.py` 已有 `draw_circle(color,cx,cy,r,segments)`、`wrap_text`、`draw_text`，**无需改 vb_draw.py**。
- `vb_json.py` 已导出常量 `AUDIO_BUTTON_SIZE=48 / AUDIO_BUTTON_MARGIN=16 / AUDIO_ALIGN`，且不 import vb_engine，无循环导入风险，可在引擎侧只读复用。

## 已确认决策
1. Skin 底色：只画在**标题框 + 正文框自身**（bg+1px border），取代整块 textArea 填充；文字色用 skin 的 text（Sit `#1E1E24` / Dark `#F3EDDF`）。
2. 编辑辅助（青框/控制点/divider 线）：**仅悬停或选中/拖拽时显示**；静止画面等同成品。
3. 正文：blocks 以 `\n` 合并成**单流**，自动换行+尊重硬换行+按 lineHeight 顶对齐堆叠+超框高裁剪；不画分段底色/分隔线/编号；点击某行选中其所属 block，仅当前选中段轻微高亮。
4. 音频：红色圆形 `#C73E3A` 白♪，位置/尺寸与导出 JSON **同源**（复用 vb_json 常量），本期不支持拖动。
5. **修改范围：仅 `vb_engine.py`**（通过 import 复用其它模块，不修改它们）。

## Files and Modules
- `C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\extensions\user_default\voicebook_layout\vb_engine.py`：本阶段唯一修改文件。
- 只读复用（不改）：`vb_draw.draw_circle/wrap_text/draw_text/draw_rect/draw_rect_outline`；`vb_json.AUDIO_BUTTON_SIZE/AUDIO_BUTTON_MARGIN`；`vb_coords.compute_layout_areas/logical_to_screen`；`SKIN_COLORS`（本文件内已有）。

## Implementation Steps（仅 vb_engine.py）
1. **顶部只读复用常量**：`from .vb_json import AUDIO_BUTTON_SIZE, AUDIO_BUTTON_MARGIN`（验证无循环导入）。
2. **新增纯函数文本流布局**（模块级，便于无 GPU 单测）：输入各 block 文本列表、内容宽/字号/行高/框高，输出“可见视觉行”列表 `(block_index, text)`，规则：按 `\n` 拆硬换行段 → `vb_draw.wrap_text` 宽度折行 → 从框顶按行高堆叠 → 超出框高的行裁剪（overflow hidden）；标题用同一函数（单文本、block_index=-1）。
3. **改 `_draw` 调用顺序**：去掉 `_draw_text_area` 整块铺色调用；保持 base → divider → text_boxes → audio → hud。
4. **删除 `_draw_text_area` 的整块 skin 填充**（方法移除或不再调用）。
5. **改 `_draw_single_text_box`（TITLE/BODY 共用）**：
   - 先画 skin bg（不透明）+ 1px skin border（产品外观，常驻）。
   - 用步骤 2 的单流结果、skin 文字色、顶对齐基线（约 `0.8*fontSize` 近似 CSS ascent）绘制；内容相对边框留 2px 安全内距；超框高不画。
   - BODY：对 `active_block_index` 所属可见行先铺一层轻高亮（skin 文字色 alpha≈0.15），再绘文字；无分段底/分隔线/标签。
   - 选中态（`self.selection==box_id`）才叠加青色外框与既有 8 向控制点；未选中不画灰框。
6. **改 `_draw_divider`**：仅当 `selection=='DIVIDER'` 或鼠标悬停容差内才画红线+手柄；否则直接返回（命中带仍在 press 逻辑里，悬停即显现）。
7. **改 `_draw_audio_button`**：用同源常量算文字区右下角圆心，`draw_circle` 画红圆 `(0.780,0.243,0.227,1.0)`，白色居中 ♪；选中态仅增亮/描边反馈，不再画方块。
8. **重写 `_draw_body_blocks`/`_body_block_layout` 为单流版本**，并让 `_hit_body_block` 用与绘制完全一致的行映射：由点击 y 反推行号→block_index，x 需在框内；签名与返回语义不变（供 `handle_mouse_press` L621 使用，不改 modal）。
9. **`handle_mouse_press` 音频命中**：3 处 48/16 魔法数替换为 import 的同源常量（命中仍用圆外接方形判定，行为等价），保证预览位置=命中位置=JSON。
10. 清理仅被旧分段渲染使用、且确认无其它文件引用的本文件常量（如 `BLOCK_COLOR_BG/SEP/TEXT`、`BLOCK_TYPE_LABELS`）；拿不准的保留不动。

## Dependencies and Considerations
- 坐标/换算/1920×1080/`compute_layout_areas`/`normalize_divider`/拖拽与 resize 逻辑全部不改；只改“怎么画”和“点哪行选哪段”。
- 音频几何单一真值来自 vb_json：预览=导出，杜绝三处魔法数漂移。
- 字体限制：blf 内置字体与浏览器字体族不同，折行点可能有 1 字级差异；位置/尺寸/字号/行高/换行规则严格对齐，字体族不在 V1 JSON 内，属可接受限制（在报告中说明）。
- 底图/scene 图层投放方式（bgLayer 全幅 vs sceneLayer 按 sceneArea）涉及截图链路，本阶段**不动**（遵守“不改截图逻辑”）；其像素级对齐并入下一阶段“8765 1:1 消费 JSON”。
- 8765 Dark 正文文字色目前渲染器默认深色的问题属 8765 侧，后续阶段处理；Blender 本阶段按设计规格用 `#F3EDDF`。

## Validation
1. `ast.parse` 静态语法检查 vb_engine.py。
2. Blender 5.2 后台：加载扩展包并 register/unregister/register 成功；确认 `vb_engine → vb_json` 导入无循环依赖。
3. 后台对步骤 2 纯函数做单测：多 block 以 `\n` 合并、块内硬换行、宽度折行、超框高裁剪的可见行数与归属 block 正确。
4. 断言音频按钮引擎几何与 `vb_json.export_data()['audioButton']` 数值一致（同源常量）。
5. 手工 GUI 自检项（交付说明，供你打开 Blender 确认）：
   - Sit/Dark 切换：仅标题/正文框变色（bg/border/文字色），无整块大铺色；
   - 静止时无青框/红线/分段标签；悬停 divider 出现红线可拖；点文本框出现青框+控制点；
   - 正文为连续文本流，点某行选中对应 block 且右侧声音面板同步，仅选中段轻高亮；
   - 音频为红圆白♪且位置=导出 JSON；
   - 导出 JSON 的 textBoxes/fontSize/lineHeight、dividerPosition、audioButton 不回归。

## Risks
- 撤销上一轮整块 textArea 铺色 → 已按确认意见执行，避免与 8765 长期不一致。
- 单流重排后点选映射若与绘制行高公式不一致会选错段 → 绘制与命中共用同一纯函数结果，消除双份计算。
- 仅改 vb_engine.py 的约束下需要复用 vb_json 常量 → 已确认无循环导入；后台加载验证兜底。
- divider 静止隐藏可能让人误以为不可拖 → 悬停即显现，且 -5/-1/+1/+5 步进与面板输入仍在。

## 明确不改动
vb_coords.py、vb_props.py、vb_modal.py、vb_draw.py、vb_json.py、vb_panels.py、任何 8765 前端文件、绘画层、截图逻辑、页面创建/切换、坐标体系、1920×1080、Undo/ESC/Modal、JSON 结构。
