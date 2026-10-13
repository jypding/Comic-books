# VoiceBook Phase B：声音面板（Block → Holo Studio → MOSS/RVC → WAV → 回填）

## Context

Phase A 已完成 ApplioRuntime（RVC 引擎 spawn + 健康检查 + 模型扫描）。Phase B 要把"声音生成"端到端接通：Blender 插件负责编辑 Block 数据，Holo Studio（Electron）负责实际生成声音（MOSS-TTS 合成 → Applio RVC 换声 → WAV），两者通过 HTTP（端口 8088）解耦。Blender 永不 import Electron，Holo Studio 永不直接碰 Blender。

核心原则（用户明确）：
- Blender 只编辑数据，Holo Studio 只生成声音
- Blender 不调用 Python/Gradio/Electron，通信统一走新增的 `vb_holo_ipc.py`
- 异步生成用 `bpy.app.timers` 轮询，子线程只发 HTTP（子线程直接改 Blender 数据会崩）
- 本阶段不训练、不下载模型、不接 UVR、不改 MOSS Runtime / Blender VoiceBook / 8765

## 端到端数据流

```
Blender 面板点"生成"
  → voicebook.generate_audio (operator)
  → threading.Thread 只发 HTTP POST（不改 Blender 数据）
  → POST 127.0.0.1:8088/api/applio/infer {text,speaker,voiceModel,blockId,projectId}
  → Holo Studio main.js (Node)
      → MossRuntime → moss-tts-cli.exe 合成 temp.wav（沿用 tts:generate 已有逻辑）
      → ApplioRuntime.infer() → core.py infer 换声 → audio/B02.wav
  → 返回 {ok:true, data:{audio,start,end}}
  → Blender 主线程 bpy.app.timers 轮询拿到结果 → 回填 block.audio/start/end → tag_redraw
```

## 改动清单（7 个文件，2 个项目）

### A. Holo Studio（Electron 主进程）— 提供 8088 HTTP API

**1. `I:\llama.cpp\runtime\ApplioRuntime.js` — 实现 `infer()`（替换 NOT_IMPLEMENTED）**

Applio 的 Gradio API 不可靠（用户补充约束 3 提示），改用 subprocess CLI。`core.py` 是 click CLI（已确认）：
```
core.py infer --input-path <wav> --output-path <wav> --pth-path <pth> --index-path <index> [options]
```
`infer(inputWav, outputWav, modelFile, indexFile)`：
- 用 Applio 自带 python：`I:\llama.cpp\Applio\env\python.exe`
- spawn：`[python, core.py, 'infer', '--input-path', in, '--output-path', out, '--pth-path', RVC_DIR+modelFile, '--index-path', indexFile 或 '']`
- 关键默认参数（沿用 _infer_opts 默认，不全部列出，只传必要的）：`--f0-method rmvpe --export-format WAV`，其余走 CLI 默认值
- cwd = APPLIO_DIR，env 带 HF_ENDPOINT（双保险）
- 等 exit，output 存在 → `{ok:true, data:{outputPath}}`，否则 `{ok:false, error}`
- index 文件可选：同名 .index 存在才传，不存在传空串/省略（run_infer_script 的 index_path 允许空）

**2. `I:\llama.cpp\runtime\services\HoloHttpApi.js` — 新建 8088 HTTP 服务（唯一新建 Holo 文件）**

用 Node 内置 `http.createServer`（不引 Express，避免新增依赖；用户说"建议用 Express"但补充约束允许 Node 原生，且 main.js 第 669 行已 `require('http')`）。监听 `127.0.0.1:8088`，提供 3 个端点，全部 JSON，统一 `{ok, data}` / `{ok:false, error}`：

- `GET /api/applio/listModels` → `serviceManager` 取 applio runtime → `listModels()` → 返回 models 数组
- `POST /api/applio/infer` → 收 `{text,speaker,voiceModel,blockId,projectId}`：
  1. 校验 voiceModel 必填，否则 `{ok:false, error:'VOICE_MODEL_REQUIRED'}`
  2. 调 MOSS 合成 temp.wav（复用 main.js 已有 spawn 逻辑，抽成 `synthesizeToTemp(text)` 或直接内联，输出到 `audio/temp/<blockId>.wav`）
  3. 调 `applioRuntime.infer(tempWav, audio/<blockId>.wav, voiceModel+'.pth', index)`
  4. 用 `ffprobe.exe`（Applio 目录自带）读 WAV 时长 → start=0.0, end=时长
  5. 返回 `{audio:'audio/<blockId>.wav', start, end}`
- `POST /api/audio/play` → 收 `{path}`，复用 audio:play 的 audiocpp_cli 播放，返回 `{ok:true}`

所有端点 try/catch 全包，永不抛异常、永不返回非 JSON。

**3. `I:\llama.cpp\frontend\main.js` — 挂载 HoloHttpApi**

在 `app.whenReady()` 注册 applio 之后，实例化 HoloHttpApi 并 `start()`，把 `serviceManager` + 已有的 MOSS 合成/AUDIO_OUTPUT_DIR/ffprobe 路径传进去。窗口全关/退出时 `stop()`。AUDIO_OUTPUT_DIR 沿用现有 `ensureAudioDir()` 的目录（audio/）。

### B. Blender 插件 — 声音面板 + IPC + 数据字段

**4. `vb_props.py` — VBBlock 新增 3 字段**

`speaker: StringProperty(default="")`、`voice_model: StringProperty(default="")`（`audio` 已存在）。旧工程缺字段自动空串（PropertyGroup 向后兼容，无需迁移代码）。

