# AI_WORK_STATE

> 本文件供不同 AI 接手时读取。
> 规则：
> - 只记录有证据支撑的内容，无法确认的一律标记为「待核实」。
> - 不得把「代码存在」等同于「功能已通过测试」。
> - 没有真实测试证据，不得标记为「已验证通过」。
> - 每次只推进一个明确任务。
> - 更新本文件时，只记录实际操作和测试证据。
>
> 最后更新：2026-10-16

---

## 1. 项目目标

（待核实）根据仓库结构和现有文件推断：将 Blender 制作的 3D 场景与气泡对白、配音结合，导出为可在浏览器中阅读的动态漫画。
- 网页部署在 GitHub Pages，分支 gh-pages。
- 线上示例链接：https://jypding.github.io/Comic-books/books/新建3D%20漫1/book/index.html（由用户在本会话提供，未在本会话中以浏览器验证）。

---

## 2. 主要目录

| 用途 | 路径 |
| --- | --- |
| 仓库根 | D:\GitRepos\Comic-books |
| 源侧（Blender 工程） | projects\新建3D 漫1\s01e01\ |
| 源侧音频 | projects\新建3D 漫1\s01e01\audio\ |
| 线上侧（网页） | books\新建3D 漫1\book\ |
| 线上侧音频 | books\新建3D 漫1\book\audio\ |
| 部署脚本 | Deploy-ComicToViewer.ps1、jyp_publish_3d.bat、publish.bat、auto_publish.bat |

证据来源：2026-10-16 由 git status 与 Get-ChildItem 输出确认。

---

## 3. 功能状态

### 3.1 已验证通过（仅文件系统与 Git 层面）

- Git 工作树干净，分支 gh-pages 与 origin/gh-pages 同步（2026-10-16，本会话 git status）。
- books\新建3D 漫1\book\audio\bubble_564000.wav 存在于本地，大小 249,644 字节（2026-10-16，Get-ChildItem）。
- books\新建3D 漫1\book 下存在 page0000 至 page0003 四个页面目录，各有 page.json、scene.glb、thumb.png。

### 3.2 已实现但未验证

- 网页端气泡文字显示：用户口头描述「浏览器里…只有对话文字」，未在本会话以浏览器或截图重新验证。
- 网页端音频播放：wav 文件存在于仓库，但用户报告「点没有声音」（2026-10-16，用户口头描述）。前端是否发起 wav 请求、返回码为何，均未核实。

### 3.3 待修复

- 用户报告：浏览器端「没有气泡对话框、只有对话文字和播放按钮、点没有声音」（2026-10-16，用户口头描述）。需区分是气泡条（bubble-strip）显示形态，还是 3D 场景内气泡缺失。
- 音频无声：需确认浏览器 Network 面板中 audio/bubble_564000.wav 请求状态。

### 3.4 待核实

- books\新建3D 漫1\book\bubble_data.json 当前内容（645 字节）未在本会话读取，无法确认气泡条目、scene 字段、audio 字段。
- books\新建3D 漫1\book\bubble_scene_map.json 当前内容（139 字节）未在本会话读取。
- 线上 GitHub Pages 是否已同步最新 commit 23ce8e2，未在本会话以浏览器或 curl 验证。
- 源侧 projects\新建3D 漫1\s01e01\bubble_data.json 是否与线上一致，未在本会话对比。
- jyp_publish_3d.bat 最近一次运行时间：用户回答「记不清」。
- 是否存在历史测试日志或笔记文件：用户回答「没有」。

---

## 4. 当前正在处理的问题

- 浏览器端音频播放失败（用户报告）。

---

## 5. 最近一次有证据的测试结果

| 时间 | 命令 | 结果 |
| --- | --- | --- |
| 2026-10-16 | git status | 工作树干净，gh-pages 与 origin/gh-pages 同步 |
| 2026-10-16 | git log --oneline -5 | 最新 commit 23ce8e2 修正 JSON 中 audio 字段为 audio/ 子目录 |
| 2026-10-16 | Get-ChildItem book | audio\bubble_564000.wav 存在，249,644 字节 |

