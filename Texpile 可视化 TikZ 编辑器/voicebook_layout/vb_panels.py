"""VoiceBook N 面板：根面板 + 4 个可折叠子面板（页面/布局/文本框/导出）。"""

import bpy
from .vb_modal import VOICEBOOK_OT_layout_start, VOICEBOOK_OT_layout_stop
from .vb_props import ensure_defaults


class VOICEBOOK_PT_Panel(bpy.types.Panel):
    bl_label = "VoiceBook 排版"
    bl_idname = "VOICEBOOK_PT_Panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "VoiceBook排版"

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.voicebook_layout
        ensure_defaults(props)

        if context.space_data.image is None:
            layout.label(text="请先打开或新建一张图像", icon='INFO')
            layout.operator(
                "voicebook.new_canvas",
                text="新建 1920×1080 画布",
                icon='FILE_NEW',
            )
            return

        if not props.is_editing:
            layout.operator(
                "voicebook.layout_start",
                text="开始排版",
                icon='PLAY',
            )
        else:
            layout.operator(
                "voicebook.layout_stop",
                text="结束排版",
                icon='X',
            )
            layout.label(text="排版模式运行中", icon='INFO')


class VOICEBOOK_PT_Page(bpy.types.Panel):
    bl_label = "页面"
    bl_idname = "VOICEBOOK_PT_Page"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "VoiceBook排版"
    bl_parent_id = "VOICEBOOK_PT_Panel"

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.voicebook_layout

        layout.prop(props, "page_id", text="页面 ID")
        layout.prop(props, "audio_path", text="音频路径")

        row = layout.row(align=True)
        row.operator("voicebook.load_base_image", text="加载 PNG", icon='IMAGE_DATA')
        row.operator("voicebook.new_canvas", text="新建画布", icon='FILE_NEW')


class VOICEBOOK_PT_Layout(bpy.types.Panel):
    bl_label = "布局"
    bl_idname = "VOICEBOOK_PT_Layout"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "VoiceBook排版"
    bl_parent_id = "VOICEBOOK_PT_Panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.voicebook_layout

        layout.prop(props, "layout_type", text="版式")

        if props.layout_type != 'FULL':
            row = layout.row(align=True)
            row.prop(props, "divider_position", text="分割线")
            sub = row.row(align=True)
            sub.operator("voicebook.divider_step", text="-5%").step = -0.05
            sub.operator("voicebook.divider_step", text="-1%").step = -0.01
            sub.operator("voicebook.divider_step", text="+1%").step = 0.01
            sub.operator("voicebook.divider_step", text="+5%").step = 0.05

        col = layout.column(align=True)
        col.prop(props, "padding_top", text="上边距")
        col.prop(props, "padding_bottom", text="下边距")
        col.prop(props, "padding_left", text="左边距")
        col.prop(props, "padding_right", text="右边距")


class VOICEBOOK_PT_TextBoxes(bpy.types.Panel):
    bl_label = "文本框"
    bl_idname = "VOICEBOOK_PT_TextBoxes"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "VoiceBook排版"
    bl_parent_id = "VOICEBOOK_PT_Panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.voicebook_layout

        box = layout.box()
        box.label(text="标题", icon='FONT_DATA')
        col = box.column(align=True)
        col.prop(props.title_box, "x", text="X")
        col.prop(props.title_box, "y", text="Y")
        col.prop(props.title_box, "w", text="宽度")
        col.prop(props.title_box, "h", text="高度")
        col.prop(props.title_box, "font_size", text="字号")
        col.prop(props.title_box, "line_height", text="行高")
        box.prop(props.title_box, "text", text="内容")

        box = layout.box()
        box.label(text="正文", icon='TEXT')
        col = box.column(align=True)
        col.prop(props.body_box, "x", text="X")
        col.prop(props.body_box, "y", text="Y")
        col.prop(props.body_box, "w", text="宽度")
        col.prop(props.body_box, "h", text="高度")
        col.prop(props.body_box, "font_size", text="字号")
        col.prop(props.body_box, "line_height", text="行高")
        box.prop(props.body_box, "text", text="内容")

        box = layout.box()
        box.label(text="皮肤", icon='BRUSH')
        box.prop(props, "ui_skin", text="启用皮肤")
        box.prop(props, "skin_type", text="皮肤类型")


class VOICEBOOK_PT_Export(bpy.types.Panel):
    bl_label = "导出"
    bl_idname = "VOICEBOOK_PT_Export"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "VoiceBook排版"
    bl_parent_id = "VOICEBOOK_PT_Panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.operator("voicebook.export_json", text="导出 JSON", icon='EXPORT')
        row.operator("voicebook.import_json", text="导入 JSON", icon='IMPORT')


class VOICEBOOK_OT_divider_step(bpy.types.Operator):
    bl_idname = "voicebook.divider_step"
    bl_label = "调整分割线"
    bl_options = {'REGISTER', 'UNDO'}

    step: bpy.props.FloatProperty(default=0.01)

    @classmethod
    def poll(cls, context):
        return context.scene.voicebook_layout is not None

    def execute(self, context):
        props = context.scene.voicebook_layout
        if props.layout_type == 'LEFT_RIGHT':
            max_val = 1920
        else:
            max_val = 1080
        delta = int(max_val * self.step)
        new_pos = props.divider_position + delta
        min_val = int(max_val * 0.15)
        max_val = int(max_val * 0.85)
        props.divider_position = max(min_val, min(max_val, new_pos))
        return {'FINISHED'}


class VOICEBOOK_OT_load_base_image(bpy.types.Operator):
    bl_idname = "voicebook.load_base_image"
    bl_label = "加载底图"
    bl_description = "加载 PNG 并设为图像编辑器当前图像（由 Blender 原生显示）"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.png", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
        )

    def execute(self, context):
        try:
            img = bpy.data.images.load(self.filepath, check_existing=True)
        except Exception as e:
            self.report({'ERROR'}, f"加载图像失败: {e}")
            return {'CANCELLED'}
        context.space_data.image = img
        self.report({'INFO'}, f"底图已加载: {img.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class VOICEBOOK_OT_new_canvas(bpy.types.Operator):
    bl_idname = "voicebook.new_canvas"
    bl_label = "新建画布"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'IMAGE_EDITOR'

    def execute(self, context):
        img = bpy.data.images.new("VoiceBook_Canvas", 1920, 1080, alpha=True)
        context.space_data.image = img
        bpy.ops.ed.undo_push(message="新建 VoiceBook 画布")
        return {'FINISHED'}


classes = [
    VOICEBOOK_PT_Panel,
    VOICEBOOK_PT_Page,
    VOICEBOOK_PT_Layout,
    VOICEBOOK_PT_TextBoxes,
    VOICEBOOK_PT_Export,
    VOICEBOOK_OT_divider_step,
    VOICEBOOK_OT_load_base_image,
    VOICEBOOK_OT_new_canvas,
]
