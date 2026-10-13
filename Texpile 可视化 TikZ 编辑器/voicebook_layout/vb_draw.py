"""VoiceBook GPU 绘制原语（屏幕直绘，零离屏，零回读）。"""

import blf
import gpu
from gpu_extras.batch import batch_for_shader

# 内置 shader 缓存（不与其他插件共享）
_shader_cache = {}


def _get_uniform_shader():
    key = 'UNIFORM_COLOR'
    if key not in _shader_cache:
        _shader_cache[key] = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader_cache[key]


def clear_shader_cache():
    _shader_cache.clear()


def draw_rect(color, x0, y0, x1, y1):
    """绘制实心矩形（屏幕像素，左下原点）。"""
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRI_FAN', {
        "pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
    }).draw(shader)


def draw_rect_outline(color, x0, y0, x1, y1, width=1.0):
    """绘制矩形边框（屏幕像素）。"""
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'LINE_LOOP', {
        "pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
    }).draw(shader)


def draw_line(color, x0, y0, x1, y1):
    """绘制线段（屏幕像素）。"""
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'LINES', {
        "pos": [(x0, y0), (x1, y1)],
    }).draw(shader)


def draw_dashed_rect(color, x0, y0, x1, y1, dash_len=8, gap_len=4):
    """绘制虚线矩形（屏幕像素）。"""
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)

    def _dashed_line(sx, sy, ex, ey):
        dx = ex - sx
        dy = ey - sy
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0:
            return
        dx /= length
        dy /= length
        pos = []
        t = 0.0
        while t < length:
            seg_end = min(t + dash_len, length)
            pos.append((sx + dx * t, sy + dy * t))
            pos.append((sx + dx * seg_end, sy + dy * seg_end))
            t = seg_end + gap_len
        if pos:
            batch_for_shader(shader, 'LINES', {"pos": pos}).draw(shader)

    _dashed_line(x0, y0, x1, y0)  # 底边
    _dashed_line(x1, y0, x1, y1)  # 右边
    _dashed_line(x1, y1, x0, y1)  # 顶边
    _dashed_line(x0, y1, x0, y0)  # 左边


def draw_handle(color, cx, cy, size=5):
    """绘制方形控制点手柄（屏幕像素）。"""
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRI_FAN', {
        "pos": [
            (cx - size, cy - size),
            (cx + size, cy - size),
            (cx + size, cy + size),
            (cx - size, cy + size),
        ],
    }).draw(shader)


def draw_circle(color, cx, cy, radius, segments=16):
    """绘制圆形（屏幕像素）。"""
    import math
    shader = _get_uniform_shader()
    shader.bind()
    shader.uniform_float("color", color)
    verts = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        verts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    batch_for_shader(shader, 'TRI_FAN', {"pos": verts}).draw(shader)


def draw_text(text, x, y, size=16, color=(1.0, 1.0, 1.0, 1.0), align='LEFT'):
    """绘制单行文字（屏幕像素，左下原点）。"""
    font_id = 0
    blf.size(font_id, size)
    blf.color(font_id, *color)
    if align == 'CENTER':
        w, _ = blf.dimensions(font_id, text)
        x -= w / 2.0
    elif align == 'RIGHT':
        w, _ = blf.dimensions(font_id, text)
        x -= w
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def wrap_text(text, max_width_px, font_size):
    """按最大宽度自动换行，返回行列表。"""
    if not text:
        return []
    font_id = 0
    blf.size(font_id, font_size)
    lines = []
    current = ""
    for char in text:
        test = current + char
        w, _ = blf.dimensions(font_id, test)
        if w > max_width_px and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def draw_text_block(text, x, y, max_width, font_size, line_height,
                    color=(1.0, 1.0, 1.0, 1.0), align='LEFT'):
    """绘制多行文本块，返回实际绘制高度。"""
    lines = wrap_text(text, max_width, font_size)
    total_h = 0
    for i, line in enumerate(lines):
        ly = y - i * line_height
        draw_text(line, x, ly, font_size, color, align)
        total_h += line_height
    return total_h
