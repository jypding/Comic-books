"""VoiceBook 模态操作符：事件分发、timer 重绘、让位逻辑、清理。"""

import sys
import bpy
from .vb_engine import VoiceBookEngine


def _original_tool_active():
    """只读探测原插件是否有激活工具（不 import 含连字符的包名）。

    原插件的 state 模块在 sys.modules 中的键为
    'add-on-image-editor-tools-v0.3.9.state'，
    含连字符无法用 import 语句引用，但可在 sys.modules 字典中查找。
    """
    for name, mod in sys.modules.items():
        if not name.endswith(".state"):
            continue
        if "image_editor" not in name.lower() and "image-editor" not in name.lower():
            continue
        current = getattr(mod, "current_tool", None)
        if isinstance(current, str) and current != 'NONE':
            return True
    return False


class VOICEBOOK_OT_layout_start(bpy.types.Operator):
    bl_idname = "voicebook.layout_start"
    bl_label = "开始排版"
    bl_description = "启动 VoiceBook 可视化排版模态"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'IMAGE_EDITOR'
            and context.space_data.image is not None
            and not VoiceBookEngine._active_instance
        )

    def invoke(self, context, event):
        # 尝试让位：若原插件有激活工具，先取消其模态
        try:
            bpy.ops.image_editor_tools.tool_cancel()
        except Exception:
            pass

        self._prev_ui_mode = str(context.space_data.ui_mode)
        if context.area.ui_type != 'IMAGE_EDITOR':
            context.area.ui_type = 'IMAGE_EDITOR'
        context.space_data.ui_mode = 'VIEW'

        bpy.ops.ed.undo_push(message="VoiceBook 排版")

        props = context.scene.voicebook_layout
        props.is_editing = True

        self._engine = VoiceBookEngine(context)

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        try:
            wm.modal_handler_add(self)
        except Exception:
            wm.event_timer_remove(self._timer)
            self._engine.cleanup()
            raise

        context.workspace.status_text_set(
            "VoiceBook排版: 拖拽分割线/文本框 | 点击选中 | Esc 退出"
        )
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        engine = getattr(self, '_engine', None)
        if engine is None or engine.should_exit:
            return self._finish(context)

        # 让位检测：若原插件工具被激活，自清理退出（只读探测，不依赖对方源码）
        if _original_tool_active():
            return self._finish(context)

        context.area.tag_redraw()

        if event.type in {'RIGHTMOUSE', 'ESC', 'Z'}:
            if event.type == 'Z' and not event.ctrl:
                return {'PASS_THROUGH'}
            return self._finish(context)

        if event.type == 'TIMER':
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'IMAGE_EDITOR':
                        area.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if engine.handle_mouse_press(event):
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
            elif event.value == 'RELEASE':
                engine.handle_mouse_release(event)
                return {'PASS_THROUGH'}

        elif event.type == 'MOUSEMOVE':
            if engine.handle_mouse_move(event):
                return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _finish(self, context):
        engine = getattr(self, '_engine', None)
        if engine is not None:
            engine.cleanup()
            self._engine = None

        timer = getattr(self, '_timer', None)
        if timer is not None:
            try:
                context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None

        try:
            props = context.scene.voicebook_layout
            props.is_editing = False
            props.selection = 'NONE'
        except Exception:
            pass

        prev = getattr(self, '_prev_ui_mode', None)
        if prev is not None:
            try:
                area = context.area
                if area is not None and area.type == 'IMAGE_EDITOR':
                    sp = area.spaces.active
                    if sp is not None:
                        sp.ui_mode = prev
            except Exception:
                pass

        context.workspace.status_text_set(None)
        return {'FINISHED'}


class VOICEBOOK_OT_layout_stop(bpy.types.Operator):
    bl_idname = "voicebook.layout_stop"
    bl_label = "结束排版"
    bl_description = "退出 VoiceBook 排版模态"

    @classmethod
    def poll(cls, context):
        return VoiceBookEngine._active_instance is not None

    def execute(self, context):
        engine = VoiceBookEngine._active_instance
        if engine is not None:
            engine.cleanup()
        return {'FINISHED'}


classes = [
    VOICEBOOK_OT_layout_start,
    VOICEBOOK_OT_layout_stop,
]
