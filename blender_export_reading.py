import bpy
import os
import json
import shutil
import importlib
from pathlib import Path

# ============================================================
# 工具函数：获取仓库根目录
# ============================================================
def get_repo_root():
    """尝试寻找包含 build.py 的仓库根目录"""
    # 1. 从当前 Blender 文件向上查找
    if bpy.data.is_saved:
        p = Path(bpy.data.filepath).resolve()
        for parent in p.parents:
            if (parent / "build.py").exists():
                return parent
    
    # 2. 从当前脚本文件向上查找
    try:
        p = Path(__file__).resolve()
        for parent in p.parents:
            if (parent / "build.py").exists():
                return parent
    except NameError:
        pass # __file__ 在某些 Blender 执行环境下不可用
            
    # 3. 兜底策略：如果没找到，尝试在当前工作目录寻找
    cwd = Path.cwd()
    if (cwd / "build.py").exists():
        return cwd
        
    # 如果还是没找到，回退到脚本所在的相对位置（假设在根目录）
    return Path.cwd()

# ============================================================
# 语音书新建工程算子 (BR_OT_new_gate_voice_book)
# ============================================================
class BR_OT_new_gate_voice_book(bpy.types.Operator):
    bl_idname = "comic.new_gate_voice_book"
    bl_label = "新建语音书工程"
    bl_description = "生成天门语音书工程blend，写入VoiceBook_Settings标记"
    bl_options = {'REGISTER', 'UNDO'}

    project_id: bpy.props.StringProperty(
        name="工程 ID",
        description="项目的唯一标识符 (例如: voice_book_01)",
        default="voice_book_01"
    )
    
    title: bpy.props.StringProperty(
        name="书籍标题",
        description="显示在阅读器顶部的正式名称",
        default="无门关"
    )
    
    author: bpy.props.StringProperty(
        name="作者",
        description="原作者或项目创建者",
        default="慧开 (无门)"
    )

    accent_color: bpy.props.FloatVectorProperty(
        name="印章主题色",
        description="天门书经典红色印章的色值",
        subtype='COLOR',
        default=(0.78, 0.24, 0.23),
        min=0.0, max=1.0
    )

    def invoke(self, context, event):
        print("[GatelessGate] NEW BR_OT_new_gate_voice_book INVOKE")
        print("[GatelessGate] source = blender_export_reading.py")
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        header = col.box()
        row = header.row(align=True)
        row.scale_y = 1.2
        row.label(text="GATELESS GATE", icon='BOOK')
        row.label(text="语音书模式", icon='SPEAKER')
        
        col.separator()
        main = col.box()
        
        group = main.column(align=True)
        group.label(text="工程配置", icon='SETTINGS')
        group.prop(self, "project_id", text="ProjectId", icon='FILE_FOLDER')
        
        main.separator()
        group = main.column(align=True)
        group.label(text="书籍信息", icon='TEXT')
        row = group.row(align=True)
        row.label(text="", icon='SORTALPHA')
        row.prop(self, "title", text="书名")
        row = group.row(align=True)
        row.label(text="", icon='USER')
        row.prop(self, "author", text="作者")
        
        main.separator()
        group = main.column(align=True)
        group.label(text="视觉风格", icon='RESTRICT_COLOR_ON')
        group.prop(self, "accent_color", text="印章主题色")

    def execute(self, context):
        print("[GatelessGate] BR_OT_new_gate_voice_book EXECUTED")
        
        # 1. 准备路径 (内联仓库根目录查找逻辑，切断外部函数依赖)
        repo_root = None
        # 优先从当前文件路径推断
        if bpy.data.is_saved:
            p = Path(bpy.data.filepath).resolve()
            for parent in p.parents:
                if (parent / "build.py").exists():
                    repo_root = parent
                    break
        # 尝试从脚本路径推断
        if repo_root is None:
            try:
                p = Path(__file__).resolve()
                for parent in p.parents:
                    if (parent / "build.py").exists():
                        repo_root = parent
                        break
            except: 
                pass
        # 兜底到当前工作目录
        if repo_root is None:
            cwd = Path.cwd()
            if (cwd / "build.py").exists():
                repo_root = cwd
            else:
                repo_root = Path.cwd()

        project_name = self.project_id if self.project_id else "voice_book_样板"
        project_dir = repo_root / "books" / project_name
        blend_dir = project_dir / "blender"
        blend_dir.mkdir(parents=True, exist_ok=True)
        target_path = blend_dir / f"{project_name}.blend"
        
        # 2. 寻找真实模板 (优先使用 voice_book_template.blend)
        template_dir = repo_root / "templates" / "voice_book" / "blender"
        template_path = template_dir / "voice_book_template.blend"
        
        if not template_path.exists():
            template_path = template_dir / "template.blend"
            
        if not template_path.exists():
            self.report({"ERROR"}, f"找不到真实天门书模板: {template_path}")
            return {"CANCELLED"}
            
        # 3. 复制模板文件 (保证材质、灯光、相机、物体完整性)
        try:
            shutil.copy2(str(template_path), str(target_path))
            print(f"[GatelessGate] Template copied to: {target_path}")
        except Exception as e:
            self.report({"ERROR"}, f"复制工程文件失败: {str(e)}")
            return {"CANCELLED"}
            
        # 4. 打开新生成的工程文件
        try:
            bpy.ops.wm.open_mainfile(filepath=str(target_path))
        except Exception as e:
            self.report({"ERROR"}, f"打开工程文件失败: {str(e)}")
            return {"CANCELLED"}
            
        # 5. 更新项目元数据
        scene = bpy.context.scene
        hex_accent = "#%02x%02x%02x" % (
            int(self.accent_color[0] * 255),
            int(self.accent_color[1] * 255),
            int(self.accent_color[2] * 255)
        )
        scene["VoiceBook_Settings"] = {
            "project_id": project_name,
            "title": self.title,
            "author": self.author,
            "accent": hex_accent
        }
        
        # 激活 Reading Mode 开关
        if hasattr(scene, "is_reading_book"):
            scene.is_reading_book = True
            
        # 6. 设置默认视口为材质预览 (Material Preview)
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
        
        # 7. 保存更改
        bpy.ops.wm.save_as_mainfile(filepath=str(target_path))
        
        self.report({"INFO"}, f"天门语音书工程已创建: {project_name}")
        return {"FINISHED"}

