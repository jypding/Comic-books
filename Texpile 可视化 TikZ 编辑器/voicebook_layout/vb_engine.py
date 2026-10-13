"""VoiceBook 排版引擎：draw_handler 持有者 + 画布绘制 + 拖拽状态机。"""

import bpy
import gpu
from . import vb_coords
from . import vb_draw
from .vb_props import CANVAS_BASE_W, CANVAS_BASE_H

# 命中容差（屏幕像素）
HIT_RADIUS = 14
HANDLE_SIZE = 6


class VoiceBookEngine:
    _active_instance = None

    def __init__(self, context):
        self.context = context
        self._draw_handler = None
        self.should_exit = False

        # 拖拽状态
        self._drag_mode = 'NONE'  # NONE/DIVIDER/TITLE_MOVE/TITLE_RESIZE/BODY_MOVE/BODY_RESIZE
        self._drag_start_pos = (0, 0)
        self._drag_start_val = None

        VoiceBookEngine._active_instance = self
        self._start_drawing()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _start_drawing(self):
        def draw_callback():
            try:
                self._draw()
            except Exception as e:
                print(f"[VoiceBook] 绘制错误: {e}")

        self._draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(
            draw_callback, (), 'WINDOW', 'POST_PIXEL'
        )

    def cleanup(self):
        self.should_exit = True
        if self._draw_handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(
                self._draw_handler, 'WINDOW'
            )
            self._draw_handler = None
        VoiceBookEngine._active_instance = None

    # ------------------------------------------------------------------
    # 属性快捷访问
    # ------------------------------------------------------------------

    def _get_props(self):
        return self.context.scene.voicebook_layout

    # ------------------------------------------------------------------
    # 主绘制（底图由 Blender 原生显示，此处只画排版叠加元素）
    # ------------------------------------------------------------------

    def _draw(self):
        rect = vb_coords.get_image_rect(self.context)
        if rect is None:
            return

        props = self._get_props()

        # 启用 alpha 混合
        gpu.state.blend_set('ALPHA')

        # 1. 文字区域虚线框
        self._draw_text_area(rect, props)

        # 2. 分割线
        self._draw_divider(rect, props)

        # 3. 文本框
        self._draw_text_boxes(rect, props)

        # 4. 声音按钮
        self._draw_audio_button(rect, props)

        # 5. HUD 提示
        self._draw_hud(rect, props)

        gpu.state.blend_set('NONE')

    def _draw_text_area(self, rect, props):
        text_area, _, _ = vb_coords.compute_layout_areas(
            props.layout_type,
            props.divider_position,
            props.padding_left, props.padding_right,
            props.padding_top, props.padding_bottom,
        )
        tx, ty, tw, th = text_area

        # 转换为屏幕坐标
        sx0, sy0 = vb_coords.logical_to_screen(rect, tx, ty)
        sx1, sy1 = vb_coords.logical_to_screen(rect, tx + tw, ty + th)

        # 虚线框
        vb_draw.draw_dashed_rect(
            (0.2, 0.6, 1.0, 0.8), sx0, sy1, sx1, sy0
        )

    def _draw_divider(self, rect, props):
        if props.layout_type == 'FULL':
            return

        _, _, dp = vb_coords.compute_layout_areas(
            props.layout_type,
            props.divider_position,
            props.padding_left, props.padding_right,
            props.padding_top, props.padding_bottom,
        )
        if dp is None:
            return

        ox, oy, disp_w, disp_h, img_w, img_h = rect

        if props.layout_type == 'LEFT_RIGHT':
            sx, _ = vb_coords.logical_to_screen(rect, dp, 0)
            y0, y1 = oy, oy + disp_h
            color = (1.0, 0.4, 0.4, 0.9) if props.selection == 'DIVIDER' else (1.0, 0.2, 0.2, 0.7)
            vb_draw.draw_line(color, sx, y0, sx, y1)
            # 上下手柄
            vb_draw.draw_handle(color, sx, y0, HANDLE_SIZE)
            vb_draw.draw_handle(color, sx, y1, HANDLE_SIZE)
        else:
            _, sy = vb_coords.logical_to_screen(rect, 0, dp)
            x0, x1 = ox, ox + disp_w
            color = (1.0, 0.4, 0.4, 0.9) if props.selection == 'DIVIDER' else (1.0, 0.2, 0.2, 0.7)
            vb_draw.draw_line(color, x0, sy, x1, sy)
            vb_draw.draw_handle(color, x0, sy, HANDLE_SIZE)
            vb_draw.draw_handle(color, x1, sy, HANDLE_SIZE)

    def _draw_text_boxes(self, rect, props):
        self._draw_single_text_box(rect, props.title_box, props, 'TITLE')
        self._draw_single_text_box(rect, props.body_box, props, 'BODY')

    def _draw_single_text_box(self, rect, box, props, box_id):
        bx, by, bw, bh = box.x, box.y, box.w, box.h
        text = box.text
        font_size = box.font_size
        line_height = box.line_height

        # 屏幕坐标
        sx0, sy0 = vb_coords.logical_to_screen(rect, bx, by)
        sx1, sy1 = vb_coords.logical_to_screen(rect, bx + bw, by + bh)

        # 背景（半透明）
        is_selected = (props.selection == box_id)
        bg_alpha = 0.15 if is_selected else 0.08
        border_color = (0.2, 0.6, 1.0, 0.9) if is_selected else (0.5, 0.5, 0.5, 0.5)
        vb_draw.draw_rect((0.2, 0.2, 0.2, bg_alpha), sx0, sy1, sx1, sy0)
        vb_draw.draw_rect_outline(border_color, sx0, sy1, sx1, sy0)

        # 文字内容
        if text:
            scale = (sx1 - sx0) / bw if bw > 0 else 1.0
            disp_font_size = max(8, int(font_size * scale))
            disp_line_height = max(12, int(line_height * scale))
            text_color = (0.95, 0.95, 0.95, 1.0)
            # 从顶部开始绘制（y 向下）
            start_y = sy0 - disp_font_size
            vb_draw.draw_text_block(
                text, sx0 + 4, start_y,
                sx1 - sx0 - 8,
                disp_font_size, disp_line_height,
                text_color, 'LEFT'
            )

        # 右侧宽度拖拽手柄
        if is_selected:
            mid_y = (sy0 + sy1) / 2
            vb_draw.draw_handle(border_color, sx1, mid_y, HANDLE_SIZE)

    def _draw_audio_button(self, rect, props):
        # 固定吸附在文字区域右下角
        text_area, _, _ = vb_coords.compute_layout_areas(
            props.layout_type,
            props.divider_position,
            props.padding_left, props.padding_right,
            props.padding_top, props.padding_bottom,
        )
        tx, ty, tw, th = text_area

        # 按钮尺寸 48×48，右下角对齐，留 16px 边距
        btn_size = 48
        margin = 16
        ax = tx + tw - btn_size - margin
        ay = ty + th - btn_size - margin

        sx0, sy0 = vb_coords.logical_to_screen(rect, ax, ay)
        sx1, sy1 = vb_coords.logical_to_screen(rect, ax + btn_size, ay + btn_size)

        is_selected = (props.selection == 'AUDIO')
        bg_color = (0.2, 0.8, 0.3, 0.9) if is_selected else (0.15, 0.6, 0.25, 0.8)
        vb_draw.draw_rect(bg_color, sx0, sy1, sx1, sy0)
        vb_draw.draw_rect_outline((1.0, 1.0, 1.0, 0.8), sx0, sy1, sx1, sy0)

        # 绘制音符符号
        cx = (sx0 + sx1) / 2
        cy = (sy0 + sy1) / 2
        vb_draw.draw_text("♪", cx, cy - 8, 20, (1.0, 1.0, 1.0, 1.0), 'CENTER')

    def _draw_hud(self, rect, props):
        ox, oy, disp_w, disp_h, img_w, img_h = rect
        hints = []
        if props.layout_type != 'FULL':
            pct = props.divider_position / (CANVAS_BASE_W if props.layout_type == 'LEFT_RIGHT' else CANVAS_BASE_H)
            hints.append(f"分割: {pct:.0%}")
        if props.selection != 'NONE':
            hints.append(f"选中: {props.selection}")
        hints.append("Esc 退出")

        hint_text = " | ".join(hints)
        vb_draw.draw_text(
            hint_text, ox + 8, oy - 24, 14,
            (0.8, 0.8, 0.8, 0.9), 'LEFT'
        )

    # ------------------------------------------------------------------
    # 命中测试与拖拽
    # ------------------------------------------------------------------

    def handle_mouse_press(self, event):
        mx, my = event.mouse_region_x, event.mouse_region_y
        rect = vb_coords.get_image_rect(self.context)
        if rect is None:
            return False

        props = self._get_props()
        self._drag_start_pos = (mx, my)

        # 1. 分割线
        if props.layout_type != 'FULL':
            _, _, dp = vb_coords.compute_layout_areas(
                props.layout_type,
                props.divider_position,
                props.padding_left, props.padding_right,
                props.padding_top, props.padding_bottom,
            )
            if dp is not None:
                if props.layout_type == 'LEFT_RIGHT':
                    sx, _ = vb_coords.logical_to_screen(rect, dp, 0)
                    if abs(mx - sx) <= HIT_RADIUS:
                        self._drag_mode = 'DIVIDER'
                        self._drag_start_val = props.divider_position
                        props.selection = 'DIVIDER'
                        return True
                else:
                    _, sy = vb_coords.logical_to_screen(rect, 0, dp)
                    if abs(my - sy) <= HIT_RADIUS:
                        self._drag_mode = 'DIVIDER'
                        self._drag_start_val = props.divider_position
                        props.selection = 'DIVIDER'
                        return True

        # 2. 文本框（先检测手柄，再检测内部）
        for box_id, box in (('TITLE', props.title_box), ('BODY', props.body_box)):
            sx0, sy0 = vb_coords.logical_to_screen(rect, box.x, box.y)
            sx1, sy1 = vb_coords.logical_to_screen(rect, box.x + box.w, box.y + box.h)

            # 右侧手柄
            if props.selection == box_id:
                mid_y = (sy0 + sy1) / 2
                if abs(mx - sx1) <= HIT_RADIUS and abs(my - mid_y) <= HIT_RADIUS:
                    self._drag_mode = f'{box_id}_RESIZE'
                    self._drag_start_val = box.w
                    return True

            # 内部
            if vb_coords.point_in_rect(mx, my, sx0, sy1, sx1 - sx0, sy0 - sy1):
                self._drag_mode = f'{box_id}_MOVE'
                self._drag_start_val = (box.x, box.y)
                props.selection = box_id
                return True

        # 3. 声音按钮
        text_area, _, _ = vb_coords.compute_layout_areas(
            props.layout_type,
            props.divider_position,
            props.padding_left, props.padding_right,
            props.padding_top, props.padding_bottom,
        )
        tx, ty, tw, th = text_area
        btn_size = 48
        margin = 16
        ax = tx + tw - btn_size - margin
        ay = ty + th - btn_size - margin
        sx0, sy0 = vb_coords.logical_to_screen(rect, ax, ay)
        sx1, sy1 = vb_coords.logical_to_screen(rect, ax + btn_size, ay + btn_size)
        if vb_coords.point_in_rect(mx, my, sx0, sy1, sx1 - sx0, sy0 - sy1):
            props.selection = 'AUDIO'
            return True

        # 未命中
        props.selection = 'NONE'
        return False

    def handle_mouse_move(self, event):
        if self._drag_mode == 'NONE':
            return False

        mx, my = event.mouse_region_x, event.mouse_region_y
        rect = vb_coords.get_image_rect(self.context)
        if rect is None:
            return False

        props = self._get_props()
        dx = mx - self._drag_start_pos[0]
        dy = my - self._drag_start_pos[1]

        # 屏幕位移 → 逻辑位移
        _, _, disp_w, disp_h, img_w, img_h = rect
        scale_x = img_w / disp_w if disp_w > 0 else 1.0
        scale_y = img_h / disp_h if disp_h > 0 else 1.0
        ldx = dx * scale_x
        ldy = -dy * scale_y  # 屏幕 y 向上，逻辑 y 向下

        if self._drag_mode == 'DIVIDER':
            if props.layout_type == 'LEFT_RIGHT':
                new_pos = self._drag_start_val + ldx
            else:
                new_pos = self._drag_start_val + ldy
            max_val = CANVAS_BASE_W if props.layout_type == 'LEFT_RIGHT' else CANVAS_BASE_H
            min_val = int(max_val * 0.15)
            max_val = int(max_val * 0.85)
            props.divider_position = int(max(min_val, min(max_val, new_pos)))
            return True

        if self._drag_mode.endswith('_MOVE'):
            box_id = self._drag_mode.split('_')[0]
            box = props.title_box if box_id == 'TITLE' else props.body_box
            ox, oy = self._drag_start_val
            new_x = ox + ldx
            new_y = oy + ldy
            new_x, new_y = vb_coords.clamp_logical(new_x, new_y, box.w, box.h)
            box.x = new_x
            box.y = new_y
            return True

        if self._drag_mode.endswith('_RESIZE'):
            box_id = self._drag_mode.split('_')[0]
            box = props.title_box if box_id == 'TITLE' else props.body_box
            new_w = self._drag_start_val + ldx
            new_w = max(20, min(CANVAS_BASE_W - box.x, new_w))
            box.w = int(new_w)
            return True

        return False

    def handle_mouse_release(self, event):
        self._drag_mode = 'NONE'
        self._drag_start_val = None
