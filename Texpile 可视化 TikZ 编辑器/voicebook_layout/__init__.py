# VoiceBook Layout [语音书排版]
#
# 独立插件：在图像编辑器（IMAGE_EDITOR）空间注册 VoiceBook 排版 N 面板。
# 与 add-on-image-editor-tools 插件共存，不修改其任何源码文件。

bl_info = {
    "name": "VoiceBook Layout [语音书排版]",
    "author": "VoiceBook",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Image Editor > Sidebar(N-Panel) > VoiceBook排版",
    "description": "VoiceBook visual layout: base image, divider, text areas, JSON IO",
    "category": "Tool",
}

import bpy

from . import vb_props
from . import vb_coords
from . import vb_draw
from . import vb_engine
from . import vb_modal
from . import vb_json
from . import vb_panels


# 注册顺序：PropertyGroup → 操作符 → 面板
classes = (
    vb_modal.classes
    + vb_json.classes
    + vb_panels.classes
)


def register():
    # 1. PropertyGroup 与 Scene.voicebook_layout 挂载
    vb_props.register()

    # 2. 操作符与面板
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    # 1. 若排版模态仍在运行，先移除 draw_handler / timer 关联资源
    try:
        engine = vb_engine.VoiceBookEngine._active_instance
        if engine is not None:
            engine.cleanup()
    except Exception:
        pass

    # 2. 逆序反注册操作符与面板
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # 3. PropertyGroup 与 Scene 指针
    vb_props.unregister()

    # 4. 清 GPU shader 缓存
    vb_draw.clear_shader_cache()


if __name__ == "__main__":
    register()
