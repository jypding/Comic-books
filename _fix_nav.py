# -*- coding: utf-8 -*-
import io, os

P = r"C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\3DComicToolkit.py"

with io.open(P, "r", encoding="utf-8") as f:
    c = f.read()

replacements = []

# ========== 1. 首个画格 ==========
replacements.append((
'''class BR_OT_first_panel_scene(bpy.types.Operator):
    """make first panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_first_panel"
    bl_label ="жЈЈж ҰйҮңйҗўз»ҳзүёй”ӣеңҳirstй”ӣ?
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.context.window.scene = bpy.data.scenes[0]
        return {'FINISHED'}''',
'''class BR_OT_first_panel_scene(bpy.types.Operator):
    """make first panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_first_panel"
    bl_label = "First"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .core.page_registry import PageRegistry
        registry = PageRegistry(context)
        if registry.mode == "language":
            pages = registry.list_pages()
            if pages:
                registry.load_page(pages[0])
            return {'FINISHED'}
        bpy.context.window.scene = bpy.data.scenes[0]
        return {'FINISHED'}'''))

# ========== 2. 末个画格 ==========
replacements.append((
'''class BR_OT_last_panel_scene(bpy.types.Operator):
    """make last panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_last_panel"
    bl_label ="йҸҲоӮЎйҮңйҗўз»ҳзүёй”ӣең astй”ӣ?
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        totalScenes = len(bpy.data.scenes) - 1
        bpy.context.window.scene = bpy.data.scenes[totalScenes]
        return {'FINISHED'}''',
'''class BR_OT_last_panel_scene(bpy.types.Operator):
    """make last panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_last_panel"
    bl_label = "Last"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .core.page_registry import PageRegistry
        registry = PageRegistry(context)
        if registry.mode == "language":
            pages = registry.list_pages()
            if pages:
                registry.load_page(pages[-1])
            return {'FINISHED'}
        totalScenes = len(bpy.data.scenes) - 1
        bpy.context.window.scene = bpy.data.scenes[totalScenes]
        return {'FINISHED'}'''))

# ========== 3. 面板 draw ==========
replacements.append((
'''        if material_swatch_object:
            layout.label(text="鍒嗛暅瀵艰埅锛?)''',
'''        # === 语音书走 Provider ===
        from .core.page_registry import PageRegistry
        _registry = PageRegistry(context)
        if _registry.mode == "language":
            _pages = _registry.list_pages()
            _current = _registry.get_current_page()
            layout.label(text="分镜导航（语音书）：")
            layout.label(text="当前: " + (_current.id if _current else "(无)"))
            layout.label(text="共 " + str(len(_pages)) + " 页")
            layout.separator()
            row = layout.row()
            row.operator("screen.spiraloid_3d_comic_first_panel", icon="TRIA_UP")
            row.operator("screen.spiraloid_3d_comic_previous_panel", icon="TRIA_LEFT", text="")
            row.operator("screen.spiraloid_3d_comic_next_panel", icon="TRIA_RIGHT", text="")
            row.operator("screen.spiraloid_3d_comic_last_panel", icon="TRIA_DOWN")
            layout.separator()
            layout.operator("screen.spiraloid_3d_comic_new_panel", text="新建分镜", icon="FILE_BLANK")
            layout.separator()
            return

        if material_swatch_object:
            layout.label(text="分镜导航：")'''))

# 应用所有替换
ok = 0
fail = 0
for old, new in replacements:
    if old in c:
        c = c.replace(old, new, 1)
        ok += 1
        print("[OK]", old.split("\n")[0][:60])
    else:
        fail += 1
        print("[FAIL]", old.split("\n")[0][:60])

with io.open(P, "w", encoding="utf-8") as f:
    f.write(c)

print()
print("成功:", ok, "失败:", fail)