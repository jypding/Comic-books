"""VoiceBook 逻辑坐标 ↔ 屏幕像素换算（纯函数，无 bpy 状态依赖）。

约定：
- 逻辑坐标：左上角原点，x 向右，y 向下，范围 [0, 1920] × [0, 1080]
- 屏幕坐标：Blender 区域左下角原点，x 向右，y 向上
- 所有 JSON / PropertyGroup 存储一律使用逻辑坐标（整数）
"""

CANVAS_W = 1920
CANVAS_H = 1080


def get_image_rect(context):
    """获取当前图像在区域中的显示矩形。

    返回 (offset_x, offset_y, disp_w, disp_h) 或 None。
    offset 为区域左下角到图像左下角的像素偏移。
    """
    space = context.space_data
    if space is None or space.type != 'IMAGE_EDITOR':
        return None
    image = space.image
    if image is None:
        return None
    try:
        img_w, img_h = image.size
    except ReferenceError:
        return None
    if img_w <= 0 or img_h <= 0:
        return None

    region = context.region
    if region is None or region.type != 'WINDOW':
        return None

    zoom_x, zoom_y = space.zoom[0], space.zoom[1]
    disp_w = float(img_w) * zoom_x
    disp_h = float(img_h) * zoom_y

    view2d = region.view2d
    bl = view2d.view_to_region(0.0, 0.0, clip=False)
    offset_x, offset_y = bl[0], bl[1]

    return (offset_x, offset_y, disp_w, disp_h, img_w, img_h)


def logical_to_screen(img_rect, lx, ly):
    """逻辑坐标 → 屏幕像素。

    img_rect: get_image_rect() 返回值
    lx, ly: 逻辑坐标（左上原点，y 向下）
    返回 (sx, sy)：屏幕像素（左下原点，y 向上）
    """
    ox, oy, disp_w, disp_h, img_w, img_h = img_rect
    sx = ox + lx / img_w * disp_w
    sy = oy + (1.0 - ly / img_h) * disp_h
    return (sx, sy)


def screen_to_logical(img_rect, sx, sy):
    """屏幕像素 → 逻辑坐标。

    返回 (lx, ly)：逻辑坐标（左上原点，y 向下），未做 clamp。
    """
    ox, oy, disp_w, disp_h, img_w, img_h = img_rect
    if disp_w <= 0 or disp_h <= 0:
        return (0, 0)
    lx = (sx - ox) / disp_w * img_w
    ly = (1.0 - (sy - oy) / disp_h) * img_h
    return (lx, ly)


def clamp_logical(lx, ly, w=0, h=0):
    """将逻辑坐标 clamp 到画布范围内，考虑元素宽高。"""
    lx = max(0, min(CANVAS_W - w, lx))
    ly = max(0, min(CANVAS_H - h, ly))
    return (int(round(lx)), int(round(ly)))


def clamp_size(w, h, lx, ly):
    """将元素尺寸 clamp 到画布范围内。"""
    w = max(20, min(CANVAS_W - lx, w))
    h = max(20, min(CANVAS_H - ly, h))
    return (int(round(w)), int(round(h)))


def compute_layout_areas(layout_type, divider_position, padding_l, padding_r,
                         padding_t, padding_b):
    """根据版式类型和分割线位置计算文字区与场景区。

    返回 (text_area, scene_area, divider_line)：
    - text_area: (x, y, w, h) 逻辑坐标
    - scene_area: (x, y, w, h) 逻辑坐标
    - divider_line: 分割线屏幕坐标（仅用于绘制，由调用方再转换）
    """
    if layout_type == 'FULL':
        text_area = (0, 0, CANVAS_W, CANVAS_H)
        scene_area = (0, 0, 0, 0)
        return text_area, scene_area, None

    if layout_type == 'LEFT_RIGHT':
        # 分割线为垂直线，divider_position 是 x 坐标
        dp = max(int(CANVAS_W * 0.15), min(int(CANVAS_W * 0.85), divider_position))
        # 文字区占左半，应用四条内边距；场景区占右半，共享外侧上/下/右内边距
        text_area = (
            padding_l,
            padding_t,
            dp - padding_l - padding_r,
            CANVAS_H - padding_t - padding_b,
        )
        scene_area = (
            dp,
            padding_t,
            CANVAS_W - dp - padding_r,
            CANVAS_H - padding_t - padding_b,
        )
        return text_area, scene_area, dp

    if layout_type == 'TOP_BOTTOM':
        # 分割线为水平线，divider_position 是 y 坐标
        dp = max(int(CANVAS_H * 0.15), min(int(CANVAS_H * 0.85), divider_position))
        # 文字区占上半；场景区占下半，共享外侧左/右/下内边距
        text_area = (
            padding_l,
            padding_t,
            CANVAS_W - padding_l - padding_r,
            dp - padding_t - padding_b,
        )
        scene_area = (
            padding_l,
            dp,
            CANVAS_W - padding_l - padding_r,
            CANVAS_H - dp - padding_b,
        )
        return text_area, scene_area, dp

    return (0, 0, CANVAS_W, CANVAS_H), (0, 0, 0, 0), None


def point_in_rect(sx, sy, rx, ry, rw, rh):
    """命中测试：屏幕点是否在矩形内（屏幕坐标）。"""
    return rx <= sx <= rx + rw and ry <= sy <= ry + rh


def rect_corners_logical(x, y, w, h):
    """返回逻辑矩形的四角坐标（顺时针：左上、右上、右下、左下）。"""
    return [
        (x, y),
        (x + w, y),
        (x + w, y + h),
        (x, y + h),
    ]