无浏览器端测试证据。无音频播放成功证据。

---

## 6. 下一步唯一建议任务

在浏览器中打开线上页面，按 F12 打开 Network 面板，点击第 2 页气泡，记录 audio/bubble_564000.wav 请求的状态码与返回内容。
- 若为 200：文件可加载，问题在前端播放逻辑或浏览器自动播放策略。
- 若为 404：线上路径不一致。
- 若无 wav 请求：前端未触发播放。

在获得该状态码之前，不进行任何代码修改。

---

## 7. 已知风险和不能随意改动的内容

- bubble_data.json 必须以 UTF-8 无 BOM 写入；带 BOM 会导致前端 JSON.parse 失败（历史问题，已在 commit bcc09a5 修复）。
- bubble_data.json 中 audio 字段必须为相对路径（如 audio/bubble_564000.wav），不可写绝对路径（历史问题，已在 commit a647ebb 修复）。
- 线上部署在 gh-pages 分支，不是 main；推送必须指定 origin gh-pages。
- 运行 jyp_publish_3d.bat 或 Deploy-ComicToViewer.ps1 会整目录重建 books\新建3D 漫1\book；若源侧 s01e01 缺少对应文件，线上会被还原为旧状态。
- projects\projects\ 曾为误产出的脏目录，已于 commit 88749e8 删除；若再次出现，应视为部署脚本路径 bug 复现。
- 前端气泡匹配逻辑位于 books\新建3D 漫1\book\assets\js\app.js 约 741-771 行，音频加载逻辑约 792-797 行（位置为历史会话中的定位，未在本会话重新核对）。

---

## 8. 未获取到的信息（下次接手时优先补齐）

- bubble_data.json 与 bubble_scene_map.json 的实际内容。
- 浏览器 F12 Network 中 audio/bubble_564000.wav 的请求结果。
- 浏览器 F12 Console 是否有报错。
- Deploy-ComicToViewer.ps1 第 37 行附近的路径拼接实现。
---

## 14. 2026-10-16 用户澄清（修正第 13 节）

用户明确表示：
- 第一页 page0000 显示的英文气泡（"So?" / "Did you…"）是历史残留的测试内容，不是预期内容。
- 第二页 page0001 的中文气泡「建军85周年…」+ 声音是正确且成功的。

### 14.1 由此修正的理解

- 第一页的英文字不是「导出失败」，而是 Blender 源场景里 p.0000 场景本就有残留的英文 Wordballoon。
- 第二页已跑通完整链路：Blender 气泡对象 → GLB → 前端渲染 → 音频播放。

### 14.2 Blender 截图证据（用户于 2026-10-16 提供）

- 视图内 page0000 显示 "So?" / "Did you…"。
- 场景集合 `Export.0000` → `Letters.0000` 下含：
  Letters_dutch.0000 / Letters_english.0000 / Letters_french.0000 / Letters_german.0000 /
  Letters_japanese.0000 / Letters_korean.0000 / Letters_spanish.0000 /
  Wordballoon / Wordballoon.001 / Border。
- 顶部信息栏显示 "Export.0000 | Wordballoon"。

### 14.3 待用户确认

- 第一页那段英文残留，是「应当删除」还是「本应替换为中文内容」？
- 是否要清空 p.0000 场景里的残留 Wordballoon，再重新导出？

### 14.4 下一步唯一任务

等用户确认第 14.3 项后，再决定是否需要只读检查 p.0000 场景中残留 Wordballoon 的具体内容与关联文字对象。
在用户确认前，不修改 Blender 场景、不导出、不发布。

---

## 15. 2026-10-16 用户决定：第一页残留按碎片处理

用户明确表示：第一页 p.0000 的英文残留（"So?" / "Did you…"）不再细究，当作碎片忽略。

### 15.1 当前确认状态

- 第二页 page0001：中文气泡「建军85周年…」+ 声音，链路跑通，成功。
- 第一页 page0000：英文残留，按碎片处理，不修复、不清除、不追踪。
- 前端音频无声问题：已由第二页成功播放验证排除。