**5. `vb_holo_ipc.py` — 唯一新增 Blender 文件（IPC 封装）**

标准库 `urllib.request`，3 个公开函数，全部捕获 ConnectionError → `{"ok":False,"error":"HOLO_OFFLINE"}`：
- `list_rvc_models()`：GET `/api/applio/listModels`，**5 秒缓存**（模块级 `_cache={time,data}`），避免面板重绘刷 HTTP
- `generate_block_audio(payload_dict)`：POST `/api/applio/infer`，payload 由调用方组装
- `play_audio(path)`：POST `/api/audio/play`
内部统一 `_post(url, obj)` / `_get(url)`，超时 5s（list）/ 长超时（infer 用单独长超时，如 120s）。只返回 dict，不抛异常、不 import bpy。

**6. `vb_panels.py` — 声音面板 + 2 个 operator**

- 面板 `VOICEBOOK_PT_VoiceBlocks` 的"当前段"box 内、`文本` 之后插入 `🔊 声音` 子区：
  - `Speaker`（blk.speaker，文本框）
  - `Voice Model`（下拉，EnumProperty 动态 items 来自 `list_rvc_models()`；空/离线时禁用）
  - `Audio`（blk.audio，只读 label）
  - `Generate`（voicebook.generate_audio）/ `Preview`（voicebook.preview_audio）
  - 无选中 block 时全部 disabled（`row.enabled = False`）；生成中按钮显示"生成中…"（operator 内置状态标志）
- `VOICEBOOK_OT_generate_audio`（voicebook.generate_audio）：
  - 组装 payload `{text,speaker,voiceModel,blockId,projectId}`（projectId 用 props.page_id）
  - 校验 voice_model 非空，否则 report 错误
  - 启动 `threading.Thread(daemon=True)`，线程内只调 `vb_holo_ipc.generate_block_audio`，结果存模块级队列 `{block_id: result}`
  - 主线程 `bpy.app.timers.register(_poll, first_interval=0.5)` 轮询队列，取到后写 `block.audio/start/end` + `tag_redraw` + 注销 timer
  - 防重入：同 blockId 生成中不重复发起
- `VOICEBOOK_OT_preview_audio`（voicebook.preview_audio）：调 `play_audio(block.audio)`，audio 空则禁用
- 下拉动态 EnumProperty 需要模块级 items 回调 + 缓存刷新按钮（refresh operator）

**7. `vb_json.py` — blocks 往返加 3 字段**

导出 `blocks[]` 每项加 `speaker`、`voiceModel`（注意 JSON key 用 camelCase `voiceModel`，对应 Python `voice_model`）、`audio` 已有；导入缺字段默认空串。旧工程（无这 3 key）兼容，已在现有 `_as_float`/`get(...,"")` 模式下自然满足。

**8. `__init__.py` — 注册**

import vb_holo_ipc（无需注册类），把 2 个新 operator 加进 classes（实际在 vb_panels.classes 里加即可，__init__ 无需改，除非 operator 放新文件——本方案放 vb_panels.py，__init__ 不动）。

## 关键技术决策

1. **Applio 推理走 CLI 不走 Gradio**：用户补充约束 3 明确"如果 Gradio 无法调用，改用 subprocess 调命令行"。已确认 `core.py infer` 是稳定 click CLI，比 Gradio HTTP API 可靠。
2. **HTTP 服务用 Node 原生 http（用户已确认）**：不引 Express，零新增 npm 包、不改 package.json/node_modules。
3. **异步用 timer 轮询不用纯 threading 改数据**：用户补充约束 4 强制。子线程只发 HTTP，主线程 timer 回填。
4. **MOSS 合成复用**：不新写 TTS 逻辑，直接复用 main.js 第 1466 行 `tts:generate` 的 CLI spawn 模式，抽到可被 HTTP 端点调用的位置。
5. **projectId**：用 `props.page_id`（默认 p.0000.w1h1），payload 里带上但 Holo 端本阶段不强制校验，仅透传记录。

## 验证（端到端，实测非模拟）

1. **Holo 端**：`node` 起 main.js 需 Electron，改为单独起 HoloHttpApi 做冒烟：`curl GET /api/applio/listModels` 返回 `{ok:true,data:{models:[]}}`（RVC 目录空）；放 1 个假 .pth 验证 list 返回。
2. **ApplioRuntime.infer**：造一个 1 秒静音 WAV 作 input；RVC 目录当前为空，**按用户决定只验证到错误路径** —— 缺模型时返回结构化 `{ok:false, error}` 不崩溃。端到端声音生成待你放真模型后自测。
3. **Blender 端**：`blender --background --python` 加载插件，验证：
   - list_rvc_models 5s 缓存（连续两次调用第二次不发 HTTP，用 mock server 计数）
   - vb_holo_ipc 连接拒绝时返回 HOLO_OFFLINE 不抛异常
   - JSON 导出 blocks 含 speaker/voiceModel/audio，导入旧 JSON（无这 3 字段）不报错且默认空串
4. **整合**：起 HoloHttpApi + Blender 后台脚本点 generate，验证 timer 轮询回填（若无真模型，验证"HOLO 返回错误时面板不卡死、按钮恢复"）。

## 不做（用户禁止）

不改 Block 坐标结构、不改 MOSS Runtime 源码、不改 vb_engine/vb_modal、不训练/下载模型、不接 UVR/人声分离、不改 8765、Blender 不 import Electron、不新增 npm 依赖（用 Node 原生 http）。