# ============================================================
# 语音标记快速导出算子 (TM_OT_quick_export_voice_cues)
# ============================================================
class TM_OT_quick_export_voice_cues(bpy.types.Operator):
    bl_idname = "comic.quick_export_voice_cues"
    bl_label = "天门书：快速导出语音标记"
    bl_description = "导出 manifest.json, voice_cues.json, GLB场景及样式文件"

    def execute(self, context):
        scene = context.scene
        if "VoiceBook_Settings" not in scene:
            self.report({"ERROR"}, "当前不是天门语音书工程，请使用【新建语音书…】创建项目")
            return {"CANCELLED"}

        book_cfg = scene["VoiceBook_Settings"]
        project_id = book_cfg.get("project_id", "unknown_book")
        fps = scene.render.fps

        repo_root = get_repo_root()
        output_root = repo_root / "books" / project_id
        output_root.mkdir(parents=True, exist_ok=True)

        # 1. 导出 voice_cues.json
        cue_list = []
        for marker in scene.timeline_markers:
            time_sec = marker.frame / fps
            cue_list.append({
                "name": marker.name,
                "frame": marker.frame,
                "time": round(time_sec, 3)
            })

        cue_payload = {"cues": cue_list}
        with open(output_root / "voice_cues.json", "w", encoding="utf-8") as f:
            json.dump(cue_payload, f, ensure_ascii=False, indent=2)

        # 2. 导出 manifest.json
        manifest = {
            "id": project_id,
            "title": book_cfg.get("title", project_id),
            "author": book_cfg.get("author", ""),
            "mode": "voice",
            "accent": book_cfg.get("accent", "#C73E3A"),
            "glb": f"{project_id}.glb"
        }
        with open(output_root / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 3. 导出 GLB 场景资源
        glb_path = output_root / f"{project_id}.glb"
        try:
            bpy.ops.export_scene.gltf(
                filepath=str(glb_path),
                export_format='GLB',
                use_selection=False,
                export_apply=True
            )
        except Exception as e:
            self.report({"WARNING"}, f"GLB 导出失败: {str(e)}")

        # 4. 导出 styles (css, json)
        styles_dir = output_root / "styles"
        styles_dir.mkdir(exist_ok=True)
        
        template_styles_dir = repo_root / "templates" / "voice_book" / "styles"
        for style_file in ["voice-book.css", "voice-theme.json"]:
            src = template_styles_dir / style_file
            if src.exists():
                shutil.copy2(src, styles_dir / style_file)

        self.report({"INFO"}, f"天门语音书标记与资源导出完成 → {project_id}")
        return {"FINISHED"}

# ============================================================
# 语音书全量构建算子 (TM_OT_export_voice_book_build)
# ============================================================
class TM_OT_export_voice_book_build(bpy.types.Operator):
    bl_idname = "comic.export_voice_book"
    bl_label = "天门书：全量导出 (Build)"
    bl_description = "调用build.py完整构建，唤起8000静态打包产物预览"

    def execute(self, context):
        scene = context.scene
        if "VoiceBook_Settings" not in scene:
            self.report({"ERROR"}, "当前不是天门语音书工程，请使用【新建语音书…】创建项目")
            return {"CANCELLED"}

        book_cfg = scene["VoiceBook_Settings"]
        project_id = book_cfg.get("project_id", "unknown_book")
        repo_root = get_repo_root()
        build_script = repo_root / "build.py"

        if not build_script.exists():
            self.report({"ERROR"}, f"找不到build.py：{build_script}")
            return {"CANCELLED"}

        import subprocess
        try:
            subprocess.run(
                ["python", str(build_script), "--book-id", project_id, "--mode", "voice"],
                cwd=str(repo_root),
                check=True
            )
        except Exception as e:
            self.report({"ERROR"}, f"build执行失败:{str(e)}")
            return {"CANCELLED"}

        self.report({"INFO"}, "全量构建完成")
        return {"FINISHED"}

# ============================================================
# 原有天门书导出算子与面板 (BR_OT_export_reading_data)
# ============================================================
class ReadingPageSettings(bpy.types.PropertyGroup):
    chapter_title: bpy.props.StringProperty(name="章节标题")
    long_text: bpy.props.StringProperty(name="正文内容")
    narration_audio: bpy.props.StringProperty(name="旁白音频", subtype='FILE_PATH')
    auto_next_on_ended: bpy.props.BoolProperty(name="播放完自动翻页", default=True)
    style_id: bpy.props.StringProperty(name="样式 ID", default="gatelessgate")

class BR_OT_export_reading_data(bpy.types.Operator):
    bl_idname = "comic.export_reading_data"
    bl_label = "导出语音书到8765"
    bl_description = "导出 Reading/Voice 模式所需的 JSON、图片和音频，并自动打开浏览器预览"
    
    def execute(self, context):
        scene = context.scene
        is_reading = False
        if hasattr(scene, "panel_settings"):
            is_reading = getattr(scene.panel_settings, "is_reading_book", False)
        else:
            is_reading = getattr(scene, "is_reading_book", False)
            
        if not is_reading:
            self.report({'ERROR'}, "当前非 Reading 模式，请先开启 Reading 开关")
            return {'CANCELLED'}

        if not bpy.data.is_saved:
            self.report({'ERROR'}, "请先保存 Blender 文件")
            return {'CANCELLED'}
            
        blend_path = Path(bpy.data.filepath)
        project_root = blend_path.parent.parent
        
        # 优先使用 VoiceBook_Settings 中的 project_id
        book_id = blend_path.parent.name
        is_voice_book = False
        if "VoiceBook_Settings" in scene:
            book_id = scene["VoiceBook_Settings"].get("project_id", book_id)
            is_voice_book = True
            
        repo_root = get_repo_root()
        output_root = repo_root / "books" / book_id
        
        pages_dir = output_root / "pages"
        audio_dir = output_root / "audio"
        images_dir = output_root / "images"
        
        for d in (pages_dir, audio_dir, images_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 获取所有场景，如果有以 p. 开头的则按 p. 过滤并排序，否则导出当前场景
        reading_scenes = [s for s in bpy.data.scenes if s.name.startswith("p.")]
        reading_scenes.sort(key=lambda s: s.name)

        if not reading_scenes:
            reading_scenes = [context.scene]

        manifest_pages = []
        for idx, s in enumerate(reading_scenes, start=1):
            pid = f"p{idx:03d}"
            page_json_path = pages_dir / f"{pid}.json"
            img_name = f"{pid}.jpg"
            img_path = images_dir / img_name
            
            orig_scene = context.window.scene
            context.window.scene = s
            s.render.filepath = str(img_path)
            s.render.image_settings.file_format = 'JPEG'
            bpy.ops.render.render(write_still=True)
            context.window.scene = orig_scene
            
            audio_rel_path = None
            if hasattr(s, "reading_page") and s.reading_page.narration_audio:
                src_audio = Path(bpy.path.abspath(s.reading_page.narration_audio))
                if src_audio.exists():
                    audio_name = src_audio.name
                    dest_audio = audio_dir / audio_name
                    shutil.copy2(src_audio, dest_audio)
                    audio_rel_path = f"audio/{audio_name}"
            
            title = ""
            dialogues = []
            for obj in s.objects:
                if obj.type == 'FONT':
                    if obj.name.lower().startswith("title"):
                        title = obj.data.body
                    elif obj.name.lower().startswith("letter.") or obj.name.lower().startswith("dialogue"):
                        parts = obj.name.split('.')
                        speaker = parts[1] if len(parts) > 1 else ""
                        dialogues.append({"speaker": speaker, "text": obj.data.body})

            # 确定页面模式
            page_mode = "reading"
            if is_voice_book or audio_rel_path:
                page_mode = "voice"

            page_data = {
                "page_id": pid,
                "pageId": pid,
                "title": title,
                "chapterTitle": getattr(s.reading_page, "chapter_title", ""),
                "image": f"images/{img_name}",
                "longText": getattr(s.reading_page, "long_text", ""),
                "style": getattr(s.reading_page, "style_id", "gatelessgate"),
                "narrationAudio": audio_rel_path,
                "autoNextOnEnded": getattr(s.reading_page, "auto_next_on_ended", True),
                "dialogues": dialogues,
                "mode": page_mode
            }
            page_json_path.write_text(json.dumps(page_data, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_pages.append(f"pages/{pid}.json")

        has_audio = any(s.reading_page.narration_audio for s in reading_scenes if hasattr(s, "reading_page"))
        
        # 确定全局模式
        global_mode = "reading"
        if is_voice_book or has_audio:
            global_mode = "voice"

        manifest = {
            "mode": global_mode,
            "bookTitle": book_id,
            "pages": manifest_pages,
            "audioDir": "audio",
            "imagesDir": "images",
            "autoNextOnEnded": True
        }
        (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        
        self.report({'INFO'}, f"成功导出 {len(manifest_pages)} 页数据")

        # 8. 自动弹出浏览器预览 (仅保留在此主导出算子)
        try:
            import webbrowser
            preview_url = f"http://127.0.0.1:5173/Comic-books/?book={book_id}&mode={global_mode}"
            webbrowser.open(preview_url)
            print(f"[GatelessGate] Opening browser preview: {preview_url}")
        except Exception as e:
            self.report({'WARNING'}, f"自动打开预览失败: {str(e)}")

        return {'FINISHED'}

class BR_PT_reading_export_panel(bpy.types.Panel):
    bl_label = "天门书导出 (Reading)"
    bl_idname = "BR_PT_reading_export_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '3D 连环画'
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        if hasattr(scene, "panel_settings"):
            return getattr(scene.panel_settings, "is_reading_book", False)
        return getattr(scene, "is_reading_book", False)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        if hasattr(scene, "reading_page"):
            box = layout.box()
            box.label(text="当前页面属性", icon='INFO')
            box.prop(scene.reading_page, "chapter_title")
            box.prop(scene.reading_page, "long_text")
            box.prop(scene.reading_page, "narration_audio")
            box.prop(scene.reading_page, "auto_next_on_ended")
            box.prop(scene.reading_page, "style_id")
        
        layout.separator()
        layout.operator("comic.export_reading_data", icon='EXPORT')

        # 追加语音书专属操作
        layout.separator()
        box = layout.box()
        box.label(text="语音书工具", icon='SPEAKER')
        box.operator("comic.new_gate_voice_book", icon='PRESET_NEW', text="新建语音书…")
        box.operator("comic.quick_export_voice_cues", icon='MARKER', text="导出语音标记 (Vite)")
        box.operator("comic.export_voice_book", icon='PACKAGE', text="全量构建 (Build)")

def menu_callback_new_gate_voicebook(self, context):
    self.layout.operator("comic.new_gate_voice_book", text="新建语音书…")

def register():
    bpy.utils.register_class(ReadingPageSettings)
    bpy.types.Scene.reading_page = bpy.props.PointerProperty(type=ReadingPageSettings)
    
    if not hasattr(bpy.types.Scene, "is_reading_book"):
        bpy.types.Scene.is_reading_book = bpy.props.BoolProperty(name="Reading Mode 开关", default=False)
    
    bpy.utils.register_class(BR_OT_new_gate_voice_book)
    bpy.utils.register_class(TM_OT_quick_export_voice_cues)
    bpy.utils.register_class(TM_OT_export_voice_book_build)
    bpy.utils.register_class(BR_OT_export_reading_data)
    bpy.utils.register_class(BR_PT_reading_export_panel)
    
    bpy.types.TOPBAR_MT_file_new.append(menu_callback_new_gate_voicebook)

def unregister():
    bpy.types.TOPBAR_MT_file_new.remove(menu_callback_new_gate_voicebook)
    
    bpy.utils.unregister_class(BR_PT_reading_export_panel)
    bpy.utils.unregister_class(BR_OT_export_reading_data)
    bpy.utils.unregister_class(TM_OT_export_voice_book_build)
    bpy.utils.unregister_class(TM_OT_quick_export_voice_cues)
    bpy.utils.unregister_class(BR_OT_new_gate_voice_book)
    
    del bpy.types.Scene.reading_page
    if hasattr(bpy.types.Scene, "is_reading_book"):
        del bpy.types.Scene.is_reading_book

if __name__ == "__main__":
    register()