### 15.2 下一步

等待用户指定新任务。

---

## 17. 2026-10-16 关键证据：GLB 过期

时间戳对比：
- books\新建3D 漫1\book\pages\page0001\scene.glb : 2026/10/14 21:29:31 (6996564 字节)
- projects\新建3D 漫1\blender\新建3D 漫1.blend   : 2026/10/15 21:21:41 (12659188 字节)

GLB 比 .blend 早一天。Wordballoon.002（带 bubble_id=bubble_564000）是 .blend 后来添加的，从未被导出。

结论：GLB 过期，非代码过滤 bug。
- 当前第二页中文气泡来源是 bubble_data.json 的 HTML bubble-strip，不是 GLB 内 3D 对象。
- 第 16 节所有候选原因作废；不需要修改导出参数。

### 17.1 下一步唯一任务（待确认风险后执行）

在执行「重新导出」前，必须先只读确认：
1. export_reading_data 是否覆盖 bubble_data.json？
2. 覆盖时是否会丢失现有手工修复（audio/ 子目录路径、BOM 移除、两条 bubble 记录）？
3. 部署脚本 jyp_publish_3d.bat 是否会在导出后整目录重建 book/？

在确认前，不重新导出，不发布。

---

## 18. 2026-10-16 只读核实：export_reading_data 的写入范围

### 18.1 该 operator 实际写出的文件（L449-524）

- {output_root}/pages/{page_id}.json（扁平，如 p0000.json）
- {output_root}/manifest.json
- {output_root}/blender/book/manifest.json
- {output_root}/voice_cues.json
- {output_root}/styles/{voice-book.css, voice-theme.json}
- 可能写 reader_sample_dir/manifest.json

### 18.2 重要发现

1. 该 operator 不写 bubble_data.json，也不写 bubble_scene_map.json。
2. output_root = repo_root/books/{project_id}，GLB 写到 {output_root}/scene_p{id}.glb。
3. 与线上实际结构 books/{project_id}/book/pages/{pageId}/scene.glb 完全不同。

### 18.3 推论

- export_reading_data 不会覆盖 bubble_data.json。
- 当前线上 book/ 结构不是这个 operator 产生的；bubble_data.json 与 GLB 的来源另有其处。
- 重新跑 export_reading_data 不能解决 page0001 GLB 过期问题。

### 18.4 下一步唯一任务

定位线上 books/新建3D 漫1/book/ 结构的实际产生者：
- 只读检查 jyp_publish_3d.bat / Deploy-ComicToViewer.ps1 / publish.bat / auto_publish.bat。
- 找到将 GLB 从 {project_id}/scene_p{id}.glb 变换到 book/pages/{pageId}/scene.glb 的代码路径。

在拿到该证据前，不重新导出，不发布。

---

## 21. 2026-10-16 只读检查：四场景 Wordballoon 对象对照

### 21.1 对照表

| 场景 | Wordballoon | FONT 内容 | bubble_id | GLB 是否含 Wordballoon |
| --- | --- | --- | --- | --- |
| p.0000 | Wordballoon + .001 | So? / you Coming? / Did You Hear that? | 无 | 有 |
| p.0001 | Wordballoon.002 | Text.002 / Text.003 (中文) | bubble_564000 | 无 |
| p.0002 | 未发现 | 无 FONT | - | 无 |
| p.0003 | 未发现 | 无 FONT | - | 无 |

### 21.2 p.0001 的 Wordballoon.002 完整属性

- type = MESH
- collection = Letters.0001
- world = (0.0000, -10.0000, 1.5200)
- parent chain = Letters_english.0001 -> Camera.0001
- hide_viewport = False, hide_render = False
- bubble_id = 'bubble_564000'
- is_bubble = True
- bubble_speaker / bubble_voice / bubble_audio / bubble_duration 均在

### 21.3 最小修改环节

要让第一个 3D 对话气泡显示：
1. 重新导出 p.0001 场景的 GLB（仅此一个场景）
2. 前端 app.js 新增 Sprite/CanvasTexture 渲染代码

