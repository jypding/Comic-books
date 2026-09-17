# -*- coding: utf-8 -*-
import io, re

P = r"C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\3DComicToolkit.py"

with io.open(P, "r", encoding="utf-8") as f:
    c = f.read()

backup = P + ".bak_nav_fix"
with io.open(backup, "w", encoding="utf-8") as f:
    f.write(c)
print("已备份:", backup)

# ========== 1. first_panel ==========
pat1 = re.compile(
    r'(class BR_OT_first_panel_scene\(bpy\.types\.Operator\):.*?def execute\(self, context\):\s*)'
    r'bpy\.context\.window\.scene = bpy\.data\.scenes\[0\]',
    re.DOTALL
)
new1 = r'\1' + '''from .core.page_registry import PageRegistry
        registry = PageRegistry(context)
        if registry.mode == "language":
            pages = registry.list_pages()
            if pages:
                registry.load_page(pages[0])
            return {'FINISHED'}
        bpy.context.window.scene = bpy.data.scenes[0]'''
c, n1 = pat1.subn(new1, c)
print("[1] first_panel:", "OK" if n1 else "FAIL")

# ========== 2. last_panel ==========
pat2 = re.compile(
    r'(class BR_OT_last_panel_scene\(bpy\.types\.Operator\):.*?def execute\(self, context\):\s*)'
    r'totalScenes = len\(bpy\.data\.scenes\) - 1\s*\n\s*'
    r'bpy\.context\.window\.scene = bpy\.data\.scenes\[totalScenes\]',
    re.DOTALL
)
new2 = r'\1' + '''from .core.page_registry import PageRegistry
        registry = PageRegistry(context)
        if registry.mode == "language":
            pages = registry.list_pages()
            if pages:
                registry.load_page(pages[-1])
            return {'FINISHED'}
        totalScenes = len(bpy.data.scenes) - 1
        bpy.context.window.scene = bpy.data.scenes[totalScenes]'''
c, n2 = pat2.subn(new2, c)
print("[2] last_panel:", "OK" if n2 else "FAIL")

# ========== 3. 面板 draw: 在 `if material_swatch_object:` 前插入 Provider 分支 ==========
# 找到 BR_MT_3d_comic_panels 类里的 `if material_swatch_object:` 那一行
# 用 "material_swatch_object = getCurrentMaterialSwatch()" 作为锚点
anchor = "material_swatch_object = getCurrentMaterialSwatch()"
if anchor in c:
    inject = anchor + '''

        # === 语音书走 Provider ===
        try:
            from .core.page_registry import PageRegistry
            _registry = PageRegistry(context)
            if _registry.mode == "language":
                _pages = _registry.list_pages()
                _current = _registry.get_current_page()
                layout.label(text="\\u5206\\u955c\\u5bfc\\u822a")
                layout.label(text="\\u5f53\\u524d: " + (_current.id if _current else "(none)"))
                layout.label(text="\\u5171 " + str(len(_pages)) + " \\u9875")
                layout.separator()
                row = layout.row()
                row.operator("screen.spiraloid_3d_comic_first_panel", icon="TRIA_UP")
                row.operator("screen.spiraloid_3d_comic_previous_panel", icon="TRIA_LEFT", text="")
                row.operator("screen.spiraloid_3d_comic_next_panel", icon="TRIA_RIGHT", text="")
                row.operator("screen.spiraloid_3d_comic_last_panel", icon="TRIA_DOWN")
                layout.separator()
                layout.operator("screen.spiraloid_3d_comic_new_panel", text="New", icon="FILE_BLANK")
                layout.separator()
                return
        except Exception as _e:
            print("[PageRegistry draw]", _e)'''
    c = c.replace(anchor, inject, 1)
    print("[3] panel draw: OK")
else:
    print("[3] panel draw: FAIL")

with io.open(P, "w", encoding="utf-8") as f:
    f.write(c)

print("完成")