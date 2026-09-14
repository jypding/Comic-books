# -*- coding: utf-8 -*-
"""
Blender 导出 → /books/<书名>/ 的构建脚本。

开发与构建环境边界说明：
1. 开发调试天门书 (5173)：使用 Vite 开发服务器，支持 mode=voice/reading 实时预览，无需运行 build.py。
2. 离线归档/发布 (8000)：执行本脚本 build.py 生成产物，使用 8000 端口验证打包后的静态产物。
3. Blender 快速导出算子：仅增量更新 voice_cues.json，**不会** 增加拷贝 styles、生成 manifest 的逻辑。

⚠️ 提醒：在静态预览模式下，若修改了样式或新建了工程，必须手动运行 build.py 以同步 styles 资源。

架构约束（禁止修改以下策略）：
 1. 输出路径：<project_root>/books/<book_id>/
    ├── book/
    │   ├── manifest.json
    │   └── pages/
    │       ├── page-001.json
    │       └── page-001/
    │           └── scene.glb        (cinematic 时导出；reading/voice 不导出)
    ├── audio/                        (可选，reading / voice)
    └── images/                       (可选，reading / voice)

 2. page.json 使用统一顶层 UnifiedPage schema（全字段可选，保持 page_id 等已验证字段）：
    - page_id (string, 保持 R3 命名)
    - mode?: "reading" | "voice" | "cinematic"   (可覆盖 manifest.mode)
    - title, chapterTitle, longText, image, audioFile, narrationAudio, autoNextOnEnded
    - dialogue / dialogues (两种格式都兼容)
    - camera / animations / model (cinematic)
    - next / prev (R3 兼容翻页字段)

 3. Blender Camera 链路不修改：
    - 仅按 blender_camera_name 在 GLB cameras 中查找并激活
    - 不修改 projectionMatrix / aspect / FOV（保持 Blender 导出值）
    - 动画仅作用于 position / quaternion / scale，交给 AnimationMixer

 4. 调用方式：
      blender -b <.blend> -P build.py -- \
          --book-id <书名> \
          --mode cinematic|reading|voice \
          [--output <project_root 绝对路径，默认 ../../..>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------- Markdown 编译逻辑 (book.md -> pages JSON) ----------

def _parse_book_md(md_path: Path) -> List[Dict[str, Any]]:
    """解析 book.md 劇本源。
    ## Page ID 开头表示一页。
    [key: value] 表示页面属性。
    Speaker: Text 表示对话。
    Narration: Text 表示旁白。
    其他为 longText。
    """
    if not md_path.exists():
        return []

    content = md_path.read_text(encoding="utf-8")
    pages: List[Dict[str, Any]] = []
    current_page: Optional[Dict[str, Any]] = None
    
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            if current_page and current_page.get("longText"):
                current_page["longText"] += "\n\n"
            continue

        # 新页面
        if line.startswith("## "):
            pid = line[3:].strip()
            current_page = _blank_page(pid)
            pages.append(current_page)
            continue
        
        if not current_page:
            continue

        # 页面属性 [key: value]
        attr_match = re.match(r"^\[(\w+):\s*(.*)\]$", line)
        if attr_match:
            key, val = attr_match.groups()
            try:
                # 尝试解析 JSON 格式的值（针对 camera, effects 等复杂字段）
                val_obj = json.loads(val)
                current_page[key] = val_obj
            except:
                current_page[key] = val
            continue

        # 对话 Speaker: Text
        diag_match = re.match(r"^([^:]+):\s*(.*)$", line)
        if diag_match:
            speaker, text = diag_match.groups()
            if speaker.lower() == "narration":
                current_page["narration"] = text
            else:
                current_page["dialogues"].append({"speaker": speaker, "text": text})
            continue

        # 普通文本 -> longText
        if current_page.get("longText") is not None:
            current_page["longText"] = (current_page["longText"] + " " + line).strip()
        else:
            current_page["longText"] = line

    # 清理多余换行
    for p in pages:
        if p.get("longText"):
            p["longText"] = p["longText"].strip()
            
    return pages


# ---------- UnifiedPage JSON（与 src/core/ProjectLoader.ts 中 UnifiedPage 保持字段一致） ----------

def _blank_page(page_id: str) -> Dict[str, Any]:
    return {
        "page_id": page_id,
        "pageId": page_id,
        "mode": None,
        "title": "",
        "thumbnail": None,
        "width": 1024,
        "height": 1024,
        "chapterTitle": "",
        "longText": "",
        "image": None,
        "layout": "standard",
        "panels": [],
        "dialogue": {"text": "", "speaker": "", "audio": None},
        "dialogues": [],
        "narration": "",
        "narrationAudio": None,
        "style": "default",
        "ui": "default",
        "interaction": [],
        "camera": {"blender_camera_name": None},
        "effects": [],
        "transition": "fade",
        "media": [],
        "animations": {"active_actions": []},
        "model": {"glb": "scene.glb", "splat": None},
        "glbAnimationClip": None,
        "pageDuration": None,
        "next": None,
        "prev": None,
    }


def _blank_manifest(book_title: str, mode: str, pages: List[str]) -> Dict[str, Any]:
    if mode == "voice":
        return {
            "id": book_title,
            "title": book_title,
            "mode": "voice",
            "accent": "#FF0000",
            "narration": {
                "model": "gemini-3.1-flash-tts-preview",
                "voice": "Charon",
                "preset": "british"
            },
            "pages": pages
        }
    return {
        "mode": mode,
        "bookTitle": book_title,
        "pages": pages,
        "audioDir": "audio",
        "imagesDir": "images",
        "autoNextOnEnded": (mode == "voice"),
        "style": "styles/voice/gatelessgate.json",
        "ui": "standard",
        "layout": "split",
        "transition": "fade",
        "cinematic": {
            "scene": "cinematic/scene.glb",
            "camera": "cinematic/camera.json",
            "animation": "cinematic/animation.json"
        }
    }


# ---------- 实际构建（当在 Blender 中运行时使用 bpy；否则作为纯 JSON 工具） ----------

def _in_blender() -> bool:
    try:
        import bpy  # noqa: F401
        return True
    except Exception:
        return False


def _blender_safe_export_gltf(glb_path: Path) -> None:
    """仅当运行在 Blender 内部时导出 GLB；否则跳过（纯离线构建不改变已验证的 GLB 链路）。"""
    if not _in_blender():
        # 不抛错：允许纯 JSON 模式运行（仅写 page.json / manifest.json）
        return
    import bpy
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    # 保持 R3 已验证的导出参数，禁止修改相机/动画链路：
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        export_cameras=True,
        export_animations=True,
        export_nla_strips=True,
        export_def_bones=True,
        export_apply=False,
        export_image_format="AUTO",
        use_selection=False,
    )


def _collect_pages_from_blender(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """从当前 .blend 中按命名约定收集页面：'Page_0001' / 'Seq_0001' 等 collection / scene 命名。"""
    if not _in_blender():
        # 纯 JSON 模式：返回一个最小的占位 page（保持 build.py 在标准 Python 环境也可执行）
        p = _blank_page("page-001")
        p["title"] = "Page 1"
        if args.mode == "cinematic":
            p["camera"]["blender_camera_name"] = "Camera"
            p["model"]["glb"] = "scene.glb"
        elif args.mode in ("reading", "voice"):
            p["image"] = "images/page-001.jpg"
            p["narrationAudio"] = "audio/page-001.mp3"
        return [p]

    import bpy
    pages: List[Dict[str, Any]] = []
    # 优先从 collection "Pages.*" 取子集合；否则按场景
    pages_coll = bpy.data.collections.get("Pages") or bpy.data.collections.get("Pages Root")
    ordered: List[Any] = []
    if pages_coll is not None:
        ordered = sorted(pages_coll.children, key=lambda c: c.name)
    else:
        ordered = sorted(bpy.data.scenes, key=lambda s: s.name)

    for idx, obj in enumerate(ordered, start=1):
        pid = f"page-{idx:03d}"
        page = _blank_page(pid)
        page["title"] = getattr(obj, "name", pid)
        if args.mode == "cinematic":
            # 尝试在 obj 里找第一个 Camera；否则取 Blender 场景主相机
            cam = None
            if hasattr(obj, "objects"):
                for o in obj.objects:
                    if getattr(o, "type", "") == "CAMERA":
                        cam = o
                        break
            if cam is None and getattr(obj, "camera", None):
                cam = obj.camera
            if cam is not None:
                page["camera"]["blender_camera_name"] = cam.name
            page["model"]["glb"] = "scene.glb"
            page["width"] = 1920
            page["height"] = 1080
        pages.append(page)

    # 填 next/prev（R3 兼容）
    for i, p in enumerate(pages):
        p["prev"] = pages[i - 1]["page_id"] if i > 0 else None
        p["next"] = pages[i + 1]["page_id"] if i + 1 < len(pages) else None
    return pages


def build(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Comic build.py: Blender → books/<book_id>/")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--mode", required=True, choices=["reading", "voice", "cinematic"])
    parser.add_argument("--book-title", default=None)
    parser.add_argument("--output", default=None, help="项目根目录 (默认为脚本所在目录)")
    args = parser.parse_args(argv)

    if args.output:
        project_root = Path(args.output).resolve()
    else:
        project_root = Path(__file__).resolve().parent

    books_root = project_root / "books"
    books_root.mkdir(parents=True, exist_ok=True)
    book_id_root = books_root / args.book_id
    book_root = book_id_root / "book"
    pages_dir = book_root / "pages"
    audio_dir = book_id_root / "audio"
    images_dir = book_id_root / "images"
    cinematic_dir = book_id_root / "cinematic"
    for d in (pages_dir, audio_dir, images_dir, cinematic_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 优先从 book.md 加载内容；若无则从 Blender 收集
    md_path = book_id_root / "book.md"
    pages = []
    if md_path.exists():
        print(f"[build.py] parsing {md_path}")
        pages = _parse_book_md(md_path)
    else:
        # 如果是 voice 模式且已有 pages/ 下的 json，说明是从模板复制的，优先保留
        existing_pages = list(pages_dir.glob("*.json"))
        if args.mode == "voice" and existing_pages:
            print(f"[build.py] preserving existing template pages for voice mode")
            for ep in existing_pages:
                try:
                    p_data = json.loads(ep.read_text(encoding="utf-8"))
                    pages.append(p_data)
                except:
                    pass
        
        if not pages:
            pages = _collect_pages_from_blender(args)

    # 写 pages/pXXX.json 与 (cinematic 时) GLB
    manifest_pages: List[str] = []
    for idx, page in enumerate(pages, start=1):
        pid = f"p{idx:03d}"
        page["page_id"] = pid
        page["pageId"] = pid
        rel_json = f"pages/{pid}.json"
        manifest_pages.append(rel_json)
        # 对齐：mode 可在 page 层覆盖 manifest 默认模式
        if page.get("mode") is None:
            page["mode"] = None  # 默认留空=不覆盖
        json_path = pages_dir / f"{pid}.json"
        json_path.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.mode == "cinematic":
            glb_path = pages_dir / pid / "scene.glb"
            _blender_safe_export_gltf(glb_path)

    manifest = _blank_manifest(
        book_title=args.book_title or args.book_id,
        mode=args.mode,
        pages=manifest_pages,
    )
    (book_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[build.py] done: book_id={args.book_id} mode={args.mode} pages={len(manifest_pages)}")
    print(f"[build.py] output: {book_root}")
    return 0


if __name__ == "__main__":
    # Blender 调用:  blender -b file.blend -P build.py -- --book-id ...
    # 标准 Python 调用: python build.py --book-id demo --mode voice
    try:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None
    except ValueError:
        argv = None
    raise SystemExit(build(argv))