p.0002/p.0003 无气泡，不需重新导出。
p.0000 按用户决定当碎片忽略。

### 21.4 关键区分

当前第二页用户看到的「中文气泡 + 声音」是 HTML bubble-strip 的成果，
不是 3D 场景内气泡。3D 气泡功能从未实现。

---

## 22. 2026-10-16 关键环境信息 + 第三阶段验证结果

### 22.1 端口分配（必须记住）

- 3D 书本地服务：**端口 8000**
- 语音书本地服务：**端口 8765**
- 两者不可混用。

### 22.2 第三阶段浏览器验证结果

环境：临时 GLB 放入 %TEMP%\s3dc_p0001_browser，
Python HTTP 服务器端口 8000，
浏览器打开 http://localhost:8000/ 翻到 Page 2。

Console 输出（PASS）：
- [MODERN_CAMERA] Found GLB Camera: Camera.0001
- targetIsCamera=true, targetIsCurrentCamera=true
- [MIXER_AUDIT] clip=Camera.0001动作, actionCount=1
- [CAMERA_ANIM] hasDirectCameraTracks=true, tracks=1
- [VERTICAL GLB] Loaded: page0001

视觉结果（FAIL）：
- 气泡框存在（两个圆角矩形轮廓可见）
- 气泡框填充呈深灰/黑色，不是白色
- 气泡内的中文文字完全不可见

### 22.3 根因

本次临时 GLB 通过直接调用 bpy.ops.export_scene.gltf 导出，
跳过了 ModernExporter.export_glb 内部的 _swap_text_materials()，
导致 FONT 材质没有替换为 __s3dc_text_tmp_* 纯黑 unlit 替身。

参照 page0000 旧 GLB：Text/Text.001/Lettering 均使用 __s3dc_text_tmp_*
黑色 unlit 材质，因此英文 "So?" 可见。

当前临时 GLB：
- Text.002/Text.003 → material L_WordballoonText.0001（无 unlit）
- Wordballoon.002 → material L_Wordballoon.0001 / OutlineDark / OutlineLight / TEMPLATE
- 场景背景 0x05070a（近黑）
- PBR 缺 pbrMetallicRoughness → Three.js 默认金属度 1.0/粗糙度 1.0 → 黑色
- 黑字贴黑气泡 → 不可见

### 22.4 结论

临时 GLB 浏览器验证：FAIL。
- 几何、extras、相机、动画全部正确
- 渲染不可读 → 必须走 ModernExporter.export_glb 路径重导

### 22.5 下一步唯一任务

研究 ModernExporter.export_glb() 的调用方式：
- 文件：C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\exporter\modern_pipeline\modern_pipeline\blender_exporter.py
- 确认 _swap_text_materials() 的行为
- 用 object.__new__ 绕过 __init__ 构造实例
- 在后台 Blender 中调用 export_glb(scene, output_path)，输出到 Temp 先验证
- 不覆盖 s01e01/pages/page0001/scene.glb

在重导并再次浏览器验证通过前，不替换任何正式文件。

---

## 22. 2026-10-16 关键环境信息 + 第三阶段验证结果

### 22.1 端口分配（必须记住）

- 3D 书本地服务：**端口 8000**
- 语音书本地服务：**端口 8765**
- 两者不可混用。

### 22.2 第三阶段浏览器验证结果

环境：临时 GLB 放入 %TEMP%\s3dc_p0001_browser，
Python HTTP 服务器端口 8000，
浏览器打开 http://localhost:8000/ 翻到 Page 2。

Console 输出（PASS）：
- [MODERN_CAMERA] Found GLB Camera: Camera.0001
- targetIsCamera=true, targetIsCurrentCamera=true
- [MIXER_AUDIT] clip=Camera.0001动作, actionCount=1
- [CAMERA_ANIM] hasDirectCameraTracks=true, tracks=1
- [VERTICAL GLB] Loaded: page0001

视觉结果（FAIL）：
- 气泡框存在（两个圆角矩形轮廓可见）
- 气泡框填充呈深灰/黑色，不是白色
- 气泡内的中文文字完全不可见

