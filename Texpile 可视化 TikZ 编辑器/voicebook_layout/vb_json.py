"""VoiceBook JSON 导入导出（V1 格式冻结）+ 页面截图。

导出结构（字段名/层级/类型严格固定，无运行时字段）：
{
  "pageId": "p.0000.w1h1",
  "canvas": {"width": 1920, "height": 1080},
  "layout": {
    "type": "left-right",
    "textArea":  {"x": int, "y": int, "w": int, "h": int},
    "sceneArea": {...},
    "dividerPosition": int
  },
  "textBoxes": {
    "title": {"x": int, "y": int, "w": int, "h": int, "text": str},
    "body":  {...}
  },
  "audioButton": {"x": int, "y": int, "w": int, "h": int, "align": "text-bottom-right"}
}
"""

import json
import os
import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import vb_coords
from .vb_props import CANVAS_BASE_W, CANVAS_BASE_H, ensure_defaults

LAYOUT_TYPE_TO_JSON = {
    'FULL': 'full',
    'LEFT_RIGHT': 'left-right',
    'TOP_BOTTOM': 'top-bottom',
}
LAYOUT_TYPE_FROM_JSON = {v: k for k, v in LAYOUT_TYPE_TO_JSON.items()}

AUDIO_BUTTON_SIZE = 48
AUDIO_BUTTON_MARGIN = 16
AUDIO_ALIGN = "text-bottom-right"


# ----------------------------------------------------------------------
# 纯数据映射
# ----------------------------------------------------------------------

def _rect_dict(x, y, w, h):
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}


def _box_dict(box):
    return {
        "x": int(box.x),
        "y": int(box.y),
        "w": int(box.w),
        "h": int(box.h),
        "text": str(box.text),
    }


def export_data(props):
    """PropertyGroup → V1 dict（纯数据，无副作用）。"""
    ensure_defaults(props)

    text_area, scene_area, dp = vb_coords.compute_layout_areas(
        props.layout_type,
        props.divider_position,
        props.padding_left, props.padding_right,
        props.padding_top, props.padding_bottom,
    )

    if props.layout_type == 'FULL' or dp is None:
        divider_position = 0
        scene_rect = _rect_dict(0, 0, 0, 0)
    else:
        divider_position = int(dp)
        scene_rect = _rect_dict(*scene_area)

    # 声音按钮：吸附在文字区域右下角
    tx, ty, tw, th = text_area
    audio_x = tx + tw - AUDIO_BUTTON_SIZE - AUDIO_BUTTON_MARGIN
    audio_y = ty + th - AUDIO_BUTTON_SIZE - AUDIO_BUTTON_MARGIN

    return {
        "pageId": str(props.page_id),
        "canvas": {"width": CANVAS_BASE_W, "height": CANVAS_BASE_H},
        "layout": {
            "type": LAYOUT_TYPE_TO_JSON[props.layout_type],
            "textArea": _rect_dict(*text_area),
            "sceneArea": scene_rect,
            "dividerPosition": divider_position,
        },
        "textBoxes": {
            "title": _box_dict(props.title_box),
            "body": _box_dict(props.body_box),
        },
        "audioButton": {
            "x": int(audio_x),
            "y": int(audio_y),
            "w": AUDIO_BUTTON_SIZE,
            "h": AUDIO_BUTTON_SIZE,
            "align": AUDIO_ALIGN,
        },
    }


# ----------------------------------------------------------------------
# 校验导入
# ----------------------------------------------------------------------

def _as_int(value, field_path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"字段 {field_path} 必须是数值")
    return int(round(value))


def _as_rect(data, field_path):
    if not isinstance(data, dict):
        raise ValueError(f"字段 {field_path} 必须是对象")
    rect = {}
    for key in ("x", "y", "w", "h"):
        if key not in data:
            raise ValueError(f"字段 {field_path}.{key} 缺失")
        rect[key] = _as_int(data[key], f"{field_path}.{key}")
    if rect["w"] < 0 or rect["h"] < 0:
        raise ValueError(f"字段 {field_path} 宽高不能为负")
    return rect["x"], rect["y"], rect["w"], rect["h"]


