import bpy

# 永久固定逻辑画布基准尺寸
CANVAS_BASE_W = 1920
CANVAS_BASE_H = 1080


def _redraw_scene(scene, context=None):
    """触发所有 IMAGE_EDITOR 区域重绘，用于属性变更后刷新画布。"""
    if context is None:
        context = bpy.context
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()


def _on_layout_update(self, context):
    _redraw_scene(context.scene, context)


def _on_padding_update(self, context):
    _redraw_scene(context.scene, context)


def _on_textbox_update(self, context):
    _redraw_scene(context.scene, context)


def _on_skin_update(self, context):
    _redraw_scene(context.scene, context)


class VOICEBOOK_PG_TextBox(bpy.types.PropertyGroup):
    """标题/正文文本框参数（逻辑坐标，左上原点）。

    注意：x/y/w/h 的默认值由根属性组在注册时按 V1 样例初始化
    （标题 0/40/710/80，正文 0/140/710/800）。
    """
    x: bpy.props.IntProperty(
        name="X", default=0, min=0, max=CANVAS_BASE_W,
        update=_on_textbox_update,
    )
    y: bpy.props.IntProperty(
        name="Y", default=0, min=0, max=CANVAS_BASE_H,
        update=_on_textbox_update,
    )
    w: bpy.props.IntProperty(
        name="Width", default=710, min=20, max=CANVAS_BASE_W,
        update=_on_textbox_update,
    )
    h: bpy.props.IntProperty(
        name="Height", default=80, min=20, max=CANVAS_BASE_H,
        update=_on_textbox_update,
    )
    text: bpy.props.StringProperty(
        name="Text", default="",
        update=_on_textbox_update,
    )
    line_height: bpy.props.IntProperty(
        name="Line Height", default=48, min=16, max=400,
        update=_on_textbox_update,
    )
    font_size: bpy.props.IntProperty(
        name="Font Size", default=36, min=8, max=400,
        update=_on_textbox_update,
    )


class VOICEBOOK_PG_Properties(bpy.types.PropertyGroup):
    """VoiceBook 排版根属性组，挂载到 Scene"""

    # ---- 版式设置 ----
    layout_type: bpy.props.EnumProperty(
        name="Layout Type",
        items=[
            ('FULL', "Full Screen", "全屏模式"),
            ('LEFT_RIGHT', "Left Text Right Scene", "左文右图"),
            ('TOP_BOTTOM', "Top Text Bottom Scene", "上文下图"),
        ],
        default='LEFT_RIGHT',
        update=_on_layout_update,
    )
    divider_position: bpy.props.IntProperty(
        name="Divider Position",
        description="分割线位置（逻辑像素，15%~85% 范围限制）",
        default=760, min=0, max=CANVAS_BASE_W,
        update=_on_layout_update,
    )
    base_image_path: bpy.props.StringProperty(
        name="Base Image",
        subtype='FILE_PATH',
        default="",
        update=_on_layout_update,
    )

    # ---- 文字区域内边距 ----
    padding_top: bpy.props.IntProperty(
        name="Padding Top", default=14, min=0, max=200,
        update=_on_padding_update,
    )
    padding_bottom: bpy.props.IntProperty(
        name="Padding Bottom", default=14, min=0, max=200,
        update=_on_padding_update,
    )
    padding_left: bpy.props.IntProperty(
        name="Padding Left", default=14, min=0, max=200,
        update=_on_padding_update,
    )
    padding_right: bpy.props.IntProperty(
        name="Padding Right", default=14, min=0, max=200,
        update=_on_padding_update,
    )

    # ---- 文本框 ----
    title_box: bpy.props.PointerProperty(type=VOICEBOOK_PG_TextBox)
    body_box: bpy.props.PointerProperty(type=VOICEBOOK_PG_TextBox)

    # ---- 声音按钮 ----
    audio_path: bpy.props.StringProperty(
        name="Audio Path",
        subtype='FILE_PATH',
        default="",
        update=_on_layout_update,
    )

    # ---- 皮肤（UI 显示风格）----
    ui_skin: bpy.props.BoolProperty(
        name="Enable Skin",
        description="启用 UI 皮肤（在画布上绘制皮肤样式）",
        default=True,
        update=_on_skin_update,
    )
    skin_type: bpy.props.EnumProperty(
        name="Skin Type",
        items=[
            ('NONE', "None", "无皮肤"),
            ('TOP', "Top", "顶部条"),
            ('RIGHT', "Right", "右侧条"),
        ],
        default='NONE',
        update=_on_skin_update,
    )

    # ---- 页面标识 ----
    page_id: bpy.props.StringProperty(
        name="Page ID",
        default="p.0000.w1h1",
    )

    # ---- 运行时状态（不导出）----
    is_editing: bpy.props.BoolProperty(default=False)
    boxes_initialized: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    selection: bpy.props.EnumProperty(
        name="Selection",
        items=[
            ('NONE', "None", "无选中"),
            ('DIVIDER', "Divider", "分割线"),
            ('TITLE', "Title Box", "标题文本框"),
            ('BODY', "Body Box", "正文文本框"),
            ('AUDIO', "Audio Button", "声音按钮"),
        ],
        default='NONE',
    )


def ensure_defaults(props):
    """按 V1 样例初始化两个文本框的差异化默认值（每个 Scene 仅执行一次）。"""
    if props.boxes_initialized:
        return
    title = props.title_box
    title.x, title.y, title.w, title.h = 0, 40, 710, 80
    title.font_size = 56
    title.line_height = 80
    body = props.body_box
    body.x, body.y, body.w, body.h = 0, 140, 710, 800
    body.font_size = 36
    body.line_height = 48
    props.boxes_initialized = True


def register():
    bpy.utils.register_class(VOICEBOOK_PG_TextBox)
    bpy.utils.register_class(VOICEBOOK_PG_Properties)
    bpy.types.Scene.voicebook_layout = bpy.props.PointerProperty(
        type=VOICEBOOK_PG_Properties
    )


def unregister():
    try:
        del bpy.types.Scene.voicebook_layout
    except AttributeError:
        pass
    for cls in reversed((VOICEBOOK_PG_Properties, VOICEBOOK_PG_TextBox)):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