### 22.3 根因

本次临时 GLB 通过直接调用 bpy.ops.export_scene.gltf 导出，
跳过了 ModernExporter.export_glb 内部的 _swap_text_materials()，
导致 FONT 材质没有替换为 __s3dc_text_tmp_* 纯黑 unlit 替身。

参照 page0000 旧 GLB：Text/Text.001/Lettering 均使用 __s3dc_text_tmp_*
黑色 unlit 材质，因此英文 "So?" 可见。

当前临时 GLB：
- Text.002/Text.003 → material L_WordballoonText.0001（无 unlit）
- Wordballoon.002 → material L_Wordballoon.0001 / OutlineDark / OutlineLight / TEMPLATE
- 场景背景 0x05070a（近黑）
- PBR 缺 pbrMetallicRoughness → Three.js 默认金属度 1.0/粗糙度 1.0 → 黑色
- 黑字贴黑气泡 → 不可见

### 22.4 结论

临时 GLB 浏览器验证：FAIL。
- 几何、extras、相机、动画全部正确
- 渲染不可读 → 必须走 ModernExporter.export_glb 路径重导

### 22.5 下一步唯一任务

研究 ModernExporter.export_glb() 的调用方式：
- 文件：C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\exporter\modern_pipeline\modern_pipeline\blender_exporter.py
- 确认 _swap_text_materials() 的行为
- 用 object.__new__ 绕过 __init__ 构造实例
- 在后台 Blender 中调用 export_glb(scene, output_path)，输出到 Temp 先验证
- 不覆盖 s01e01/pages/page0001/scene.glb

在重导并再次浏览器验证通过前，不替换任何正式文件。

---

## 23. 2026-10-16 第五阶段结果：材质后处理方案验证通过

### 23.1 后处理输入输出

- 输入：%TEMP%\s3dc_p0001_verify\scene.glb（7,181,488 字节）
- 输出：%TEMP%\s3dc_p0001_verify_material\scene.glb（7,181,872 字节，+384）
- BIN chunk 字节级 0 差异
- 后处理脚本：%TEMP%\postprocess_glb_materials.py

### 23.2 后处理内容

5 个材质补 pbrMetallicRoughness（metallicFactor=0, roughnessFactor=0.9）：
- L_Wordballoon.0001           baseColor=[1.0,1.0,1.0,1.0]
- L_WordballoonText.0001       baseColor=[0.0,0.0,0.0,1.0]
- L_WordballoonOutlineDark.0001 baseColor=[0.0,0.0,0.0,1.0]
- L_WordballoonOutlineLight.0001 baseColor=[0.71,0.71,0.71,1.0]
- L_Wordballoon.TEMPLATE       baseColor=[1.0,1.0,1.0,1.0]

### 23.3 静态验证（PASS）

- BIN chunk 字节级 0 差异
- extras 保留：Wordballoon.002 / Text.002 / Text.003 均有 bubble_id=bubble_564000, is_bubble=True
- 相机节点名 Camera.0001 保留
- 结构对比：只有 5 材质 +pbrMetallicRoughness，其他不变

### 23.4 浏览器验证（PASS）

- URL：http://localhost:8000/，Page 2/4
- 白底黑字中文「建军85周年暨第」+「十二届全军美术作品」清晰可读
- Console 无红色报错（favicon 404 与 OrbitControls deprecation 无害）
- 相机 Camera.0001 正常绑定
- 截图：用户提供

### 23.5 剩余问题（用户反馈）

1. 气泡没有边线：Blender 里的黑色描边（OutlineDark）在浏览器中看不到。
   可能原因：OutlineDark 外扩副本被填充层覆盖，或深度测试顺序问题。
2. 气泡"死的"：Blender 里设置了 "Slide Down" 动画策略，但网页上气泡静态直接出现，没有出场动画。

这两项均不属于本轮后处理范围，需另立任务。

### 23.6 下一步

等待用户指定：优先解决边线显示，还是气泡出场动画，还是先应用当前修复到正式 GLB。