def import_data(props, data):
    """V1 dict → PropertyGroup。校验失败抛 ValueError，state 不变更。

    调用方应先自行 json.load，再调用本函数。
    """
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象")

    # canvas
    canvas = data.get("canvas")
    if not isinstance(canvas, dict):
        raise ValueError("canvas 字段缺失或格式错误")
    cw = _as_int(canvas.get("width"), "canvas.width")
    ch = _as_int(canvas.get("height"), "canvas.height")
    if cw != CANVAS_BASE_W or ch != CANVAS_BASE_H:
        raise ValueError(f"仅支持 {CANVAS_BASE_W}×{CANVAS_BASE_H} 画布，收到 {cw}×{ch}")

    # layout
    layout = data.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("layout 字段缺失或格式错误")
    type_str = layout.get("type")
    if type_str not in LAYOUT_TYPE_FROM_JSON:
        raise ValueError(f"未知版式类型: {type_str!r}")
    layout_type = LAYOUT_TYPE_FROM_JSON[type_str]

    ta = _as_rect(layout.get("textArea"), "layout.textArea")
    sa_raw = layout.get("sceneArea")
    if not isinstance(sa_raw, dict):
        raise ValueError("layout.sceneArea 字段缺失或格式错误")
    divider = _as_int(layout.get("dividerPosition"), "layout.dividerPosition")

    # textBoxes
    boxes_raw = data.get("textBoxes")
    if not isinstance(boxes_raw, dict):
        raise ValueError("textBoxes 字段缺失或格式错误")

    def _as_box(rect_data, path):
        x, y, w, h = _as_rect(rect_data, path)
        text = rect_data.get("text", "")
        if not isinstance(text, str):
            raise ValueError(f"{path}.text 必须是字符串")
        if w < 20 or h < 20:
            raise ValueError(f"{path} 宽高不能小于 20")
        if x < 0 or y < 0 or x + w > CANVAS_BASE_W or y + h > CANVAS_BASE_H:
            raise ValueError(f"{path} 超出画布范围")
        return x, y, w, h, text

    if "title" not in boxes_raw or "body" not in boxes_raw:
        raise ValueError("textBoxes 必须包含 title 和 body")
    title_vals = _as_box(boxes_raw["title"], "textBoxes.title")
    body_vals = _as_box(boxes_raw["body"], "textBoxes.body")

    # audioButton（位置由文字区派生，仅校验结构存在）
    audio_raw = data.get("audioButton")
    if not isinstance(audio_raw, dict):
        raise ValueError("audioButton 字段缺失或格式错误")
    for key in ("x", "y", "w", "h", "align"):
        if key not in audio_raw:
            raise ValueError(f"audioButton.{key} 缺失")

    # ---- 校验全部通过后一次性提交 ----
    tx, ty, tw, th = ta
    if tw < 0 or th < 0 or tx < 0 or ty < 0:
        raise ValueError("textArea 坐标非法")
    if tx + tw > CANVAS_BASE_W or ty + th > CANVAS_BASE_H:
        raise ValueError("textArea 超出画布范围")

    props.layout_type = layout_type

    # 由区域几何反推分割线与内边距
    if layout_type == 'FULL':
        props.divider_position = 0
        props.padding_left = tx
        props.padding_top = ty
        props.padding_right = CANVAS_BASE_W - (tx + tw)
        props.padding_bottom = CANVAS_BASE_H - (ty + th)
    elif layout_type == 'LEFT_RIGHT':
        if not (0 <= divider <= CANVAS_BASE_W):
            raise ValueError("dividerPosition 超出画布宽度")
        props.divider_position = divider
        props.padding_left = tx
        props.padding_top = ty
        props.padding_right = divider - (tx + tw)
        props.padding_bottom = CANVAS_BASE_H - (ty + th)
    else:  # TOP_BOTTOM
        if not (0 <= divider <= CANVAS_BASE_H):
            raise ValueError("dividerPosition 超出画布高度")
        props.divider_position = divider
        props.padding_left = tx
        props.padding_top = ty
        props.padding_right = CANVAS_BASE_W - (tx + tw)
        props.padding_bottom = divider - (ty + th)

    x, y, w, h, text = title_vals
    tb = props.title_box
    tb.x, tb.y, tb.w, tb.h, tb.text = x, y, w, h, text
    x, y, w, h, text = body_vals
    bb = props.body_box
    bb.x, bb.y, bb.w, bb.h, bb.text = x, y, w, h, text

    page_id = data.get("pageId")
    if isinstance(page_id, str) and page_id:
        props.page_id = page_id

    props.selection = 'NONE'
    props.boxes_initialized = True


# ----------------------------------------------------------------------
# 操作符
# ----------------------------------------------------------------------

class VOICEBOOK_OT_export_json(bpy.types.Operator, ExportHelper):
    bl_idname = "voicebook.export_json"
    bl_label = "导出 VoiceBook JSON"
    bl_description = "导出 V1 排版 JSON（2 空格缩进）"
    bl_options = {'REGISTER'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = context.scene.voicebook_layout.page_id + ".json"
        return super().invoke(context, event)

    def execute(self, context):
        props = context.scene.voicebook_layout
        data = export_data(props)
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.report({'ERROR'}, f"写入失败: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已导出: {self.filepath}")
        return {'FINISHED'}


class VOICEBOOK_OT_import_json(bpy.types.Operator, ImportHelper):
    bl_idname = "voicebook.import_json"
    bl_label = "导入 VoiceBook JSON"
    bl_description = "导入 V1 排版 JSON，校验通过后覆盖当前排版"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        props = context.scene.voicebook_layout
        try:
            with open(self.filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.report({'ERROR'}, f"读取/解析失败: {e}")
            return {'CANCELLED'}

        try:
            import_data(props, data)
        except ValueError as e:
            self.report({'ERROR'}, f"JSON 校验失败，已取消导入: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已导入: {os.path.basename(self.filepath)}")
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()
        return {'FINISHED'}


class VOICEBOOK_OT_capture_screenshot(bpy.types.Operator, ExportHelper):
    bl_idname = "voicebook.capture_screenshot"
    bl_label = "获取页面截图"
    bl_description = "将图像编辑器当前图像保存为 PNG，并作为排版底图加载"
    bl_options = {'REGISTER'}

    filename_ext = ".png"
    filter_glob: bpy.props.StringProperty(default="*.png", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
            and context.space_data.image is not None
        )

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = context.scene.voicebook_layout.page_id + ".png"
        return super().invoke(context, event)

    def execute(self, context):
        image = context.space_data.image
        if image is None:
            self.report({'ERROR'}, "图像编辑器中没有打开的图像")
            return {'CANCELLED'}
        try:
            image.save_render(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"截图保存失败: {e}")
            return {'CANCELLED'}
        context.scene.voicebook_layout.base_image_path = self.filepath
        self.report({'INFO'}, f"页面截图已保存并设为底图: {self.filepath}")
        return {'FINISHED'}


classes = [
    VOICEBOOK_OT_export_json,
    VOICEBOOK_OT_import_json,
    VOICEBOOK_OT_capture_screenshot,
]
