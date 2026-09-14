bl_info = {
    'name': '3D Comic Toolkit',
    'author': 'Bay Raitt',
    'version': (0, 5),
    'blender': (5, 2, 0),
    "description": "3D Comic Toolkit - requires factory addons: Bool Tool to be activated!! ",
    'category': 'Import-Export',
    'location': '3DView Toolbar > 3D Comic',
    'wiki_url': ''
    }

import bpy
import os
import sys
import shutil
import os.path
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper

from bpy_extras.object_utils import AddObjectHelper, object_data_add

from platform import system
from shutil import copytree as copy_tree_compat
import glob

from bpy.props import *
import subprocess

import warnings
import re
from itertools import count, repeat
from collections import namedtuple
import math
from math import pi
import random

from bpy.types import Operator
from mathutils import *
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    CollectionProperty,
)
from bpy.types import (Panel,
                       PropertyGroup,
                       AddonPreferences
                       )

import bmesh
from .core.utils import _get_publish_root
from .exporter import modern_pipeline
# import bpy.utils.previews
# from bpy.app.handlers import persistent

#------------------------------------------------------
# Blender 5.2 compatibility: distutils removed in Python 3.12+
# Wrapper to emulate distutils.dir_util.copy_tree using shutil.copytree
def copy_tree(src, dst, preserve_mode=1, preserve_times=1, preserve_symlinks=0, update=0, verbose=0, dry_run=0):
    """Compatibility wrapper replacing distutils.dir_util.copy_tree."""
    import os
    if not os.path.exists(dst):
        os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            copy_tree(s, d, preserve_mode, preserve_times, preserve_symlinks, update, verbose, dry_run)
        else:
            copytree_compat(s, d) if False else __import__('shutil').copy2(s, d)
    return os.listdir(dst)


# ========================================================
# Blender 5.2 Compatibility Helpers (API-only, no business logic)
# ========================================================
_B52_GLTF_UNSUPPORTED_PARAMS = {'export_colors', 'export_selected', 'export_displacement'}


def find_layer_collection(layer_collection, target_name):
    """Recursively locate a LayerCollection by name (Blender 5.2 safe).
    Does NOT create anything; returns None if not found."""
    if layer_collection.name == target_name:
        return layer_collection
    for child in layer_collection.children:
        found = find_layer_collection(child, target_name)
        if found is not None:
            return found
    return None


def _load_modern_pipeline():
    """Import Modern Pipeline's exporter using standard package import.
    
    Returns export_to_modern_web, or raises ImportError with a clear message.
    """
    try:
        from .exporter.modern_pipeline import blender_exporter
        if not hasattr(blender_exporter, "export_to_modern_web"):
            raise ImportError("export_to_modern_web missing from blender_exporter")
        return blender_exporter.export_to_modern_web
    except ImportError as e:
        print(f"[3DComicToolkit] Failed to load modern pipeline: {e}")
        raise ImportError(f"Modern Pipeline load failed: {e}")


def _b52_adapt_scene_to_comic_panel(scene, panel_index):
    """[P0-E] Make an ordinary imported scene usable as a comic panel.

    Renames the scene to the p.NNNN.w100h100 convention and guarantees the
    Export./Letters. collections the toolkit expects.  Existing objects are
    scanned (mesh/camera/text) rather than recreated, and a camera is only
    added when the scene genuinely has none.
    """
    padded = "%04d" % panel_index
    scene.name = "p." + padded + ".w100h100"

    export_collection_name = "Export." + padded
    letters_collection_name = "Letters." + padded

    export_collection = bpy.data.collections.get(export_collection_name)
    if export_collection is None:
        export_collection = bpy.data.collections.new(export_collection_name)
    if export_collection.name not in {c.name for c in scene.collection.children}:
        scene.collection.children.link(export_collection)

    # [P0-F] Letters is optional in generic .blend files, but downstream code
    # indexes it; create it empty rather than leaving it missing.
    letters_collection = bpy.data.collections.get(letters_collection_name)
    if letters_collection is None:
        letters_collection = bpy.data.collections.new(letters_collection_name)
    if letters_collection.name not in {c.name for c in export_collection.children}:
        export_collection.children.link(letters_collection)

    meshes, cameras, texts = [], [], []
    for obj in list(scene.collection.all_objects):
        if obj.type == 'MESH':
            meshes.append(obj)
        elif obj.type == 'CAMERA':
            cameras.append(obj)
        elif obj.type == 'FONT':
            texts.append(obj)

    already_in_export = {o.name for o in export_collection.all_objects}
    for obj in meshes + cameras:
        if obj.name not in already_in_export:
            try:
                export_collection.objects.link(obj)
            except RuntimeError:
                pass

    already_in_letters = {o.name for o in letters_collection.all_objects}
    for obj in texts:
        if obj.name not in already_in_letters:
            try:
                letters_collection.objects.link(obj)
            except RuntimeError:
                pass

    if cameras:
        if scene.camera is None:
            scene.camera = cameras[0]
    else:
        cam_data = bpy.data.cameras.new("Camera." + padded)
        cam_obj = bpy.data.objects.new("Camera." + padded, cam_data)
        cam_obj.location = (0.0, -8.0, 1.6)
        cam_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        export_collection.objects.link(cam_obj)
        scene.camera = cam_obj
        print('[3DComicToolkit] %s had no camera, created %s' % (scene.name, cam_obj.name))

    print('[3DComicToolkit] Adapted %s (mesh=%d camera=%d text=%d)'
          % (scene.name, len(meshes), max(len(cameras), 1), len(texts)))
    return scene


def _b52_resolve_bake_source_collection(context):
    """[P0-C] Best-effort lookup of the collection to bake.

    Order: active layer collection -> active object's collection ->
    selected objects' collection -> first scene collection holding meshes.
    Returns None when nothing usable exists (caller reports a clean error).
    """
    scene = getattr(context, 'scene', None)
    if scene is None:
        return None

    def _has_mesh(col):
        try:
            return any(o.type == 'MESH' for o in col.all_objects)
        except Exception:
            return False

    try:
        active_lc = context.view_layer.active_layer_collection
        if active_lc is not None:
            col = active_lc.collection
            # The scene master collection is not a valid bake source.
            if col is not None and col is not scene.collection and _has_mesh(col):
                return col
    except Exception:
        pass

    active_obj = getattr(context, 'object', None)
    if active_obj is not None:
        for col in active_obj.users_collection:
            if col is not scene.collection:
                return col

    for obj in (getattr(context, 'selected_objects', None) or []):
        for col in obj.users_collection:
            if col is not scene.collection:
                return col

    for col in scene.collection.children:
        if _has_mesh(col):
            return col

    return None


def _b52_root_layer_collection():
    return bpy.context.view_layer.layer_collection


def _b52_get_layer_collection(name):
    """Safe recursive lookup. Returns LayerCollection or None."""
    if name is None:
        return None
    return find_layer_collection(_b52_root_layer_collection(), name)


def _b52_set_lc_exclude(name, exclude_value):
    """Safely set .exclude on a LayerCollection by recursive name lookup.
    Silently no-op if the LayerCollection does not exist."""
    lc = _b52_get_layer_collection(name)
    if lc is not None:
        lc.exclude = exclude_value
    return lc


def _b52_get_lc_nested(parent_name, child_name):
    """Find a nested child LayerCollection: children[parent_name].children[child_name]."""
    parent_lc = _b52_get_layer_collection(parent_name)
    if parent_lc is None:
        return None
    return find_layer_collection(parent_lc, child_name)


def _b52_set_lc_nested_exclude(parent_name, child_name, exclude_value):
    child_lc = _b52_get_lc_nested(parent_name, child_name)
    if child_lc is not None:
        child_lc.exclude = exclude_value
    return child_lc


def _b52_set_active_layer_collection(name):
    """Safely set view_layer.active_layer_collection by recursive name lookup."""
    lc = _b52_get_layer_collection(name)
    if lc is not None:
        bpy.context.view_layer.active_layer_collection = lc
    return lc


def _b52_is_object_in_view_layer(obj, view_layer=None):
    """Return True when ``obj`` belongs to the current view layer."""
    if obj is None:
        return False
    view_layer = view_layer or getattr(bpy.context, 'view_layer', None)
    if view_layer is None:
        return False
    try:
        return obj.name in view_layer.objects
    except Exception:
        try:
            return view_layer.objects.get(obj.name) is not None
        except Exception:
            try:
                return any(vl_obj == obj for vl_obj in view_layer.objects)
            except Exception:
                return False


def _b52_safe_select_object(obj, deselect_all=False, make_active=False):
    """Best-effort Blender 5.2 safe selection helper for export code."""
    if obj is None:
        return False
    view_layer = getattr(bpy.context, 'view_layer', None)
    if not _b52_is_object_in_view_layer(obj, view_layer):
        print('[b52 safe select] skip object outside current view layer: ' + getattr(obj, 'name', '<unknown>'))
        return False
    if deselect_all:
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:
            pass
    try:
        obj.select_set(state=True)
    except Exception as _sel_e:
        print('[b52 safe select] select_set failed for {}: {}'.format(getattr(obj, 'name', '<unknown>'), _sel_e))
        return False
    if make_active and view_layer is not None:
        try:
            view_layer.objects.active = obj
        except Exception:
            pass
    return True


def _b52_safe_export_scene_gltf(**kwargs):
    """bpy.ops.export_scene.gltf wrapper that strips Blender 5.2 unsupported parameters
    and injects fallback context attributes the official addon may require."""
    filtered = {k: v for k, v in kwargs.items()
                if k not in _B52_GLTF_UNSUPPORTED_PARAMS}

    _vl = getattr(bpy.context, 'view_layer', None)
    _fallback_active = getattr(_vl, 'objects', None) and getattr(_vl.objects, 'active', None)
    if _fallback_active is None:
        for _o in (getattr(bpy.data, 'objects', None) or []):
            _fallback_active = _o; break
    _fallback_selected = list(getattr(_vl, 'objects', None).selected) if (_vl and hasattr(getattr(_vl, 'objects', None), 'selected')) else []
    if _fallback_selected and _fallback_active is None:
        _fallback_active = _fallback_selected[0]

    _ctx_override = {}
    _ctx_override['active_object'] = _fallback_active
    _ctx_override['object'] = _fallback_active
    _ctx_override['selected_objects'] = _fallback_selected
    _ctx_override['selected_editable_objects'] = _fallback_selected
    _ctx_override['window'] = getattr(bpy.context, 'window', None) or (
        (bpy.context.window_manager.windows[0] if bpy.context.window_manager and len(bpy.context.window_manager.windows) else None))
    _ctx_override['workspace'] = getattr(bpy.context, 'workspace', None)
    _ctx_override['screen'] = getattr(bpy.context, 'screen', None) or (
        (_ctx_override['workspace'].screens[0] if (_ctx_override['workspace'] and hasattr(_ctx_override['workspace'], 'screens') and len(_ctx_override['workspace'].screens)) else None))
    _ctx_override['area'] = getattr(bpy.context, 'area', None)
    _ctx_override['region'] = getattr(bpy.context, 'region', None)
    _ctx_override['space_data'] = getattr(bpy.context, 'space_data', None)

    try:
        with bpy.context.temp_override(**_ctx_override):
            return bpy.ops.export_scene.gltf(**filtered)
    except (TypeError, ValueError, AttributeError):
        try:
            with bpy.context.temp_override(**{k: v for k, v in _ctx_override.items() if v is not None}):
                return bpy.ops.export_scene.gltf(**filtered)
        except Exception:
            try:
                return bpy.ops.export_scene.gltf('EXEC_DEFAULT', **filtered)
            except Exception as _gl_e:
                print('[gltf export fallback] all override fail: ' + str(_gl_e))
                raise


def _action_fcurves(action):
    """Return an Action's f-curves across Blender's legacy and layered APIs."""
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        return legacy_fcurves

    fcurves = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                try:
                    fcurves.extend(channelbag.fcurves)
                except Exception:
                    continue
    return fcurves


def _b52_set_light_use_shadow(light_obj, enabled):
    """Blender 5.2 compatibility wrapper for light shadow toggles."""
    if light_obj is None:
        return
    light_data = getattr(light_obj, 'data', None)
    if light_data is None:
        return
    for attr_name in ('use_shadow', 'use_contact_shadow'):
        if hasattr(light_data, attr_name):
            try:
                setattr(light_data, attr_name, bool(enabled))
                return
            except Exception:
                continue


def _b52_snap_selected_to_cursor(context, use_offset=False):
    """Run view3d.snap_selected_to_cursor inside a valid 3D view override."""
    try:
        for area in getattr(context.screen, 'areas', ()):
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            try:
                with context.temp_override(area=area, region=region, window=context.window):
                    bpy.ops.view3d.snap_selected_to_cursor(use_offset=bool(use_offset))
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        bpy.ops.view3d.snap_selected_to_cursor(use_offset=bool(use_offset))
        return True
    except Exception:
        return False


def _b52_safe_world_background_color_source(world_obj):
    """Safely retrieve the Background color source node from a world.
    Returns (color_node_or_None, default_value_tuple_or_None)."""
    if world_obj is None:
        return None, None
    if not getattr(world_obj, 'use_nodes', False):
        return None, None
    if world_obj.node_tree is None:
        return None, None
    bg = world_obj.node_tree.nodes.get('Background')
    if bg is None:
        return None, None
    inp0 = bg.inputs[0]
    default_val = inp0.default_value
    if inp0.links and len(inp0.links) > 0:
        try:
            from_node = inp0.links[0].from_node
            return from_node, default_val
        except (IndexError, AttributeError):
            return None, default_val
    return None, default_val


def _b52_safe_world_background_shader(world_obj):
    """Return an existing Background shader node or create a safe fallback.
    This avoids direct indexing into world_output.inputs[0].links[0] when the node tree
    is empty or Blender 5.2 has not created the expected world setup yet."""
    if world_obj is None:
        return None
    tree = getattr(world_obj, 'node_tree', None)
    if tree is None:
        return None
    world_output = tree.nodes.get('World Output')
    if world_output is None:
        world_output = tree.nodes.new(type='ShaderNodeOutputWorld')
    if not getattr(world_output, 'inputs', None) or len(world_output.inputs) == 0:
        return None
    try:
        for link in world_output.inputs[0].links:
            if getattr(link, 'from_node', None) is not None:
                return link.from_node
    except Exception:
        pass
    bg = tree.nodes.get('Background')
    if bg is not None:
        return bg
    return None


# ========================================================
# end Blender 5.2 Compatibility Helpers
# ========================================================


#------------------------------------------------------
# addon preferences

# class ComicPreferences(AddonPreferences):
#     # this must match the addon name, use '__package__'
#     # when defining this in a submodule of a python package.
#     bl_idname = __name__

#     assets_folder = StringProperty(
#             name="Assets Folder",
#             subtype='DIR_PATH',
#             )

#     def draw(self, context):
#         layout = self.layout
#         layout.label(text="Location for Spiraloid Template Assets")
#         layout.prop(self, "assets_folder")



#------------------------------------------------------
# global variables

developer_mode = False
backstage_collection_name = ""
last_applied_pose_index = 0
isChildLock = False
previous_sky_color_index = 0
previous_random_int = 0 
isWorkmodeToggled = True
isWireframe = False
previous_toolbar_state = False
previous_region_ui_state = False
previous_mode = 'EDIT'
previous_selection = ""
active_language_abreviated = "en"
active_language = "english"
working_folder = ""
material_swatch_object = ""
issue_folder = ""
main_dir = os.path.dirname(__file__)
addon_resources_dir = main_dir + "/Resources/"

#------------------------------------------------------
# utilities

def warn_not_saved(self, context):
    self.layout.label(text= "You must save your file first!")

def warn_folder_exists(self, context):
    self.layout.label(text= "Folder Already Exists!")

def warn_language_set(self, context):
    scene = context.scene
    language = scene.panel_settings.s3dc_language
    self.layout.label(text= "Language set to " + language + " for all scenes")


def sanitize_missing_fonts():
    """Ensure missing external fonts do not abort export.

    If a font file is absent or points to a legacy Dropbox path, the function
    silently swaps all text/font references to Blender's built-in default font
    (Bfont when available), without deleting text objects or breaking export.
    """
    try:
        default_font = bpy.data.fonts.get("Bfont")
        if default_font is None:
            for font in bpy.data.fonts:
                if font is not None:
                    default_font = font
                    break
        if default_font is None:
            return

        def is_bad_font_path(font_path):
            if not font_path:
                return False
            fp = str(font_path).replace('\\', '/').lower()
            if 'x:/dropbox' in fp or 'x:\\dropbox' in fp or 'dropbox' in fp or 'ccastrocity' in fp:
                return True
            if fp.endswith(('.otf', '.ttf')):
                try:
                    return not os.path.exists(bpy.path.abspath(font_path))
                except Exception:
                    return True
            return False

        changed = False
        for font in list(bpy.data.fonts):
            fp = getattr(font, 'filepath', '') or ''
            if is_bad_font_path(fp):
                print("[字体兼容] 丢失字体：%s" % (font.name or fp))
                print("[字体兼容] 已切换到 Blender 默认字体")
                changed = True
                for obj in bpy.data.objects:
                    if obj.type == 'FONT':
                        try:
                            if getattr(obj.data, 'font', None) == font:
                                obj.data.font = default_font
                        except Exception:
                            pass
                for curve in bpy.data.curves:
                    if getattr(curve, 'type', None) == 'FONT':
                        try:
                            if getattr(curve, 'font', None) == font:
                                curve.font = default_font
                        except Exception:
                            pass

        for obj in bpy.data.objects:
            if obj.type == 'FONT':
                try:
                    font = getattr(obj.data, 'font', None)
                    if font is None:
                        obj.data.font = default_font
                        continue
                    fp = getattr(font, 'filepath', '') or ''
                    if is_bad_font_path(fp):
                        obj.data.font = default_font
                except Exception:
                    pass

        for curve in bpy.data.curves:
            if getattr(curve, 'type', None) == 'FONT':
                try:
                    font = getattr(curve, 'font', None)
                    fp = getattr(font, 'filepath', '') or ''
                    if font is None or is_bad_font_path(fp):
                        curve.font = default_font
                except Exception:
                    pass

        if changed:
            print("[字体兼容] 已完成丢失字体兼容修正，导出将继续使用 Blender 默认字体。")

    except Exception:
        print("[字体兼容] sanitize_missing_fonts 发生异常")
        import traceback
        traceback.print_exc()
        print("[字体兼容] bpy.data.fonts:")
        for font in list(bpy.data.fonts):
            print("  - %s | %s" % (getattr(font, 'name', '<unnamed>'), getattr(font, 'filepath', '')))
        print("[字体兼容] FONT objects:")
        for obj in bpy.data.objects:
            if obj.type == 'FONT':
                font = getattr(getattr(obj, 'data', None), 'font', None)
                print("  - %s | %s | %s" % (obj.name, getattr(font, 'name', '<none>'), getattr(font, 'filepath', '')))


def operator_exists(idname):
    """True only if the operator is really registered.

    bpy.ops.<missing> returns a stub submodule instead of raising, so the old
    getattr()+__repr__() probe always succeeded and callers went on to touch
    addon properties that were never registered.  Resolve through
    bpy.ops.get_rna_type() / the operator's poll instead.
    """
    names = idname.split(".")
    if len(names) != 2:
        return False
    module, func = names
    try:
        submodule = getattr(bpy.ops, module)
    except AttributeError:
        return False
    if not hasattr(submodule, func):
        return False
    try:
        # get_rna_type() raises for unregistered operators.
        getattr(submodule, func).get_rna_type()
    except Exception:
        return False
    return True

def to_hex(c):
    if c < 0.0031308:
        srgb = 0.0 if c < 0.0 else c * 12.92
    else:
        srgb = 1.055 * math.pow(c, 1.0 / 2.4) - 0.055

    return hex(max(min(int(srgb * 255 + 0.5), 255), 0))

def toHex(r,g,b):
    rgb = [r,g,b]
    result = ""
    i=0
    while i < 3:
        val = str(to_hex(rgb[i]))
        val = val[2:]
        if len(val) == 1:
            val += val
        result+=val
        i+=1
    return result

def clean_string(f):
    chars = bytearray() # avoid lists
    i = 0
    while True:
        c = f.read(1)
        i += 1
        if (c == b'\x00' ): # c is bytes() 
            return (chars.decode('utf-8') )
        chars.append( c[0] ) # stick another bare byte onto chars


def scene_mychosenobject_poll(self, object):
    return object.type == 'MESH'

def empty_trash(self, context):
    for block in bpy.data.collections:
        if not block.users:
            bpy.data.collections.remove(block)

    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)

    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)

    for block in bpy.data.textures:
        if block.users == 0:
            bpy.data.textures.remove(block)

    for block in bpy.data.images:
        if block.users == 0:
            bpy.data.images.remove(block)

    for block in bpy.data.actions:
        if block.users == 0:
            bpy.data.actions.remove(block)

    for block in bpy.data.lights:
        if block.users == 0:
            bpy.data.lights.remove(block)

    for block in bpy.data.curves:
        if block.users == 0:
            bpy.data.curves.remove(block)

    for block in bpy.data.cameras:
        if block.users == 0:
            bpy.data.cameras.remove(block)

    # Blender 5.0: bpy.data.grease_pencils renamed to bpy.data.annotations
    grease_data = getattr(bpy.data, 'annotations', None) or getattr(bpy.data, 'grease_pencils', None)
    if grease_data:
        for block in grease_data:
            if block.users == 0:
                grease_data.remove(block)

    for block in bpy.data.texts:
        if block.users == 0:
            bpy.data.texts.remove(block)

    for block in bpy.data.fonts:
        if block.users == 0:
            bpy.data.fonts.remove(block)

    for block in bpy.data.libraries:
        if block.users == 0:
            bpy.data.libraries.remove(block)

    for block in bpy.data.worlds:
        if block.users == 0:
            bpy.data.worlds.remove(block)
            

    for block in bpy.data.particles:
        if block.users == 0:
            bpy.data.particles.remove(block)

    try:
        bpy.ops.outliner.orphans_purge()
    except:
        pass
    try:
        bpy.ops.outliner.orphans_purge()
    except:
        pass
    try:
        bpy.ops.outliner.orphans_purge()
    except:
        pass

    return {'FINISHED'}

## track changed objects and update scene after -- dangerous
# def scene_update_handler(scene):
#     updated_objects = []
#     for o in scene.objects:
#         is_cycler = o.get("Suzanne")
#         if is_cycler:
#             updated_objects.append(o)
#     if(len(updated_objects) > 0):
#         print("updated objects: " + updated_objects[0].name)

#------------------------------------------------------
# mesh tools 

def NormalInDirection( normal, direction, limit = 0.5 ):
    return direction.dot( normal ) > limit

def GoingUp( normal, limit = 0.5):
    return NormalInDirection( normal, Vector( (0, 0, 1 ) ), limit )

def GoingDown( normal, limit = 0.5):
    return NormalInDirection( normal, Vector( (0, 0, -1 ) ), limit )

def GoingSide( normal, limit = 0.5):
    return GoingUp( normal, limit ) == False and GoingDown( normal, limit ) == False

def automap(mesh_objects, decimate_ratio):

    # UV map target_object if no UV's present
    for mesh_object in mesh_objects:
        if (bpy.context.mode != 'OBJECT'):
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        if mesh_object.type == 'MESH':
            bpy.ops.object.select_all(action='DESELECT')
            mesh_object.select_set(state=True)
            bpy.context.view_layer.objects.active = mesh_object
            if not len( mesh_object.data.uv_layers ):
                bpy.ops.mesh.uv_texture_add()
                bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                bpy.ops.mesh.select_all(action='SELECT')
                # bpy.ops.uv.smart_project(angle_limit=66, island_margin=0.02, area_weight=0.75, correct_aspect=True, scale_to_bounds=True)
                # bpy.ops.uv.seams_from_islands()
                # bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)
                # bpy.ops.uv.minimize_stretch(iterations=1024)
                # bpy.ops.uv.average_islands_scale()

                bpy.ops.uv.cube_project(cube_size=10, scale_to_bounds=True)

                # area = bpy.context.area
                # old_type = area.type
                # if bakemesh.data.uv_layers:
                    # area.type = 'IMAGE_EDITOR'
                    # if operator_exists("uvpackmaster2"):
                    #     bpy.context.scene.uvp2_props.pack_to_others = False
                    #     bpy.context.scene.uvp2_props.margin = 0.015
                    #     bpy.ops.uvpackmaster2.uv_pack()
                # if old_type != "":
                    # area.type = old_type
            
            if (decimate_ratio != 1):
                    # bpy.ops.mesh.bisect(plane_co=(0, 0, 0), plane_no=(1, 0, 0), xstart=mesh_object.dimensions[1], xend=mesh_object.dimensions[1], ystart=mesh_object.dimensions[2], yend=mesh_object.dimensions[2])
                    # bpy.ops.mesh.mark_seam(clear=False)
                    # bpy.ops.mesh.select_all(action='SELECT')
                    # bpy.ops.mesh.bisect(plane_co=(0, 0, 0), plane_no=(0, 1, 0), xstart=mesh_object.dimensions[1], xend=mesh_object.dimensions[1], ystart=mesh_object.dimensions[2], yend=mesh_object.dimensions[2])
                    # bpy.ops.mesh.mark_seam(clear=False)
                    # bpy.ops.mesh.select_all(action='SELECT')
                    # bpy.ops.mesh.bisect(plane_co=(0, 0, 0), plane_no=(0, 0, 1), xstart=mesh_object.dimensions[1], xend=mesh_object.dimensions[1], ystart=mesh_object.dimensions[2], yend=mesh_object.dimensions[2])
                    # bpy.ops.mesh.mark_seam(clear=False)
                    # bpy.ops.mesh.select_all(action='SELECT')

                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                    bpy.ops.object.modifier_add(type='DECIMATE')
                    bpy.context.object.modifiers["Decimate"].decimate_type = 'DISSOLVE'
                    bpy.context.object.modifiers["Decimate"].angle_limit = 0.0523599
                    bpy.context.object.modifiers["Decimate"].delimit = {'UV'}
                    bpy.ops.object.modifier_apply( modifier="Decimate")

                    bpy.ops.object.modifier_add(type='TRIANGULATE')
                    bpy.context.object.modifiers["Triangulate"].keep_custom_normals = True
                    bpy.context.object.modifiers["Triangulate"].quad_method = 'FIXED'
                    bpy.ops.object.modifier_apply( modifier="Triangulate")


                    bpy.ops.object.modifier_add(type='DECIMATE')
                    bpy.context.object.modifiers["Decimate"].ratio = decimate_ratio
                    bpy.ops.object.modifier_apply( modifier="Decimate")

                    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                    bpy.ops.mesh.delete_loose()
                    bpy.ops.mesh.dissolve_degenerate()
                    bpy.ops.mesh.remove_doubles()
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)



    #select all meshes and pack into one UV set together
    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    bpy.ops.object.select_all(action='DESELECT')
    for mesh_object in mesh_objects:
        mesh_object.select_set(state=True)
        bpy.context.view_layer.objects.active = mesh_object

    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    C=bpy.context
    old_area_type = C.area.type
    C.area.type='IMAGE_EDITOR'
    C.area.ui_type = 'UV'
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.mesh.select_all(action='SELECT')
    # bpy.ops.uv.select_all(action='SELECT')
    # bpy.ops.uv.minimize_stretch(override, iterations=100)
    uvp2_props = getattr(bpy.context.scene, "uvp2_props", None)
    if operator_exists("uvpackmaster2.uv_pack") and uvp2_props is not None:
        uvp2_props.pack_to_others = False
        uvp2_props.margin = 0.01
        uvp2_props.rot_step = 5
        bpy.ops.uvpackmaster2.uv_measure_area()
        bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(margin=0.005)
        bpy.ops.uvpackmaster2.uv_pack()
    else:
        # Blender 5.2 native UV fallback (no UVPackmaster installed).
        print('[3DComicToolkit] UVPackmaster not available, using native UV pack')
        bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(margin=0.005)
    C.area.type=old_area_type


    # bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    # for area in bpy.context.screen.areas:
    #         if area.type == 'IMAGE_EDITOR':
    #             for region in area.regions:
    #                 if region.type == 'WINDOW':
    #                     override = {'area': area, 'region': region, 'edit_object': bpy.context.edit_object}
    #                     bpy.context.scene.tool_settings.use_uv_select_sync = True
    #                     bpy.ops.uv.select_all(action='SELECT')
    #                     bpy.ops.mesh.select_all(action='SELECT')
    #                     # bpy.ops.uv.minimize_stretch(override, iterations=100)
    #                     if operator_exists("uvpackmaster2"):
    #                         bpy.context.scene.uvp2_props.pack_to_others = False
    #                         bpy.context.scene.uvp2_props.margin = 0.01
    #                         bpy.context.scene.uvp2_props.rot_step = 5
    #                         bpy.ops.uvpackmaster2.uv_measure_area()
    #                         bpy.ops.uv.average_islands_scale()
    #                         bpy.ops.uv.pack_islands(override , margin=0.005)
    #                         bpy.ops.uvpackmaster2.uv_pack()
    #                     else:
    #                         bpy.ops.uv.average_islands_scale(override)
    #                         bpy.ops.uv.pack_islands(override , margin=0.005)





        # bpy.ops.mesh.select_all(action='SELECT')
        # C=bpy.context
        # old_area_type = C.area.type
        # C.area.type='IMAGE_EDITOR'
        # bpy.ops.uv.pack_islands(margin=0.017)
        # C.area.type=old_area_type


    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    bpy.ops.object.select_all(action='DESELECT')
    for mesh_object in mesh_objects:
        mesh_object.select_set(state=True)
        bpy.context.view_layer.objects.active = mesh_object


        # raise Exception('stopping script')

    return {'FINISHED'} 


#------------------------------------------------------
# drop tools

def get_align_matrix(location, normal):
    up = Vector((0,0,1))
    angle = normal.angle(up)
    axis = up.cross(normal)
    mat_rot = Matrix.Rotation(angle, 4, axis)
    mat_loc = Matrix.Translation(location)
    mat_align = mat_rot @ mat_loc
    return mat_align

def transform_ground_to_world(layer, ground):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    object_eval = ground.evaluated_get(depsgraph)
    tmpMesh = bpy.data.meshes.new_from_object(object_eval)        
    tmpMesh.transform(ground.matrix_world)
    tmp_ground = bpy.data.objects.new(name='tmpGround', object_data=tmpMesh)
    layer.objects.link(tmp_ground)
    layer.objects.update()
    return tmp_ground

def get_lowest_world_co_from_mesh(ob, mat_parent=None):
    bme = bmesh.new()
    bme.from_mesh(ob.data)
    mat_to_world = ob.matrix_world.copy()
    if mat_parent:
        mat_to_world = mat_parent @ mat_to_world
    lowest=None
    #bme.verts.index_update() #probably not needed
    for v in bme.verts:
        if not lowest:
            lowest = v
        if (mat_to_world @ v.co).z < (mat_to_world @ lowest.co).z:
            lowest = v
    lowest_co = mat_to_world @ lowest.co
    bme.free()
    return lowest_co

def get_lowest_world_co(context, ob, mat_parent=None):
    if ob.type == 'MESH':
        return get_lowest_world_co_from_mesh(ob)

    elif ob.type == 'EMPTY' and ob.dupli_type == 'GROUP':
        if not ob.dupli_group:
            return None

        else:
            lowest_co = None
            for ob_l in ob.dupli_group.objects:
                if ob_l.type == 'MESH':
                    lowest_ob_l = get_lowest_world_co_from_mesh(ob_l, ob.matrix_world)
                    if not lowest_co:
                        lowest_co = lowest_ob_l
                    if lowest_ob_l.z < lowest_co.z:
                        lowest_co = lowest_ob_l

            return lowest_co

 #------------------------------------------------------
   
def drop_objects(self, context, use_origin, align):
    ground = context.object
    # ground_collection_name = bpy.context.object.users_collection[0].name
    ground.select_set(state=False)
    # bpy.context.view_layer.objects.active = context.selected_objects[0]

    obs = context.selected_objects
    # obs.remove(ground)
    tmp_ground = transform_ground_to_world(context.scene.collection, ground)
    down = Vector((0, 0, -10000))

    for ob in obs:
        if use_origin:
            lowest_world_co = ob.location
        else:
            lowest_world_co = get_lowest_world_co(context, ob)
        if not lowest_world_co:
            print(ob.type, 'is not supported. Failed to drop', ob.name)
            continue
        is_hit, hit_location, hit_normal, hit_index = tmp_ground.ray_cast(lowest_world_co, down)
        if not is_hit:
            print(ob.name, 'didn\'t hit the ground')
            continue

        # simple drop down
        to_ground_vec =  hit_location - lowest_world_co
        ob.location += to_ground_vec

        # drop with align to hit normal
        if align:
            to_center_vec = ob.location - hit_location #vec: hit_loc to origin
            # rotate object to align with face normal
            mat_normal = get_align_matrix(hit_location, hit_normal)
            rot_euler = mat_normal.to_euler()
            mat_ob_tmp = ob.matrix_world.copy().to_3x3()
            mat_ob_tmp.rotate(rot_euler)
            mat_ob_tmp = mat_ob_tmp.to_4x4()
            ob.matrix_world = mat_ob_tmp
            # move_object to hit_location
            ob.location = hit_location
            # move object above surface again
            to_center_vec.rotate(rot_euler)
            ob.location += to_center_vec


    #cleanup
    bpy.ops.object.select_all(action='DESELECT')
    # bpy.context.active_object.select_set(state=True)
    # bpy.ops.object.delete('EXEC_DEFAULT')
    for ob in obs:
        ob.select_set(state=True)
    bpy.data.objects.remove(bpy.data.objects[tmp_ground.name], do_unlink=True)
    empty_trash(self, context)


class OBJECT_OT_drop_to_ground(Operator):
    """Drop selected objects on active object"""
    bl_idname = "object.drop_on_active"
    bl_label = "落到地面（Drop to Ground）"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Drop selected objects on active object"

    align : BoolProperty(
            name="Align to ground",
            description="Aligns the object to the ground",
            default=True)
    use_origin : BoolProperty(
            name="Use Center",
            description="Drop to objects origins",
            default=False)

    ##### POLL #####
    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) >= 2

    ##### EXECUTE #####
    def execute(self, context):
        print('\nDropping Objects')
        drop_objects(self, context)
        return {'FINISHED'}

#------------------------------------------------------
# gets

def getCurrentSceneIndex():
    currScene =  bpy.context.scene
    for currSceneIndex in range(0,len(bpy.data.scenes)):
        if bpy.data.scenes[currSceneIndex].name == currScene.name:
            return currSceneIndex

def relinkAllSwatchColors():
    material_swatch_object = getCurrentMaterialSwatch()
    world_nodes = bpy.context.scene.world 
    # safety checks: bail out if we don't have a material swatch or a proper background node
    if not material_swatch_object:
        return
    if not world_nodes:
        return
    sky_color = material_swatch_object.get("Sky")
    background_node = None
    try:
        background_node = world_nodes.node_tree.nodes.get('Background') if getattr(world_nodes, 'node_tree', None) else None
    except Exception:
        background_node = None

    if background_node is None or not hasattr(background_node, 'inputs') or len(background_node.inputs) == 0 or len(getattr(background_node.inputs[0], 'links', [])) == 0:
        return
    colorNode = background_node.inputs[0].links[0].from_node
    if sky_color:
        try:
            colorNode.outputs[0].driver_remove("default_value")[0]
            colorNode.outputs[0].driver_remove("default_value")[1]
            colorNode.outputs[0].driver_remove("default_value")[2]
        except:
            pass

        colorDriverRed = colorNode.outputs[0].driver_add("default_value")[0]
        colorDriverGreen = colorNode.outputs[0].driver_add("default_value")[1]
        colorDriverBlue = colorNode.outputs[0].driver_add("default_value")[2]

        colorDriverRed.driver.type = 'SUM'
        newVar = colorDriverRed.driver.variables.new()
        newVar.name = "Sky"
        newVar.type = 'SINGLE_PROP'
        newVar.targets[0].id = material_swatch_object
        newVar.targets[0].data_path = '["Sky"][0]'

        colorDriverGreen.driver.type = 'SUM'
        newVar = colorDriverGreen.driver.variables.new()
        newVar.name = "Sky"
        newVar.type = 'SINGLE_PROP'
        newVar.targets[0].id = material_swatch_object
        newVar.targets[0].data_path = '["Sky"][1]'

        colorDriverBlue.driver.type = 'SUM'
        newVar = colorDriverBlue.driver.variables.new()
        newVar.name = "Sky"
        newVar.type = 'SINGLE_PROP'
        newVar.targets[0].id = material_swatch_object
        newVar.targets[0].data_path = '["Sky"][2]'



        #remove driver
        #remake driver
        print ("woo")

def getCurrentPanelNumber(padded):
    _win = getattr(bpy.context, 'window', None)
    scene_name = _win.scene.name if (_win and getattr(_win, 'scene', None)) else bpy.context.scene.name
    currSceneIndex = getCurrentSceneIndex()
    panels = []
    pi = 0
    panel_number = pi
    if (currSceneIndex > 0):
        for scene in bpy.data.scenes:
            if "p." in scene.name:
                panels.append(scene.name)        
        for panel in panels :
            for i in range(0,len(bpy.data.scenes)):
                if bpy.data.scenes[currSceneIndex].name == panel:
                    pi = currSceneIndex - 1
                    panel_number = pi
    else:
        panel_number = 0

    if padded:
        paddedNumString = "%04d" % panel_number
        return paddedNumString
    else:
        return panel_number

def getCurrentLetterGroup():
    #make sure letter collection is active
    getCurrentLettersCollection()
    language = bpy.context.scene.panel_settings.s3dc_language
    paddedNumString = getCurrentPanelNumber(True)
    letters_group_name = "Letters_" + language + "." + paddedNumString
    letters_group = bpy.data.collections.get(letters_group_name)
    for ob in bpy.data.objects: 
        if ob.name == letters_group_name: 
            return ob
        # else:
        #     report({'ERROR'}, 'No Letters named ' + letters_group_name + ' found under camera') 

def getCurrentActiveCollection(self, context):
    try:
        active_collection = bpy.context.collection
    except:
        pass 
    if active_collection:
        return active_collection
    else:
        self.report({'INFO'}, 'No active Collection found !')

def getCurrentExportCollection(self, context):
    currSceneIndex = getCurrentSceneIndex()
    currScene =  bpy.context.scene
    numString = getCurrentPanelNumber(False)
    paddedNumString = "%04d" % numString
    export_collection_name = "Export." + paddedNumString
    # export_collection = bpy.data.collections.get(export_collection_name)

    try:
        active_collection = bpy.context.collection
        # active_collection_children = active_collection.children
    except:
        pass 

    export_collection_name =  "Export." + str(paddedNumString) 

    export_collection = bpy.data.collections.get(export_collection_name)        
    if export_collection:
        return export_collection
    else:
        if active_collection:
            try:
                scene_master = bpy.context.scene.collection
                if active_collection != scene_master:
                    try:
                        dc = bpy.data.collections.get(active_collection.name)
                        if dc is not None:
                            dc.name = export_collection_name
                            self.report({'INFO'}, 'No Export Collection found, renamed active collection to ' + export_collection_name)
                            return dc
                    except Exception:
                        pass
                new_col = bpy.data.collections.new(export_collection_name)
                bpy.context.scene.collection.children.link(new_col)
                for obj in list(active_collection.objects):
                    new_col.objects.link(obj)
                for ch in list(active_collection.children):
                    new_col.children.link(ch)
                self.report({'INFO'}, 'No Export Collection found, created new ' + export_collection_name + ' from active collection contents')
                return new_col
            except Exception as _e:
                self.report({'WARNING'}, 'Rename/Create Export Collection fallback failed: ' + str(_e))
                return active_collection
        else:
            self.report({'INFO'}, 'No active or Export Collection named ' + export_collection_name + 'found in ' + currScene.name + '!')

def getCurrentBackstageCollectionName():
    # toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global

    # if toonfill_use_global:
    #     backstage_collection_name = "Backstage.Global"
    # else:
    currSceneIndex = getCurrentSceneIndex()
    currScene =  bpy.context.scene
    if currSceneIndex != 0:
        paddedNumString = getCurrentPanelNumber(True)
        backstage_collection_name = "Backstage." + paddedNumString
    else:
        backstage_collection_name = "Backstage.Global"
    return backstage_collection_name

def getCurrentBackstageCollection():
    # toonfill_use_global = bpy.context.scene.s3dc_toonfill_use_global
    toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global

    currSceneIndex = getCurrentSceneIndex()
    backstage_collection_name = getCurrentBackstageCollectionName()
    backstage_collection = ""

    # if toonfill_use_global:
        # scene_collections = bpy.data.scenes[0].collection.children
        # backstage_collection = bpy.data.scenes[0].collection.children['Backstage.Global']
    # else:
    scene_collections = bpy.data.scenes[currSceneIndex].collection.children
    for col in scene_collections:
        if backstage_collection_name in col.name:
            backstage_collection = bpy.data.collections.get(backstage_collection_name)
    # try:
    #     active_collection = bpy.context.collection
    #     # active_collection_children = active_collection.children
    # except:
    #     pass 

    return backstage_collection


def getCurrentLightingCollection(self, context):
    currSceneIndex = getCurrentSceneIndex()
    currScene =  bpy.context.scene
    numString = getCurrentPanelNumber(False)
    paddedNumString = "%04d" % numString
    lighting_collection_name = "Lighting." + paddedNumString
    scene_collections = bpy.data.scenes[currSceneIndex].collection.children
    scene_cameras = currScene.collection.children

    all_collections = []
    coll = bpy.context.scene.collection
    for c in traverse_tree(coll):
        all_collections.append(c)


    for col in all_collections:
        if lighting_collection_name in col.name:
            lighting_collection = bpy.data.collections.get(lighting_collection_name)
            if lighting_collection:
                return lighting_collection
            else:
                report({'INFO'}, 'No lighting Collection found!')

def getCurrentLettersCollection():
    """[P0-F] Letters collection is optional; never return None.

    Callers do letters_collection.objects unconditionally, so a .blend without
    any text objects used to raise AttributeError.  Create the collection empty
    instead - "no letters" is a legitimate state.
    """
    currScene = bpy.context.scene
    numString = getCurrentPanelNumber(False)
    paddedNumString = "%04d" % numString
    letters_collection_name = "Letters." + paddedNumString
    letters_collection = bpy.data.collections.get(letters_collection_name)

    if letters_collection is None:
        letters_collection = bpy.data.collections.new(letters_collection_name)
        # Prefer parenting under this panel's Export collection, else the scene.
        export_collection = bpy.data.collections.get("Export." + paddedNumString)
        parent = export_collection if export_collection is not None else currScene.collection
        try:
            parent.children.link(letters_collection)
        except RuntimeError:
            pass
        print('[3DComicToolkit] Created missing ' + letters_collection_name)

    _b52_set_lc_exclude(letters_collection_name, False)
    return letters_collection

def loop_children_recursively(obj, children=[], reset=True):
    """returns all object child objects"""
    if reset:
        children = []
    for child in obj.children:
        isnt_root = not (child.type == 'EMPTY')
        if isnt_root and child not in children:
            children.append(child)
            children = loop_children_recursively(child, children, False)
    return children

def get_all_children(parent_object):
    tmp_child_objects = []
    child_objects = loop_children_recursively(parent_object, tmp_child_objects, False)
    return child_objects

def traverse_tree(t):
    yield t
    for child in t.children:
        yield from traverse_tree(child)

def parent_lookup(coll):
    parent_lookup = {}
    for coll in traverse_tree(coll):
        for c in coll.children.keys():
            parent_lookup.setdefault(c, coll.name)
    return parent_lookup

def get_parent_collection(coll):
    coll_name = coll.name
    C = bpy.context
    coll_scene = C.scene.collection
    coll_parents = parent_lookup(coll_scene)
    parent_collection_name = coll_parents.get(coll_name)
    parent_collection = bpy.data.collections.get(parent_collection_name)        
    return parent_collection

def getCurrentMaterialSwatch():
    panel_number = getCurrentPanelNumber(True)
    
    global material_swatch_object
    material_swatch_object = None  # [FIX 1/3] 所有路径均初始化，避免首次 backstage 为空时 UnboundLocalError
    material_swatch_object_name = "Materials.Global"
    try:
        toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global
    except Exception:
        toonfill_use_global = True
    if not toonfill_use_global:
        material_swatch_object_name = "Materials." + panel_number
    backstage_collection = getCurrentBackstageCollection()
    if backstage_collection:
            # bpy.context.view_layer.layer_collection.children[backstage_collection.name].exclude = False
            backstage_objects = backstage_collection.objects
            for mobj in backstage_objects:
                if material_swatch_object_name in mobj.name:
                    material_swatch_object = mobj
                    # bpy.context.view_layer.layer_collection.children[backstage_collection.name].exclude = True
    return material_swatch_object

def getMaterialSwatch(isGlobal):
    material_swatch_object = None  # [FIX 1/3] 初始化局部变量，避免 backstage=None 或找不到 Materials.* 时 UnboundLocalError
    if isGlobal:
        material_swatch_object_name = "Materials.Global"
    else:
        panel_number = getCurrentPanelNumber(True)
        material_swatch_object_name = "Materials." + panel_number
    backstage_collection = getCurrentBackstageCollection()
    if backstage_collection:
            backstage_objects = backstage_collection.objects
            for mobj in backstage_objects:
                if material_swatch_object_name in mobj.name:
                    material_swatch_object = mobj
    return material_swatch_object

def getSharedActorBlendFilenames(self, context):
    file_path = bpy.data.filepath
    file_dir = os.path.dirname(os.path.dirname(file_path))
    SharedActorFilepath =  file_dir + "\\blender\\shared\\actors\\"
    items =  [("none", " ", "none", 0)]
    actor_dir = os.path.dirname(SharedActorFilepath)
    files = []
    if os.path.isdir(actor_dir):
        files = [f for f in os.listdir(actor_dir) if f.endswith(".blend")]
    for file in files:
        filename = SharedActorFilepath + file
        stringFragments = file.split('_')
        asset_name = stringFragments[0]
        if os.path.exists(filename):
            items.append((file, asset_name, "",))
    return items

def swapSelectSharedActorUpdate(self, context):
    swapSelectSharedActor(self, context)
    return None

def swapSelectSharedActor(self, context):
    scene = context.scene
    targetFileName = scene.panel_settings.s3dc_shared_actor_blend_filenames
    file_path = bpy.data.filepath
    file_dir = os.path.dirname(os.path.dirname(file_path))
    filename =  file_dir + "\\blender\\shared\\actors\\" + targetFileName
    if os.path.exists(filename):
        # print("::::::::::::::::::" + filename)
        # with bpy.data.libraries.load(str(file)) as (data_from, data_to):
        #     object_names = [ob for ob in data_from.objects]
        # for object_name in object_names:
        #     items.append((object_name, object_name, ""))
        scene.panel_settings.s3dc_shared_actor_blend_filenames = "none"
        load_resource(self, context, filename, False)
    return True


#------------------------------------------------------
# scene tools

def set_active_language(self, context): 
    current_scene = bpy.context.scene
    currSceneIndex = getCurrentSceneIndex()
    current_scene_name = bpy.data.scenes[currSceneIndex].name
    active_language_index = current_scene["panel_settings"]["s3dc_language"]
    active_language = bpy.context.scene.panel_settings.s3dc_language
    if not active_language:
        current_scene["panel_settings"]["language"] = 0
    print(active_language)
    panels = []
    for scene in bpy.data.scenes:
        if "p." in scene.name:
            panels.append(scene.name)
            # scene["panel_settings"]["language"] = active_language_index
            scene["panel_settings"]["language"] = active_language_index

    for panel in panels :
        for i in range(len(bpy.data.scenes)):
            if bpy.data.scenes[i].name == panel:
                bpy.context.window.scene = bpy.data.scenes[i]
                letters_collection = getCurrentLettersCollection()
                objects = letters_collection.objects
                for obj in objects:
                    if "Letters_" in obj.name and active_language not in obj.name:
                        bpy.ops.object.select_all(action='DESELECT')
                        objects = get_all_children(obj)
                        for c in objects:
                            c.hide_set(True)
                            c.hide_viewport = True


                    if "Letters_" in obj.name and active_language in obj.name:
                        # is_hidden = obj.hide_get()
                        # if is_hidden:
                        #     obj.hide_set(False)
                        #     obj.hide_viewport = False
                        bpy.ops.object.select_all(action='DESELECT')
                        objects = get_all_children(obj)
                        for c in objects:
                            c.hide_set(False)
                            c.hide_viewport = False


    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.window.scene = bpy.data.scenes[currSceneIndex]
    bpy.context.window_manager.popup_menu(warn_language_set, title="SUCCESS", icon='ERROR')
    return {'None'} 

def renameAllScenesAfter(self, context):
    startingSceneIndex = getCurrentSceneIndex()
    backstage_collection = getCurrentBackstageCollection()

    # panels = []
    # for scene in bpy.data.scenes:
    #     if "p." in scene.name:
    #         panels.append(scene.name)
    for iSceneIndex in range(len(bpy.data.scenes) -1,startingSceneIndex, -1 ):        
        if "p." in bpy.data.scenes[iSceneIndex].name:
            scene = bpy.data.scenes[iSceneIndex]
            oldSceneIndex = iSceneIndex - 1
            newPanelNumber = "%04d" % iSceneIndex
            oldPanelNumber = "%04d" % oldSceneIndex

            stringFragments = bpy.data.scenes[iSceneIndex].name.split('.')
            x_stringFragments = stringFragments[2]
            xx_stringFragments = x_stringFragments.split('h')
            current_panel_height = xx_stringFragments[1]
            xxx_stringFragments = xx_stringFragments[0].split('w')
            current_panel_width = xxx_stringFragments[1]
            scene.name = 'p.'+ str(newPanelNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)

            # print("=======DEBUG: " + scene.name)
            # raise KeyboardInterrupt()


        # m = currSceneIndex -1
        # if m > currScene:
        #     if "p." in bpy.data.scenes[m].name:
        #         scene = bpy.data.scenes[m]
        #         n = currSceneIndex
        #         nn = currSceneIndex - 1

        #         sceneNumber = "%04d" % n
        #         oldSceneNumber = "%04d" % nn




        #         # scene.name = 'p.'+ str(sceneNumber) + ".w100h100"

        #         stringFragments = bpy.data.scenes[m].name.split('.')
        #         x_stringFragments = stringFragments[2]
        #         xx_stringFragments = x_stringFragments.split('h')
        #         current_panel_height = xx_stringFragments[1]
        #         xxx_stringFragments = xx_stringFragments[0].split('w')
        #         current_panel_width = xxx_stringFragments[1]


            scene.name = 'p.'+ str(newPanelNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)

            if backstage_collection:
                _b52_set_lc_exclude(backstage_collection.name, False)

            scene_objects = scene.objects
            for obj in scene_objects:
                if newPanelNumber in obj.name:
                    obj.name = obj.name.replace(oldPanelNumber, newPanelNumber)

            scene_collections = scene.collection.children
            for col in scene_collections:
                if oldPanelNumber in col.name:
                    col.name = col.name.replace(oldPanelNumber, newPanelNumber)

            scene_cameras = scene.collection.children
            for col in scene_collections:
                if oldPanelNumber in col.name:
                    col.name = col.name.replace(oldPanelNumber, newPanelNumber)

        if backstage_collection:
            _b52_set_lc_exclude(backstage_collection.name, True)

    return {'FINISHED'}

def load_resource(self, context, blendFileName, is_random):
    global previous_random_int
    global addon_resources_dir
    _lr_obj = getattr(bpy.context, 'object', None)
    if _lr_obj:
        if "OBJECT" not in _lr_obj.mode:
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
            bpy.ops.object.select_all(action='DESELECT')

    currSceneIndex = getCurrentSceneIndex()
    export_collection = getCurrentExportCollection(self, context)
    if export_collection:
        export_collection_name = export_collection.name
        def _find_lc(lc, name):
            if lc.collection.name == name:
                return lc
            for c in lc.children:
                r = _find_lc(c, name)
                if r:
                    return r
            return None
        _target_lc = _find_lc(bpy.context.view_layer.layer_collection, export_collection_name)
        if _target_lc:
            bpy.context.view_layer.active_layer_collection = _target_lc
    else:
        panelNumber = getCurrentPanelNumber(True)
        export_collection_name = "Export." + panelNumber
        export_collection =  bpy.data.collections.new(export_collection_name)
        bpy.context.scene.collection.children.link(export_collection)

    scene_collections = bpy.data.scenes[currSceneIndex].collection.children
    # objects = context.selected_objects
    # if objects is not None :
    #     bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    #     bpy.ops.object.select_all(action='DESELECT')

    user_dir = os.path.expanduser("~")
    # common_subdir = "2.90/scripts/addons/3DComicToolkit/Resources/"   this fails on github installs because the name is Spiraloid-
    # common_subdir = "2.90/scripts/addons/Spiraloid-Toolkit-for-Blender-3DComicToolkit/Resources/"
    # if system() == 'Linux':
    #     addon_path = "/.config/blender/" + common_subdir
    # elif system() == 'Windows':
    #     addon_path = (
    #         "\\AppData\\Roaming\\Blender Foundation\\Blender\\"
    #         + common_subdir.replace("/", "\\")
    #     )
    #     # os.path.join()
    # elif system() == 'Darwin':
    #     addon_path = "/Library/Application Support/Blender/" + common_subdir
    # addon_dir = user_dir + addon_path


    # user = bpy.utils.user_resource('SCRIPTS', "addons\\test2\\")
    use_addon_resource = False
    if not os.path.exists(blendFileName):
        use_addon_resource = True
        # scripts_dir = bpy.utils.user_resource('SCRIPTS', "addons")
        # addon_resources_subdir = "/Spiraloid-Toolkit-for-Blender-3DComicToolkit-master/Resources/"
        addon_dir =  addon_resources_dir
        extractedBlendFileName = blendFileName
    else:
        use_addon_resource = False
        addon_dir = os.path.dirname(os.path.dirname(blendFileName))
        extractedBlendFileName = os.path.basename(os.path.dirname(blendFileName))

    if is_random:
        stringFragments = extractedBlendFileName.split('.')
        index = []     
        for file in os.listdir(addon_dir):
            if file.startswith(stringFragments[0]+"."):
                if not file.endswith(".blend1"):
                    index.append(file)
        i = len(index) -1
        if i >= 0:
            random_int = random.randint(0, i)
            while (random_int == previous_random_int):
                random_int = random.randint(0, i)
                if (random_int != previous_random_int):
                    break
        else:
            random_int = 0
        padded_random_int = "%03d" % random_int
        filepath = addon_dir + stringFragments[0] + "." + padded_random_int + ".blend"
        previous_random_int = random_int
    else:
        if use_addon_resource:
            filepath = addon_dir + blendFileName
        else:
            filepath = blendFileName


    context = bpy.context
    resourceSceneIndex = 0
    scenes = []
    mainCollection = context.scene.collection

    

    if use_addon_resource:
        with bpy.data.libraries.load(filepath ) as (data_from, data_to):
            for name in data_from.scenes:
                scenes.append({'name': name})
            data_to.scenes = data_from.scenes
        scenes = bpy.data.scenes[-len(scenes):]
        resourceSceneIndex = -len(scenes)
        if resourceSceneIndex != 0 :
            nextScene =  bpy.data.scenes[resourceSceneIndex]
            loaded_scene_collections = bpy.data.scenes[resourceSceneIndex].collection.children
            
            for coll in loaded_scene_collections:
                bpy.ops.object.make_local(type='ALL')
                bpy.ops.object.select_all(action='DESELECT')
                for obj in coll.all_objects:
                    bpy.context.collection.objects.link(obj)  
                    obj.select_set(state=True)
                    bpy.context.view_layer.objects.active = obj
        bpy.data.scenes.remove(nextScene)
    else:
        master_collection = bpy.context.scene.collection
        extractedBlendFileName = os.path.basename(blendFileName)
        stringFragments = extractedBlendFileName.split('_')
        asset_name = stringFragments[0]
        with bpy.data.libraries.load(filepath, link=True, relative=True ) as (data_from, data_to):
            data_to.collections = data_from.collections
        for new_coll in data_to.collections:
            new_coll_name = new_coll.name
            if asset_name in new_coll_name:
                paddedNumString = getCurrentPanelNumber(True)
                new_asset_coll_name = asset_name + str(paddedNumString)
                new_coll.name = new_asset_coll_name
                def _find_lc(lc, name):
                    if lc.collection.name == name:
                        return lc
                    for c in lc.children:
                        r = _find_lc(c, name)
                        if r:
                            return r
                    return None
                _target_lc = _find_lc(bpy.context.view_layer.layer_collection, export_collection_name)
                if _target_lc:
                    bpy.context.view_layer.active_layer_collection = _target_lc
                instance = bpy.data.objects.new(new_asset_coll_name, None)
                instance.instance_type = 'COLLECTION'
                instance.instance_collection = new_coll
                export_collection.children.link(new_coll)
                collection_objects = new_coll.all_objects
                for obj in collection_objects:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(state=True)
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.make_override_library(collection=new_asset_coll_name)
                    bpy.data.collections.remove(new_coll)
                    linked_override_collection = bpy.context.selected_objects[0].users_collection[0]
                    export_collection.children.link(linked_override_collection)
            bpy.data.scenes[currSceneIndex].collection.children.unlink(linked_override_collection)
            # bpy.data.scenes[currSceneIndex].collection.children.unlink(linked_override_collection)
            # obj["shared_asset_filepath"] = filepath


        # for scene in scenes:
        #     for coll in scene.collection.children:
        #         bpy.ops.object.select_all(action='DESELECT')
        #         for obj in coll.all_objects:
        #             bpy.context.collection.objects.link(obj)  
        #             obj.select_set(state=True)
        #             bpy.context.view_layer.objects.active = obj
        #     bpy.data.scenes.remove(scene)

    return {'FINISHED'}

def load_shared_resource(self, context, blendFileName, is_random):
    global previous_random_int
    global addon_resources_dir

    shared_asset_filepath = ""
    if bpy.context.object:
        if "OBJECT" not in bpy.context.object.mode:
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
            bpy.ops.object.select_all(action='DESELECT')

    currSceneIndex = getCurrentSceneIndex()
    export_collection = getCurrentExportCollection(self, context)
    if export_collection:
        export_collection_name = export_collection.name
        def _find_lc(lc, name):
            if lc.collection.name == name:
                return lc
            for c in lc.children:
                r = _find_lc(c, name)
                if r:
                    return r
            return None
        _target_lc = _find_lc(bpy.context.view_layer.layer_collection, export_collection_name)
        if _target_lc:
            bpy.context.view_layer.active_layer_collection = _target_lc
    else:
        panelNumber = getCurrentPanelNumber(True)
        export_collection_name = "Export." + panelNumber
        export_collection =  bpy.data.collections.new(export_collection_name)
        bpy.context.scene.collection.children.link(export_collection)

    scene_collections = bpy.data.scenes[currSceneIndex].collection.children
    user_dir = os.path.expanduser("~")

    # scripts_dir = bpy.utils.user_resource('SCRIPTS', "addons")
    # addon_resources_subdir = "/Spiraloid-Toolkit-for-Blender-3DComicToolkit-master/Resources/"        
    # addon_dir = scripts_dir + addon_resources_subdir
    addon_dir = addon_resources_dir

    stringFragments = blendFileName.split('.')
    if is_random:
        index = []     
        for file in os.listdir(addon_dir):
            if file.startswith(stringFragments[0]+"."):
                if not file.endswith(".blend1"):
                    index.append(file)
        if (len(index) > 1):
            random_int = random.randint(0, len(index) -1)
            while (random_int == previous_random_int):
                random_int = random.randint(0, len(index) -1)
                if (random_int != previous_random_int):
                    break
        else:
            random_int = 0
        padded_random_int = "%03d" % random_int
        template_filepath = addon_dir + stringFragments[0] + "." + padded_random_int + ".blend"
        template_glb_filepath = addon_dir + stringFragments[0] + "." + padded_random_int + ".glb"
        previous_random_int = random_int
    else:
        template_filepath = addon_dir + blendFileName
        template_glb_filepath = addon_dir + stringFragments[0] + ".glb"


    if os.path.exists(template_filepath):
        # 5.2 FIX: shared assets must be stored under the project root, not Blender install shared dir
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shared_assets_folder = os.path.join(project_root, 'panels', 'shared')
        os.makedirs(shared_assets_folder, exist_ok=True)
        template_basefilename = os.path.basename(template_filepath)
        shared_asset_filepath = os.path.join(shared_assets_folder, template_basefilename)

        if not os.path.exists(shared_asset_filepath):
            shutil.copy(template_filepath, shared_asset_filepath)

    if os.path.exists(template_glb_filepath):
        # 5.2 FIX: keep GLB copies alongside the project local shared assets folder
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shared_glb_path = os.path.join(project_root, 'panels', 'shared')
        os.makedirs(shared_glb_path, exist_ok=True)
        template_glb_basefilename = os.path.basename(template_glb_filepath)
        if os.path.exists(shared_glb_path):
            shared_asset_glb_filepath = os.path.join(shared_glb_path, template_glb_basefilename)
            shutil.copy(template_glb_filepath, shared_asset_glb_filepath)
        else:
            self.report({'ERROR'}, "No Comic folders Found")

    if os.path.exists(shared_asset_filepath):
        context = bpy.context
        resourceSceneIndex = 0
        # scenes = []
        with bpy.data.libraries.load(shared_asset_filepath, link=True, relative=True ) as (data_from, data_to):
            data_to.collections = data_from.collections

        for new_coll in data_to.collections:
            if stringFragments[0] in new_coll.name:
                # instance = bpy.data.collections.new(new_coll.name )
                # instance.instance_type = 'COLLECTION'
                # instance.instance_collection = new_coll
                export_collection.children.link(new_coll)
                new_coll_name = new_coll.name
                # for obj in new_coll.all_objects:
                obj = new_coll.all_objects[0]
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(state=True)
                bpy.context.view_layer.objects.active = obj
                # if obj.type == 'ARMATURE':
                #     bpy.ops.object.make_override_library(collection=new_coll_name)
                # # raise KeyboardInterrupt()
                #     # export_collection.children.link(linked_override)

                #     bpy.data.collections.remove(new_coll)
                #     linked_override_collection = bpy.context.selected_objects[0].users_collection[0]
                #     export_collection.children.link(linked_override_collection)
                #     bpy.data.scenes[currSceneIndex].collection.children.unlink(linked_override_collection)
                # else:
                    # raise KeyboardInterrupt()
                bpy.ops.object.make_override_library(collection=new_coll_name)
                bpy.data.collections.remove(new_coll)
                linked_override_collection = bpy.context.selected_objects[0].users_collection[0]
                export_collection.children.link(linked_override_collection)
                bpy.data.scenes[currSceneIndex].collection.children.unlink(linked_override_collection)
                obj["shared_asset_filepath"] = shared_asset_filepath


            # for name in data_from.scenes:
            #     scenes.append({'name': name})
            # action = bpy.ops.wm.link
            # action(directory=filepath + "/Collection/" + stringFragments[0], files=scenes )
            # scenes = bpy.data.scenes[-len(scenes):]

        # resourceSceneIndex = -len(scenes)
        # if resourceSceneIndex != 0 :
        #     nextScene =  bpy.data.scenes[resourceSceneIndex]
        #     loaded_scene_collections = bpy.data.scenes[resourceSceneIndex].collection.children
        #     shared_asset_collections = bpy.data.collections.get("Shared Assets")
            
        #     for coll in loaded_scene_collections:
        #         bpy.ops.object.make_local(type='ALL')
        #         bpy.ops.object.select_all(action='DESELECT')
        #         for obj in coll.all_objects:
        #             bpy.context.collection.objects.link(obj)  
        #             obj.select_set(state=True)
        #             bpy.context.view_layer.objects.active = obj

        #             for shared_c in shared_asset_collections.children:
        #                 if category_name in shared_c.name:
        #                     shared_c.objects.link(obj)  

        #     bpy.data.scenes.remove(nextScene)




    return {'FINISHED'}

def validate_naming(self, context):
        currSceneIndex = getCurrentSceneIndex()
        currScene =  bpy.data.scenes[currSceneIndex]
        paddedSceneNumber = getCurrentPanelNumber(True)
        current_scene_name = bpy.data.scenes[currSceneIndex].name
        stringFragments = current_scene_name.split('.')
        x_stringFragments = stringFragments[2]
        xx_stringFragments = x_stringFragments.split('h')
        current_panel_height = xx_stringFragments[1]
        xxx_stringFragments = xx_stringFragments[0].split('w')
        current_panel_width = xxx_stringFragments[1]
        # panelSceneName = 'p.'+ str(paddedSceneNumber) + ".w100h100"
        panelSceneName = 'p.'+ str(paddedSceneNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)
        bpy.data.scenes[currSceneIndex].name = panelSceneName
        # renameAllScenesAfter(self, context)

        scene_collections = bpy.data.scenes[currSceneIndex].collection.children
        for c in scene_collections:
            if "Export." in c.name:
                export_collection = c
                c.name = "Export." + str(paddedSceneNumber) 
            if "Wip." in c.name:
                wip_collection = c
                c.name = "Wip." + str(paddedSceneNumber) 
            if "Lighting." in c.name:
                c.name = "Lighting." + str(paddedSceneNumber) 
            if "Letters." in c.name:
                c.name = "Letters." + str(paddedSceneNumber) 
            if "Backstage." in c.name:
                c.name = "Backstage." + str(paddedSceneNumber) 
            _b52_set_lc_exclude(c.name, False)

        letters_collection = getCurrentLettersCollection()
        backstage_collection = getCurrentBackstageCollection()
        if backstage_collection:
            panel_number = getCurrentPanelNumber(True)
            material_swatch_object_name = "Materials." + panel_number
            backstage_collection = getCurrentBackstageCollection()
            if backstage_collection:
                backstage_objects = backstage_collection.objects
                for mobj in backstage_objects:
                    if "Materials.0" in mobj.name:
                        mobj.name = material_swatch_object_name
                        bpy.ops.object.select_all(action='DESELECT')
                        mobj.select_set(state=True)
                        bpy.context.view_layer.objects.active = mobj
                        for i, mat in reversed(list(enumerate(mobj.data.materials))):
                            mobj.active_material_index = i
                            active_mat =  mobj.active_material
                            active_mat_name = active_mat.name

                            stringFragments = active_mat_name.split('.')
                            active_mat_name_prefix = stringFragments[0]
                            new_material_name = active_mat_name_prefix + "." + panel_number
                            active_mat.name = new_material_name

                    if "Materials.Global" in mobj.name:
                        backstage_collection.objects.unlink(mobj)
                        empty_trash(self, context)
                        global_material_swatch_object = bpy.data.scenes[0].collection.children['Backstage.Global'].objects['Materials.Global']
                        backstage_collection.objects.link(global_material_swatch_object)
            relinkAllSwatchColors()

        # if backstage_collection:
        #     objects = backstage_collection.objects
        #     for obj in objects:
        #         if "Materials.Global" in obj.name:
        #             bpy.ops.object.select_all(action='DESELECT')
        #             obj.select_set(state=True)
        #             bpy.context.view_layer.objects.active = obj
        #             bpy.ops.object.delete()
        #             global_material_swatch_object = bpy.data.scenes[0].collection.children['Backstage.Global'].objects['Materials.Global']
        #             backstage_collection.objects.link(global_material_swatch_object)

        # if backstage_collection:
        #     objects = backstage_collection.objects
        #     for obj in objects:
        #         if "Materials." in obj.name:
        #             obj.name = "Materials." + str(paddedSceneNumber) 


        export_collection = getCurrentExportCollection(self, context)
        if export_collection:
            for c in export_collection.children:
                if "Lighting." in c.name:
                    c.name = "Lighting." + str(paddedSceneNumber) 

            objects = export_collection.objects
            for obj in objects:
                if "Camera." in obj.name:
                    bpy.context.scene.camera = bpy.data.objects[obj.name]
                    obj.name = 'Camera.'+ str(paddedSceneNumber)
                if "Camera_aim." in obj.name:
                    obj.name = 'Camera_aim.'+ str(paddedSceneNumber)

            letters_objects = letters_collection.objects
            for obj in letters_objects:

                has_letters_english = False
                has_letters_spanish = False
                has_letters_japanese = False
                has_letters_korean = False
                has_letters_german = False
                has_letters_french = False
                has_letters_dutch = False

                if "Letters_spanish." in obj.name:
                    obj.name = 'Letters_spanish.'+ str(paddedSceneNumber)
                    has_letters_spanish = True
                    active_language_abreviated = 'es'
                if "Letters_japanese." in obj.name:
                    obj.name = 'Letters_japanese.'+ str(paddedSceneNumber)
                    has_letters_japanese = True
                    active_language_abreviated = 'ja'
                if "Letters_korean." in obj.name:
                    obj.name = 'Letters_korean.'+ str(paddedSceneNumber)  
                    has_letters_korean = True
                    active_language_abreviated = 'ko'

                if "Letters_german." in obj.name:
                    obj.name = 'Letters_german.'+ str(paddedSceneNumber)
                    has_letters_german = True
                    active_language_abreviated = 'de'

                if "Letters_french." in obj.name:
                    obj.name = 'Letters_french.'+ str(paddedSceneNumber)  
                    has_letters_french = True
                    active_language_abreviated = 'fr'

                if "Letters_dutch." in obj.name:
                    obj.name = 'Letters_dutch.'+ str(paddedSceneNumber)  
                    has_letters_dutch = True
                    active_language_abreviated = 'da'

                if "Letters_eng." in obj.name:
                    obj.name = 'Letters_english.'+ str(paddedSceneNumber)

                if "Letters_english." in obj.name:
                    obj.name = 'Letters_english.'+ str(paddedSceneNumber)
                    has_letters_english = True
                    active_language_abreviated = 'en-US'

                    # if not has_letters_spanish:
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     ob = obj.copy()
                    #     object_collection = obj.users_collection[0].name
                    #     bpy.data.collections[object_collection].objects.link(ob)
                    #     ob.name = 'Letters_spanish.'+ str(paddedSceneNumber)

                    # if not has_letters_japanese:
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     ob = obj.copy()
                    #     object_collection = obj.users_collection[0].name
                    #     bpy.data.collections[object_collection].objects.link(ob)
                    #     ob.name = 'Letters_japanese.'+ str(paddedSceneNumber)

                    # if not has_letters_korean:
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     ob = obj.copy()
                    #     object_collection = obj.users_collection[0].name
                    #     bpy.data.collections[object_collection].objects.link(ob)
                    #     ob.name = 'Letters_korean.'+ str(paddedSceneNumber)

                    # if not has_letters_german:
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     ob = obj.copy()
                    #     object_collection = obj.users_collection[0].name
                    #     bpy.data.collections[object_collection].objects.link(ob)
                    #     ob.name = 'Letters_german.'+ str(paddedSceneNumber)

                    # if not has_letters_french:
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     ob = obj.copy()
                    #     object_collection = obj.users_collection[0].name
                    #     bpy.data.collections[object_collection].objects.link(ob)
                    #     ob.name = 'Letters_french.'+ str(paddedSceneNumber)
        else:
            self.report({'ERROR'}, 'No Export Collection Found!  Scene Must be reinitialized')

        for obj in currScene.objects:
            if "Lighting." in obj.name:
                obj.name = 'Lighting.'+ str(paddedSceneNumber)
            if "Key." in obj.name:
                obj.name = "Key." + str(paddedSceneNumber) 
            if "Turntable." in obj.name:
                obj.name = "Turntable." + str(paddedSceneNumber) 


        if backstage_collection:
            _b52_set_lc_exclude(backstage_collection.name, True)

        if currScene.world:
            currScene.world.name = "Sky." + paddedSceneNumber




def toggle_workmode(self, context, rendermode):
    global isWorkmodeToggled
    global currentSubdLevel
    global previous_mode
    global previous_selection
    global isWireframe
    global previous_toolbar_state
    global previous_region_ui_state
    global previous_gpencil_object

    if rendermode:
        isWorkmodeToggled = True        

    if previous_mode != 'PAINT_GPENCIL':
        if bpy.context.mode == 'OBJECT':
            previous_mode =  'OBJECT'
    else:
        previous_mode =  'PAINT_GPENCIL'

    _workspace = getattr(bpy.context, 'workspace', None)
    if bpy.app.background or _workspace is None:
        return

    if bpy.context.mode == 'EDIT_MESH':
        previous_mode =  'EDIT'
        _sd = getattr(bpy.context, 'space_data', None)
        if _sd is not None and getattr(_sd, 'overlay', None) is not None:
            _sd.overlay.show_overlays = False
    if bpy.context.mode == 'POSE':
        previous_mode =  'POSE'
        _sd = getattr(bpy.context, 'space_data', None)
        if _sd is not None and getattr(_sd, 'overlay', None) is not None:
            _sd.overlay.show_bones = True
    if bpy.context.mode == 'SCULPT':
        previous_mode =  'SCULPT'
    if bpy.context.mode == 'PAINT_VERTEX':
        previous_mode =  'VERTEX_PAINT'
    if bpy.context.mode == 'WEIGHT_PAINT':
        previous_mode =  'WEIGHT_PAINT'
    if bpy.context.mode == 'TEXTURE_PAINT':
        previous_mode =  'TEXTURE_PAINT'
    if bpy.context.mode == 'PAINT_GPENCIL':
        previous_mode =  'PAINT_GPENCIL'
        previous_gpencil_object = bpy.context.active_object


    my_areas = _workspace.screens[0].areas
    for area in my_areas:
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                my_shading = 'WIREFRAME'  # 'WIREFRAME' 'SOLID' 'MATERIAL' 'RENDERED'
                space.overlay.show_overlays = True
                space.overlay.show_floor = True
                space.overlay.show_axis_x = True
                space.overlay.show_axis_y = True
                space.overlay.show_outline_selected = True
                space.overlay.show_cursor = True
                space.overlay.show_extras = True
                space.overlay.show_relationship_lines = True
                space.overlay.show_bones = True
                space.overlay.show_motion_paths = True
                space.overlay.show_object_origins = True
                space.overlay.show_annotation = True
                space.overlay.show_text = True
                space.overlay.show_stats = True
                previous_toolbar_state = space.show_region_toolbar
                previous_region_ui_state = space.show_region_ui


                if isWorkmodeToggled:
                    previous_selection = bpy.context.selected_objects
                    space.overlay.show_overlays = True
                    space.overlay.show_floor = False
                    space.overlay.show_axis_x = False
                    space.overlay.show_axis_y = False
                    space.overlay.show_cursor = False
                    space.overlay.show_relationship_lines = False
                    space.overlay.show_bones = False
                    space.overlay.show_motion_paths = False
                    space.overlay.show_object_origins = False
                    space.overlay.show_annotation = False
                    space.overlay.show_text = False
                    space.overlay.show_stats = False
                    space.overlay.show_outline_selected = False
                    space.overlay.show_extras = False
                    space.show_gizmo = False
                    space.overlay.show_text = False
                    space.overlay.show_stats = False
                    space.show_region_toolbar = previous_toolbar_state
                    space.show_region_ui = previous_region_ui_state
                    # space.show_region_header = False



                    selected_objects = bpy.context.selected_objects
                    if not selected_objects:
                        space.overlay.show_outline_selected = True


                    space.overlay.wireframe_threshold = 1
                    if space.overlay.show_wireframes:
                        isWireframe = True
                        space.overlay.show_outline_selected = True
                        space.overlay.show_extras = True
                        space.overlay.show_overlays = True
                        space.overlay.show_text = True
                        space.overlay.show_stats = True


                        # bpy.context.space_data.overlay.show_cursor = True
                    else:
                        isWireframe = False
                        # bpy.context.space_data.overlay.show_outline_selected = False
                        # bpy.context.space_data.overlay.show_extras = False

                    # bpy.context.space_data.overlay.show_wireframes = False

                    if bpy.context.scene.render.engine == 'BLENDER_EEVEE':
                        # bpy.context.scene.eevee.use_bloom = True
                        # bpy.context.scene.eevee.use_ssr = True
                        my_shading =  'MATERIAL'

                        lights = [o for o in bpy.context.scene.objects if o.type == 'LIGHT']
                        if (lights):
                            space.shading.use_scene_lights = True
                            space.shading.use_scene_world = True
                        else:
                            space.shading.use_scene_lights = True
                            space.shading.use_scene_world = False

                        if bpy.context.scene.world:
                            space.shading.use_scene_world = True
                        else:
                            space.shading.use_scene_world = False


                    if bpy.context.scene.render.engine == 'CYCLES':
                        my_shading =  'RENDERED'
                        lights = [o for o in bpy.context.scene.objects if o.type == 'LIGHT']
                        # if (lights):
                        #     bpy.context.space_data.shading.use_scene_lights_render = True
                        # else:
                        #     bpy.context.space_data.shading.use_scene_lights = False
                        #     bpy.context.space_data.shading.studiolight_intensity = 1


                        if bpy.context.scene.world is None:
                            if (lights):
                                space.shading.use_scene_world_render = False
                                space.shading.studiolight_intensity = 0.01
                            else:
                                space.shading.use_scene_world_render = False
                                space.shading.studiolight_intensity = 1
                        else:
                            space.shading.use_scene_world_render = True
                            if (lights):
                                space.shading.use_scene_lights_render = True

                    if previous_mode == 'PAINT_GPENCIL':
                        if previous_gpencil_object:
                            selected_object = bpy.context.view_layer.objects.active
                            if selected_object:
                                if selected_object.type == 'GPENCIL':
                                    bpy.ops.gpencil.paintmode_toggle()
                                    bpy.context.mode == 'PAINT_GPENCIL'


                else:
                    space.overlay.show_overlays = True
                    space.overlay.show_cursor = True
                    space.overlay.show_floor = True
                    space.overlay.show_axis_x = True
                    space.overlay.show_axis_y = True
                    space.overlay.show_extras = True
                    space.overlay.show_relationship_lines = False
                    space.overlay.show_bones = True
                    space.overlay.show_motion_paths = True
                    space.overlay.show_object_origins = True
                    space.overlay.show_annotation = True
                    space.overlay.show_text = True
                    space.overlay.show_stats = True
                    space.overlay.wireframe_threshold = 1
                    space.show_gizmo = True
                    # space.show_region_header = True
                    space.show_region_toolbar = previous_toolbar_state
                    space.show_region_ui = previous_region_ui_state


                    if previous_mode == 'EDIT':
                        if not len(bpy.context.selected_objects):
                            bpy.ops.object.editmode_toggle()
                        # else:
                        #     for ob in previous_selection :
                        #         # if ob.type == 'MESH' : 
                        #         ob.select_set(state=True)
                        #         bpy.context.view_layer.objects.active = ob
                        #     bpy.ops.object.editmode_toggle()

                    if previous_mode == 'PAINT_GPENCIL':
                        if previous_gpencil_object:
                            # bpy.ops.object.select_all(action='DESELECT')

                            try:
                                previous_gpencil_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = previous_gpencil_object
                                bpy.ops.gpencil.paintmode_toggle()
                            except:
                                pass

                            my_shading = 'MATERIAL'
                            space.overlay.show_overlays = True
                            space.overlay.show_cursor = True
                            space.overlay.show_floor = True
                            space.overlay.show_axis_x = True
                            space.overlay.show_axis_y = True
                            space.overlay.show_extras = True
                            space.overlay.show_relationship_lines = False
                            space.overlay.show_bones = True
                            space.overlay.show_motion_paths = True
                            space.overlay.show_object_origins = True
                            space.overlay.show_annotation = True
                            space.overlay.show_text = True
                            space.overlay.show_stats = True
                            space.overlay.wireframe_threshold = 1
                            space.overlay.show_fade_inactive = False
                            space.show_gizmo = True

                            # space.show_region_header = True
                            space.show_region_toolbar = previous_toolbar_state
                            space.show_region_ui = previous_region_ui_state



                    if previous_mode == 'VERTEX_PAINT':
                        my_shading = 'SOLID'
                        space.shading.light = 'FLAT'


                    if previous_mode == 'SCULPT':
                        my_shading =  'SOLID'
                        space.shading.color_type = 'MATERIAL'
                        space.overlay.show_floor = False
                        space.overlay.show_axis_x = False
                        space.overlay.show_axis_y = False
                        space.overlay.show_cursor = False
                        space.overlay.show_relationship_lines = False
                        space.overlay.show_bones = False
                        space.overlay.show_motion_paths = False
                        space.overlay.show_object_origins = False
                        space.overlay.show_annotation = False
                        space.overlay.show_text = False
                        space.overlay.show_text = False
                        space.overlay.show_outline_selected = False
                        space.overlay.show_extras = False
                        space.overlay.show_overlays = True
                        space.show_gizmo = False

                    if previous_mode == 'EDIT' or previous_mode == 'OBJECT' or previous_mode == 'POSE':
                        my_shading = 'SOLID'
                        # for ob in bpy.context.scene.objects:
                        #     if ob.type == 'MESH':
                        #         if ob.data.vertex_colors:
                        #             bpy.context.space_data.shading.color_type = 'VERTEX'
                        #         else:
                        #             bpy.context.space_data.shading.color_type = 'RANDOM'


                    if isWireframe:
                        space.overlay.show_wireframes = True
                    else:
                        space.overlay.show_wireframes = False
                    space.shading.color_type = 'RANDOM'
                    space.shading.show_backface_culling = False
                    space.shading.show_shadows = True


    for obj in bpy.context.scene.objects:
        # if obj.visible_get and obj.type == 'MESH':
        if obj.visible_get :
            
            # for mod in [m for m in obj.modifiers if m.type == 'MULTIRES']:
            #     mod_max_level = mod.render_levels
            #     if isWorkmodeToggled:
            #         currentSubdLevel = mod.levels
            #         mod.levels = mod_max_level
            #         mod.sculpt_levels = mod_max_level
            #     if not isWorkmodeToggled:
            #         mod.levels = currentSubdLevel
            #         mod.sculpt_levels = currentSubdLevel
            #         if currentSubdLevel != 0:
            #             bpy.context.space_data.overlay.show_wireframes = False


            # for mod in [m for m in obj.modifiers if m.type == 'SUBSURF']:
            #     mod_max_level = mod.render_levels
            #     if isWorkmodeToggled:
            #         currentSubdLevel = mod.levels
            #         mod.levels = mod_max_level
            #     if not isWorkmodeToggled:
            #         mod.levels = currentSubdLevel
            #         if currentSubdLevel != 0:
            #             bpy.context.space_data.overlay.show_wireframes = False

            scene = bpy.context.scene
            if isWorkmodeToggled:
                is_toon_shaded = obj.get("is_toon_shaded")
                if is_toon_shaded:
                    for mod in obj.modifiers:
                        mod_name = mod.name
                        if 'InkThickness' in mod_name:
                            obj.modifiers["InkThickness"].show_viewport = True
                        if 'WhiteOutline' in mod_name:
                            obj.modifiers["WhiteOutline"].show_viewport = True
                        if 'BlackOutline' in mod_name:
                            obj.modifiers["BlackOutline"].show_viewport = True
            else:
                is_toon_shaded = obj.get("is_toon_shaded")
                if is_toon_shaded:
                    for mod in obj.modifiers:
                        mod_name = mod.name
                        if 'InkThickness' in mod_name:
                            obj.modifiers["InkThickness"].show_viewport = False
                        if 'WhiteOutline' in mod_name:
                            obj.modifiers["WhiteOutline"].show_viewport = False
                        if 'BlackOutline' in mod_name:
                            obj.modifiers["BlackOutline"].show_viewport = False
                     
        

                # bpy.ops.object.mode_set(mode=previous_mode, toggle=False)


            # for area in my_areas:
            #     for space in area.spaces:
            #         if space.type == 'VIEW_3D':
            #             space.shading.type = my_shading

    # set viewport display
    for area in  bpy.context.screen.areas:  # iterate through areas in current screen
        if area.type == 'VIEW_3D':
            for space in area.spaces:  # iterate through spaces in current VIEW_3D area
                if space.type == 'VIEW_3D':  # check if space is a 3D view
                    # space.shading.type = 'MATERIAL'  # set the viewport shading to material
                    space.shading.type = my_shading
                    try: 
                        if scene.world is not None:
                            space.shading.use_scene_world = True
                            space.shading.use_scene_lights = True
                    except:
                        pass

                            

    for image in bpy.data.images:
        image.reload()

    isWorkmodeToggled = not isWorkmodeToggled
    return {'FINISHED'}

def add_ao(self, context, objects):
    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)                
    selected_objects = objects 
    if selected_objects is not None :
        # ob = bpy.context.view_layer.objects.active
        for ob in selected_objects:
            if ob.type == 'MESH':
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                if ob.active_material is not None:
                    mat =  ob.active_material
                    mat.use_nodes = True
                    ao_group_name = 'AO group'

                    gnodes = [n for n in mat.node_tree.nodes if n.name == ao_group_name]
                    print(gnodes)
                    for g in gnodes:
                        g.select = True
                        matnodes.active = g
                        bpy.ops.node.delete_reconnect()


                    mat_output = mat.node_tree.nodes.get('Material Output')
                    shader_node = mat_output.inputs[0].links[0].from_node


                    group = bpy.data.node_groups.new(type="ShaderNodeTree", name= ao_group_name)

                    #Creating Group Input
                    # Blender 4.0+: use group.interface.new_socket() instead of group.inputs/outputs.new()
                    group.interface.new_socket(name="Input1", in_out='INPUT', socket_type='NodeSocketShader')
                    group.interface.new_socket(name="AO Intensity", in_out='INPUT', socket_type='NodeSocketFloat')
                    input_node = group.nodes.new("NodeGroupInput")
                    input_node.location = (0, 0)



                    #Creating Group Output
                    group.interface.new_socket(name="Output1", in_out='OUTPUT', socket_type='NodeSocketShader')
                    output_node = group.nodes.new("NodeGroupOutput")
                    output_node.location = (500, 0)


                    # Creating Principled bsdf Node
                    #You can create any node here which you think are required to be in the group as these will be created automatically in a group


                    # ao_group = mat.node_tree.nodes.new('ShaderNodeGroup')


                    # # ao_group.name = ao_group_name
                    # ao_group.node_tree = bpy.data.node_groups[mat.node_tree.name] 
                    # # ao_group.node_tree = bpy.data.node_groups['BASE SKP']
                    # D.node_groups['NodeGroup'].nodes['Group Input']
                    
                    # #  relink everything
                    # mat.node_tree.links.new(shader_node.outputs[0], ao_group.inputs[0])
                    # mat.node_tree.links.new(ao_group.outputs[0], mat_output.inputs[0])

                    # # ao_group_input = mat.node_tree.nodes.new('NodeGroupInput')
                    # # ao_group_output = mat.node_tree.nodes.new('NodeGroupOutput')

                    ao = group.nodes.new(type='ShaderNodeAmbientOcclusion')
                    black = group.nodes.new(type='ShaderNodeEmission')
                    mix = group.nodes.new(type='ShaderNodeMixShader')
                    gamma = group.nodes.new(type='ShaderNodeGamma')

                    ao.samples = 4
                    ao.inputs[1].default_value = 0.5

                    black.inputs[0].default_value = (0, 0, 0, 1)


                    mat_output = mat.node_tree.nodes.get('Material Output')
                    existing_shader = mat_output.inputs[0].links[0].from_node


                    group.links.new(ao.outputs[0], gamma.inputs[0])
                    group.links.new(gamma.outputs[0], mix.inputs[0])
                    group.links.new(black.outputs[0], mix.inputs[1])
                    # group.links.new(existing_shader.outputs[0], mix.inputs[2])
                    group.links.new(input_node.outputs[0], mix.inputs[2])
                    group.links.new(mix.outputs[0], mat_output.inputs[0])


                    #creating links between nodes in group
                    group.links.new(input_node.outputs[1], gamma.inputs[1])
                    group.links.new(mix.outputs[0], output_node.inputs[0])

                    # Putting Node Group to the node editor
                    tree = bpy.context.object.active_material.node_tree
                    group_node = tree.nodes.new("ShaderNodeGroup")
                    group_node.node_tree = group
                    group_node.location = (-40,0)

                    #connections bewteen node group to output 
                    links = tree.links    
                    link = links.new(group_node.outputs[0], mat_output.inputs[0])
                    link = links.new(shader_node.outputs[0], group_node.inputs[0])

                    #setup material slider ranges
                    # Blender 4.0+: access interface items for min/max_value
                    try:
                        group.inputs[1].name = "AO Intensity"
                        group.inputs[1].default_value = 3
                        group.inputs[1].min_value = 0
                        group.inputs[1].max_value = 50
                    except AttributeError:
                        # 4.0+ interface API: find the socket by name
                        for item in group.interface.items_tree:
                            if item.name == "AO Intensity":
                                item.default_value = 3
                                item.min_value = 0
                                item.max_value = 50
                                break
                # else:
                #     self.report({'ERROR'}, 'You must have a material assigned first!')
                    
        for ob in selected_objects:
            ob.select_set(state=True)
            bpy.context.view_layer.objects.active = ob
    return {'FINISHED'}

def outline(self,context,mesh_objects):
    panel_settings = bpy.context.scene.panel_settings
    toonfill_mode = panel_settings.s3dc_toonfill_mode
    toonfill_type = panel_settings.s3dc_toonfill_type
    # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    # bpy.ops.object.select_all(action='DESELECT')

    paddedNumString = getCurrentPanelNumber(True)
    backstage_collection = getCurrentBackstageCollection()
    if not backstage_collection:
        self.report({'INFO'}, 'No Backstage Collection found, initializng as 3D Comic Panel!')
        BR_OT_panel_init.execute(self, context)

    # material_swatch_object = getCurrentMaterialSwatch()
    global_material_swatch = getMaterialSwatch(True)
    export_collection = getCurrentExportCollection(self, context)
    backstage_collection = getCurrentBackstageCollection()
    backstage_collection_name = getCurrentBackstageCollectionName()
    toonfill_use_global_ink = bpy.context.scene.panel_settings.s3dc_toonfill_use_global_ink
    panel_number = getCurrentPanelNumber(True)
    panel_material_swatch = getMaterialSwatch(False)
    panel_material_swatch_name = panel_material_swatch.name
    global_material_swatch = getMaterialSwatch(True)
    global_material_swatch_name = global_material_swatch.name

    if toonfill_use_global_ink:
        material_swatch_object = global_material_swatch
    else:
        material_swatch_object = panel_material_swatch


    if backstage_collection:
        try:
            _b52_set_lc_exclude(backstage_collection_name, False)
        except:
            pass
    backstage_objects = backstage_collection.objects

    if bpy.context.mode != 'EDIT_MESH':
        for mesh_object in mesh_objects:
            # if mesh_object.type == 'MESH' or mesh_object.type == 'CURVE' or mesh_object.type == 'FONT':
            mesh_object_name = mesh_object.name
            if mesh_object_name != panel_material_swatch_name and  mesh_object_name != global_material_swatch_name:
                if mesh_object.type == 'MESH' :
                    is_insensitive = False
                    is_toon_shaded = mesh_object.get("is_toon_shaded")
                    if not is_toon_shaded:
                        if "ink" == toonfill_type or "toon" == toonfill_type or "clear" == toonfill_type  or "whiteout" == toonfill_type  or "blackout" == toonfill_type :
                            if mesh_object.active_material:
                                # mesh_object.active_material.use_nodes = True
                                # mesh_object.active_material.node_tree.nodes.clear()
                                # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                                mesh_object.data.materials.clear()
                            for mod in mesh_object.modifiers:
                                mod_name = mod.name
                                if 'InkThickness' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)
                                if 'WhiteOutline' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)
                                if 'BlackOutline' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)

                            for vgroup in mesh_object.vertex_groups:
                                if 'Ink_Thickness' in vgroup.name:
                                    mesh_object.vertex_groups.remove(vgroup)

                            try:
                                drivers_data = mesh_object.animation_data.drivers
                                for dr in drivers_data:  
                                    mesh_object.driver_remove(dr.data_path, -1)
                            except:
                                pass
                            
                            empty_trash(self, context)

                        if "ink" in toonfill_type:
                            ink_thickness = mesh_object.dimensions[1] * 0.035
                            if bpy.context.object:
                                if "OBJECT" not in bpy.context.object.mode:
                                    if "DRAW" in bpy.context.object.mode :
                                        bpy.ops.gpencil.paintmode_toggle(back=False)
                                        bpy.ops.object.select_all(action='DESELECT')
                                    else:
                                        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                                        bpy.ops.object.select_all(action='DESELECT')

                            mesh_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = mesh_object
                            # if "EDIT" not in bpy.context.object.mode:
                            bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                            if mesh_object.type == 'MESH':
                                bpy.ops.mesh.select_all(action='SELECT')
                            # if mesh_object.type == 'CURVE':
                            #     bpy.ops.curve.select_all(action='TOGGLE')

                                ink_thickness_vgroup_name = "Ink_Thickness"
                                mesh_object.vertex_groups.new(name = ink_thickness_vgroup_name)
                                ink_thickness_vgroup = mesh_object.vertex_groups[-1]
                                bpy.ops.object.vertex_group_assign()

                                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = mesh_object

                                # [P0-B] Always bind ink_thick_tex before use.
                                # It used to be assigned only inside the search
                                # loop, so a miss raised UnboundLocalError below.
                                ink_thick_tex = None

                                if not toonfill_use_global_ink:
                                    ink_thick_tex_name = "L_InkThickness." + str(paddedNumString)
                                    ink_thick_tex = bpy.data.textures.get(ink_thick_tex_name)

                                    if ink_thick_tex is None:
                                        ink_thick_tex = bpy.data.textures.new(ink_thick_tex_name, type='CLOUDS')

                                    ink_thick_tex.noise_type = 'SOFT_NOISE'
                                    ink_thick_tex.noise_depth = 0
                                    ink_thick_tex.nabla = 0.001
                                    ink_thick_tex.intensity = 0.99

                                    if material_swatch_object:
                                        objectInkSmoothnessDriver = ink_thick_tex.driver_add('noise_scale')
                                        objectInkSmoothnessDriver.driver.type = 'SUM'
                                        newVar = objectInkSmoothnessDriver.driver.variables.new()
                                        newVar.name = "ink_wobble"
                                        newVar.type = 'SINGLE_PROP'
                                        newVar.targets[0].id = material_swatch_object 
                                        newVar.targets[0].data_path = '["OutlineWobble"]'
                                        objectInkSmoothnessDriver.driver.expression =  "ink_wobble"
                                        objectInkSmoothnessDriver = "ink_wobble"
                                    else:
                                        ink_thick_tex.noise_scale = 0.3
                                else:
                                    ink_thick_tex_name = "L_InkThickness.Global"
                                    ink_thick_tex = bpy.data.textures.get(ink_thick_tex_name)
                                    # [P0-B] Global ink texture had no creation
                                    # path at all; create it so the modifier
                                    # below always receives a real texture.
                                    if ink_thick_tex is None:
                                        ink_thick_tex = bpy.data.textures.new(ink_thick_tex_name, type='CLOUDS')
                                        ink_thick_tex.noise_type = 'SOFT_NOISE'
                                        ink_thick_tex.noise_depth = 0
                                        ink_thick_tex.nabla = 0.001
                                        ink_thick_tex.intensity = 0.99
                                        ink_thick_tex.noise_scale = 0.3



                                ink_thick_mod = mesh_object.modifiers.new(name = 'InkThickness', type = 'VERTEX_WEIGHT_EDIT')
                                ink_thick_mod.vertex_group = ink_thickness_vgroup.name
                                ink_thick_mod.default_weight = 0
                                ink_thick_mod.use_add = True

                                ink_thick_mod.normalize = False
                                ink_thick_mod.falloff_type = 'STEP'
                                ink_thick_mod.invert_falloff = True
                                ink_thick_mod.mask_constant = 1
                                ink_thick_mod.mask_texture = ink_thick_tex
                                ink_thick_mod.mask_tex_use_channel = 'INT'
                                # ink_thick_mod.mask_tex_mapping = 'LOCAL'
                                ink_thick_mod.mask_tex_mapping = 'GLOBAL'

                            white_outline_mod = mesh_object.modifiers.new(name = 'WhiteOutline', type = 'SOLIDIFY')
                            white_outline_mod.use_flat_faces = True
                            white_outline_mod.use_flip_normals = True
                            white_outline_mod.thickness = -ink_thickness / 2
                            white_outline_mod.offset = -1
                            white_outline_mod.material_offset = 2
                            if mesh_object.type == 'MESH':
                                white_outline_mod.vertex_group = ink_thickness_vgroup.name
                            white_outline_mod.show_in_editmode = False
                            white_outline_mod.thickness_clamp = 0.5
                            white_outline_mod.thickness_vertex_group = 0.1


                            if not material_swatch_object:
                                mesh_object["OutlineThickness"] = 0.5


                            objectInkThicknessDriver = white_outline_mod.driver_add('thickness')
                            objectInkThicknessDriver.driver.type = 'SCRIPTED'
                            newVar = objectInkThicknessDriver.driver.variables.new()
                            newVar.name = "ink_thickness"
                            newVar.type = 'SINGLE_PROP'
                            if material_swatch_object:
                                newVar.targets[0].id = material_swatch_object 
                            else:
                                newVar.targets[0].id = mesh_object 
                            newVar.targets[0].data_path = '["OutlineThickness"]'
                            objectInkThicknessDriver.driver.expression =  "ink_thickness  * -0.1"
                            objectInkThicknessDriver = "ink_thickness * -.1"

                            if material_swatch_object:
                                objectInkSmoothnessDriver = white_outline_mod.driver_add('thickness_vertex_group')
                                objectInkSmoothnessDriver.driver.type = 'SUM'
                                newVar = objectInkSmoothnessDriver.driver.variables.new()
                                newVar.name = "ink_smooth"
                                newVar.type = 'SINGLE_PROP'
                                newVar.targets[0].id = material_swatch_object 
                                newVar.targets[0].data_path = '["OutlineSmooth"]'
                                objectInkSmoothnessDriver.driver.expression =  "ink_smooth"
                                objectInkSmoothnessDriver = "ink_smooth"



                            black_outline_mod = mesh_object.modifiers.new(name = 'BlackOutline', type = 'SOLIDIFY')
                            black_outline_mod.use_flip_normals = True
                            black_outline_mod.use_flat_faces = True

                            # black_outline_mod.thickness = ink_thickness 

                            thicknessDriver = black_outline_mod.driver_add('thickness')
                            thicknessDriver.driver.type = 'SCRIPTED'
                            newVar = thicknessDriver.driver.variables.new()
                            newVar.name = "thickness"
                            newVar.type = 'SINGLE_PROP'
                            newVar.targets[0].id = mesh_object 
                            newVar.targets[0].data_path = 'modifiers["WhiteOutline"].thickness'
                            # thicknessDriver.driver.expression =  "(thickness  * 1.15) - .02"
                            # thicknessDriver.driver.expression =  "(thickness  * -1) - (thickness  * 1)"
                            thicknessDriver.driver.expression =  "thickness  * -1.5"

                            factorDriver = black_outline_mod.driver_add('thickness_vertex_group')
                            factorDriver.driver.type = 'SCRIPTED'
                            newVar = factorDriver.driver.variables.new()
                            newVar.name = "thickness_vertex_group"
                            newVar.type = 'SINGLE_PROP'
                            newVar.targets[0].id = mesh_object 
                            newVar.targets[0].data_path = 'modifiers["WhiteOutline"].thickness_vertex_group'
                            factorDriver.driver.expression =  "thickness_vertex_group"


                            black_outline_mod.offset = 1
                            black_outline_mod.material_offset = 1
                            if mesh_object.type == 'MESH':
                                black_outline_mod.vertex_group = ink_thickness_vgroup.name
                            black_outline_mod.show_in_editmode = False
                            black_outline_mod.thickness_clamp = 0
                            # black_outline_mod.thickness_vertex_group = 0.2

                            decimators = []
                            for i in range(len(mesh_object.modifiers)):
                                mod = mesh_object.modifiers[i]
                                mod_name = mod.name
                                if 'Decimate' in mod_name:
                                    decimators.append(i)
                            if decimators:
                                firstDecimatorIndex = int(decimators[0])
                                ink_thick_mod_name = ink_thick_mod.name
                                white_outline_mod_name = white_outline_mod.name
                                black_outline_mod_name = black_outline_mod.name

                                # bpy.ops.object.modifier_move_to_index(modifier=black_outline_mod_name, index=firstDecimatorIndex)
                                # bpy.ops.object.modifier_move_to_index(modifier=white_outline_mod_name, index=firstDecimatorIndex)
                                # bpy.ops.object.modifier_move_to_index(modifier=ink_thick_mod_name, index=firstDecimatorIndex)

                            # bpy.ops.object.modifier_move_to_index(modifier=ink_thick_mod_name, firstDecimatorIndex)
                            # bpy.ops.object.modifier_move_to_index(modifier=white_outline_mod_name, firstDecimatorIndex)
                            # bpy.ops.object.modifier_move_to_index(modifier=black_outline_mod_name, firstDecimatorIndex)



                            # bpy.context.object.material_slots[1].link = 'DATA'
                            # bpy.ops.object.material_slot_add()
                            if "ink" == toonfill_type:
                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                material_swatch_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = material_swatch_object
                                bpy.ops.object.material_slot_copy()

                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = mesh_object
                                for i, mat in reversed(list(enumerate(mesh_object.data.materials))):
                                    mat_name = mat.name
                                    if "ink" not in toonfill_type:
                                        if "L_Toon." not in mat_name:
                                            # letter.data.materials.pop(index=i)
                                            mesh_object.active_material_index = i
                                            bpy.ops.object.material_slot_remove()
                                        # bpy.ops.object.material_slot_remove({'object': mesh_object})
                                    else:
                                        if "L_Toon." not in mat_name and "L_OutlineNoShadowLight." not in mat_name  and "L_OutlineNoShadowDark." not in mat_name :
                                            mesh_object.active_material_index = i
                                            bpy.ops.object.material_slot_remove()



                        if "toon" in toonfill_type:
                            hasVertexColor = False
                            if mesh_object.hide_select:
                                mesh_object.hide_select = False
                                is_insensitive = True

                            if backstage_collection:
                                # bpy.context.scene.collection.objects.link(mobj)
                                # bpy.ops.object.select_all(action='DESELECT')
                                # mesh_object.select_set(state=True)
                                # mobj.select_set(state=True)
                                # bpy.context.view_layer.objects.active = mobj
                                # bpy.ops.object.material_slot_copy()
                                # bpy.context.scene.collection.objects.unlink(mobj)
                                # bpy.ops.object.select_all(action='DESELECT')
                                # mesh_object.select_set(state=True)
                                # bpy.context.view_layer.objects.active = mesh_object

                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                material_swatch_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = material_swatch_object
                                bpy.ops.object.material_slot_copy()

                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = mesh_object
                                for i, mat in reversed(list(enumerate(mesh_object.data.materials))):
                                    mat_name = mat.name
                                    if "ink" not in toonfill_type:
                                        if "L_Toon." not in mat_name:
                                            # letter.data.materials.pop(index=i)
                                            mesh_object.active_material_index = i
                                            bpy.ops.object.material_slot_remove()
                                        # bpy.ops.object.material_slot_remove({'object': mesh_object})
                                    else:
                                        if "L_Toon." not in mat_name and "L_OutlineNoShadowLight." not in mat_name  and "L_OutlineNoShadowDark." not in mat_name :
                                            mesh_object.active_material_index = i
                                            bpy.ops.object.material_slot_remove()


                                for p in mesh_object.data.polygons:
                                    if p.material_index >= len(mesh_object.data.materials):
                                        p.material_index = -1
                                bpy.ops.object.select_all(action='DESELECT')
                                mesh_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = mesh_object
                            else:
                                if mesh_object.active_material:
                                    mesh_object.active_material.node_tree.nodes.clear()
                                    # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                                    mesh_object.data.materials.clear()


                                if mesh_object.active_material is None:
                                    if mesh_object.type == 'MESH':
                                        if mesh_object.data.vertex_colors:
                                            hasVertexColor = True

                                    assetName = mesh_object.name
                                    matName = (assetName + "Mat")
                                    mat = bpy.data.materials.new(name=matName)
                                    mat.use_nodes = True
                                    mat_output = mat.node_tree.nodes.get('Material Output')
                                    shader = mat_output.inputs[0].links[0].from_node
                                    nodes = mat.node_tree.nodes
                                    for node in nodes:
                                        if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                                            nodes.remove(node) 

                                    if (hasVertexColor):
                                        shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                    else:
                                        shader = mat.node_tree.nodes.new(type='ShaderNodeBsdfDiffuse')

                                    shaderToRGB_A = mat.node_tree.nodes.new(type='ShaderNodeShaderToRGB')
                                    ramp_A = mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
                                    light_path = mat.node_tree.nodes.new(type='ShaderNodeLightPath')
                                    mix_shader = mat.node_tree.nodes.new(type='ShaderNodeMixShader')


                                    shader.inputs[0].default_value = (1, 1,1, 1) # base color
                                    ramp_A.color_ramp.elements[0].position = 0.00
                                    ramp_A.color_ramp.elements[1].position = 0.09
                                    ramp_A.color_ramp.interpolation = 'CONSTANT'

                                    mat.node_tree.links.new(shader.outputs[0], shaderToRGB_A.inputs[0])
                                    mat.node_tree.links.new(shaderToRGB_A.outputs[0], ramp_A.inputs[0])
                                    mat.node_tree.links.new(ramp_A.outputs[0], mix_shader.inputs[2])
                                    mat.node_tree.links.new(light_path.outputs[0], mix_shader.inputs[0])
                                    mat.node_tree.links.new(mix_shader.outputs[0], mat_output.inputs[0])

                                    # for i in range(len(ob.material_slots)):
                                    #     bpy.context.object.active_material_index = i
                                    #     outline_mat = ob.active_material
                                    #     if "WhiteOutline" in outline_mat.name:
                                    #         for node in outline_mat.node_tree.nodes:
                                    #             if "Background" in node.name: 
                                    #                 shader = node

                                    #             if "BSDF" in node.name: 
                                    #                 shader = node
                                                    
                                    #             if shader:
                                    #                 ncolorNode = outline_mat.node_tree.nodes.new('ShaderNodeAttribute')
                                    #                 ncolorNode.attribute_name = vertexColorName
                                    #                 outline_mat.node_tree.links.new(shader.inputs[0], ncolorNode.outputs[0])


                                    if (hasVertexColor):
                                        vertexColorName = mesh_object.data.vertex_colors[0].name
                                        colorNode = mat.node_tree.nodes.new('ShaderNodeAttribute')
                                        colorNode.attribute_name = vertexColorName
                                        mat.node_tree.links.new(shader.inputs[0], colorNode.outputs[0])

                                    mesh_object["is_gradient"] = True              
                                    mesh_object["toon_color_light"] = [1.0,0.333,1.0,1.0]              
                                    mesh_object["toon_color_dark"] = [0.33,0.1,0.0,1.0]              

                                    if "ink" not in toonfill_mode:
                                        for mod in mesh_object.modifiers:
                                            mod_name = mod.name
                                            if 'InkThickness' in mod_name:
                                                bpy.ops.object.modifier_remove(modifier="InkThickness")
                                            if 'WhiteOutline' in mod_name:
                                                bpy.ops.object.modifier_remove(modifier="WhiteOutline")
                                            if 'BlackOutline' in mod_name:
                                                bpy.ops.object.modifier_remove(modifier="BlackOutline")

                                    # Assign it to object
                                    if mesh_object.data.materials:
                                        mesh_object.data.materials[0] = mat
                                    else:
                                        mesh_object.data.materials.append(mat)

                        # if "ink" == toonfill_type:
                        #     if backstage_collection:
                        #         # bpy.context.scene.collection.objects.link(mobj)
                        #         # bpy.ops.object.select_all(action='DESELECT')
                        #         # mesh_object.select_set(state=True)
                        #         # mobj.select_set(state=True)
                        #         # bpy.context.view_layer.objects.active = mobj
                        #         # bpy.ops.object.material_slot_copy()
                        #         # bpy.context.scene.collection.objects.unlink(mobj)
                        #         # bpy.ops.object.select_all(action='DESELECT')
                        #         # mesh_object.select_set(state=True)
                        #         # bpy.context.view_layer.objects.active = mesh_object

                        #         bpy.ops.object.select_all(action='DESELECT')
                        #         mesh_object.select_set(state=True)
                        #         material_swatch_object.select_set(state=True)
                        #         bpy.context.view_layer.objects.active = material_swatch_object
                        #         bpy.ops.object.material_slot_copy()

                        #         bpy.ops.object.select_all(action='DESELECT')
                        #         mesh_object.select_set(state=True)
                        #         bpy.context.view_layer.objects.active = mesh_object
                        #         for i, mat in reversed(list(enumerate(mesh_object.data.materials))):
                        #             if "ink" in toonfill_mode and "toon" in toonfill_mode:
                        #                 if ("L_Toon." not in mat.name) and  ("L_OutlineNoShadowLight." not in mat.name) and  ("L_OutlineNoShadowDark." not in mat.name):
                        #                     mesh_object.active_material_index = i
                        #                     bpy.ops.object.material_slot_remove()
                        #             else:
                        #                 if ("L_Ink." not in mat.name) and  ("L_OutlineNoShadowLight." not in mat.name) and  ("L_OutlineNoShadowDark." not in mat.name):
                        #                     mesh_object.active_material_index = i
                        #                     bpy.ops.object.material_slot_remove()

                        #         for p in mesh_object.data.polygons:
                        #             if p.material_index >= len(mesh_object.data.materials):
                        #                 p.material_index = -1
                        #         bpy.ops.object.select_all(action='DESELECT')
                        #         mesh_object.select_set(state=True)
                        #         bpy.context.view_layer.objects.active = mesh_object


                        #     else:
                        #         OutlineMatName = "BlackOutline"
                        #         matName = (OutlineMatName + "Mat")
                        #         mat = bpy.data.materials.new(name=matName)
                        #         mesh_object.data.materials.append(mat)             
                        #         mat.use_nodes = True
                        #         mat_output = mat.node_tree.nodes.get('Material Output')
                        #         shader = mat_output.inputs[0].links[0].from_node
                        #         nodes = mat.node_tree.nodes
                        #         for node in nodes:
                        #             if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                        #                 nodes.remove(node) 
                        #         shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                        #         shader.name = "Background"
                        #         shader.label = "Background"
                        #         shader.inputs[0].default_value = (0, 0, 0, 1)
                        #         mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])

                        #         mat.use_backface_culling = True
                        #         mat.shadow_method = 'NONE'

                        #         OutlineMatName = "WhiteOutline"
                        #         matName = (OutlineMatName + "Mat")
                        #         mat = bpy.data.materials.new(name=matName)
                        #         mesh_object.data.materials.append(mat)             
                        #         mat.use_nodes = True
                        #         mat_output = mat.node_tree.nodes.get('Material Output')
                        #         shader = mat_output.inputs[0].links[0].from_node
                        #         nodes = mat.node_tree.nodes
                        #         for node in nodes:
                        #             if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                        #                 nodes.remove(node) 
                        #         shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                        #         shader.name = "Background"
                        #         shader.label = "Background"
                        #         shader.inputs[0].default_value = (1, 1, 1, 1)
                        #         mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])
                        #         mat.use_backface_culling = True
                        #         mat.shadow_method = 'NONE'

                        try:
                            del mesh_object["is_toon_shaded"]
                        except:
                            pass 

                        if "clear" == toonfill_type:
                            if mesh_object.active_material:
                                # mesh_object.active_material.use_nodes = True
                                # mesh_object.active_material.node_tree.nodes.clear()
                                # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                                mesh_object.data.materials.clear()
                            for mod in mesh_object.modifiers:
                                mod_name = mod.name
                                if 'InkThickness' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)
                                if 'WhiteOutline' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)
                                if 'BlackOutline' in mod_name:
                                    bpy.ops.object.modifier_remove(modifier=mod.name)

                            for vgroup in mesh_object.vertex_groups:
                                vgroup_name = vgroup.name
                                if 'Ink_Thickness' in vgroup_name:
                                    mesh_object.vertex_groups.remove(vgroup)

                            try:
                                drivers_data = mesh_object.animation_data.drivers
                                for dr in drivers_data:  
                                    mesh_object.driver_remove(dr.data_path, -1)
                            except:
                                pass


                        if "whiteout" == toonfill_type or "blackout" == toonfill_type :
                            if mesh_object.active_material:
                                # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                                mesh_object.data.materials.clear()
                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            material_swatch_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = material_swatch_object
                            bpy.ops.object.material_slot_copy()

                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = mesh_object
                            for i, mat in reversed(list(enumerate(mesh_object.data.materials))):
                                mat_name = mat.name
                                if "whiteout" == toonfill_type:
                                    if "L_WhiteShadow." not in mat_name:
                                        mesh_object.active_material_index = i
                                        bpy.ops.object.material_slot_remove()
                                if "blackout" == toonfill_type:
                                    if  "L_BlackShadow." not in mat_name:
                                        mesh_object.active_material_index = i
                                        bpy.ops.object.material_slot_remove()



                        if "toon" in toonfill_type or "ink" in toonfill_type  or "whiteout" == toonfill_type  or "blackout" == toonfill_type :
                            mesh_object["is_toon_shaded"] = True

    try:
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    except:
        pass
    _b52_set_lc_exclude(backstage_collection.name, True)
    return {'FINISHED'} 


#------------------------------------------------------
# pose tools

def get_pose_index(obj, pose_name ):
    idx = 0
    for pm in obj.pose_library.pose_markers:
        if pose_name == pm.name:
            return idx
        idx += 1
    return None

def cycle_pose(self, objects, direction):
    global last_applied_pose_index
    objects = bpy.context.selected_objects
    if objects is not None :
        for obj in objects:
            starting_mode = bpy.context.object.mode
            if obj.type != 'ARMATURE':
                for mod in obj.modifiers:
                    mod_name = mod.name
                    if 'Skeleton' in mod_name:
                        armt = mod.object

            if obj.type == 'ARMATURE':
                    armt = obj

            if armt:                   
                is_hidden = armt.hide_get()
                if is_hidden:
                    armt.hide_set(False)
                    armt.hide_viewport = False
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                bpy.ops.object.select_all(action='DESELECT')
                armt.select_set(state=True)
                bpy.context.view_layer.objects.active = armt
                bpy.ops.object.mode_set(mode='POSE', toggle=False)
                # armt = obj.data
                # boneNames = armt.bones.keys()
                # myBones = armt.bones
                # bpy.ops.pose.select_all(action='DESELECT')
                # for poseBone in obj.pose.bones:
                #     poseBone.bone.select = True



                next_pose_index =  last_applied_pose_index
                if "POSE" in starting_mode:
                    selected_bones = bpy.context.selected_pose_bones

                active_pose_library = armt.pose_library
                if active_pose_library:
                    if next_pose_index is None:
                        print("pose %s not found." )
                    else:
                        pose_count = len(armt.pose_library.pose_markers)

                        if "next" in direction:
                            if next_pose_index < (pose_count -1):
                                next_pose_index = next_pose_index + 1  
                            else:
                                next_pose_index = 0

                        if "previous" in direction:
                            if next_pose_index > 0:
                                next_pose_index = next_pose_index - 1  
                            else:
                                next_pose_index = (pose_count -1)

                        if "OBJECT" in starting_mode:
                            bpy.ops.pose.select_all(action='SELECT')

                        if "POSE" in starting_mode:
                            bpy.ops.pose.select_all(action='DESELECT')
                            for bone in selected_bones:
                                poseBone = armt.pose.bones[bone.name]
                                poseBone.bone.select = True

                        bpy.ops.poselib.apply_pose(pose_index=next_pose_index) # add this line <<<<<<<<
                        last_applied_pose_index =  next_pose_index
                        last_pose_name = armt.pose_library.pose_markers[last_applied_pose_index].name
                        self.report({'INFO'}, 'Pose ' + last_pose_name +  ' applied!')


                else:
                    if "OBJECT" in starting_mode:
                        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                        bpy.ops.object.select_all(action='DESELECT')
                        obj.select_set(state=True)
                        bpy.context.view_layer.objects.active = obj

                    if is_hidden:
                        armt.hide_set(True)
                        # armt.hide_viewport = True
                    self.report({'INFO'}, 'Armature has no active pose library!')

def clean_poses(self):
    objects = bpy.context.selected_objects
    if objects is not None :
        for obj in objects:
            if obj.type == 'ARMATURE':
                armt = obj
            if armt:                   
                bpy.ops.object.mode_set(mode='POSE', toggle=False)
                active_pose_library = armt.pose_library    
                if active_pose_library:
                    bpy.ops.poselib.action_sanitize()
                    pose_count = range(0,len(armt.pose_library.pose_markers))
                    i = 0
                    action = bpy.data.actions.get(active_pose_library.name)
                    if action is not None:
                        fcurves = _action_fcurves(action)
                        for pose_index in armt.pose_library.pose_markers:
                            for fc in fcurves:
                                for key in fc.keyframe_points:
                                    if key.co[0] == pose_index.frame:
                                        key.co[0] = i + 1
                                        fc.evaluate(i + 1)
                            i = i + 1
                    bpy.ops.poselib.action_sanitize()

def add_full_pose(self):
    global last_applied_pose_index
    objects = bpy.context.selected_objects
    if objects is not None :
        for obj in objects:
            if obj.type == 'ARMATURE':
                armt = obj
                print(armt.name)
            if armt:
                frame_max = 1                  
                frames = 0   
                count = 0               
                bpy.ops.object.mode_set(mode='POSE', toggle=False)
                active_pose_library = armt.pose_library    
                if active_pose_library:
                    selected_bones = bpy.context.selected_pose_bones
                    bpy.ops.pose.select_all(action='DESELECT')
                    for bone in selected_bones:
                        poseBone = armt.pose.bones[bone.name]
                        poseBone.bone.select = True

                    frames = [m.frame for m in armt.pose_library.pose_markers]
                    count = len(frames)
                    frame_max = max(frames) if len(frames) else 0
                    bpy.ops.poselib.pose_add(frame=frames[-1]+1, name='Pose.000')
                    bpy.ops.poselib.action_sanitize()
                    bpy.ops.pose.select_all(action='DESELECT')
                    for bone in selected_bones:
                        poseBone = armt.pose.bones[bone.name]
                        poseBone.bone.select = True
                    last_pose_name = armt.pose_library.pose_markers[count-1].name
                    bpy.ops.poselib.apply_pose(pose_index=count)
                    last_applied_pose_index = count
                    self.report({'INFO'}, 'Pose ' + last_pose_name +  ' added to pose library!')

def overwrite_full_pose(self):
    global last_applied_pose_index
    objects = bpy.context.selected_objects
    if objects is not None :
        for obj in objects:
            if obj.type == 'ARMATURE':
                armt = obj
                print(armt.name)
            if armt: 
                bpy.ops.object.mode_set(mode='POSE', toggle=False)
                active_pose_library = armt.pose_library    
                if active_pose_library:

                    #make sure inherit rotation is on.
                    for poseBone in armt.pose.bones:
                        bpy.ops.pose.select_all(action='DESELECT')
                        poseBone.bone.select = True
                        matrix_final = armt.matrix_world @ poseBone.matrix
                        bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='ENABLE')
                        poseBone.matrix_world = matrix_final

                    selected_bones = bpy.context.selected_pose_bones
                    bpy.ops.pose.select_all(action='DESELECT')
                    for bone in selected_bones:
                        poseBone = armt.pose.bones[bone.name]
                        poseBone.bone.select = True
                    bpy.ops.poselib.pose_add(frame = last_applied_pose_index)
                    bpy.ops.poselib.action_sanitize()
                    bpy.ops.pose.select_all(action='DESELECT')
                    for bone in selected_bones:
                        poseBone = armt.pose.bones[bone.name]
                        poseBone.bone.select = True
                    self.report({'INFO'}, 'Pose added to pose library!')

def remove_full_pose(self):
    global last_applied_pose_index
    objects = bpy.context.selected_objects
    if objects is not None :
        for obj in objects:
            if obj.type == 'ARMATURE':
                armt = obj
                print(armt.name)
            if armt:                   
                bpy.ops.object.mode_set(mode='POSE', toggle=False)
                active_pose_library = armt.pose_library    
                if active_pose_library:
                    last_pose_name = armt.pose_library.pose_markers[last_applied_pose_index].name
                    bpy.ops.poselib.pose_remove(pose=last_pose_name)
                    last_applied_pose_index = last_applied_pose_index -1 
                    bpy.ops.poselib.apply_pose(pose_index=last_applied_pose_index)
                    self.report({'INFO'}, 'Pose removed ' + last_pose_name +  ' from pose library!')

#------------------------------------------------------
# export tools

def smart_anim_bake(obj): 
    try:
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    except:
        pass
    startFrame = bpy.context.scene.frame_start
    endFrame = bpy.context.scene.frame_end 
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(state=True)
    bpy.context.view_layer.objects.active = obj
    C=bpy.context
    _sa_area = getattr(C, 'area', None)
    _sa_old_area_type = None
    _sa_has_area = _sa_area is not None
    if _sa_has_area:
        _sa_old_area_type = _sa_area.type
        _sa_area.type='GRAPH_EDITOR'
        
    if obj.type != 'ARMATURE':
        try:
            bpy.ops.nla.bake(frame_start=startFrame, frame_end=endFrame, visual_keying=False, clear_constraints=True, bake_types={'OBJECT'})  
        except Exception:
            pass

        degp = bpy.context.evaluated_depsgraph_get()

        if _sa_has_area:
            try:
                bpy.ops.graph.select_all(action='SELECT')
                bpy.ops.graph.decimate(mode='ERROR', remove_error_margin=0.1)
                bpy.ops.graph.interpolation_type(type='BEZIER')
            except Exception:
                pass
        bpy.context.scene.frame_set(startFrame)
        obj.keyframe_insert(data_path="location", index=-1, frame=startFrame)
        bpy.context.scene.frame_set(endFrame)
        obj.keyframe_insert(data_path="location", index=-1, frame=endFrame)
       
    if _sa_old_area_type is not None:
        _sa_area2 = getattr(C, 'area', None)
        if _sa_area2 is not None:
            _sa_area2.type=_sa_old_area_type
    
def prep_cycler_instance_export(self, context):
    export_collection = getCurrentExportCollection(self, context)
    for obj in export_collection.all_objects:
        if obj.type == 'EMPTY':
            is_cycler = obj.get("is_cycler")
            if is_cycler:
                bpy.ops.object.select_all(action='DESELECT')
                for c in obj.children:
                    if not c.hide_viewport:
                        bpy.ops.object.select_all(action='DESELECT')
                        c.select_set(state=True)
                        bpy.context.view_layer.objects.active = c 
                        bpy.ops.object.duplicates_make_real()
                        real_instance_object = bpy.context.selected_objects[0]
                        bpy.ops.object.make_single_user(object=True, obdata=True, material=True, animation=False)
                        bpy.ops.object.select_all(action='DESELECT')
                        real_instance_object.select_set(state=True)
                        obj.select_set(state=True)                    
                        bpy.context.view_layer.objects.active = obj
                        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
                        bpy.ops.object.select_all(action='DESELECT')
                        c.select_set(state=True)               
                        bpy.context.view_layer.objects.active = c                                        
                        bpy.ops.object.delete()
                    else:
                        objs = bpy.data.objects
                        objs.remove(objs[c.name], do_unlink=True)

def prep_letters_export(self, context, scene):
    C=bpy.context
    if (C):
        _pl_area = getattr(C, 'area', None)
        _pl_old_area_type = None
        if _pl_area is not None:
            _pl_old_area_type = _pl_area.type
            _pl_area.type='VIEW_3D'

        # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        startFrame = 1
        endFrame = 72

        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
        # bpy.context.window.scene = scene 
        # # activate export collection.
        # collections = scene.collection.children
        # for col in collections:
        #     col_name = col.name
        #     if "Letters." in col_name:
        #         bpy.context.view_layer.layer_collection.children[col_name].exclude = False

        startFrame = bpy.context.scene.frame_start
        endFrame = bpy.context.scene.frame_end
        bpy.context.scene.frame_current = startFrame


        export_collection = getCurrentExportCollection(self, context)
        export_collection_name = export_collection.name
        
        letters_collection = getCurrentLettersCollection()

        if not letters_collection:
            self.report({'WARNING'}, "Letters Collection was not found in scene, skipping letters export of " + scene.name)
        else:
            letters_collection_name = letters_collection.name
            _b52_set_lc_exclude(letters_collection_name, False)
            # child_collections = bpy.context.view_layer.layer_collection.children[letters_collection_name].collection.children
            # for col in child_collections:
            #     col_name = col.name
            #     bpy.context.view_layer.layer_collection.children[letters_collection_name].children[col_name].exclude = False

        #     meshes = []

            # for obj in bpy.context.scene.objects:
            #     if obj is not None:
            #         if "Letters_" in obj.name:
            #             child_objects = get_all_children(obj)
            #             for c in child_objects:
            #                 c.hide_set(True)
            #                 c.hide_viewport = True
            #             obj.hide_set(True)
            #             obj.hide_viewport = True

            for obj in bpy.context.scene.objects:
                if obj is not None:
                    if "Letters_" in obj.name: 
                        # print(active_language)
                        # raise KeyboardInterrupt()
                        active_language = scene.panel_settings.s3dc_language
                        if active_language in obj.name:

                            bpy.ops.object.select_all(action='DESELECT')
                            # obj.select_set(state=True)
                            # bpy.context.view_layer.objects.active = obj
                            # bpy.ops.collection.objects_add_active(collection=export_collection_name)
                            # bpy.ops.collection.objects_remove(collection=letters_collection)

                            obj.hide_set(False)
                            obj.hide_viewport = False

                            if obj.animation_data:
                                if obj.type == 'OBJECT':
                                    print('>>>>> attempting to process: ' + obj.name)
                                    smart_anim_bake(obj)

                            child_objects = get_all_children(obj)
                            for c in child_objects:
                                c.hide_set(False)
                                c.hide_viewport = False

                                if c.type == 'FONT':
                                    if not _b52_safe_select_object(c, deselect_all=True, make_active=True):
                                        continue
                                    bpy.ops.object.convert(target='MESH')
                                    mod = c.modifiers.new(name = 'Decimate', type = 'DECIMATE')
                                    mod.ratio = 0.5
                                    bpy.ops.object.modifier_apply(modifier=mod.name)

                                bpy.ops.object.select_all(action='DESELECT')
                                # c.select_set(state=True)
                                # bpy.context.view_layer.objects.active = c
                                # bpy.ops.collection.objects_add_active(collection=export_collection_name)
                                # bpy.ops.collection.objects_remove(collection=letters_collection)

                                if c not in export_collection.objects.values():
                                    export_collection.objects.link(c)
                                if any(o.name == c.name for o in letters_collection.objects):
                                   letters_collection.objects.unlink(c)

                            # 只在物体不存在于导出集合时才添加
                            if not any(o is obj for o in export_collection.objects):
                                export_collection.objects.link(obj)
                            if any(o is obj for o in letters_collection.objects):
                                 letters_collection.objects.unlink(obj)

                            is_toon_shaded = obj.get("is_toon_shaded")
                            if is_toon_shaded:
                                for mod in obj.modifiers:
                                    mod_name = mod.name
                                    if 'InkThickness' in mod_name:
                                        obj.modifiers["InkThickness"].show_viewport = True
                                    if 'WhiteOutline' in mod_name:
                                        obj.modifiers["WhiteOutline"].show_viewport = True
                                    if 'BlackOutline' in mod_name:
                                        obj.modifiers["BlackOutline"].show_viewport = True

                            if obj.visible_get() and obj.type == 'GPENCIL':
                                if not _b52_safe_select_object(obj, deselect_all=True, make_active=True):
                                    continue

                                # set a temporary context to poll correctly
                                context = bpy.context.copy()
                                for area in bpy.context.screen.areas:
                                    if area.type == 'VIEW_3D':
                                        for region in area.regions:
                                            if region.type == 'WINDOW':
                                                context['area'] = area
                                                context['region'] = region
                                                break
                                        break
                                # bpy.ops.gpencil.convert(context, type='CURVE', use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='NONE', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                                # [Blender5.x兼容V3] 原 gpencil.convert(context=override字典, ...) → temp_override上下文，复用已有context['area']/context['region']
                                try:
                                    _gpa = context.get('area'); _gpr = context.get('region')
                                    if _gpa and _gpr:
                                        try:
                                            with context.temp_override(area=_gpa, region=_gpr):
                                                bpy.ops.gpencil.convert(type='CURVE', bevel_depth=0.05, bevel_resolution=3, use_normalize_weights=False, radius_multiplier=0.1, use_link_strokes=False, start_frame=startFrame, end_frame=endFrame, use_timing_data=False)
                                        except (TypeError, ValueError, AttributeError):
                                            with bpy.context.temp_override(area=_gpa, region=_gpr):
                                                bpy.ops.gpencil.convert(type='CURVE', bevel_depth=0.05, bevel_resolution=3, use_normalize_weights=False, radius_multiplier=0.1, use_link_strokes=False, start_frame=startFrame, end_frame=endFrame, use_timing_data=False)
                                    else:
                                        bpy.ops.gpencil.convert(type='CURVE', bevel_depth=0.05, bevel_resolution=3, use_normalize_weights=False, radius_multiplier=0.1, use_link_strokes=False, start_frame=startFrame, end_frame=endFrame, use_timing_data=False)
                                except Exception as _gpe:
                                    print(f'[gpencil.convert fallback] 上下文失败: {_gpe}')
                                    try:
                                        bpy.ops.gpencil.convert(type='CURVE', bevel_depth=0.05, bevel_resolution=3, use_normalize_weights=False, radius_multiplier=0.1, use_link_strokes=False, start_frame=startFrame, end_frame=endFrame, use_timing_data=False)
                                    except Exception:
                                        pass

                                # C=bpy.context
                                # old_area_type = C.area.type
                                # C.area.type='VIEW_3D'
                                # bpy.ops.gpencil.convert(context, type='CURVE', bevel_depth=0.0, bevel_resolution=0, use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='FULL', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                                # C.area.type=old_area_type
                                

                                selected_objects = bpy.context.selected_objects
                                gp_mesh = selected_objects[1] if len(selected_objects) > 1 else None
                                if gp_mesh is None or not _b52_safe_select_object(gp_mesh, deselect_all=True, make_active=True):
                                    continue
                                gp_mesh.data.bevel_depth = 0.005
                                gp_mesh.data.bevel_resolution = 1

                                pmesh = bpy.ops.object.convert(target='MESH')
                                if not _b52_safe_select_object(gp_mesh, deselect_all=True, make_active=True):
                                    continue
                                bpy.ops.object.modifier_add(type='DECIMATE')
                                gp_mesh.modifiers["Decimate"].decimate_type = 'DISSOLVE'
                                gp_mesh.modifiers["Decimate"].angle_limit = 0.0610865
                                bpy.ops.object.modifier_add(type='DECIMATE')
                                gp_mesh.modifiers["Decimate.001"].ratio = 0.2
                                matName = (gp_mesh.name + "Mat")
                                mat = bpy.data.materials.new(name=matName)
                                mat.use_nodes = True
                                mat.node_tree.nodes.clear()
                                mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                                shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                shader.inputs[0].default_value =  [0, 0, 0, 1]
                                shader.name = "Background"
                                shader.label = "Background"
                                mat_output = mat.node_tree.nodes.get('Material Output')
                                mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])

                                # Assign it to object
                                if gp_mesh.data.materials:
                                    gp_mesh.data.materials[0] = mat
                                else:
                                    gp_mesh.data.materials.append(mat)  

                            for mod in [m for m in obj.modifiers]:
                                mod.show_viewport = True
                                bpy.ops.object.modifier_apply(modifier=mod.name)     

            _b52_set_lc_exclude(letters_collection_name, True)

    if _pl_old_area_type is not None:
        _pl_area2 = getattr(C, 'area', None)
        if _pl_area2 is not None:
            _pl_area2.type=_pl_old_area_type

    return {'FINISHED'}

def export_panel(self, context, export_only_current, remove_skeletons):
    global addon_resources_dir
    sanitize_missing_fonts()
    # if bpy.data.is_dirty:
    #     # self.report({'WARNING'}, "You must save your file first!")
    #     bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
    panel_settings = bpy.context.scene.panel_settings
    apply_armature = panel_settings.s3dc_apply_armatures

    bpy.context.scene.tool_settings.use_keyframe_insert_auto = False


    # else:
    _ctx_obj = getattr(bpy.context, 'object', None)
    if _ctx_obj:
        if "OBJECT" not in _ctx_obj.mode:
            if "DRAW" in _ctx_obj.mode :
                bpy.ops.gpencil.paintmode_toggle(back=False)
                bpy.ops.object.select_all(action='DESELECT')
            else:
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                bpy.ops.object.select_all(action='DESELECT')


    #make sure letter collection is active
    getCurrentLettersCollection()

    # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    startFrame = 1
    endFrame = 72

    # path to the folder
    file_path = bpy.data.filepath
    file_name = bpy.path.display_name_from_filepath(file_path)
    file_ext = '.blend'
    blend_file_dir = file_path.replace(file_name+file_ext, '')

    file_dir = os.path.dirname(os.path.dirname(file_path)) 
    episode_dir_name = os.path.basename(file_dir)
    basefilename = os.path.splitext(file_name)[0]
    tmp_path_to_file = (os.path.join(file_dir, basefilename))
    js_file_path = (os.path.join(file_dir, "files.js"))
    bat_file_path = (os.path.join(file_dir, "Read_Local.bat"))
    drive_letter = os.path.splitext(file_name)[0]

    currSceneIndex = getCurrentSceneIndex()
    current_scene_name = bpy.data.scenes[currSceneIndex].name

    active_language = bpy.context.scene.panel_settings.s3dc_language

    if "english" in active_language:
        active_language_abreviated = 'en'                    
    if "spanish" in active_language:
        active_language_abreviated = 'es'
    if "japanese." in active_language:
        active_language_abreviated = 'ja'
    if "korean." in active_language:
        active_language_abreviated = 'ko'
    if "german." in active_language:
        active_language_abreviated = 'de'
    if "french." in active_language:
        active_language_abreviated = 'fr'
    if "dutch." in active_language:
        active_language_abreviated = 'da'

    if not active_language_abreviated:
        self.report({'ERROR'}, "No Active Language!")



    # export all scenes
    i = 0


    # delete existing panels
    if os.path.exists(file_dir+'\\panels\\'):
        if not export_only_current:
            # delete existing panel.glb fils.
            for panel_files in glob.glob(file_dir+'\\panels\\*.' + active_language_abreviated +'.glb'):
                print('os.remove(', panel_files, ')')
                os.remove(panel_files)
        else:
            for panel_files in glob.glob(file_dir +'\\panels\\'+ current_scene_name + '.' + active_language_abreviated + '.glb'):
                print('os.remove(', panel_files, ')')
                os.remove(panel_files)
    else:
        os.mkdir(file_dir+'\\panels\\')

    if not os.path.exists(file_dir+'\\panels\\shared\\'):
        try:
            addon_reader_dir = addon_resources_dir + "/Reader"
            src_shared = os.path.join(addon_reader_dir, "panels", "shared")
            dst_shared = file_dir + '\\panels\\shared'
            if os.path.isdir(src_shared):
                os.makedirs(dst_shared, exist_ok=True)
                copy_tree(src_shared, dst_shared)
                self.report({'INFO'}, "Auto-copied missing panels/shared/ from addon resources")
            else:
                self.report({'WARNING'}, "No shared folder present near save location! 3D Comic directory needs to be rebuilt? (source " + src_shared + " missing)")
        except Exception as _sh_e:
            self.report({'WARNING'}, "No shared folder present near save location! 3D Comic directory needs to be rebuilt? (auto-copy failed: " + str(_sh_e) + ")")



    # copy template reader files
    if not export_only_current:            
        if not os.path.exists(file_dir+'\\index.html'):
            # # copy 3D Comic Html
            # user_dir = os.path.expanduser("~")
            # reader_subdir = "/Reader"
            # if system() == 'Linux':
            #     addon_path = "/.config/blender/" + common_subdir
            # elif system() == 'Windows':
            #     addon_path = (
            #         "\\AppData\\Roaming\\Blender Foundation\\Blender\\"
            #         + common_subdir.replace("/", "\\")
            #     )
            #     # os.path.join()
            # elif system() == 'Darwin':
            #     addon_path = "/Library/Application Support/Blender/" + common_subdir
            # addon_dir = user_dir + addon_path

            # scripts_dir = bpy.utils.user_resource('SCRIPTS', "addons")
            # addon_resources_subdir = "/Spiraloid-Toolkit-for-Blender-3DComicToolkit-master/Resources/"        
            # addon_dir = scripts_dir + addon_resources_subdir
            addon_dir = addon_resources_dir
            addon_reader_dir = addon_dir + "/Reader"
            copy_tree(addon_reader_dir, file_dir)        


    if not export_only_current:
        # begin writing the javascript file for the comic
        js_file = open(js_file_path, "w")
        js_file.write('var files = [' +'\n')
        # js_file.write('      "./panels/header.w100h50.glb",' +'\n')  
        # js_file.write('      "./panels/black.w100h100.glb",' +'\n')  

    panels = []
    if export_only_current:
        panels.append(bpy.data.scenes[currSceneIndex])
    
    for scene in bpy.data.scenes:
        if not export_only_current:
            if "p." in scene.name:
                panels.append(scene)

    for scene in panels:
        # turn off all collections in every scene.
        for general_scene in bpy.data.scenes:
            _ctx_win = getattr(bpy.context, 'window', None)
            if _ctx_win is not None:
                _ctx_win.scene = general_scene
            else:
                try:
                    bpy.context.window_manager.windows[0].scene = general_scene
                except Exception:
                    pass
            scene_collections = general_scene.collection.children
            for col in scene_collections:
                col_name = col.name
                _b52_set_lc_exclude(col_name, True)
            bpy.ops.object.select_all(action='DESELECT')

        # initialize the scene
        _ctx_win = getattr(bpy.context, 'window', None)
        if _ctx_win is not None:
            _ctx_win.scene = scene
        else:
            try:
                bpy.context.window_manager.windows[0].scene = scene
            except Exception:
                pass
        startFrame = bpy.context.scene.frame_start
        endFrame = bpy.context.scene.frame_end
        bpy.context.scene.frame_current = startFrame
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
        _ctx_obj2 = getattr(bpy.context, 'object', None)
        if _ctx_obj2:
            starting_mode = _ctx_obj2.mode
            if "OBJECT" not in starting_mode:
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                bpy.ops.object.select_all(action='DESELECT')
        toggle_workmode(self, context, True)

        # set the context to be the view_3d in object mode.
        C=bpy.context
        old_area_type = None
        _ctx_area = getattr(C, 'area', None)
        if _ctx_area is not None:
            old_area_type = _ctx_area.type
            _ctx_area.type='VIEW_3D'

        # prepare the letters for export
        prep_letters_export(self, context, scene)

        # verify and activate export collection.
        export_collection = getCurrentExportCollection(self, context)
        if not export_collection:
            self.report({'WARNING'}, "Export Collection " + export_collection.name + "was not found in scene, skipping export of" + scene.name)
        else:
            linked_library_collections = []
            export_collection_name = export_collection.name
            _b52_set_lc_exclude(export_collection_name, False)
            _tmp_b52_lc = _b52_get_layer_collection(export_collection_name)
            child_collections = _tmp_b52_lc.collection.children if _tmp_b52_lc is not None else []
            for col in child_collections:
                col_name = col.name
                is_override_library = col.override_library
                if is_override_library:
                    col_objects = col.all_objects
                    for ref_obj in col_objects:
                        is_shared = ref_obj.get("is_shared")
                        if is_shared:
                            ref_obj = col_objects[0]
                            ref_empty = bpy.data.objects.new('ref_' + ref_obj.name, None)  # Create new empty object
                            export_collection.objects.link(ref_empty)  # Link empty to the current object's collection
                            ref_empty.empty_display_type = 'PLAIN_AXES'
                            ref_empty.location = ref_obj.location
                            linked_library_blend_filepath_name = ref_obj.data.library.filepath
                            linked_library_blend_file_name =  os.path.basename(linked_library_blend_filepath_name)
                            linked_library_stringFragments = linked_library_blend_file_name.split('_')
                            asset_name = linked_library_stringFragments[0]
                            linked_folder_abspath = (os.path.join(file_dir, "panels\\shared\\"))
                            linked_glb_abspath_filename = (linked_folder_abspath + "\\" + asset_name + ".glb")
                            linked_glb_relpath_filename = ("./shared/" + asset_name + ".glb")
                            if not os.path.exists(linked_glb_abspath_filename):
                                self.report({'ERROR'}, 'Cannot find shared asset :' + linked_glb_abspath_filename)
                            ref_empty["ref_filename"] = linked_glb_relpath_filename

                        else:
                            _b52_set_lc_exclude(col_name, False)
                            if _b52_safe_select_object(ref_obj, deselect_all=True, make_active=True):
                                bpy.ops.object.make_local(type='ALL')

                    # for cobj in col_objects:
                    #     if cobj is not None:
                    #         if bpy.context.object:
                    #             starting_mode = bpy.context.object.mode
                    #             if "OBJECT" not in starting_mode:
                    #                 bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                    #                 bpy.ops.object.select_all(action='DESELECT')
                    #         cobj.select_set(state=True)
                    #         bpy.context.view_layer.objects.active = cobj
                    #         bpy.ops.object.make_local(type='ALL')



                    # if ref_obj.type == 'ARMATURE':
                    #     ref_obj.make_local()
                    #     ch = [child for child in ref_obj.children if child.type == 'MESH' and child.find_armature()]
                    #     for ob in ch:
                    #         bpy.ops.object.select_all(action='DESELECT')
                    #         ob.select_set(state=True)
                    #         bpy.context.view_layer.objects.active = ob
                    #         bpy.data.objects.remove(bpy.data.objects[ob.name], do_unlink=True)

                        # print("=======DEBUG: " + str(currSceneIndex))
                        # raise KeyboardInterrupt()


                        # for mod in obj.modifiers:
                        #     if 'Skeleton' not in mod_name:
                        #         expiring_mod_name = mod.name 
                        #         bpy.ops.object.modifier_remove(modifier=expiring_mod_name)


                    # print("=======DEBUG: " + str(currSceneIndex))
                    # raise KeyboardInterrupt()

                    # if ref_obj.type == 'ARMATURE':
                    #     print("Found Linked Armature")
                    # else:


                    # if ref_obj == 'ARMATURE':
                    #     for mod in obj.modifiers:
                    #         if 'Skeleton' not in mod_name:
                    #             expiring_mod_name = mod.name 
                    #             bpy.ops.object.modifier_remove(modifier=expiring_mod_name)
                    # else:
                    #     export_collection.children.unlink(col)

                    # bpy.data.scenes[currSceneIndex].collection.children.link(col)
                    # bpy.context.view_layer.layer_collection.children[col_name].exclude = True
                    linked_library_collections.append(col)                        
                else:
                    _b52_set_lc_nested_exclude(export_collection_name, col_name, False)

                # print("=======DEBUG: " + str(currSceneIndex))
                # raise KeyboardInterrupt()


            meshes = []
            armatures = []
            active_camera = bpy.context.scene.camera
            if active_camera is None:
                camera_candidates = [obj for obj in export_collection.all_objects if obj.type == 'CAMERA']
                if camera_candidates:
                    active_camera = camera_candidates[0]
                    try:
                        bpy.context.scene.camera = active_camera
                        print(f"[Quick Export] 使用导出相机: {active_camera.name}")
                    except Exception as cam_err:
                        print(f"[Quick Export] 无法设置导出相机: {active_camera.name} / {cam_err}")
                else:
                    self.report({'WARNING'}, 'No Camera found in export collection of scene: ' + bpy.context.scene.name)
                    active_camera = None

            # make all cycler collection instances real and delete the hidden ones.
            prep_cycler_instance_export(self, context)

            export_objects = export_collection.all_objects
            for obj in export_objects:
                if obj is not None:
                    _ctx_obj3 = getattr(bpy.context, 'object', None)
                    if _ctx_obj3:
                        starting_mode = _ctx_obj3.mode
                        if "OBJECT" not in starting_mode:
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                            bpy.ops.object.select_all(action='DESELECT')

                    if active_camera is not None and "Camera." in obj.name:
                        if "Camera." in active_camera.name:
                            if _b52_safe_select_object(active_camera, make_active=True):
                                export_camera = active_camera
                                bpy.context.scene.frame_set(startFrame)
                                obj.keyframe_insert(data_path="location", index=-1, frame=startFrame)
                                bpy.context.scene.frame_set(endFrame)
                                obj.keyframe_insert(data_path="location", index=-1, frame=endFrame)

                    if "Camera_aim." in obj.name:
                        bpy.context.scene.frame_set(startFrame)
                        obj.keyframe_insert(data_path="location", index=-1, frame=startFrame)
                        bpy.context.scene.frame_set(endFrame)
                        obj.keyframe_insert(data_path="location", index=-1, frame=endFrame)

                    # # make instances real                           
                    # bpy.ops.object.select_all(action='DESELECT')
                    # obj.select_set(state=True)
                    # bpy.context.view_layer.objects.active = obj
                    # bpy.ops.object.duplicates_make_real()

                    # freshly_deinstanced_selected_objects = bpy.context.selected_objects
                    # for ob in freshly_deinstanced_selected_objects:
                    #     if ob.type == 'MESH':
                    #         bpy.ops.object.select_all(action='DESELECT')
                    #         ob.select_set(state=True)
                    #         bpy.context.view_layer.objects.active = ob
                    #         bpy.ops.object.convert(target='MESH')



            objects = export_collection.all_objects
            for obj in objects:
                if obj is not None and obj.visible_get():
                    print (obj.name)
                    if not _b52_safe_select_object(obj, deselect_all=True, make_active=True):
                        continue

                    if obj.type == 'ARMATURE':
                        armatures.append(obj)

                    if obj.type == 'MESH':
                        if apply_armature:
                            if obj.find_armature():
                                for mod in obj.modifiers:
                                    mod_name = mod.name
                                    if 'Skeleton' in mod_name:
                                        bpy.ops.object.modifier_apply( modifier="Decimate")
                                        meshes.append(obj)

                            else:
                                meshes.append(obj)
                        else:
                            if not obj.find_armature():
                                meshes.append(obj)

                        if obj.animation_data:
                            # Collect places where animation/driver data possibly present.
                            keyable_list = [getattr(obj.data, 'shape_keys', None)]
                            for ms in obj.material_slots:
                                if not ms:
                                    continue
                                keyable_list.append(ms.material)
                            for ps in obj.particle_systems:
                                keyable_list.append(ps.settings)
                            keyable_list.append(obj)
                            keyable_list.append(obj.data)

                            # Print data paths of available animation/driver f-curves.
                            for keyable in keyable_list:
                                if not keyable or not keyable.animation_data:
                                    continue
                                action = keyable.animation_data.action
                                if action:
                                    for fc in _action_fcurves(action):
                                        print(">>>>>> found animation on: " + obj.name + ", baking..." )
                                        smart_anim_bake(obj)
                                else:
                                    for fc in keyable.animation_data.drivers:
                                        print(">>>>>> found drivers on: " + obj.name + " " + fc.data_path)
                                        obj.animation_data_clear()
                                

                        is_toon_shaded = obj.get("is_toon_shaded")
                        if is_toon_shaded:
                            if not _b52_safe_select_object(obj, deselect_all=True, make_active=True):
                                continue

                            try:
                                # ToonDarkColor = obj.material_slots[0].material.node_tree.nodes["ColorRamp"].color_ramp.elements[0].color 
                                ToonLightColor = obj.material_slots[0].material.node_tree.nodes["ColorRamp"].color_ramp.elements[1].color 
                                ToonDarkColor = obj.material_slots[0].material.node_tree.nodes["ColorRamp"].color_ramp.elements[0].color 

                                # obj["ToonBlack"] = (Color((ToonDarkColor[0], ToonDarkColor[1], ToonDarkColor[2])))
                                # obj["ToonWhite"] = (Color((ToonLightColor[0], ToonLightColor[1], ToonLightColor[2])))


                                hex_color_light = toHex(ToonLightColor[0],ToonLightColor[1],ToonLightColor[2])
                                hex_color_dark = toHex(ToonDarkColor[0],ToonDarkColor[1],ToonDarkColor[2])



                                # obj.data["toon_color"] = (Color((ToonLightColor[0], ToonLightColor[1], ToonLightColor[2])))
                                # obj.data["toon_color"] = "0x" + hex_color
                                obj.data["toon_color_light"] = "#" + hex_color_light
                                obj.data["toon_color_dark"] = "#" + hex_color_dark
                            except:
                                pass

                            for mod in obj.modifiers:
                                mod_name = mod.name
                                if 'InkThickness' in mod_name:
                                    obj.modifiers["InkThickness"].show_viewport = True
                                if 'WhiteOutline' in mod_name:
                                    obj.modifiers["WhiteOutline"].show_viewport = True
                                if 'BlackOutline' in mod_name:
                                    obj.modifiers["BlackOutline"].show_viewport = True

                    if obj.visible_get() and obj.type == 'GPENCIL':
                        # bpy.ops.gpencil.editmode_toggle(False)
                        # bpy.ops.object.mode_set(mode='OBJECT')

                        if "OBJECT" not in obj.mode:
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  

                        if not _b52_safe_select_object(obj, deselect_all=True, make_active=True):
                            continue
                        if obj.active_material is not None:
                            gp_mat =  obj.active_material
                            gp_color = gp_mat.grease_pencil.color
                        # set a temporary context to poll correctly
                        context = bpy.context.copy()
                        for area in bpy.context.screen.areas:
                            if area.type == 'VIEW_3D':
                                for region in area.regions:
                                    if region.type == 'WINDOW':
                                        context['area'] = area
                                        context['region'] = region
                                        break
                                break
                        # [Blender5.x兼容V3] 原 gpencil.convert(context=override字典, ...) → temp_override上下文，复用已有context['area']/context['region']
                        try:
                            _gpa = context.get('area'); _gpr = context.get('region')
                            if _gpa and _gpr:
                                try:
                                    with context.temp_override(area=_gpa, region=_gpr):
                                        bpy.ops.gpencil.convert(type='CURVE', use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='NONE', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                                except (TypeError, ValueError, AttributeError):
                                    with bpy.context.temp_override(area=_gpa, region=_gpr):
                                        bpy.ops.gpencil.convert(type='CURVE', use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='NONE', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                            else:
                                bpy.ops.gpencil.convert(type='CURVE', use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='NONE', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                        except Exception as _gpe:
                            print(f'[gpencil.convert fallback] 上下文失败: {_gpe}')
                            try:
                                bpy.ops.gpencil.convert(type='CURVE', use_normalize_weights=True, radius_multiplier=1.0, use_link_strokes=False, timing_mode='NONE', frame_range=100, start_frame=1, use_realtime=False, end_frame=250, gap_duration=0.0, gap_randomness=0.0, seed=0, use_timing_data=False)
                            except Exception:
                                pass
                        selected_objects = bpy.context.selected_objects
                        gp_mesh = selected_objects[1]
                        if not _b52_safe_select_object(gp_mesh, deselect_all=True, make_active=True):
                            continue
                        gp_mesh.data.bevel_depth = 0.005
                        gp_mesh.data.bevel_resolution = 1

                        pmesh = bpy.ops.object.convert(target='MESH')
                        if not _b52_safe_select_object(gp_mesh, deselect_all=True, make_active=True):
                            continue

                        if len(gp_mesh.data.polygons) >= 2000:
                            bpy.ops.object.modifier_add(type='DECIMATE')
                            gp_mesh.modifiers["Decimate"].decimate_type = 'DISSOLVE'
                            gp_mesh.modifiers["Decimate"].angle_limit = 0.0610865
                            bpy.ops.object.modifier_add(type='DECIMATE')
                            gp_mesh.modifiers["Decimate.001"].ratio = 0.5

                        matName = (gp_mesh.name + "Mat")
                        mat = bpy.data.materials.new(name=matName)
                        mat.use_nodes = True
                        mat.node_tree.nodes.clear()
                        mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                        shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                        if gp_mat:
                            shader.inputs[0].default_value =  gp_color
                        else:
                            shader.inputs[0].default_value =  [0, 0, 0, 1]

                        shader.name = "Background"
                        shader.label = "Background"
                        mat_output = mat.node_tree.nodes.get('Material Output')
                        mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])
                        # Assign it to object
                        if gp_mesh.data.materials:
                            gp_mesh.data.materials[0] = mat
                        else:
                            gp_mesh.data.materials.append(mat)  

                        bpy.context.collection.objects.unlink(gp_mesh) 
                        export_collection.objects.link(gp_mesh)
                        meshes.append(gp_mesh)
                        bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
                        # raise KeyboardInterrupt()
                        

                    # if obj.visible_get and  obj.type == 'FONT':
                    #     bpy.ops.object.select_all(action='DESELECT')
                    #     obj.select_set(state=True)
                    #     bpy.context.view_layer.objects.active = obj
                    #     bpy.ops.object.convert(target='MESH')
                    #     bpy.ops.object.select_all(action='DESELECT')


            # meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']

            # get the minimum coordinate in scene
            if meshes:
                minV = Vector((min([min([co[0] for co in m.bound_box]) for m in meshes]),
                            min([min([co[1] for co in m.bound_box]) for m in meshes]),
                            min([min([co[2] for co in m.bound_box]) for m in meshes])))
                maxV = Vector((max([max([co[0] for co in m.bound_box]) for m in meshes]),
                            max([max([co[1] for co in m.bound_box]) for m in meshes]),
                            max([max([co[2] for co in m.bound_box]) for m in meshes])))
                scene_bounds = (minV[0] + maxV[0])*50
            else:
                scene_bounds = 100

            # process meshes 
            if meshes:
                for mesh in meshes:
                    if not _b52_safe_select_object(mesh, deselect_all=True, make_active=True):
                        continue
                    print('>>>>> Scene: ' + scene.name)
                    print('>>>>> Mesh: ' + mesh.name)
                    bpy.ops.object.make_local(type='ALL')
                    for mod in [m for m in mesh.modifiers]:
                        try:
                            drivers_data = mesh.animation_data.drivers
                            for dr in drivers_data:  
                                mesh.driver_remove(dr.data_path, -1)
                        except:
                            pass

                        if (mesh.type == 'MESH'):
                            try:
                                if not getattr(mod, 'show_viewport', False):
                                    print(f"[Quick Export] 跳过修改器: {mesh.name} / {mod.name} / 关闭")
                                    continue
                                if not getattr(mod, 'is_valid', True):
                                    print(f"[Quick Export] 跳过修改器: {mesh.name} / {mod.name} / 不可应用")
                                    continue
                                bpy.ops.object.modifier_apply(modifier=mod.name)
                            except RuntimeError as mod_err:
                                reason = str(mod_err).strip() or "apply failed"
                                print(f"[Quick Export] 跳过修改器: {mesh.name} / {mod.name} / {reason}")
                            except Exception as mod_err:
                                reason = str(mod_err).strip() or "apply failed"
                                print(f"[Quick Export] 跳过修改器: {mesh.name} / {mod.name} / {reason}")

                    # bpy.ops.object.convert(target='MESH')


                    if (mesh.type == 'CURVE'):
                        C=bpy.context
                        if (C):
                            _cv_area = getattr(C, 'area', None)
                            if _cv_area is not None:
                                _cv_old = _cv_area.type
                                _cv_area.type='VIEW_3D'
                                bpy.ops.object.convert(target='MESH')
                                _cv_area.type=_cv_old
                            else:
                                try:
                                    bpy.ops.object.convert(target='MESH')
                                except Exception:
                                    pass


                    objectConstraints = mesh.constraints
                    if (objectConstraints):
                        for const in objectConstraints:
                            bpy.ops.object.visual_transform_apply()
                            bpy.ops.constraint.delete(constraint=const.name, owner='OBJECT')
                            # mesh.constraints.remove(const)

                    is_toon_shaded = mesh.get("is_toon_shaded")
                    if is_toon_shaded:
                        if mesh.material_slots[0].material is not None:
                            matnodes = mesh.material_slots[0].material.node_tree.nodes
                            background_shader = matnodes.get('Background')
                            if not background_shader:
                                matnodes.clear()
                                mat_output = matnodes.new(type='ShaderNodeOutputMaterial')
                                shader = matnodes.new(type='ShaderNodeBsdfPrincipled')
                                mesh.material_slots[0].material.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])




            # # delete all the skeletons to reduce file size
            # if (remove_skeletons):
            #     if (armatures):
            #         for obj in armatures:
            #             ch = [child for child in obj.children if child.type == 'MESH' and child.find_armature()]
            #             for ob in ch:
            #                 if ob.visible_get: 
            #                     bpy.ops.object.select_all(action='DESELECT')
            #                     ob.select_set(state=True)
            #                     bpy.context.view_layer.objects.active = ob
            #                     bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

            #             bpy.ops.object.select_all(action='DESELECT')
            #             obj.select_set(state=True)
            #             bpy.context.view_layer.objects.active = obj
            #             override = bpy.context.copy()
            #             override['selected_objects'] = list(bpy.context.scene.objects)
            #             bpy.ops.object.delete(override)


            # cam_ob = bpy.context.scene.camera
            # if cam_ob is None:
            #     self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)
            # elif cam_ob.type == 'CAMERA':
            #     # cam_ob.data.clip_end = scene_bounds
            #     cam_ob.data.clip_end = 200

            # process camera

            # if active_camera is not None :
            #     for obj in objects:
            #         bpy.ops.object.select_all(action='DESELECT')
            #         if "Camera_aim." in obj.name:
            #             obj.select_set(state=True)
            #             bpy.context.view_layer.objects.active = obj
            #             bpy.ops.nla.bake(frame_start=startFrame, frame_end=endFrame, visual_keying=True, clear_constraints=True, bake_types={'OBJECT'})

            #     bpy.ops.object.select_all(action='DESELECT')
            #     active_camera.select_set(state=True)
            #     bpy.context.view_layer.objects.active = active_camera
            #     bpy.ops.nla.bake(frame_start=startFrame, frame_end=endFrame, visual_keying=True, clear_constraints=True, bake_types={'OBJECT'})
                
            #     # temp context switch
            #     #types = {'VIEW_3D', 'TIMELINE', 'GRAPH_EDITOR', 'DOPESHEET_EDITOR', 'NLA_EDITOR', 'IMAGE_EDITOR', 'SEQUENCE_EDITOR', 'CLIP_EDITOR', 'TEXT_EDITOR', 'NODE_EDITOR', 'LOGIC_EDITOR', 'PROPERTIES', 'OUTLINER', 'USER_PREFERENCES', 'INFO', 'FILE_BROWSER', 'CONSOLE'}
            #     C=bpy.context
            #     old_area_type = C.area.type
            #     C.area.type='GRAPH_EDITOR'
            #     bpy.ops.graph.decimate(mode='ERROR', remove_error_margin=0.001)

            #     C.area.type='DOPESHEET_EDITOR'
            #     bpy.ops.action.interpolation_type(type='BEZIER')
            #     C.area.type=old_area_type

            # else:
            #     self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)


                

                # if "Letters_eng." in obj.name:
                #     active_camera.select_set(state=True)
                #     bpy.context.view_layer.objects.active = active_camera
                # if "Lighting." in obj.name:
                #     active_camera.select_set(state=True)
                #     bpy.context.view_layer.objects.active = active_camera


                # for mod in obj.modifiers:
                #     if 'Skeleton' in mod_name:
                #         bpy.ops.object.modifier_apply( modifier="Skeleton")


            # selected_objects = bpy.context.selected_objects
            # for obj in objects:

                # if obj.animation_data:
                #     smart_anim_bake(obj)

                    # bpy.context.scene.frame_current = startFrame
                    # obj.keyframe_insert(data_path="location", index=-1, frame=startFrame)
                    # # bpy.ops.anim.keyframe_insert(type='Available')
                    # bpy.context.scene.frame_current = endFrame
                    # obj.keyframe_insert(data_path="location", index=-1, frame=endFrame)
                    # # bpy.ops.anim.keyframe_insert(type='Available')





            # letters = [o for o in bpy.context.scene.objects if o.type == 'FONT']
            # for text in letters:
            #     bpy.ops.object.select_all(action='DESELECT')
            #     text.select_set(state=True)
            #     bpy.context.view_layer.objects.active = text
            #     bpy.ops.object.convert(target='MESH')
                # mod = text.modifiers.new(name = 'Decimate', type = 'DECIMATE')
                # mod.ratio = 0.5




            # process world_nodes 
            # world_nodes = bpy.data.worlds[bpy.context.scene.world.name].node_tree.nodes
            world_nodes = bpy.context.scene.world
            if world_nodes:
                if world_nodes.use_nodes:
                    # safely resolve the Background node and its color source
                    background_node = None
                    try:
                        background_node = world_nodes.node_tree.nodes.get('Background') if getattr(world_nodes, 'node_tree', None) else None
                    except Exception:
                        background_node = None

                    if background_node is None or not hasattr(background_node, 'inputs') or len(background_node.inputs) == 0:
                        background_color = (0, 0, 0, 1)
                    else:
                        try:
                            links = getattr(background_node.inputs[0], 'links', []) or []
                            if len(links) > 0:
                                background_node_color_input = links[0].from_node
                            else:
                                background_node_color_input = None
                        except Exception:
                            background_node_color_input = None

                        if background_node_color_input and hasattr(background_node_color_input, 'outputs') and len(background_node_color_input.outputs) > 0:
                            background_color = background_node_color_input.outputs[0].default_value
                        else:
                            try:
                                background_color = background_node.inputs[0].default_value
                            except Exception:
                                background_color = (0, 0, 0, 1)

                    bpy.ops.object.select_all(action='DESELECT')
                    load_resource(self, context, "skyball.blend", False)
                    ob = bpy.data.objects.get("skyball")
                    if ob is None:
                        _sel_objs = getattr(bpy.context, 'selected_objects', None) or []
                        if _sel_objs:
                            ob = _sel_objs[0]
                    if ob is None:
                        for _obj in bpy.data.objects:
                            if _obj.type == 'MESH' and 'skyball' in _obj.name.lower():
                                ob = _obj
                                break
                    if ob is None:
                        raise RuntimeError("skyball mesh not found after load_resource")
                    _b52_safe_select_object(ob, deselect_all=True, make_active=True)

                    if ob.active_material is not None:
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 ob 全部材质槽
                        ob.data.materials.clear()
                    bpy.ops.object.shade_smooth()

                    assetName = ob.name
                    matName = (assetName + "Mat")
                    mat = bpy.data.materials.new(name=matName)
                    mat.use_nodes = True
                    mat.node_tree.nodes.clear()
                    mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                    shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                    shader.inputs[0].default_value =  [background_color[0], background_color[1], background_color[2], 1]
                    mat.use_backface_culling = True
                    shader.name = "Background"
                    shader.label = "Background"


                    mat_output = mat.node_tree.nodes.get('Material Output')
                    if shader is not None and mat_output is not None:
                        mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])
                    # Assign it to object
                    if ob.data.materials:
                        ob.data.materials[0] = mat
                    else:
                        ob.data.materials.append(mat)


            # armatures = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
            # for a in armatures:
            #     bpy.ops.object.select_all(action='DESELECT')
            #     bpy.context.view_layer.objects.active = a
            #     a.select_set(state=True)

            actions = bpy.data.actions
            for action in actions:
                if '3DComic_poses' in action.name:
                    try:
                        action.user_clear()
                    except:
                        pass
                    # empty_trash(self, context)


            # for linked_collection in linked_library_collections:
            #     linked_collection_name = linked_collection.name
            #     bpy.context.view_layer.layer_collection.children[linked_collection_name].exclude = False
            #     for lob in linked_collection.objects:
            #         if lob.type == 'ARMATURE':
            #             bpy.ops.object.select_all(action='DESELECT')
            #             lob.select_set(state=True)
            #             bpy.context.view_layer.objects.active = lob
            #             #get shared file name
            #             linked_library_blend_file_name = lob.data.library.name
            #             stringFragments = linked_library_blend_file_name.split('.')
            #             linked_library_filename = stringFragments[0]
                        
            #             # check if shared_asset_name.glb exists.
            #             linked_glb_filename = (file_dir + '/panels/shared/' + linked_library_filename + ".glb")
            #             if not os.path.exists(linked_glb_filename):
            #                 self.report({'ERROR'}, 'Cannot find shared asset :' + linked_glb_filename)

            #             # make shared asset local
            #             bpy.ops.object.make_local(type='ALL')

            #             # add custom property with string of shared asset
            #             lob["shared_filename"] = linked_glb_filename


            #             #delete all meshes associated with armature
            #             for child in lob.children:
            #                 bpy.ops.object.select_all(action='DESELECT')
            #                 child.select_set(state=True)
            #                 bpy.context.view_layer.objects.active = child
            #                 bpy.ops.object.delete() 

            panel_path = (os.path.join(file_dir, "panels"))
            path_to_export_file = (panel_path + "\\" + scene.name + "." + active_language_abreviated + ".glb")
            _b52_safe_export_scene_gltf(
                export_format='GLB',
                ui_tab='GENERAL', 
                export_copyright='', 
                export_image_format='AUTO', 
                export_texture_dir='', 
                export_texcoords=True, 
                export_normals=True, 
                export_draco_mesh_compression_enable=False, 
                export_draco_mesh_compression_level=6, 
                export_draco_position_quantization=14, 
                export_draco_normal_quantization=10, 
                export_draco_texcoord_quantization=12, 
                export_draco_color_quantization=10, 
                export_draco_generic_quantization=12, 
                export_tangents=False, 
                export_materials='EXPORT', 
                export_colors=True, 
                export_cameras=True, 
                export_selected=False, 
                use_selection=False, 
                export_extras=True, 
                export_yup=True, 
                export_apply=True, 
                export_animations=True, 
                export_frame_range=True, 
                export_frame_step=1, 
                export_force_sampling=False, 
                export_nla_strips=False, 
                export_def_bones=False, 
                export_current_frame=False, 
                export_skins=True, 
                export_all_influences=False, 
                export_morph=True, 
                export_morph_normal=True, 
                export_morph_tangent=False, 
                export_lights=True, 
                export_displacement=False, 
                will_save_settings=False, 
                filepath=(path_to_export_file), 
                check_existing=True, 
                filter_glob='*.glb;*.gltf')

                # export_format='GLB', 
                # ui_tab='GENERAL', 
                # export_copyright='', 
                # export_image_format='AUTO', 
                # export_texture_dir='', 
                # export_texcoords=True, 
                # export_normals=True, 
                # export_draco_mesh_compression_enable=False, 
                # export_draco_mesh_compression_level=6, 
                # export_draco_position_quantization=14, 
                # export_draco_normal_quantization=10, 
                # export_draco_texcoord_quantization=12, 
                # export_draco_generic_quantization=12, 
                # export_tangents=False, 
                # export_materials='EXPORT', 
                # export_colors=True, 
                # export_cameras=True, 
                # export_selected=False, 
                # use_selection=False, 
                # export_extras=True, 
                # export_yup=True, 
                # export_apply=True, 
                # export_animations=True, 
                # export_frame_range=True, 
                # export_frame_step=1, 
                # export_force_sampling=False, 
                # export_nla_strips=False, 
                # export_def_bones=False, 
                # export_current_frame=False, 
                # export_skins=True, 
                # export_all_influences=False, 
                # export_morph=True, 
                # export_morph_normal=False, 
                # export_morph_tangent=False, 
                # export_lights=True, 
                # export_displacement=False, 
                # will_save_settings=False, 
                # filepath=(path_to_export_file), 
                # check_existing=True, 
                # filter_glob='*.glb;*.gltf')

                # (
            # write the line for this file into the javascript file. 





            if not export_only_current:
                # js_file.write('      "./panels/' + scene.name + '.' + active_language_abreviated + '.glb",' +'\n')
                js_file.write('      "./panels/' + scene.name + '.' + active_language_abreviated + '.glb",' +'\n')

            # --- 5.2 Comic-books Mode A (2D image sequence p001.jpg) ---
            try:
                if bpy.context.scene.camera is None and active_camera is not None:
                    bpy.context.scene.camera = active_camera
                if bpy.context.scene.camera is None:
                    camera_candidates = [obj for obj in export_collection.all_objects if obj.type == 'CAMERA']
                    if camera_candidates:
                        bpy.context.scene.camera = camera_candidates[0]
                        print(f"[Quick Export] 兜底绑定相机: {camera_candidates[0].name}")
                import os as _cb_os
                _cb_img_dir = _cb_os.path.join(file_dir, 'images')
                _cb_os.makedirs(_cb_img_dir, exist_ok=True)
                if not hasattr(export_panel, '_cb_p_counter'):
                    export_panel._cb_p_counter = 0
                export_panel._cb_p_counter += 1
                _pnum = export_panel._cb_p_counter
                _img_name = 'p{:03d}.jpg'.format(_pnum)
                _img_path = _cb_os.path.join(_cb_img_dir, _img_name)
                _render = bpy.context.scene.render
                _old_engine = _render.engine
                _old_res_x = _render.resolution_x
                _old_res_y = _render.resolution_y
                _old_perc = _render.resolution_percentage
                _old_ff = _render.image_settings.file_format
                _old_fp = _render.filepath
                try:
                    _old_qu = _render.image_settings.quality
                except Exception:
                    _old_qu = 92
                try:
                    if bpy.app.background:
                        print('[Comic-books A] SKIP render in background mode (p{:03d})'.format(_pnum))
                    else:
                        _render.engine = 'BLENDER_EEVEE' if hasattr(_render, 'eevee') else 'CYCLES'
                        _render.resolution_x = 1920
                        _render.resolution_y = 1080
                        _render.resolution_percentage = 100
                        _render.image_settings.file_format = 'JPEG'
                        try:
                            _render.image_settings.quality = 92
                        except Exception:
                            pass
                        _render.filepath = _img_path
                        try:
                            bpy.ops.render.render(write_still=True)
                            print('[Comic-books A] OK page {:03d}: {}'.format(_pnum, _img_name))
                        except Exception as _rr_e:
                            print('[Comic-books A] WARN render fail (keep GLB export): ' + str(_rr_e))
                finally:
                    try:
                        _render.engine = _old_engine
                        _render.resolution_x = _old_res_x
                        _render.resolution_y = _old_res_y
                        _render.resolution_percentage = _old_perc
                        _render.image_settings.file_format = _old_ff
                        _render.filepath = _old_fp
                        try:
                            _render.image_settings.quality = _old_qu
                        except Exception:
                            pass
                    except Exception:
                        pass
                # --- 5.2 Comic-books Mode B (3D popup) copy GLB -> 3d/pNNN.glb ---
                try:
                    _cb_3d_dir = _cb_os.path.join(file_dir, '3d')
                    _cb_os.makedirs(_cb_3d_dir, exist_ok=True)
                    _src_glb = _cb_os.path.join(file_dir, 'panels', scene.name + '.' + str(active_language_abreviated) + '.glb')
                    _dst_glb = _cb_os.path.join(_cb_3d_dir, 'p{:03d}.glb'.format(_pnum))
                    if _cb_os.path.isfile(_src_glb):
                        import shutil as _cb_shutil
                        try:
                            _cb_shutil.copy2(_src_glb, _dst_glb)
                            print('[Comic-books B] OK 3d/p{:03d}.glb'.format(_pnum))
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception as _cb_a_e:
                print('[Comic-books A] WARN Mode A exception (GLB export untouched): ' + str(_cb_a_e))


            # rehide this collection so it's not in the next export.  
            # bpy.context.view_layer.layer_collection.children[export_collection_name].exclude = True

            # bpy.ops.scene.delete()

        # for obj in bpy.context.scene.objects:
        #     bpy.ops.object.select_all(action='DESELECT')
        #     obj.select_set(state=True)
        #     bpy.context.view_layer.objects.active = obj
        #     bpy.ops.object.delete() 
        # empty_trash(self, context)

                # export_copyright="Bay Raitt", 
                # filepath=(path_to_export_file), 
                # use_selection=False, 
                # export_format='GLB', 
                # export_image_format='JPEG', 
                # export_yup=True, 
                # export_apply=True, 
                # export_cameras=True, 
                # export_animations=True, 
                # export_frame_range=True, 
                # export_frame_step=1, 
                # export_force_sampling=True, 
                # export_nla_strips=False, 
                # export_def_bones=True, 
                # export_current_frame=False, 
                # export_skins=True, 
                # export_all_influences=False,
                # export_materials=True, 
                # export_colors=True
                # )

                # export_morph=True, 
                # export_morph_normal=True, 
                # export_morph_tangent=False
                # export_texture_dir="", 
                # export_texcoords=True, 
                # export_normals=True, 
                # export_draco_mesh_compression_enable=False, 
                # export_draco_mesh_compression_level=6, 
                # export_draco_position_quantization=14, 
                # export_draco_normal_quantization=10, 
                # export_draco_texcoord_quantization=12, 
                # export_draco_generic_quantization=12, 
                # export_tangents=False, 
                # export_selected=False, 
                # export_extras=False, 
                # export_lights=False 

            # will_save_settings=False,
            # check_existing=True
            # export_texture_dir="Materials", 
            # export_draco_mesh_compression_enable=False, 
            # export_draco_mesh_compression_level=6, 
            # export_draco_position_quantization=14, 
            # export_draco_normal_quantization=10, 
            # export_draco_texcoord_quantization=12, 
            # export_draco_generic_quantization=12, 
            # bpy.ops.export_scene.obj(   filepath = path_to_export_file, use_selection   =   True )
            i = i + 1

    if not export_only_current:            
        # finish writing the javascript file
        js_file.write('      "./panels/shared/p.black.w100h25.generic.glb",' +'\n')  
        # js_file.write('      "./panels/footer.w100h50.glb",' +'\n')  
        js_file.write('];' +'\n')
        js_file.close()

        # --- 5.2 Comic-books Mode A + B index.html (jypding/Comic-books compatible) ---
        try:
            import os as _cb_os, json as _cb_json, glob as _cb_glob
            _cb_self_dir = _cb_os.path.dirname(os.path.abspath(__file__))
            _tpl_path = _cb_os.path.join(_cb_self_dir, 'comicbooks_reader_template.html')
            _img_dir = _cb_os.path.join(file_dir, 'images')
            _imgs = []
            if _cb_os.path.isdir(_img_dir):
                _all = sorted(_cb_glob.glob(_cb_os.path.join(_img_dir, 'p[0-9][0-9][0-9].jpg'))
                             + _cb_glob.glob(_cb_os.path.join(_img_dir, 'p[0-9][0-9][0-9].png')))
                _imgs = ['./images/' + _cb_os.path.basename(f) for f in _all]
            _json_txt = _cb_json.dumps(_imgs, ensure_ascii=False)
            _html = ''
            try:
                with open(_tpl_path, 'r', encoding='utf-8') as _f:
                    _html = _f.read()
            except Exception:
                _html = '<!doctype html><html lang=zh-CN><head><meta charset=utf-8><title>Comic-books</title></head><body><h1>Template missing</h1><p>Re-run Build 3D Comic after re-install.</p></body></html>'
            _html = _html.replace('__CB_IMAGES_JSON__', _json_txt)
            _out = _cb_os.path.join(file_dir, 'index.html')
            with open(_out, 'w', encoding='utf-8') as _f:
                _f.write(_html)
            print('[Comic-books A/B] OK write index.html -> {}   (images = {})'.format(_out, len(_imgs)))

            # --- Stage 3: Book/ static publish package (GitHub Pages ready: manifest.json + pages/ + assets/) ---
            try:
                import shutil as _cb_shutil
                _book_dir = _cb_os.path.join(file_dir, 'Book')
                _book_pages_dir = _cb_os.path.join(_book_dir, 'pages')
                _book_assets_dir = _cb_os.path.join(_book_dir, 'assets')
                _book_3d_dir = _cb_os.path.join(_book_assets_dir, '3d')
                _cb_os.makedirs(_book_pages_dir, exist_ok=True)
                _cb_os.makedirs(_book_3d_dir, exist_ok=True)

                _book_images = []
                _book_glbs = []
                # 1. copy images/pNNN.jpg -> Book/pages/pNNN.jpg
                if _cb_os.path.isdir(_img_dir):
                    for _src in sorted(_cb_os.listdir(_img_dir)):
                        if _cb_glob.fnmatch.fnmatch(_src, 'p[0-9][0-9][0-9].jpg') or _cb_glob.fnmatch.fnmatch(_src, 'p[0-9][0-9][0-9].png'):
                            _sfull = _cb_os.path.join(_img_dir, _src)
                            if _cb_os.path.isfile(_sfull):
                                try:
                                    _cb_shutil.copy2(_sfull, _cb_os.path.join(_book_pages_dir, _src))
                                    _book_images.append('./pages/' + _src)
                                except Exception:
                                    pass
                # 2. copy 3d/pNNN.glb -> Book/assets/3d/pNNN.glb
                _3d_dir = _cb_os.path.join(file_dir, '3d')
                if _cb_os.path.isdir(_3d_dir):
                    for _src in sorted(_cb_os.listdir(_3d_dir)):
                        if _cb_glob.fnmatch.fnmatch(_src, 'p[0-9][0-9][0-9].glb'):
                            _sfull = _cb_os.path.join(_3d_dir, _src)
                            if _cb_os.path.isfile(_sfull):
                                try:
                                    _cb_shutil.copy2(_sfull, _cb_os.path.join(_book_3d_dir, _src))
                                    _book_glbs.append('./assets/3d/' + _src)
                                except Exception:
                                    pass
                # 3. manifest.json
                _manifest = {
                    "schema": "comic-books-book-v1",
                    "reader": "https://jypding.github.io/Comic-books/",
                    "title": os.path.basename(file_dir) or "Untitled",
                    "language": active_language_abreviated,
                    "page_count": max(len(_book_images), len(_book_glbs)),
                    "pages": [
                        {
                            "index": _pi,
                            "image": _book_images[_pi] if _pi < len(_book_images) else None,
                            "model3d": _book_glbs[_pi] if _pi < len(_book_glbs) else None
                        }
                        for _pi in range(max(len(_book_images), len(_book_glbs)))
                    ]
                }
                with open(_cb_os.path.join(_book_dir, 'manifest.json'), 'w', encoding='utf-8') as _fm:
                    _cb_json.dump(_manifest, _fm, ensure_ascii=False, indent=2)
                # 4. Book/index.html — standalone static runtime, NO localhost:8000 dependency, CDN model-viewer only
                _book_html = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Book — Comic-books Reader</title>
<style>
  :root { --bg:#000; --fg:#eee; --accent:#ffd166; --btn:rgba(255,255,255,.08); --btn-hover:rgba(255,255,255,.18) }
  * { box-sizing:border-box } html,body { margin:0; padding:0; height:100%; background:var(--bg); color:var(--fg);
    font-family:-apple-system,"Noto Sans CJK SC","Microsoft YaHei",sans-serif; overflow:hidden }
  #app { position:fixed; inset:0; display:flex; flex-direction:column }
  header { height:48px; display:flex; align-items:center; justify-content:space-between; padding:0 16px;
    background:rgba(0,0,0,.55); backdrop-filter:blur(6px); border-bottom:1px solid rgba(255,255,255,.08); z-index:10 }
  header .title { font-weight:600; letter-spacing:.5px; color:var(--accent) }
  header .meta { opacity:.75; font-size:13px }
  #stage { flex:1 1 auto; position:relative; display:flex; align-items:center; justify-content:center; background:#0a0a0a;
    overflow:hidden; touch-action:pan-y; cursor:grab }
  #page { max-width:100%; max-height:100%; object-fit:contain; box-shadow:0 20px 80px rgba(0,0,0,.6);
    border-radius:6px; transition:transform .25s ease; user-select:none; -webkit-user-drag:none }
  #page.hit3d { cursor:zoom-in }
  .nav { position:absolute; top:0; bottom:0; width:22%; display:flex; align-items:center; justify-content:center;
    z-index:5; opacity:0; transition:opacity .2s }
  .nav:hover { opacity:1 }
  .nav.prev { left:0; justify-content:flex-start; padding-left:20px }
  .nav.next { right:0; justify-content:flex-end; padding-right:20px }
  .nav button { background:var(--btn); border:none; color:var(--fg); width:56px; height:56px; border-radius:50%;
    font-size:22px; cursor:pointer; transition:background .2s }
  .nav button:hover { background:var(--btn-hover) }
  #progress { position:absolute; bottom:14px; left:50%; transform:translateX(-50%); display:flex; gap:6px; z-index:6;
    padding:6px 10px; background:rgba(0,0,0,.45); border-radius:999px }
  #progress .dot { width:8px; height:8px; border-radius:50%; background:rgba(255,255,255,.3); transition:all .2s }
  #progress .dot.active { background:var(--accent); transform:scale(1.3) }
  footer { height:36px; display:flex; align-items:center; justify-content:space-between; padding:0 16px; font-size:12px; opacity:.7;
    background:rgba(0,0,0,.55); border-top:1px solid rgba(255,255,255,.08); z-index:10 }
  #modal3d { position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:100; display:none;
    align-items:center; justify-content:center; flex-direction:column }
  #modal3d.open { display:flex }
  #modal3d .hd { position:absolute; top:0; left:0; right:0; padding:12px 20px; display:flex;
    justify-content:space-between; align-items:center; background:rgba(0,0,0,.55);
    border-bottom:1px solid rgba(255,255,255,.08) }
  #modal3d .close { background:var(--btn); color:var(--fg); border:none; border-radius:8px; padding:8px 14px; cursor:pointer }
  #modeSwitch { background:var(--btn); color:var(--fg); border:none; padding:6px 12px; border-radius:999px;
    font-size:12px; cursor:pointer }
  #modeSwitch:hover { background:var(--btn-hover) }
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="title">Book / Comic-books Reader</div>
    <div style="display:flex; align-items:center; gap:10px">
      <button id="modeSwitch">Mode A (Images)</button>
      <div class="meta" id="counter">- / -</div>
    </div>
  </header>
  <div id="stage" tabindex="0">
    <img id="page" alt="comic page" draggable="false">
    <div class="nav prev" id="navPrev"><button>&lsaquo;</button></div>
    <div class="nav next" id="navNext"><button>&rsaquo;</button></div>
    <div id="progress"></div>
  </div>
  <footer>
    <div>Book/ static package — ready for GitHub Pages. Images: ./pages/, 3D: ./assets/3d/</div>
    <div>No localhost:8000 dependency</div>
  </footer>
</div>

<div id="modal3d">
  <div class="hd">
    <div class="title" style="color:var(--accent)">Interactive 3D Scene</div>
    <button class="close" id="close3d">Close X</button>
  </div>
  <div id="modelViewerHost" style="width:100%; height:calc(100% - 52px); position:relative"></div>
</div>

<script>
  // Manifest path is relative (Book/manifest.json)
  (async function(){
    const IMAGES = __BOOK_IMAGES__;
    const GLBS   = __BOOK_GLBS__;
    const stage = document.getElementById('stage');
    const img   = document.getElementById('page');
    const dots  = document.getElementById('progress');
    const count = document.getElementById('counter');
    const prev  = document.getElementById('navPrev');
    const next  = document.getElementById('navNext');
    const modeSwitch = document.getElementById('modeSwitch');
    let idx = 0, modeA = true, touchX0 = null;

    function render() {
      if (!IMAGES.length && !GLBS.length) {
        stage.innerHTML = '<div style="text-align:center; opacity:.85; padding:20px"><h2>Comic-books Book</h2>' +
          '<p>No pages found.</p><p>Run Build 3D Comic + Export in Blender to produce Book/.</p></div>';
        count.textContent = '0 / 0';
        return;
      }
      if (IMAGES.length) {
        img.style.display = '';
        img.src = IMAGES[Math.min(idx, IMAGES.length-1)];
      } else {
        img.style.display = 'none';
      }
      const total = Math.max(IMAGES.length, GLBS.length);
      count.textContent = (idx+1) + ' / ' + total;
      dots.innerHTML = '';
      for (let i=0;i<total;i++) {
        const d=document.createElement('div');
        d.className = 'dot' + (i===idx?' active':'');
        d.onclick = ()=>{ idx=i; render() };
        dots.appendChild(d);
      }
      img.classList.toggle('hit3d', !modeA);
    }
    prev.onclick = ()=>{ const total = Math.max(IMAGES.length, GLBS.length) || 1; if (idx>0) idx--; else idx=total-1; render() };
    next.onclick = ()=>{ const total = Math.max(IMAGES.length, GLBS.length) || 1; idx=(idx+1)%total; render() };
    stage.addEventListener('wheel', e=>{ e.preventDefault(); (e.deltaY>0 || e.deltaX>0 ? next : prev).onclick(); }, {passive:false});
    document.addEventListener('keydown', e=>{
      if (e.key==='ArrowLeft') prev.onclick();
      if (e.key==='ArrowRight' || e.key===' ') next.onclick();
      if (e.key==='Home') { idx=0; render() }
      if (e.key==='End')  { idx=Math.max(0, (Math.max(IMAGES.length, GLBS.length))-1); render() }
      if (e.key==='Escape') document.getElementById('modal3d').classList.remove('open');
    });
    stage.addEventListener('pointerdown', e=>{ touchX0=e.clientX; stage.classList.add('dragging') });
    stage.addEventListener('pointerup', e=>{
      stage.classList.remove('dragging');
      if (touchX0!=null) {
        const dx = e.clientX - touchX0;
        if (Math.abs(dx) > 40) { dx<0 ? next.onclick() : prev.onclick() }
        else if (Math.abs(dx) < 6 && !modeA) tryOpen3D();
      }
      touchX0 = null;
    });
    modeSwitch.onclick = ()=>{
      modeA = !modeA;
      modeSwitch.textContent = modeA ? 'Mode A (Images)' : 'Mode B (Click page -> 3D)';
      render();
    };
    img.addEventListener('click', ()=>{ if (!modeA) tryOpen3D() });

    const mvHost = document.getElementById('modelViewerHost');
    const modal = document.getElementById('modal3d');
    document.getElementById('close3d').onclick = ()=>modal.classList.remove('open');
    function tryOpen3D() {
      const n = String(idx+1).padStart(3,'0');
      const glb = (GLBS.length) ? (GLBS[Math.min(idx, GLBS.length-1)]) : ('./assets/3d/p' + n + '.glb');
      mvHost.innerHTML = '<model-viewer src="'+glb+'" camera-controls auto-rotate shadow-intensity="1" ' +
        'exposure="1" environment-image="neutral" style="width:100%;height:100%;background:#0a0a0a" ' +
        'onerror=\'this.outerHTML="<div style=&quot;padding:40px;text-align:center;opacity:.75&quot;>No 3D scene for this page.</div>"\' ' +
        '><button slot="ar-button" style="display:none">AR</button></model-viewer>';
      if (!window._mvInjected) {
        const s = document.createElement('script');
        s.type = 'module';
        s.src  = 'https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js';
        s.onerror = ()=>{ mvHost.innerHTML =
          '<div style="padding:40px;text-align:center;opacity:.85"><h3>Mode B - Interactive 3D</h3>' +
          '<p>Offline: model-viewer did not load.</p><p>Connect internet or upload to Comic-books GitHub Pages.</p></div>';
        };
        document.head.appendChild(s);
        window._mvInjected = true;
      }
      modal.classList.add('open');
    }
    render();
    stage.focus();
  })();
</script>
</body>
</html>"""
                _book_html = _book_html.replace('__BOOK_IMAGES__', _cb_json.dumps(_book_images, ensure_ascii=False))
                _book_html = _book_html.replace('__BOOK_GLBS__',   _cb_json.dumps(_book_glbs,   ensure_ascii=False))
                with open(_cb_os.path.join(_book_dir, 'index.html'), 'w', encoding='utf-8') as _fb:
                    _fb.write(_book_html)
                print('[Book/GitHubPages] OK static package -> {}   (pages={}, 3d={})'.format(
                    _book_dir, len(_book_images), len(_book_glbs)))
            except Exception as _book_e:
                print('[Book/GitHubPages] WARN generate Book/ fail: ' + str(_book_e))

        except Exception as _cb_e:
            print('[Comic-books A/B] WARN generate index.html fail: ' + str(_cb_e))

        # ============================================================
        # Modern Export Pipeline - 现代导出管线
        # ============================================================
        # 在旧导出完成后，调用 Modern Pipeline 生成 page.json + 现代 Viewer
        # 保持旧的 files.js 生成逻辑不变（兼容性），但不再作为最终数据源
        try:
            print('[ModernPipeline] ========================================')
            print('[ModernPipeline] Starting Modern Export Pipeline')
            print('[ModernPipeline] ========================================')

            from exporter.modern_pipeline import generate_modern_export

            result = generate_modern_export(
                file_dir=file_dir,
                panels=panels,
                active_language=active_language_abreviated,
                episode_name="s01e01",
            )

            print('[ModernPipeline] ========================================')
            print(f'[ModernPipeline] Modern Export Completed: {result["pages_count"]} pages')
            print(f'[ModernPipeline] Output: {result["output_dir"]}')
            print('[ModernPipeline] ========================================')

        except Exception as modern_err:
            # Modern Pipeline 失败不影响旧导出流程
            print('[ModernPipeline] ========================================')
            print(f'[ModernPipeline] ERROR: {modern_err}')
            print('[ModernPipeline] Fallback to legacy export only')
            print('[ModernPipeline] ========================================')
            import traceback
            traceback.print_exc()

    #     # create local server bat file (windows only)
    #     bat_file = open(bat_file_path, "w")
    #     stringFragments = file_dir.split(':')
    #     drive_letter = stringFragments[0] + ":"

    #     bat_file.write('@echo off' +'\n')  
    #     bat_file.write(drive_letter +'\n')  
    #     bat_file.write('cd ' + file_dir +'\n')  
    #     bat_file.write('taskkill /IM "python.exe" /F' +'\n')
    #     bat_file.write('start http://localhost:8000/?lan=' + active_language_abreviated +'^&savepoint=0\n')  
    #     bat_file.write('python -m  http.server ' +'\n')
    #     # bat_file.write('tasklist /nh /fi "imagename eq python.exe" | find /i "python.exe" > nul | (python -m  http.server)' +'\n')
    #     bat_file.write('pause' +'\n')
    #     bat_file.close()

    if export_only_current :
        js_file = open(js_file_path, "w")
        js_file.write('var files = [' +'\n')
        for panel_scene in bpy.data.scenes:
            if "p." in panel_scene.name:
                js_file.write('      "./panels/' + panel_scene.name + '.' + active_language_abreviated + '.glb",' +'\n')
        js_file.write('      "./panels/shared/p.black.w100h25.generic.glb",' +'\n')
        js_file.write('];' +'\n')
        js_file.close()


    self.report({'INFO'}, 'Exported Panels!')



    if old_area_type is not None:
        _ctx_area = getattr(C, 'area', None)
        if _ctx_area is not None:
            _ctx_area.type=old_area_type

    ## reopen scene from before build comic
    bpy.ops.wm.open_mainfile(filepath=file_path)
    self.report({'INFO'}, 'Exported Comic!')
    # subprocess.Popen('explorer '+ file_dir)
    # subprocess.Popen(bat_file_path)
    # BR_MT_read_3d_comic.execute(self, context)
    
    return {'FINISHED'}

#------------------------------------------------------
# export tools

def reset_blender():
    return {'FINISHED'}








class NewComicSettings(bpy.types.PropertyGroup):
    title : bpy.props.StringProperty(name="Title", description="Enter Title Name", default="Inkbots S1 EP01")
    author : bpy.props.StringProperty(name="Author", description="Are you Moebius, Eisner, McFarlane, Miyazaki, Miller, Torres, Lee, Kirby?", default="Author Name")
    url : bpy.props.StringProperty(name="Author URL", description="where do you want readers to visit", default="https://3dcomic.shop/inkbots")
    start_panel_count : bpy.props.IntProperty(name="How Many Panels?",  description="Create a number of blank panels to start", min=1, max=99, default=1 )

class BR_OT_new_3d_comic(bpy.types.Operator, ImportHelper):
    """Start a new 3D Comic from scratch"""
    bl_idname = "comic.new_comic_project"
    bl_label = "新建漫画工程（Create Comic Folder）"
    bl_options = {'REGISTER', 'UNDO'}
    # config: bpy.props.PointerProperty(type=NewComicSettings)
    filepath : bpy.props.StringProperty(
        name="文件路径",
        description="3D Comic webite root folder",
        subtype='FILE_PATH'
    )
    filter_glob: StringProperty( default='*.blend', options={'HIDDEN'}, )
    project_mode: bpy.props.EnumProperty(
        items=[
            ("cinematic", "Cinematic", "3D Cinematic Mode"),
            ("voice", "Voice", "Voice Book Mode"),
            ("reading", "Reading", "Pure Reading Mode"),
        ],
        name="Project Mode",
        default="cinematic"
    )

    # directory = bpy.props.StringProperty(name="file path", description="3D Comic webite root folder")
    # comic_name = bpy.props.StringProperty(name="comic name", description="Name of 3D Comic Site", default= "s01e01")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}   

    # def draw(self, context):
    #     layout = self.layout
    #     # scene = context.scene
    #     # new_3d_panel_settings = scene.new_3d_panel_settings
    #     layout.prop(comic_name, "title", description="Name of 3D Comic Site")
    #     # layout.prop(new_3d_panel_settings, "author")
    #     # layout.prop(new_3d_panel_settings, "url")
    #     # layout.prop(new_3d_panel_settings, "start_panel_count")
    #     # layout.separator()


    def execute(self, context):
        import subprocess
        import os
        
        # 1. 准备参数
        root = "D:\\GitRepos\\Comic-books"
        ps_script = os.path.join(root, "New-ComicProject.ps1")
        
        # 修复 ProjectId 为空的问题：去掉路径末尾的斜杠和空白，并取基本名（去掉扩展名）
        clean_path = self.filepath.strip().rstrip(os.sep).rstrip('/')
        project_id, _ = os.path.splitext(os.path.basename(clean_path))
        mode = self.project_mode
        
        # 增加临时诊断
        print(f"[CreateVoiceBook] ProjectId={project_id!r}")
        print(f"[CreateVoiceBook] Mode={mode!r}")

        if not project_id:
            self.report({'ERROR'}, "❌ 项目 ID 不能为空，请在对话框中输入项目名称")
            return {'CANCELLED'}
        
        # 2. 调用 PowerShell 脚本
        cmd = [
            "powershell.exe",
            "-ExecutionPolicy", "Bypass",
            "-File", ps_script,
            "-ProjectId", project_id,
            "-Mode", mode,
            "-UserDir", os.path.dirname(self.filepath.strip().rstrip(os.sep).rstrip("/"))
        ]
        
        try:
            # 修复编码问题：不使用 text=True，手动解码并处理错误字符 (Windows 优先使用 gbk)
            process = subprocess.run(cmd, capture_output=True, check=False)
            
            stdout = process.stdout.decode('gbk', errors='replace')
            stderr = process.stderr.decode('gbk', errors='replace')
            
            if process.returncode != 0:
                error_msg = stderr.strip() or stdout.strip() or f"Exit Code: {process.returncode}"
                self.report({'ERROR'}, f"❌ 创建失败: {error_msg}")
                print(f"PowerShell Error Output:\n{stderr}")
                return {'CANCELLED'}

            self.report({'INFO'}, f"✅ 项目创建成功: {project_id} ({mode})")
            print(f"PowerShell Output:\n{stdout}")
            
            # 3. Blender 工程初始化
            if mode == "cinematic":
                global addon_resources_dir
                global backstage_collection_name
                
                # Cinematic 模式保持原有的 s01e01 结构
                root_folder = os.path.dirname(self.filepath)
                issue_name = "s01e01"
                issue_folder = os.path.join(root_folder, project_id, issue_name)
                working_folder = os.path.join(issue_folder, "blender")
                images_folder = os.path.join(issue_folder, "images")
                
                os.makedirs(working_folder, exist_ok=True)
                os.makedirs(images_folder, exist_ok=True)
                os.makedirs(os.path.join(working_folder, "shared"), exist_ok=True)

                filename = os.path.join(working_folder, f"{project_id}_v.001.blend")
                
                template_path = os.path.join(addon_resources_dir, "comic_default.blend")
                if os.path.exists(template_path):
                    bpy.ops.wm.read_homefile(filepath=template_path, load_ui=False)
                    bpy.ops.wm.save_as_mainfile(filepath=filename)
                    bpy.context.scene.name = "Cover"
                    if 'Title' in bpy.data.objects:
                        bpy.data.objects['Title'].data.body = project_id
                    
                    # 视图设置
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == 'VIEW_3D':
                                area.spaces[0].region_3d.view_perspective = 'CAMERA'
                                try:
                                    with context.temp_override(window=window, area=area, region=area.regions[0]):
                                        if bpy.ops.view3d.view_center_camera.poll():
                                            bpy.ops.view3d.view_center_camera()
                                except Exception: pass
                    
                    # 渲染设置与初始 Banner 生成
                    scene = bpy.context.scene
                    scene.render.filepath = os.path.join(images_folder, "main_banner.jpg")
                    scene.render.image_settings.color_mode = 'RGB'
                    scene.render.image_settings.file_format = 'JPEG'
                    scene.render.resolution_x = 1024
                    scene.render.resolution_y = 345
                    bpy.ops.render.render(write_still=True)
                    backstage_collection_name = getCurrentBackstageCollectionName()
                    self.report({'INFO'}, f"✅ 漫画场景已就绪: {filename}")

            elif mode == "voice":
                # Voice 模式使用扁平结构，无 s01e01
                root_folder = os.path.join(root, "books")
                project_dir = os.path.join(root_folder, project_id)
                blender_dir = os.path.join(project_dir, "blender")
                os.makedirs(blender_dir, exist_ok=True)

                # 补全完整书本目录结构
                for sub in ["audio", "book", "book/pages", "images", "styles",
                            "assets", "interaction", "schema", "timeline"]:
                    os.makedirs(os.path.join(project_dir, sub), exist_ok=True)

                # 从模板复制基础文件（如果有）
                import shutil
                tpl_root = os.path.join(root, "templates", "voice_book")
                if os.path.isdir(tpl_root):
                    for item in os.listdir(tpl_root):
                        src = os.path.join(tpl_root, item)
                        dst = os.path.join(project_dir, item)
                        if os.path.isfile(src) and not os.path.exists(dst):
                            if item.endswith(".blend1") or item.endswith(".blend11") or item.startswith("."):
                                continue
                            try: shutil.copy2(src, dst)
                            except Exception: pass
                        elif os.path.isdir(src) and item not in ("blender",):
                            for fn in os.listdir(src):
                                s2 = os.path.join(src, fn)
                                d2 = os.path.join(dst, fn)
                                if os.path.isfile(s2) and not os.path.exists(d2):
                                    os.makedirs(dst, exist_ok=True)
                                    try: shutil.copy2(s2, d2)
                                    except Exception: pass

                filename = os.path.join(blender_dir, f"{project_id}.blend")
                
                # 使用语音书模板 blend
                template_blend = os.path.join(root, "templates", "voice_book", "blender", "template.blend")
                if os.path.exists(template_blend):
                    bpy.ops.wm.open_mainfile(filepath=template_blend)
                else:
                    # 如果模板不存在，创建一个基础的
                    bpy.ops.wm.read_factory_settings(use_empty=True)

                # 确保 Backstage.Global 集合存在（分镜导航面板的 poll 条件）
                _bs = None
                for _c in bpy.data.collections:
                    if _c.name == "Backstage.Global":
                        _bs = _c
                        break
                if _bs is None:
                    _bs = bpy.data.collections.new("Backstage.Global")
                    bpy.context.scene.collection.children.link(_bs)

                # 确保 Materials.Global 对象存在（draw 里 getCurrentMaterialSwatch 的判断条件）
                _has_mat = False
                for _o in _bs.objects:
                    if "Materials.Global" in _o.name:
                        _has_mat = True
                        break
                if not _has_mat:
                    _mat_obj = bpy.data.objects.new("Materials.Global", None)
                    _bs.objects.link(_mat_obj)
                
                # 强制初始化集合结构
                colls = ["Characters", "Interactive_Object", "Camera", "Audio_Markers", "Export"]
                for cname in colls:
                    if cname not in bpy.data.collections:
                        new_col = bpy.data.collections.new(cname)
                        bpy.context.scene.collection.children.link(new_col)
                
                # 添加 VoiceBook_Settings 属性
                bpy.context.scene["VoiceBook_Settings"] = {
                    "style_id": "gatelessgate",
                    "mode": "voice"
                }
                
                # 保存文件
                bpy.ops.wm.save_as_mainfile(filepath=filename)

                # 延迟打开 N 面板（避免 open_mainfile 后 context 未就绪导致崩溃）
                def _open_n_panel_for_voice():
                    try:
                        for _w in bpy.context.window_manager.windows:
                            for _a in _w.screen.areas:
                                if _a.type == 'VIEW_3D':
                                    for _s in _a.spaces:
                                        if _s.type == 'VIEW_3D':
                                            _s.show_region_ui = True
                                            try:
                                                _s.region_ui_category = "3D Comics"
                                            except Exception:
                                                pass
                                    for _r in _a.regions:
                                        if _r.type == 'UI':
                                            try:
                                                _r.active_panel_category = "3D Comics"
                                            except Exception:
                                                pass
                    except Exception:
                        pass
                    return None
                try:
                    bpy.app.timers.register(_open_n_panel_for_voice, first_interval=0.3)
                except Exception:
                    pass

                self.report({'INFO'}, f"✅ 语音书场景已就绪: {filename}")

            return {'FINISHED'}
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr or e.stdout or str(e)
            self.report({'ERROR'}, f"❌ 创建失败: {error_msg}")
            print(f"Error: {error_msg}")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"❌ 意外错误: {str(e)}")
            return {'CANCELLED'}

        # panels = []
        # for scene in bpy.data.scenes:
        #     if "p." in scene.name:
        #         panels.append(scene.name)

        # for panel in panels :
        #     for i in range(len(bpy.data.scenes)):
        #         if bpy.data.scenes[i].name == panel:
        #             m = currSceneIndex - 1
        #             if m > currSceneIndex:
        #                 sceneNumber = "%04d" % m
        #                 bpy.data.scenes[m].name = 'p.'+ str(sceneNumber)


        # #create scene collection
        # shared_assets_collection_name = "Shared Assets"
        # shared_assets_collection = bpy.data.collections.new(shared_assets_collection_name)
        # bpy.context.scene.collection.children.link(shared_assets_collection)  

        # #create subcollection
        # cname = "Actors"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Props"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Places"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Places_Props"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Vehicles"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Creatures"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Vfx"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Items"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Figurines"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)
        # cname = "Materials"
        # c = bpy.data.collections.new(cname)
        # shared_assets_collection.children.link(c)


        # angle=math.radians(90.0)
        # bpy.ops.object.camera_add(enter_editmode=False, align='WORLD', location=(0, -12, 1.52), rotation=(angle, 0, 0), scale=(1, 1, 1))
        
        # firstPanelName = 'p.0001'
        # newScene = bpy.ops.scene.new(type='NEW')
        # firstPanelSceneIndex = getCurrentSceneIndex()
        # bpy.data.scenes[firstPanelSceneIndex].name = firstPanelName

        # this crashes for some unknown reasion
        # BR_OT_insert_comic_scene.execute(self, context)


        # scene = bpy.context.scene
        # for i in range(start_panel_count):
        #     # BR_OT_insert_comic_scene.execute(self,context)   # causes crash



        # BR_OT_insert_comic_scene.execute(self, context)
        # for i in range(start_panel_count):
        #     scene = context.scene
        #     settings = scene.new_3d_panel_settings
        #     title_name = settings.title
        #     start_panel_count = settings.start_panel_count
        #     panel_width = 100
        #     currSceneIndex = getCurrentSceneIndex()
        #     renameAllScenesAfter(self, context)
        #     newSceneIndex = currSceneIndex + 1
        #     newSceneIndexPadded = "%04d" % newSceneIndex
        #     newSceneName = 'p.'+ str(newSceneIndexPadded) + ".w" + str(panel_width) + "h100"
        #     newScene = bpy.ops.scene.new(type='NEW')
        #     bpy.context.scene.name = newSceneName
        #     BR_OT_panel_init.execute(self, context)
        #     BR_OT_panel_validate_naming_all.execute(self, context)
        #     for v in bpy.context.window.screen.areas:
        #         if v.type=='VIEW_3D':
        #             v.spaces[0].region_3d.view_perspective = 'CAMERA'
        #             override = {
        #                 'area': v,
        #                 'region': v.regions[0],
        #             }
        #     bpy.ops.object.select_all(action='DESELECT')
        #     bpy.context.window.scene = bpy.data.scenes[newSceneIndex]

        # save_filepath = str(self.directory) + "." +  str(title_name) + ".blend"
        # bpy.ops.wm.save_as_mainfile(filepath=save_filepath)
        # print (self.directory)
        # bpy.ops.wm.save_as_mainfile(filepath=self.directory)

        # bpy.ops.wm.save_as_mainfile(filepath=self.filepath)

        # bpy.ops.wm.save_as_mainfile(filepath=filename)
        

        # BR_OT_new_panel_row.execute(self, context) # why does this crash......
        
        return {'FINISHED'}
        
    # def invoke(self, context, event):
    #     return context.window_manager.invoke_props_dialog(self)

class BR_OT_first_panel_scene(bpy.types.Operator):
    """make first panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_first_panel"
    bl_label ="首个画格（First）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.context.window.scene = bpy.data.scenes[0]
        return {'FINISHED'}

class BR_OT_last_panel_scene(bpy.types.Operator):
    """make last panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_last_panel"
    bl_label ="末个画格（Last）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        totalScenes = len(bpy.data.scenes) - 1
        bpy.context.window.scene = bpy.data.scenes[totalScenes]
        return {'FINISHED'}

class BR_OT_next_panel_scene(bpy.types.Operator):
    """make next panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_next_panel"
    bl_label ="下一画格（Next）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        index = 0
        totalScenes = len(bpy.data.scenes)
        currScene = getCurrentSceneIndex()
        nextScene = currScene + 1

        # print ('totalScenes is : ', totalScenes)
        print ('currScene is : ', currScene)
        print ('nextScene is : ', nextScene)
        
        if nextScene == totalScenes:
            index = 0
        else:
            index = nextScene
        # print ('index is : ',  index)
        bpy.context.window.scene = bpy.data.scenes[index]


        return {'FINISHED'}

class BR_OT_previous_panel_scene(bpy.types.Operator):
    """make previous panel scene the active scene"""
    bl_idname = "screen.spiraloid_3d_comic_previous_panel"
    bl_label ="上一画格（Previous）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        index = 0
        totalScenes = len(bpy.data.scenes)
        currScene = getCurrentSceneIndex()
        prevScene = currScene -1

        print ('totalScenes is : ', totalScenes)
        print ('currScene is : ', currScene)
        
        if currScene == 0:
            index = totalScenes -1
        else:
            index = prevScene
            print ('index is : ',  index)
        bpy.context.window.scene = bpy.data.scenes[index]

        return {'FINISHED'}

# class BR_OT_clone_comic_scene(bpy.types.Operator):
#     """ Insert a new panel scene after the currently active panel scene, copying contents"""
#     bl_idname = "view3d.spiraloid_3d_comic_clone_panel"
#     bl_label ="Clone"
#     bl_options = {'REGISTER', 'UNDO'}

#     def execute(self, context):
#         currSceneIndex = getCurrentSceneIndex()
#         panels = []
#         for scene in bpy.data.scenes:
#             if "p." in scene.name:
#                 panels.append(scene.name)

#         for panel in panels :
#             for i in range(len(bpy.data.scenes)):
#                 if bpy.data.scenes[i].name == panel:
#                     m = currSceneIndex - 1
#                     if m > currSceneIndex:
#                         sceneNumber = "%04d" % n
#                         bpy.data.scenes[m].name = 'p.'+ str(sceneNumber)

#         resourceSceneIndex = currSceneIndex + 1
#         resourceSceneIndexPadded = "%04d" % resourceSceneIndex
#         targetSceneName = 'p.'+ str(resourceSceneIndexPadded)
#         newScene = bpy.ops.scene.new(type='FULL_COPY')
#         bpy.data.scenes[newSceneIndex].name = targetSceneName
#         bpy.context.window.scene = bpy.data.scenes[resourceSceneIndex]
#         BR_OT_panel_init.execute(self, context)


#         return {'FINISHED'}


class BR_OT_clone_comic_scene(bpy.types.Operator):
    """ Insert a new panel scene after the currently active panel scene, copying contents"""
    bl_idname = "view3d.spiraloid_3d_comic_clone_panel"
    bl_label ="克隆画格（Duplicate）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global material_swatch_object
        material_swatch_object = getCurrentMaterialSwatch()

        currSceneIndex = getCurrentSceneIndex()
        current_scene_name = bpy.data.scenes[currSceneIndex].name
        stringFragments = current_scene_name.split('.')
        x_stringFragments = stringFragments[2]
        xx_stringFragments = x_stringFragments.split('h')
        current_panel_height = xx_stringFragments[1]
        xxx_stringFragments = xx_stringFragments[0].split('w')
        current_panel_width = xxx_stringFragments[1]

        renameAllScenesAfter(self, context)

        newSceneIndex = currSceneIndex + 1
        sceneNumber = "%04d" % newSceneIndex  
        # newSceneName = 'p.'+ str(sceneNumber) + ".w100h100"
        newSceneName = 'p.'+ str(sceneNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)

        newScene = bpy.ops.scene.new(type='FULL_COPY')
        bpy.context.scene.name = newSceneName
        
        bpy.context.scene.cursor.location[2] = 1.52

        # BR_OT_panel_init.execute(self, context)
        BR_OT_panel_validate_naming_all.execute(self, context)

        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                v.spaces[0].region_3d.view_perspective = 'CAMERA'
                try:
                    with context.temp_override(area=v, region=v.regions[0]):
                        if bpy.ops.view3d.view_center_camera.poll():
                            bpy.ops.view3d.view_center_camera()
                except (TypeError, ValueError, AttributeError):
                    try:
                        with bpy.context.temp_override(area=v, region=v.regions[0]):
                            if bpy.ops.view3d.view_center_camera.poll():
                                bpy.ops.view3d.view_center_camera()
                    except Exception:
                        pass
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.window.scene = bpy.data.scenes[newSceneIndex]


        return {'FINISHED'}



class BR_OT_blank_comic_scene(bpy.types.Operator):
    """ Insert a new panel scene after the currently active panel scene, copying contents"""
    bl_idname = "view3d.spiraloid_3d_comic_blank_panel"
    bl_label ="插入黑屏（Insert Black）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        insert_comic_panel(self, context, "Static")
        return {'FINISHED'}

def insert_comic_panel(self, context, camera_strategy):
    global material_swatch_object
    objects = bpy.context.selected_objects
    for obj in objects:
        if obj is not None:
            if bpy.context.object:
                starting_mode = bpy.context.object.mode
                if "OBJECT" not in starting_mode:
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                    bpy.ops.object.select_all(action='DESELECT')

    toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global
    scene = context.scene
    new_panel_row_settings = scene.new_panel_row_settings
    new_panel_count = new_panel_row_settings.new_panel_count
    use_borders = new_panel_row_settings.border_strategy

    for i in range(new_panel_count):
        panel_width = int(100 / new_panel_count)
        currSceneIndex = getCurrentSceneIndex()
        renameAllScenesAfter(self, context)

        numString = getCurrentPanelNumber(False)
        newSceneIndex = currSceneIndex + 1
        newPanelIndex = numString + 1
        newPanelIndexPadded = "%04d" % newPanelIndex
        newSceneName = 'p.'+ str(newPanelIndexPadded) + ".w" + str(panel_width) + "h"  + str(panel_width)
        newScene = bpy.ops.scene.new(type='NEW')
        bpy.context.scene.name = newSceneName
        bpy.context.window.scene = bpy.data.scenes[newSceneIndex]
        # print("=======DEBUG: " + str(currSceneIndex))
        # raise KeyboardInterrupt()
        BR_OT_panel_init.execute(self, context)
        BR_OT_panel_validate_naming_all.execute(self, context)
        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                v.spaces[0].region_3d.view_perspective = 'CAMERA'
                try:
                    with context.temp_override(area=v, region=v.regions[0]):
                        if bpy.ops.view3d.view_center_camera.poll():
                            bpy.ops.view3d.view_center_camera()
                except (TypeError, ValueError, AttributeError):
                    try:
                        with bpy.context.temp_override(area=v, region=v.regions[0]):
                            if bpy.ops.view3d.view_center_camera.poll():
                                bpy.ops.view3d.view_center_camera()
                    except Exception:
                        pass
        bpy.ops.object.select_all(action='DESELECT')

        backstage_collection = getCurrentBackstageCollection()
        if backstage_collection:
            global_material_swatch_object = bpy.data.scenes[0].collection.children['Backstage.Global'].objects['Materials.Global']
            backstage_collection.objects.link(global_material_swatch_object)


            if not toonfill_use_global:
                _b52_set_lc_exclude(backstage_collection.name, True)

        if "Static" not in camera_strategy:
            key_camera_auto(self, context, camera_strategy)
        if use_borders:
            BR_OT_add_letter_border.execute(self, context)
        material_swatch_object = getCurrentMaterialSwatch()
        toggle_workmode(self, context, False)


        # bpy.context.scene["s3dc_toonfill_use_global"] = BoolProperty(s3dc_toonfill_use_global)
        # bpy.context.scene["s3dc_dynamic_shadows"] = BoolProperty(s3dc_dynamic_shadows)
        # bpy.context.scene["s3dc_toonfill_mode_enum"] = EnumProperty(items=items)
        # bpy.context.scene["s3dc_toonfill_type"] = EnumProperty(items=items)


    return {'FINISHED'}




# def split_comic_panel(self, context, camera_strategy):
#     toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global

#     scene = context.scene
#     new_panel_row_settings = scene.new_panel_row_settings
#     new_panel_count = new_panel_row_settings.new_panel_count
#     use_borders = new_panel_row_settings.border_strategy

#     for i in range(2):

#         # rowSceneNames = getRowSceneNames()
#         # rowCount = len(rowSceneNames)
#         panel_width = int(100 / 2)
#         panel_number = getCurrentPanelNumber(True)    
#         currentRowScene_name = 'p.'+ str(panel_number) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)
#         bpy.data.scenes[currSceneIndex].name = currentRowScene_name

#         currSceneIndex = getCurrentSceneIndex()
#         renameAllScenesAfter(self, context)

#         numString = getCurrentPanelNumber(False)
#         newSceneIndex = currSceneIndex + 1
#         newPanelIndex = numString + 1
#         newPanelIndexPadded = "%04d" % newPanelIndex
#         newSceneName = 'p.'+ str(newPanelIndexPadded) + ".w" + str(panel_width) + "h"  + str(panel_width)

#         newScene = bpy.ops.scene.new(type='FULL_COPY')

#         bpy.context.scene.name = newSceneName
#         bpy.context.window.scene = bpy.data.scenes[newSceneIndex]
#         raise KeyboardInterrupt()
#         # print("=======DEBUG: " + str(currSceneIndex))
#         BR_OT_panel_init.execute(self, context)
#         BR_OT_panel_validate_naming_all.execute(self, context)
#         for v in bpy.context.window.screen.areas:
#             if v.type=='VIEW_3D':
#                 v.spaces[0].region_3d.view_perspective = 'CAMERA'
#                 override = {
#                     'area': v,
#                     'region': v.regions[0],
#                 }
#         bpy.ops.object.select_all(action='DESELECT')

#         backstage_collection = getCurrentBackstageCollection()
#         if backstage_collection:
#             global_material_swatch_object = bpy.data.scenes[0].collection.children['Backstage.Global'].objects['Materials.Global']
#             backstage_collection.objects.link(global_material_swatch_object)

#             if not toonfill_use_global:
#                 bpy.context.view_layer.layer_collection.children[backstage_collection.name].exclude = True

#         if "Static" not in camera_strategy:
#             key_camera_auto(self, context, camera_strategy)
#         if use_borders:
#             BR_OT_add_letter_border.execute(self, context)

#     return {'FINISHED'}


class NewPanelRowSettings(bpy.types.PropertyGroup):
    new_panel_count : bpy.props.IntProperty(name="side-by-side panel count:",  description="number of side-by-side panels to insert in new row", min=1, max=4, default=1 )
    
    camera_strategy : bpy.props.EnumProperty(
        name="Camera Move", 
        description="Type of camera movement for new panels", 
        items={
            ("camera_slide_up", "Slide Up","SlideUp", 0),
            ("camera_slide_down","Slide Down", "SlideDown", 1),
            ("camera_truck_in", "Truck In","TruckIn", 2),
            ("camera_truck_out", "Truck Out","TruckOut", 3),
            ("camera_pan_left", "Pan Left","PanLeft", 4),
            ("camera_pan_right", "Pan Right","PanRight", 5),
            ("camera_random", "Randomize","Random", 6),
            ("world_spin_cw", "Randomize","Random", 7),
            ("world_spin_ccw", "Randomize","Random", 8),
            ("Static", "Static","Static", 9),
            },
        default="camera_random"
    )
    border_strategy : bpy.props.BoolProperty(name="Frame",  description="create a border frame around the panels", default=True )
    duplicate : bpy.props.BoolProperty(name="Duplicate",  description="Duplicate current panel", default=True )

# class BR_OT_new_panel_row(bpy.types.Operator, ImportHelper):
class BR_OT_new_panel_row(bpy.types.Operator):
    """Insert a new empty comic panel scene or scenes side by side"""
    bl_idname = "screen.spiraloid_3d_comic_new_panel_split"
    bl_label = "添加画格行（Add Panels）"
    bl_options = {'REGISTER', 'UNDO'}
    # config: bpy.props.PointerProperty(type=NewPanelRowSettings)

    # [FIX 3/3] 恢复 draw() + invoke_props_dialog：点击 Insert... 后弹出带 OK/Cancel 的对话框（与 2.93 原版一致，含 number of new panels in row）
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        try:
            new_panel_row_settings = scene.new_panel_row_settings
        except AttributeError:
            layout.label(text="Error: new_panel_row_settings not registered", icon="ERROR")
            return
        layout.prop(new_panel_row_settings, "new_panel_count", text="number of new panels in row")
        split = layout.split(factor=0.5)
        col_1 = split.column()
        col_2 = split.column()
        col_1.separator()
        col_1.prop(new_panel_row_settings, "border_strategy", text="Frame / Border")
        col_1.prop(new_panel_row_settings, "duplicate", text="Duplicate Current")
        layout.prop(new_panel_row_settings, "camera_strategy", text="镜头运动")
        layout.separator()

    def invoke(self, context, event):
        # 弹出对话框（宽 420），点击 OK 后执行 execute()
        return context.window_manager.invoke_props_dialog(self, width=420)

    # def draw(self, context):
    #     layout = self.layout
    #     scene = context.scene
    #     new_panel_row_settings = scene.new_panel_row_settings
    #     layout = self.layout
    #     layout.prop(new_panel_row_settings, "new_panel_count")
    #     split = layout.split(factor=0.5)
    #     col_1 = split.column()
    #     col_2 = split.column()
    #     layout.separator()
    #     col_1.separator()
    #     col_1.prop(new_panel_row_settings, "border_strategy")
    #     col_1.prop(new_panel_row_settings, "duplicate")
    #     layout.prop(new_panel_row_settings, "camera_strategy", text="镜头运动")
    #     layout.separator()

    # def execute(self, context):
    #     currSceneIndex = getCurrentSceneIndex()
    #     scene = bpy.data.scenes[0]
    #     if "Cover" not in scene.name:
    #         self.report({'ERROR'}, 'No 3D Comic folders found next to .blend file!  you need to Build 3D Comic first.')
    #     else:
    #         settings = context.scene.new_panel_row_settings
    #         # current_scene_name = context.scene.name
    #         # if "p." in bpy.context.scene.name:    
    #         if not settings.duplicate:
    #             insert_comic_panel(self, context, settings.camera_strategy)
    #         else:
    #             if currSceneIndex == 0:
    #                 self.report({'ERROR'}, "You Don't have any panels to duplicate and split yet")
    #             else:
    #                 split_comic_panel(self, context, settings.camera_strategy)
    #         # else:
    #             # self.report({'ERROR'}, "No Active Comic Found")

    #     return {'FINISHED'}

    # def invoke(self, context, event):
    #     return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global
        scene = context.scene
        new_panel_row_settings = scene.new_panel_row_settings
        new_panel_count = new_panel_row_settings.new_panel_count
        use_borders = new_panel_row_settings.border_strategy
        currSceneIndex = getCurrentSceneIndex()


        # rowSceneNames = getRowSceneNames()
        # rowCount = len(rowSceneNames)
        rowSceneIndexes = []
        panel_width = int(100 / 2)
        panel_number = getCurrentPanelNumber(True)    
        currentRowScene_name = 'p.'+ str(panel_number) + '.w' + str(panel_width) + 'h' + str(panel_width)
        bpy.data.scenes[currSceneIndex].name = currentRowScene_name
        rowSceneIndexes.append(currSceneIndex)

        renameAllScenesAfter(self, context)

        numString = getCurrentPanelNumber(False)
        newSceneIndex = currSceneIndex + 1
        newPanelIndex = numString + 1
        newPanelIndexPadded = "%04d" % newPanelIndex
        newSceneName = 'p.'+ str(newPanelIndexPadded) + ".w" + str(panel_width) + "h"  + str(panel_width)

        newScene = bpy.ops.scene.new(type='FULL_COPY')

        bpy.context.scene.name = newSceneName
        bpy.context.window.scene = bpy.data.scenes[newSceneIndex]
        rowSceneIndexes.append(newSceneIndex)




        # raise KeyboardInterrupt()
        # print("=======DEBUG: " + str(currSceneIndex))

        for sceneIndex in rowSceneIndexes:
            bpy.context.window.scene = bpy.data.scenes[sceneIndex]
            # BR_OT_panel_init.execute(self, context)
            BR_OT_panel_validate_naming_all.execute(self, context)


        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                v.spaces[0].region_3d.view_perspective = 'CAMERA'
                try:
                    with context.temp_override(area=v, region=v.regions[0]):
                        if bpy.ops.view3d.view_center_camera.poll():
                            bpy.ops.view3d.view_center_camera()
                except (TypeError, ValueError, AttributeError):
                    try:
                        with bpy.context.temp_override(area=v, region=v.regions[0]):
                            if bpy.ops.view3d.view_center_camera.poll():
                                bpy.ops.view3d.view_center_camera()
                    except Exception:
                        pass
        bpy.ops.object.select_all(action='DESELECT')

        # backstage_collection = getCurrentBackstageCollection()
        # if backstage_collection:
        #     global_material_swatch_object = bpy.data.scenes[0].collection.children['Backstage.Global'].objects['Materials.Global']
        #     backstage_collection.objects.link(global_material_swatch_object)

        #     if not toonfill_use_global:
        #         bpy.context.view_layer.layer_collection.children[backstage_collection.name].exclude = True

        # if "Static" not in camera_strategy:
        #     key_camera_auto(self, context, camera_strategy)
        # if use_borders:
        #     BR_OT_add_letter_border.execute(self, context)

        return {'FINISHED'}



class BR_OT_new_panel(bpy.types.Operator):
    """Insert a new empty comic panel"""
    bl_idname = "screen.spiraloid_3d_comic_new_panel"
    bl_label = "添加画格（Add Panel）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = bpy.data.scenes[0]
        if "Cover" not in scene.name:
            self.report({'ERROR'}, 'No 3D Comic folders found next to .blend file!  you need to Build 3D Comic first.')
        else:
            insert_comic_panel(self, context, "camera_random")
        return {'FINISHED'}


class BR_OT_insert_comic_scene(bpy.types.Operator):
    """ Insert a new panel scene after the currently active panel scene"""
    bl_idname = "view3d.spiraloid_3d_comic_create_panel"
    bl_label ="创建新画格…（New Panel）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        insert_comic_panel(self, context, settings.camera_strategy)

        # currSceneIndex = getCurrentSceneIndex()
        # renameAllScenesAfter(self, context)
        # # panels = []
        # # for scene in bpy.data.scenes:
        # #     if "p." in scene.name:
        # #         panels.append(scene.name)

        # # for panel in panels :
        # #     for i in range(len(bpy.data.scenes)):
        # #         if bpy.data.scenes[i].name == panel:
        # #             m = currSceneIndex - 1
        # #             if m > currSceneIndex:
        # #                 sceneNumber = "%04d" % m
        # #                 bpy.data.scenes[m].name = 'p.'+ str(sceneNumber)

        # newSceneIndex = currSceneIndex + 1
        # newSceneIndexPadded = "%04d" % newSceneIndex
        # newSceneName = 'p.'+ str(newSceneIndexPadded) + ".w100h100"
        # newScene = bpy.ops.scene.new(type='NEW')
        # bpy.context.scene.name = newSceneName
        # BR_OT_panel_init.execute(self, context)
        # BR_OT_panel_validate_naming_all.execute(self, context)

        # for v in bpy.context.window.screen.areas:
        #     if v.type=='VIEW_3D':
        #         v.spaces[0].region_3d.view_perspective = 'CAMERA'
        #         override = {
        #             'area': v,
        #             'region': v.regions[0],
        #         }




        # bpy.ops.object.select_all(action='DESELECT')





        # return {'FINISHED'}



class BR_OT_extract_comic_scene(bpy.types.Operator):
    """export current panel scene"""
    bl_idname = "view3d.spiraloid_3d_comic_extract_panel"
    bl_label ="提取画格场景…（Extract Panel Scene）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # if bpy.data.is_dirty:
        #     # self.report({'WARNING'}, "You must save your file first!")
        #     bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')

        # else:
        currSceneIndex = getCurrentSceneIndex()
        sceneNumber = "%04d" % currSceneIndex
        current_scene = bpy.context.scene
        current_scene_name = current_scene.name
        file_path = bpy.data.filepath
        file_name = bpy.path.display_name_from_filepath(file_path)
        file_ext = '.blend'
        blend_file_dir = file_path.replace(file_name+file_ext, '')
        file_dir = os.path.dirname(os.path.dirname(file_path))
                 
        panels_dir = file_dir+"\\panels\\"
        if not os.path.exists(panels_dir):
            os.makedirs(panels_dir)

        export_file = (panels_dir + current_scene_name + ".blend") 

        for scene in bpy.data.scenes :
            scene_name = scene.name
            if scene is not current_scene :
                # bpy.ops.scene.delete({'scene': bpy.data.scenes[current_scene_name]})  
                # bpy.context.screen.scene = bpy.data.scenes[scene_name]
                bpy.context.window.scene = bpy.data.scenes[scene_name]
                bpy.ops.scene.delete()
                empty_trash(self, context)

        bpy.ops.wm.save_as_mainfile(filepath=export_file)
        ## reopen scene from before build comic
        bpy.ops.wm.open_mainfile(filepath=file_path)
        self.report({'INFO'}, 'Exported  ./panels/' + current_scene_name + '.blend!')


        return {'FINISHED'}

class BR_OT_inject_comic_scene(Operator, ImportHelper):
    """import current panel scene"""
    bl_idname = "view3d.spiraloid_3d_comic_inject_panel"
    bl_label ="注入画格场景…（Inject Panel Scene）"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".blend"  # ExportHelper mixin class uses this
    filter_glob: StringProperty(
        default="*.blend",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )


    def execute(self, context):
        objects = bpy.context.selected_objects
        if objects is not None :
            for obj in objects:
                starting_mode = bpy.context.object.mode
                if "OBJECT" not in starting_mode:
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                    bpy.ops.object.select_all(action='DESELECT')

        filepath = self.filepath
        file_path = bpy.data.filepath

        # currSceneIndex = getCurrentSceneIndex()
        # renameAllScenesAfter(self, context)
        # newSceneIndex = currSceneIndex + 1
        # newSceneIndexPadded = "%04d" % newSceneIndex
        # imported_scene_name = 'temp.'+ str(newSceneIndexPadded) + ".w100h100"



        currSceneIndex = getCurrentSceneIndex()
        renameAllScenesAfter(self, context)
        numString = getCurrentPanelNumber(False)
        newSceneIndex = currSceneIndex + 1
        newPanelIndex = numString + 1
        newPanelIndexPadded = "%04d" % newPanelIndex
        imported_scene_name = 'temp.'+ str(newPanelIndexPadded) + ".w100h100"


        # scenes = []
        # with bpy.data.libraries.load(filepath ) as (data_from, data_to):
        #     for name in data_from.scenes:
        #         scenes.append({'name': name})
                        
        #     action = bpy.ops.wm.append
        #     action(directory=filepath + "/Scene/", files=scenes, use_recursive=True)
        #     scenes = bpy.data.scenes[-len(scenes):]

        # [P0-E] Accept both layouts:
        #   * legacy 3DComicToolkit .blend -> scenes prefixed with "p."
        #   * any ordinary .blend           -> import every scene it contains
        # Previously a non-"p." scene reported an error per scene and then
        # crashed on imported_scene.name because nothing had been appended.
        with bpy.data.libraries.load(filepath) as (data_from, data_to):
            available_scenes = list(data_from.scenes)

        panel_scene_names = [n for n in available_scenes if n.startswith("p.")]
        is_legacy_comic = bool(panel_scene_names)
        scene_names = panel_scene_names if is_legacy_comic else available_scenes

        if not scene_names:
            self.report({'ERROR'}, 'No scenes found in ' + os.path.basename(filepath))
            return {'CANCELLED'}

        if is_legacy_comic:
            print('[3DComicToolkit] Importing legacy comic: %d panel scene(s)' % len(scene_names))
        else:
            print('[3DComicToolkit] Importing generic .blend: %d scene(s)' % len(scene_names))

        names_before = {s.name for s in bpy.data.scenes}
        bpy.ops.wm.append(
            directory=filepath + "/Scene/",
            files=[{'name': n} for n in scene_names],
            use_recursive=True,
        )
        imported_scenes = [s for s in bpy.data.scenes if s.name not in names_before]

        if not imported_scenes:
            self.report({'ERROR'}, 'Import produced no scenes from ' + os.path.basename(filepath))
            return {'CANCELLED'}

        # Generic .blend files carry no panel naming; adapt them so the rest of
        # the toolkit (Page/Panel/Camera/Letters/Export) can operate on them.
        if not is_legacy_comic:
            for offset, imported_scene in enumerate(imported_scenes):
                _b52_adapt_scene_to_comic_panel(imported_scene, newPanelIndex + offset)

        bpy.context.window.scene = imported_scenes[0]

        # BR_OT_panel_init.execute(self, context)
        BR_OT_panel_validate_naming_all.execute(self, context)
        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                v.spaces[0].region_3d.view_perspective = 'CAMERA'
                try:
                    with context.temp_override(area=v, region=v.regions[0]):
                        if bpy.ops.view3d.view_center_camera.poll():
                            bpy.ops.view3d.view_center_camera()
                except (TypeError, ValueError, AttributeError):
                    try:
                        with bpy.context.temp_override(area=v, region=v.regions[0]):
                            if bpy.ops.view3d.view_center_camera.poll():
                                bpy.ops.view3d.view_center_camera()
                    except Exception:
                        pass
        bpy.ops.object.select_all(action='DESELECT')

        return {'FINISHED'}





class BR_OT_delete_comic_scene(bpy.types.Operator):
    """ Delete currently active panel scene"""
    bl_idname = "view3d.spiraloid_3d_comic_delete_panel"
    bl_label ="删除画格（Delete）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        currSceneIndex = getCurrentSceneIndex()
        previousSceneIndex = currSceneIndex - 1
        paddedNumString = getCurrentPanelNumber(True)
        ink_thick_tex_name = "L_InkThickness." + str(paddedNumString)
        for itex in bpy.data.textures: 
            itex_name = itex.name
            if ink_thick_tex_name == itex_name:
                bpy.data.textures.remove(itex)


        bpy.ops.scene.delete()
        bpy.context.window.scene = bpy.data.scenes[previousSceneIndex]
        renameAllScenesAfter(self, context)
        BR_OT_panel_validate_naming_all.execute(self, context)
        try:
            bpy.context.window.scene = bpy.data.scenes[currSceneIndex]
        except:
            bpy.data.scenes[previousSceneIndex]



        return {'FINISHED'}

class BR_OT_reorder_scene_later(bpy.types.Operator):
    """Shift current scene later, changing the read order of panel scenes"""
    bl_idname = "screen.spiraloid_3d_comic_reorder_scene_later"
    bl_label ="画格后移（Shift Scene Later）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # currSceneIndex = getCurrentSceneIndex()
        # nextSceneIndex = currSceneIndex + 1
        # current_scene_name = bpy.data.scenes[currSceneIndex].name
        # next_scene_name = bpy.data.scenes[nextSceneIndex].name
        # bpy.data.scenes[nextSceneIndex].name = next_scene_name + ".1111111111"
        # bpy.data.scenes[currSceneIndex].name = next_scene_name
        # bpy.data.scenes[nextSceneIndex].name = current_scene_name

        # validate_naming()
        # bpy.context.window.scene = bpy.data.scenes[currSceneIndex]
        # validate_naming()
        # bpy.context.window.scene = bpy.data.scenes[nextSceneIndex]
        currSceneIndex = getCurrentSceneIndex()
        nextSceneIndex = currSceneIndex + 1
        current_scene_name = bpy.data.scenes[currSceneIndex].name
        next_scene_name = bpy.data.scenes[nextSceneIndex].name
        tmp_name = "zzzz999"
        bpy.data.scenes[nextSceneIndex].name = tmp_name
        currSceneIndex = getCurrentSceneIndex()
        bpy.data.scenes[currSceneIndex].name = next_scene_name


        # bpy.data.scenes[currSceneIndex].name = previous_scene_name

        for i in range(len(bpy.data.scenes)):
            if bpy.data.scenes[i].name == tmp_name:
                bpy.data.scenes[i].name = current_scene_name
                bpy.context.window.scene = bpy.data.scenes[currSceneIndex]

        bpy.context.window.scene = bpy.data.scenes[currSceneIndex]
        validate_naming(self, context)
        bpy.context.window.scene = bpy.data.scenes[nextSceneIndex]
        validate_naming(self, context)


        return {'FINISHED'}

class BR_OT_reorder_scene_earlier(bpy.types.Operator):
    """Shift current scene Earlier, changing the read order of panel scenes"""
    bl_idname = "screen.spiraloid_3d_comic_reorder_scene_earlier"
    bl_label ="画格前移（Shift Scene Earlier）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        currSceneIndex = getCurrentSceneIndex()
        previousSceneIndex = currSceneIndex - 1
        current_scene_name = bpy.data.scenes[currSceneIndex].name
        previous_scene_name = bpy.data.scenes[previousSceneIndex].name
        tmp_name = "zzzz"
        bpy.data.scenes[previousSceneIndex].name = tmp_name
        currSceneIndex = getCurrentSceneIndex()
        bpy.data.scenes[currSceneIndex].name = previous_scene_name
        validate_naming(self, context)


        # bpy.data.scenes[currSceneIndex].name = previous_scene_name

        for i in range(len(bpy.data.scenes)):
            if bpy.data.scenes[i].name == tmp_name:
                bpy.data.scenes[i].name = current_scene_name
                bpy.context.window.scene = bpy.data.scenes[currSceneIndex + 1]
                validate_naming(self, context)

        bpy.context.window.scene = bpy.data.scenes[currSceneIndex]

        return {'FINISHED'}


class BR_OT_add_letter_border(bpy.types.Operator):
    """Add a panel border"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_border"
    bl_label ="添加外框气泡（Add Border）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if bpy.context.object:
            starting_mode = bpy.context.object.mode
            if "OBJECT" not in starting_mode:
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                bpy.ops.object.select_all(action='DESELECT')

        export_collection = getCurrentExportCollection(self, context)
        active_camera = bpy.context.scene.camera
        if active_camera is not None :
            active_camera_name = active_camera.name
        else:
            self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)

        bpy.ops.object.select_all(action='DESELECT')
        # load_resource("letter_wordballoon.blend", False)
        load_resource(self, context, "letter_border.002.blend", False)
        # load_resource("letter_caption.blend")
        # load_resource("letter_sfx.blend")

        objects = bpy.context.selected_objects
        if objects is not None :
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        letter = objects[0]
        letter_group = getCurrentLetterGroup()

        bpy.ops.object.select_all(action='DESELECT')
        letter.select_set(state=True)
        letter_group.select_set(state=True)
        bpy.context.view_layer.objects.active = letter_group
        # bpy.ops.object.parent_set()
        bpy.ops.object.parent_no_inverse_set()

        bpy.ops.object.select_all(action='DESELECT')
        letter.select_set(state=True)
        bpy.context.view_layer.objects.active = letter
        bpy.ops.object.origin_clear()

        camera_position = active_camera.matrix_world.to_translation()


        letters_collection = getCurrentLettersCollection()
        if not letters_collection:
            self.report({'WARNING'}, "Letters Collection was not found in scene, skipping letters export of " + scene.name)
        else:
            for obj in objects:
                bpy.context.collection.objects.unlink(obj) 
                letters_collection.objects.link(obj)

        bpy.ops.object.select_all(action='DESELECT')
        # letter.select_set(state=True)
        # bpy.context.view_layer.objects.active = letter
        # for v in bpy.context.window.screen.areas:
        #     if v.type=='VIEW_3D':
        #         bpy.ops.view3d.snap_cursor_to_selected()


        return {'FINISHED'}



class BR_OT_add_letter_caption(bpy.types.Operator):
    """Add a new worldballoon with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_caption"
    bl_label ="添加普通对话气泡（Add Caption）"
    bl_options = {'REGISTER', 'UNDO'}

    # def execute(self, context):

    #     export_collection = getCurrentExportCollection(self, context)
    #     active_camera = bpy.context.scene.camera
    #     if active_camera is not None :
    #         active_camera_name = active_camera.name
    #     else:
    #         self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)

    #     bpy.ops.object.select_all(action='DESELECT')
    #     # load_resource("letter_wordballoon.blend", False)
    #     # load_resource(self, context, "letter_wordballoon.000.blend", True)
    #     load_resource(self, context, "letter_caption.000.blend", True)

    #     # load_resource("letter_caption.blend")
    #     # load_resource("letter_sfx.blend")

    #     objects = bpy.context.selected_objects
    #     if objects is not None :
    #         bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    #     letter = objects[0]
    #     letter_group = getCurrentLetterGroup()

    #     bpy.ops.object.select_all(action='DESELECT')
    #     letter.select_set(state=True)
    #     letter_group.select_set(state=True)
    #     bpy.context.view_layer.objects.active = letter_group
    #     # bpy.ops.object.parent_set()
    #     bpy.ops.object.parent_no_inverse_set()

    #     bpy.ops.object.select_all(action='DESELECT')
    #     letter.select_set(state=True)
    #     bpy.context.view_layer.objects.active = letter
    #     bpy.ops.object.origin_clear()

    #     camera_position = active_camera.matrix_world.to_translation()


    #     letters_collection = getCurrentLettersCollection()
    #     if not letters_collection:
    #         self.report({'WARNING'}, "Export Collection " + letters_collection.name + "was not found in scene, skipping export of" + scene.name)
    #     else:
    #         for obj in objects:
    #             bpy.context.collection.objects.unlink(obj) 
    #             letters_collection.objects.link(obj)

    #     bpy.ops.object.select_all(action='DESELECT')
    #     letter.select_set(state=True)
    #     bpy.context.view_layer.objects.active = letter


    #     return {'FINISHED'}

    def execute(self, context):
        add_letter(self, context, "caption", 1)
        return {'FINISHED'}



def add_letter(self, context, letter_type, letter_count):
    if bpy.context.object:
        starting_mode = bpy.context.object.mode
        if "OBJECT" not in starting_mode:
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
            bpy.ops.object.select_all(action='DESELECT')

    export_collection = getCurrentExportCollection(self, context)
    backstage_collection = getCurrentBackstageCollection()

    

    active_camera = bpy.context.scene.camera
    if active_camera is not None :
        active_camera_name = active_camera.name
    else:
        self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)

    bpy.ops.object.select_all(action='DESELECT')
    # load_resource("letter_wordballoon.blend", False)

    if "wordballoon" in letter_type:
        if letter_count == 1:
            load_resource(self, context, "letter_wordballoon.000.blend", True)
        if letter_count == 2:
            load_resource(self, context, "letter_wordballoon_double.000.blend", True)
        if letter_count == 3:
            load_resource(self, context, "letter_wordballoon_triple.000.blend", True)
        if letter_count == 4:
            load_resource(self, context, "letter_wordballoon_quadruple.000.blend", True)


    if "caption" in letter_type:
        if letter_count == 1:
            load_resource(self, context, "letter_caption.000.blend", True)



    if "sfx" in letter_type:
        if letter_count == 1:
            load_resource(self, context, "letter_sfx.000.blend", True)
    #     load_resource(self, context, "letter_sfx.blend", False)


    # load_resource("letter_caption.blend")
    # load_resource("letter_sfx.blend")

    objects = bpy.context.selected_objects
    if objects is not None :
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    letter = objects[0]
    letter_group = getCurrentLetterGroup()

    bpy.ops.object.select_all(action='DESELECT')
    letter.select_set(state=True)
    letter_group.select_set(state=True)
    bpy.context.view_layer.objects.active = letter_group
    # bpy.ops.object.parent_set()
    bpy.ops.object.parent_no_inverse_set()

    if backstage_collection:
        _b52_set_lc_exclude(backstage_collection.name, False)
        backstage_objects = backstage_collection.objects
        for mobj in backstage_objects:
            if "Materials." in mobj.name:
                # bpy.context.scene.collection.objects.link(mobj)
                bpy.ops.object.select_all(action='DESELECT')
                letter.select_set(state=True)
                mobj.select_set(state=True)
                bpy.context.view_layer.objects.active = mobj
                bpy.ops.object.material_slot_copy()

                bpy.ops.object.select_all(action='DESELECT')
                letter.select_set(state=True)
                bpy.context.view_layer.objects.active = letter
                for i, mat in reversed(list(enumerate(letter.data.materials))):
                    if ("L_Wordballoon." not in mat.name) and  ("L_WordballoonOutlineDark." not in mat.name) and  ("L_WordballoonOutlineLight." not in mat.name):
                        # letter.data.materials.pop(index=i)
                        letter.active_material_index = i
                        bpy.ops.object.material_slot_remove()

                for p in letter.data.polygons:
                    if p.material_index >= len(letter.data.materials):
                        p.material_index = -1
                        


                for tobj in letter.children:
                    if tobj.type == 'FONT':
                        bpy.ops.object.select_all(action='DESELECT')
                        tobj.select_set(state=True)
                        mobj.select_set(state=True)
                        bpy.context.view_layer.objects.active = mobj
                        bpy.ops.object.material_slot_copy()

                        bpy.ops.object.select_all(action='DESELECT')
                        tobj.select_set(state=True)
                        bpy.context.view_layer.objects.active = tobj
                        for i, tmat in reversed(list(enumerate(tobj.data.materials))):
                            if ("L_WordballoonText." not in tmat.name):
                                # tobj.data.materials.pop(index=i)
                                tobj.active_material_index = i
                                bpy.ops.object.material_slot_remove()


        # bpy.context.scene.collection.objects.unlink(mobj)
        # bpy.context.scene.collection.objects.unlink(text_material_object)
        bpy.ops.object.select_all(action='DESELECT')
        letter.select_set(state=True)
        bpy.context.view_layer.objects.active = letter
        _b52_set_lc_exclude(backstage_collection.name, True)
    

    bpy.ops.object.select_all(action='DESELECT')
    letter.select_set(state=True)
    bpy.context.view_layer.objects.active = letter
    bpy.ops.object.origin_clear()

    camera_position = active_camera.matrix_world.to_translation()


    letters_collection = getCurrentLettersCollection()
    if not letters_collection:
        self.report({'WARNING'}, "Export Collection " + letters_collection.name + "was not found in scene, skipping export of" + scene.name)
    else:
        for obj in objects:
            bpy.context.collection.objects.unlink(obj) 
            letters_collection.objects.link(obj)

    bpy.ops.object.select_all(action='DESELECT')
    letter.select_set(state=True)
    bpy.context.view_layer.objects.active = letter
    for v in bpy.context.window.screen.areas:
        if v.type=='VIEW_3D':
            bpy.ops.view3d.snap_cursor_to_selected()


    return {'FINISHED'}


class BR_OT_add_letter_wordballoon(bpy.types.Operator):
    """Add a new worldballoon with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_wordballoon"
    bl_label ="添加单词气泡（Add Wordballoon）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        add_letter(self, context, "wordballoon", 1)
        return {'FINISHED'}

class BR_OT_add_letter_wordballoon_double(bpy.types.Operator):
    """Add a new worldballoon with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_wordballoon_double"
    bl_label ="添加双格气泡（Add Wordballoon Double）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        add_letter(self, context, "wordballoon", 2)
        return {'FINISHED'}

class BR_OT_add_letter_wordballoon_triple(bpy.types.Operator):
    """Add a new worldballoon with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_wordballoon_triple"
    bl_label ="添加三格气泡（Add Wordballoon Triple）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        add_letter(self, context, "wordballoon", 3)
        return {'FINISHED'}

class BR_OT_add_letter_wordballoon_quadruple(bpy.types.Operator):
    """Add a new worldballoon with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_wordballoon_quadruple"
    bl_label ="添加四格气泡（Add Wordballoon Quadruple）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        add_letter(self, context, "wordballoon", 4)
        return {'FINISHED'}


# class BR_OT_language_select_english(bpy.types.Operator):
#     """Set Active lettering language to English"""
#     bl_idname = "view3d.spiraloid_3d_comic_language_select_english"
#     bl_label ="English"
#     bl_options = {'REGISTER', 'UNDO'}

#     def execute(self, context):
#         global active_language 
#         current_scene = bpy.context.scene
#         active_language = current_scene.panel_settings.s3dc_language
#         set_active_language()
#         return {'FINISHED'}



class BR_OT_add_letter_sfx(bpy.types.Operator):
    """Add a new sfx with letters"""
    bl_idname = "view3d.spiraloid_3d_comic_add_letter_sfx"
    bl_label ="添加音效气泡（Add Sfx）"
    bl_options = {'REGISTER', 'UNDO'}

    # def execute(self, context):
    #     if bpy.context.object:
    #         starting_mode = bpy.context.object.mode
    #         if "OBJECT" not in starting_mode:
    #             bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
    #             bpy.ops.object.select_all(action='DESELECT')
    #     export_collection = getCurrentExportCollection(self, context)
    #     letters_collection = getCurrentLettersCollection()
    #     objects = bpy.context.selected_objects

    #     active_camera = bpy.context.scene.camera
    #     if active_camera is not None :
    #         active_camera_name = active_camera.name
    #     else:
    #         self.report({'ERROR'}, 'No Camera found in scene: ' + bpy.context.scene.name)

    #     bpy.ops.object.select_all(action='DESELECT')
    #     # load_resource("letter_wordballoon.blend")
    #     # load_resource("letter_caption.blend")
    #     load_resource(self, context, "letter_sfx.blend", False)
    #     imported_objects = bpy.context.selected_objects

    #     if not letters_collection:
    #         self.report({'WARNING'}, "Export Collection " + letters_collection.name + "was not found in scene, skipping export of" + scene.name)
    #     else:
    #         if imported_objects:
    #             bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    #             letter = imported_objects[0]
    #             letter_group = getCurrentLetterGroup()
    #             for obj in imported_objects:
    #                 bpy.context.collection.objects.unlink(obj) 
    #                 letters_collection.objects.link(obj)

    #             bpy.ops.object.select_all(action='DESELECT')
    #             letter.select_set(state=True)
    #             letter_group.select_set(state=True)
    #             bpy.context.view_layer.objects.active = letter_group
    #             # bpy.ops.object.parent_set()
    #             bpy.ops.object.parent_no_inverse_set()

    #             bpy.ops.object.select_all(action='DESELECT')
    #             letter.select_set(state=True)
    #             bpy.context.view_layer.objects.active = letter
    #             bpy.ops.object.origin_clear()

    #             camera_position = active_camera.matrix_world.to_translation()


    #     bpy.ops.object.select_all(action='DESELECT')
    #     letter.select_set(state=True)
    #     bpy.context.view_layer.objects.active = letter
    #     for v in bpy.context.window.screen.areas:
    #         if v.type=='VIEW_3D':
    #             bpy.ops.view3d.snap_cursor_to_selected()


    #     return {'FINISHED'}

    def execute(self, context):
        add_letter(self, context, "sfx", 1)
        return {'FINISHED'}



def key_camera_auto(self, context, camera_strategy):
    panel_number = getCurrentPanelNumber(True)

    active_camera = bpy.context.scene.camera
    start = bpy.context.scene.frame_start
    end = bpy.context.scene.frame_end
    previous_random_int = 0
    mid = int(end / 2.3)
    randomized_camera_strategy = "undefined camera strategy"
    if active_camera:
        active_camera.animation_data_clear()
        C=bpy.context
        if (C):
            old_area_type = C.area.type
            C.area.type='DOPESHEET_EDITOR'

            if camera_strategy == "camera_random":
                # print("Camera needs to pan randomly!!!!!!!!!!!!!")
                index =[
                    ("camera_slide_up"),
                    ("camera_slide_down"),
                    ("camera_pan_left"),
                    ("camera_pan_right"),
                    ("camera_truck_in"),
                    ("camera_truck_out"),
                    ("turntable_cw"),
                    ("turntable_ccw")
                ]
                i = len(index) -1
                if i >= 0:
                    random_int = random.randint(0, i)
                    while (random_int == previous_random_int):
                        random_int = random.randint(0, i)
                        if (random_int != previous_random_int):
                            break
                else:
                    random_int = 0
                previous_random_int = random_int
                camera_strategy = index[random_int]
            # print(randomized_camera_strategy)

            if camera_strategy == "camera_slide_up":
                bpy.context.scene.frame_current = start
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = -10
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 0
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "camera_slide_down":
                bpy.context.scene.frame_current = start
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 10
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 3
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "camera_pan_left":
                bpy.context.scene.frame_current = start
                active_camera.location[0] = 10
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] = 2
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "camera_pan_right":
                bpy.context.scene.frame_current = start
                active_camera.location[0] = -10
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] = -2
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "camera_truck_in":
                bpy.context.scene.frame_current = start
                active_camera.location[0] =  0
                active_camera.location[1] = -30
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] =  0
                active_camera.location[1] = -15
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "camera_truck_out":
                bpy.context.scene.frame_current = start
                active_camera.location[0] =  0
                active_camera.location[1] = -12
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=start)

                bpy.context.scene.frame_current = mid
                active_camera.location[0] =  0
                active_camera.location[1] = -17
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=mid)

                bpy.context.scene.frame_current = end
                active_camera.location[0] = 0.0
                active_camera.location[1] = -30
                active_camera.location[2] = 1.52
                active_camera.keyframe_insert(data_path="location", index=-1, frame=end)

                bpy.ops.action.interpolation_type(type='BEZIER')
                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "turntable_cw":
                bpy.ops.object.select_all(action='DESELECT')
                bpy.ops.curve.primitive_bezier_circle_add(radius=1, enter_editmode=False, align='WORLD', location=(0, 0, 0), scale=(3, 3, 3))
                turntable_object = bpy.context.selected_objects[0]
                turntable_object_name = "Turntable." + panel_number
                turntable_object.name = turntable_object_name

                bpy.context.scene.frame_current = start
                turntable_object.rotation_euler[0] = 0
                turntable_object.rotation_euler[1] = 0
                turntable_object.rotation_euler[2] = 4.71239
                turntable_object.keyframe_insert(data_path="rotation_euler", index=-1, frame=start)

                bpy.ops.action.select_all(action='SELECT')
                bpy.ops.action.interpolation_type(type='SINE')

                # Blender 5.2: Action.fcurves 访问防护（用户要求 hasattr + 长度判断）
                _ad_tt = getattr(turntable_object, 'animation_data', None)
                _act_tt = getattr(_ad_tt, 'action', None) if _ad_tt is not None else None
                if _act_tt is None or not hasattr(_act_tt, 'fcurves'):
                    # 无 Action 或 Action 无 fcurves 属性 → 不设置 easing、直接 return 跳过
                    try: C.area.type = old_area_type
                    except Exception: pass
                    return
                _fcs_tt = getattr(_act_tt, 'fcurves', None)
                if _fcs_tt is None or len(_fcs_tt) < 3:
                    # fcurves 不足 3 条（未创建 rotation_euler.z）→ 直接 return 跳过
                    try: C.area.type = old_area_type
                    except Exception: pass
                    return
                # 安全设置 EASE_OUT（单层 try/except，替代 28 层嵌套，消除 Python nested blocks 超限）
                try:
                    _kf0 = _fcs_tt[2].keyframe_points[0]
                    if _kf0 is not None:
                        _kf0.easing = 'EASE_OUT'
                except (AttributeError, IndexError, TypeError, KeyError, ValueError):
                    pass
                bpy.context.scene.frame_current = end
                turntable_object.rotation_euler[0] = 0
                turntable_object.rotation_euler[1] = 0
                turntable_object.rotation_euler[2] =  -6.44026
                turntable_object.keyframe_insert(data_path="rotation_euler", index=-1, frame=end)

                bpy.ops.action.select_all(action='DESELECT')

            if camera_strategy == "turntable_ccw":
                bpy.ops.object.select_all(action='DESELECT')
                bpy.ops.curve.primitive_bezier_circle_add(radius=4, enter_editmode=False, align='WORLD', location=(0, 0, 0), scale=(3, 3, 3))
                turntable_object = bpy.context.selected_objects[0]
                turntable_object_name = "Turntable." + panel_number
                turntable_object.name = turntable_object_name

                bpy.context.scene.frame_current = start
                turntable_object.rotation_euler[0] = 0
                turntable_object.rotation_euler[1] = 0
                turntable_object.rotation_euler[2] = -4.71239
                turntable_object.keyframe_insert(data_path="rotation_euler", index=-1, frame=start)

                bpy.ops.action.select_all(action='SELECT')
                bpy.ops.action.interpolation_type(type='SINE')

                # Blender 5.2: Action.fcurves 访问防护（用户要求 hasattr + 长度判断）
                _ad_tt = getattr(turntable_object, 'animation_data', None)
                _act_tt = getattr(_ad_tt, 'action', None) if _ad_tt is not None else None
                if _act_tt is None or not hasattr(_act_tt, 'fcurves'):
                    # 无 Action 或 Action 无 fcurves 属性 → 不设置 easing、直接 return 跳过
                    try: C.area.type = old_area_type
                    except Exception: pass
                    return
                _fcs_tt = getattr(_act_tt, 'fcurves', None)
                if _fcs_tt is None or len(_fcs_tt) < 3:
                    # fcurves 不足 3 条（未创建 rotation_euler.z）→ 直接 return 跳过
                    try: C.area.type = old_area_type
                    except Exception: pass
                    return
                # 安全设置 EASE_OUT（单层 try/except，替代 28 层嵌套，消除 Python nested blocks 超限）
                try:
                    _kf0 = _fcs_tt[2].keyframe_points[0]
                    if _kf0 is not None:
                        _kf0.easing = 'EASE_OUT'
                except (AttributeError, IndexError, TypeError, KeyError, ValueError):
                    pass
                bpy.context.scene.frame_current = end
                turntable_object.rotation_euler[0] = 0
                turntable_object.rotation_euler[1] = 0
                turntable_object.rotation_euler[2] =  6.44026
                turntable_object.keyframe_insert(data_path="rotation_euler", index=-1, frame=end)

                bpy.ops.action.select_all(action='DESELECT')

                


        print("New Panel Auto Camera is: " + camera_strategy)
        C.area.type = old_area_type
    return {'FINISHED'}




class BR_OT_key_scale_hide(bpy.types.Operator):
    """Generate keyframes to scale the selected to 0.0001 and then appear on the current frame with a bounce curve"""
    bl_idname = "wm.spiraloid_3d_comic_key_scale_hide"
    bl_label ="关键帧缩放隐藏（key scale hide）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        C=bpy.context
        if (C):
            old_area_type = C.area.type
            C.area.type='DOPESHEET_EDITOR'
            bpy.ops.action.select_all(action='DESELECT')
            for ob in selected_objects:
                duration = 20
                visible_frame = bpy.context.scene.frame_current
                hide_frame = visible_frame - duration

                bpy.context.scene.frame_current = visible_frame
                ob.keyframe_insert(data_path="scale", index=-1, frame=visible_frame)

                bpy.context.scene.frame_current = hide_frame
                ob.scale[1] = 0.0001
                ob.scale[2] = 0.0001
                ob.scale[0] = 0.0001


                ob.keyframe_insert(data_path="scale", index=-1, frame=hide_frame)
                bpy.ops.action.interpolation_type(type='BOUNCE')
                bpy.ops.action.select_all(action='DESELECT')

        C.area.type = old_area_type


        return {'FINISHED'}

class BR_OT_key_camera_random(bpy.types.Operator):
    """Generate keyframes for camera randomly"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_random"
    bl_label ="随机构图（random）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_random")
        return {'FINISHED'}

class BR_OT_key_camera_slide_up(bpy.types.Operator):
    """Generate keyframes for camera slide up"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_slide_up"
    bl_label ="上滑（slide up）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_slide_up")
        return {'FINISHED'}

class BR_OT_key_camera_slide_down(bpy.types.Operator):
    """Generate keyframes for camera slide down"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_slide_down"
    bl_label ="下滑（slide down）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_slide_down")
        return {'FINISHED'}


class BR_OT_key_camera_pan_left(bpy.types.Operator):
    """Generate keyframes for camera slide down"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_pan_left"
    bl_label ="左平移（slide left）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_pan_left")
        return {'FINISHED'}


class BR_OT_key_camera_pan_right(bpy.types.Operator):
    """Generate keyframes for camera pan right"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_pan_right"
    bl_label ="右平移（slide right）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_pan_left")
        return {'FINISHED'}


class BR_OT_key_camera_truck_in(bpy.types.Operator):
    """Generate keyframes for camera truck in"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_truck_in"
    bl_label ="推入（truck in）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_truck_in")
        return {'FINISHED'}


class BR_OT_key_camera_truck_out(bpy.types.Operator):
    """Generate keyframes for camera truck in"""
    bl_idname = "wm.spiraloid_3d_comic_key_camera_truck_out"
    bl_label ="拉出（truck out）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "camera_truck_out")
        return {'FINISHED'}


class  BR_OT_key_world_spin_cw(bpy.types.Operator):
    """Generate keyframes for camera spinning clockwise"""
    bl_idname = "wm.spiraloid_3d_comic_key_world_spin_cw"
    bl_label ="世界顺时针旋转（spin CW）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "world_spin_cw")
        return {'FINISHED'}

class  BR_OT_key_world_spin_ccw(bpy.types.Operator):
    """Generate keyframes for camera spinning counter clockwise"""
    bl_idname = "wm.spiraloid_3d_comic_key_world_spin_ccw"
    bl_label ="世界逆时针旋转（spin CCW）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        key_camera_auto(self, context, "world_spin_ccw")
        return {'FINISHED'}





class BR_OT_panel_validate_naming(bpy.types.Operator):
    """Verify 3d panel naming is correct for export"""
    bl_idname = "view3d.spiraloid_3d_comic_panel_validate_naming"
    bl_label ="校验画格命名（Validate Panel Naming）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        validate_naming(self, context)
        return {'FINISHED'}



class BR_OT_panel_validate_naming_all(bpy.types.Operator):
    """Verify 3d panel naming is correct for export"""
    bl_idname = "view3d.spiraloid_3d_comic_panel_validate_naming_all"
    bl_label ="校验全部画格命名（Validate All Panel Naming）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        currSceneIndex = getCurrentSceneIndex()

        panels = []
        for scene in bpy.data.scenes:
            if "p." in scene.name:
                panels.append(scene.name)
        for panel in panels :
            for i in range(len(bpy.data.scenes)):
                if bpy.data.scenes[i].name == panel:
                    bpy.context.window.scene = bpy.data.scenes[i]                
                    validate_naming(self, context)

        bpy.context.window.scene = bpy.data.scenes[currSceneIndex]

        return {'FINISHED'}




class BR_OT_panel_init(bpy.types.Operator):
    """Setup scene as a 3D comic panel"""
    bl_idname = "view3d.spiraloid_3d_comic_panel_init"
    bl_label ="初始化画格（Initialize Panel）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if bpy.context.object:
            starting_mode = bpy.context.object.mode
            if "OBJECT" not in starting_mode:
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                bpy.ops.object.select_all(action='DESELECT')


        currSceneIndex = getCurrentSceneIndex()
        currScene =  bpy.data.scenes[currSceneIndex]
        currsceneName = currScene.name
        panelNumber = getCurrentPanelNumber(True)
        existing_prefix_name = "previously_existing_"
        active_camera = bpy.context.scene.camera



        current_scene_name = bpy.data.scenes[currSceneIndex].name
        stringFragments = current_scene_name.split('.')
        if len(stringFragments) >= 2:
            x_stringFragments = stringFragments[2]
            xx_stringFragments = x_stringFragments.split('h')
            current_panel_height = xx_stringFragments[1]
            xxx_stringFragments = xx_stringFragments[0].split('w')
            current_panel_width = xxx_stringFragments[1]
            panelSceneName = 'p.'+ str(panelNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)
        else:
            panelSceneName = 'p.'+ str(panelNumber) + '.w100h100'

        bpy.data.scenes[currSceneIndex].name = panelSceneName

        wip_collection_name = "Wip." + panelNumber
        export_collection_name = "Export." + panelNumber
        letters_collection_name = "Letters." + panelNumber
        backstage_collection_name = "Backstage." + panelNumber

        scene_collections = bpy.data.scenes[currSceneIndex].collection.children

        # for c in scene_collections:
        #     c.name = existing_prefix_name + c.name

        objects = bpy.context.scene.objects
        pcamera = []
        pcamera_aim = []
        if active_camera:
            for obj in objects:
                if obj.type == 'CAMERA':
                    obj.name = existing_prefix_name + "Camera"
                    pcamera.append(obj)
                if "Camera_aim." in obj.name:
                    obj.name = existing_prefix_name + "Camera_aim"
                    pcamera_aim.append(obj)


        # wip_collection = bpy.data.collections.new(wip_collection_name)
        # bpy.context.scene.collection.children.link(wip_collection)


        hasExportCollection = False
        hasLettersCollection = False
        hasBackstageCollection = False

        scene_collections = bpy.data.scenes[currSceneIndex].collection.children
        for c in scene_collections:
            collectionNameStringFragments = c.name.split('.')

            if "Export" in collectionNameStringFragments[0]:
                c.name = export_collection_name
                hasExportCollection = True
                export_collection = c

            if "Letters" in collectionNameStringFragments[0]:
                c.name = letters_collection_name
                hasLettersCollection = True
                letters_collection = c

            if "Backstage" in collectionNameStringFragments[0]:
                c.name = backstage_collection_name
                hasBackstageCollection = True
                backstage_collection = c

        # # stop to see what's going on
        # raise KeyboardInterrupt()

        try:
            active_collection = bpy.context.collection
        except:
            pass 

        if hasExportCollection:
            export_collection = bpy.data.collections.get(export_collection_name)
        else:
            export_collection =  bpy.data.collections.new(export_collection_name)
            bpy.context.scene.collection.children.link(export_collection)

        # # stop to see what's going on
        # raise KeyboardInterrupt()


        if hasLettersCollection:
            letters_collection = bpy.data.collections.get(letters_collection_name)
        else:
            letters_collection =  bpy.data.collections.new(letters_collection_name)
            bpy.context.scene.collection.children.link(letters_collection)


        if hasBackstageCollection:
            backstage_collection = bpy.data.collections.get(backstage_collection_name)
        else:
            backstage_collection =  bpy.data.collections.new(backstage_collection_name)
            bpy.context.scene.collection.children.link(backstage_collection)




        # existing_export_collection = bpy.data.collections.get(export_collection_name)
        # existing_letters_collection = bpy.data.collections.get(letters_collection_name)



        # load default scene
        load_resource(self, context, "panel_default.blend", False)



        # link imported collection to scene so it shows up in outliner
        loaded_export_collection_name =  "Export.TEMPLATE"
        loaded_export_collection = bpy.data.collections.get(loaded_export_collection_name)
        loaded_letter_collection_name =  "Letters.TEMPLATE"
        loaded_letter_collection = bpy.data.collections.get(loaded_letter_collection_name)
        loaded_backstage_collection_name =  "Backstage.TEMPLATE"
        loaded_backstage_collection = bpy.data.collections.get(loaded_backstage_collection_name)

        # # stop to see what's going on
        # raise KeyboardInterrupt()

        bpy.context.scene.collection.children.link(loaded_export_collection)
        bpy.context.scene.collection.children.link(loaded_letter_collection)
        bpy.context.scene.collection.children.link(loaded_backstage_collection)






        if active_camera:
            for obj in objects:
                if obj.type == 'CAMERA':
                    if "Camera.TEMPLATE" in obj.name:
                        camera_name = 'Camera.'+ str(panelNumber)
                        obj.name = camera_name
                        bpy.context.scene.camera = bpy.data.objects[obj.name]   
                        letters_collection = getCurrentLettersCollection()
                        obj.location[0] = active_camera.location[0]
                        obj.location[1] = active_camera.location[1]
                        obj.location[2] = active_camera.location[2]
                        if letters_collection:
                            letters_objects = letters_collection.objects
                            for letter_group in letters_objects:
                                if letter_group.type == 'EMPTY':
                                    if "Letters_" in letter_group.name:
                                        scene_camera = bpy.context.scene.objects[camera_name]
                                        bpy.ops.object.select_all(action='DESELECT')
                                        letter_group.select_set(state=True)
                                        scene_camera.select_set(state=True)
                                        bpy.context.view_layer.objects.active = scene_camera
                                        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
                        obj.data.lens = active_camera.data.lens
                        obj.data.clip_start = active_camera.data.clip_start
                        obj.data.clip_end = active_camera.data.clip_end
                        obj.data.dof.use_dof = active_camera.data.dof.use_dof
                        obj.data.sensor_fit = active_camera.data.sensor_fit
                        obj.data.show_background_images = active_camera.data.show_background_images
                        obj.data.show_safe_areas = active_camera.data.show_safe_areas
                        bpy.data.objects.remove(bpy.data.objects[active_camera.name], do_unlink=True)
                        # bpy.context.scene.camera = obj
               
                if "Camera_aim." in obj.name:
                    obj.name = 'Camera_aim.'+ str(panelNumber)

                # if pcamera_aim:
                    # obj = pcamera_aim[0]
                    # bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
        else:
            for obj in objects:
                if obj.type == 'CAMERA':
                    if "Camera.TEMPLATE" in obj.name:
                        obj.name = 'Camera.'+ str(panelNumber)
                        bpy.context.scene.camera = bpy.data.objects[obj.name]   
                if obj.type == 'EMPTY':                
                    if "Camera_aim.TEMPLATE" in obj.name:
                        obj.name = 'Camera_aim.'+ str(panelNumber)

        if letters_collection:
            letters_objects = letters_collection.objects
            template_letters_objects = loaded_letter_collection.objects
            for tobj in template_letters_objects:
                isMatchFound = False
                templateStringFragments = tobj.name.split('.TEMPLATE')
                new_letter_group_name = templateStringFragments[0] + "." + str(panelNumber) 
                for lobj in letters_objects:
                    if lobj.type == 'EMPTY':
                        if "Letters_" in lobj.name:
                            letterNameStringFragments = lobj.name.split('.')
                            if letterNameStringFragments[0] == templateStringFragments[0]:
                                isMatchFound = True
                if isMatchFound:
                    bpy.data.objects.remove(bpy.data.objects[tobj.name], do_unlink=True)
                else:
                    letters_collection.objects.link(tobj)
                    tobj.name = new_letter_group_name

            for obj in letters_objects:
                if obj.type == 'EMPTY':
                    if "Letters_" in obj.name:
                        letterPrefixStringFragments = lobj.name.split('.')
                        new_letter_group_name = letterPrefixStringFragments[0] + "." + str(panelNumber) 

                        # letters_collection.objects.link(obj)

                        if "TEMPLATE" in obj.name:
                            isMatchFound = False
                            languageStringFragments = obj.name.split('.TEMPLATE')
                            new_letter_group_name = languageStringFragments[0] + "." + str(panelNumber) 
                            for o in letters_objects:
                                if o.name == new_letter_group_name:
                                    bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
                                    isMatchFound = True
                            if not isMatchFound:
                                obj.name = new_letter_group_name

                        try:
                            loaded_letter_collection.objects.unlink(obj)
                            export_collection.objects.unlink(obj)
                        except:
                            pass

            scene_collections = bpy.data.scenes[currSceneIndex].collection.children
            for c in scene_collections:
                if c.name == loaded_letter_collection_name:                        
                    bpy.data.scenes[currSceneIndex].collection.children.unlink(c)
                if c.name == loaded_export_collection_name:                        
                    bpy.data.scenes[currSceneIndex].collection.children.unlink(c)


            coll = bpy.data.collections.get(loaded_letter_collection_name)
            if coll:
                obs = [o for o in coll.objects if o.users == 1]
                while obs:
                    bpy.data.objects.remove(obs.pop())
                bpy.data.collections.remove(coll)

            coll = bpy.data.collections.get(loaded_export_collection_name)
            if coll:
                obs = [o for o in coll.objects if o.users == 1]
                while obs:
                    bpy.data.objects.remove(obs.pop())
                bpy.data.collections.remove(coll)






        if backstage_collection:
            backstage_objects = backstage_collection.objects
            template_backstage_objects = loaded_backstage_collection.objects
            for tobj in template_backstage_objects:
                templateStringFragments = tobj.name.split('.TEMPLATE')
                new_backstage_object_name = templateStringFragments[0] + "." + str(panelNumber) 
                backstage_collection.objects.link(tobj)
                # export_collection.objects.unlink(tobj)
                tobj.name = new_backstage_object_name

            backstage_objects = backstage_collection.objects
            for obj in backstage_objects:
                if "Materials" in obj.name:
                    for i in range(len(obj.material_slots)):
                        mat = obj.material_slots[i].material
                        if ".TEMPLATE" in mat.name:
                            templateStringFragments = mat.name.split('.TEMPLATE')
                            new_backstage_material_name = templateStringFragments[0] + "." + str(panelNumber) 
                            mat.name = new_backstage_material_name
                    try:
                        export_collection.objects.unlink(obj)
                    except:
                        pass

            scene_collections = bpy.data.scenes[currSceneIndex].collection.children
            for c in scene_collections:
                if c.name == loaded_backstage_collection_name:                        
                    bpy.data.scenes[currSceneIndex].collection.children.unlink(c)
                if c.name == loaded_export_collection_name:                        
                    bpy.data.scenes[currSceneIndex].collection.children.unlink(c)


            coll = bpy.data.collections.get(loaded_backstage_collection_name)
            if coll:
                obs = [o for o in coll.objects if o.users == 1]
                while obs:
                    bpy.data.objects.remove(obs.pop())
                bpy.data.collections.remove(coll)

            coll = bpy.data.collections.get(loaded_export_collection_name)
            if coll:
                obs = [o for o in coll.objects if o.users == 1]
                while obs:
                    bpy.data.objects.remove(obs.pop())
                bpy.data.collections.remove(coll)

            _b52_set_lc_exclude(backstage_collection.name, True)


            # shuffled_letters_objects = letters_collection.objects
            # if shuffled_letters_objects:
            #     for obj in shuffled_letters_objects:
            #         if obj.type == 'EMPTY':
            #                 if "TEMPLATE" in obj.name:
            #                     languageStringFragments = obj.name.split('.TEMPLATE')
            #                     for ob in shuffled_letters_objects:
            #                         if "TEMPLATE" not in ob.name:
            #                             if languageStringFragments[0] in ob.name:
            #                                 bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
            #                                 letterGroupStringFragments = ob.name.split('.')
            #                                 ob.name = letterGroupStringFragments[0] + "." + str(panelNumber)



        # objects = bpy.context.scene.objects
        # for obj in objects:
        #     try:
        #         bpy.context.scene.collection.objects.unlink(obj)
        #     except:
        #         pass
            
        #     for c in bpy.data.collections:
        #         try:
        #             c.objects.unlink(obj)
        #         except:
        #             pass
        #     if "Letters_" not in obj.name:
        #         export_collection.objects.link(obj)
        #     else:
        #         letters_collection.objects.link(obj)
        # objects = export_collection.objects
        # pcamera = []
        # pcamera_aim = []
        # for obj in objects:
        #     if obj.type == 'CAMERA':
        #         pcamera.append(obj)
        #     if "Camera_aim." in obj.name:
        #         pcamera_aim.append(obj)


        # if pcamera:
        #     obj = pcamera[0]
        #     bpy.context.scene.camera = bpy.data.objects[obj.name]

        #     if active_camera:
        #         obj.name = 'Camera.'+ str(panelNumber)
        #         obj.location[0] = active_camera.location[0]
        #         obj.location[1] = active_camera.location[1]
        #         obj.location[2] = active_camera.location[2]
        #         bpy.data.objects.remove(bpy.data.objects[active_camera.name], do_unlink=True)

            
        #     if pcamera_aim:
        #         obj = pcamera_aim[0]
        #         obj.name = 'Camera_aim.'+ str(panelNumber)

        # letters_objects = letters_collection.objects
        # for obj in letters_objects:
        #     if "Letters_english." in obj.name:
        #         obj.name = 'Letters_english.'+ str(panelNumber)
        #     if "Letters_spanish." in obj.name:
        #         obj.name = 'Letters_spanish.'+ str(panelNumber)
        #     if "Letters_japanese." in obj.name:
        #         obj.name = 'Letters_japanese.'+ str(panelNumber)
        #     if "Letters_korean." in obj.name:
        #         obj.name = 'Letters_korean.'+ str(panelNumber)  
        #     if "Letters_german." in obj.name:
        #         obj.name = 'Letters_german.'+ str(panelNumber)  
        #     if "Letters_french." in obj.name:
        #         obj.name = 'Letters_french.'+ str(panelNumber)  
        #     if "Letters_dutch." in obj.name:
        #         obj.name = 'Letters_dutch.'+ str(panelNumber)  


        # # library = bpy.data.libraries['panel_default.blend']
        # # for usid in  library.users_id:
        # #     usid.user_clear()

        # # for library in bpy.data.libraries:
        # #     bpy.data.libraries.

        bpy.context.scene.render.resolution_x = 1024
        bpy.context.scene.render.resolution_y = 1024
        bpy.context.scene.frame_start = 1 
        bpy.context.scene.frame_end = 72
        bpy.context.scene.cursor.location[2] = 1.52


        #cleanup
        for c in scene_collections:
            if existing_prefix_name in c.name:
                bpy.data.scenes[currSceneIndex].collection.children.unlink(c)
                bpy.data.collections.remove(c)



        objects = bpy.context.scene.objects
        for obj in objects:
            if existing_prefix_name in obj.name:
                bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
        empty_trash(self, context)




        for itex in bpy.data.textures: 
            if "L_InkThickness.TEMPLATE" in itex.name:
                itexStringFragments = itex.name.split('.TEMPLATE')
                itex.name = itexStringFragments[0] + "." + str(panelNumber)
                print(itex.name)

        global material_swatch_object
        material_swatch_object = getCurrentMaterialSwatch()


        return {'FINISHED'}



# class BR_OT_panel_init(bpy.types.Operator):
#     """Setup scene as a 3D comic panel"""
#     bl_idname = "view3d.spiraloid_3d_comic_panel_init"
#     bl_label ="Initialize Panel"
#     bl_options = {'REGISTER', 'UNDO'}

#     def execute(self, context):
#         currSceneIndex = getCurrentSceneIndex()
#         currPanelIndex = getCurrentPanelNumber(False)
#         panelNumber = "%04d" % currPanelIndex
#         # sceneNumber = "%04d" % currSceneIndex
#         current_scene_name = bpy.data.scenes[currSceneIndex].name
#         old_export_collection_name = "old_export_collection"

#         stringFragments = current_scene_name.split('.')
#         x_stringFragments = stringFragments[2]
#         xx_stringFragments = x_stringFragments.split('h')
#         current_panel_height = xx_stringFragments[1]
#         xxx_stringFragments = xx_stringFragments[0].split('w')
#         current_panel_width = xxx_stringFragments[1]
#         # print (stringFragments)
#         # print (x_stringFragments)
#         # print (xx_stringFragments)
#         # print (xxx_stringFragments)


#         bpy.ops.object.select_all(action='DESELECT')
#         active_camera = bpy.context.scene.camera

#         # panels = []
#         # for scene in bpy.data.scenes:
#         #     if "p." in scene.name:
#         #         panels.append(scene.name)

#         # for panel in panels :
#         #     for i in range(len(bpy.data.scenes)):
#         #         if bpy.data.scenes[i].name == panel:
#         #             m = currSceneIndex - 1
#         #             if m > currSceneIndex:
#         #                 sceneNumber = "%04d" % m
#         #                 bpy.data.scenes[m].name = 'p.'+ str(sceneNumber)


#         currScene =  bpy.data.scenes[currSceneIndex]
#         currsceneName = currScene.name
#         # panelSceneName = 'p.'+ str(sceneNumber) + ".w100h100"
#         panelSceneName = 'p.'+ str(panelNumber) + '.w' + str(current_panel_width) + 'h' + str(current_panel_height)

#         # if panelSceneName != currsceneName:
#         bpy.data.scenes[currSceneIndex].name = panelSceneName
#         # currsceneName = currScene.name

#         # for c in bpy.data.collections:
#         #     if c.name is export_collection_name:


#         wip_collection_name = "Wip." + panelNumber
#         export_collection_name = "Export." + panelNumber
#         letters_collection_name = "Letters." + panelNumber
#         scene_collections = bpy.data.scenes[currSceneIndex].collection.children

#         for c in scene_collections:
#             if c.name == export_collection_name:
#                 c.name = old_export_collection_name
#                 self.report({'INFO'}, 'Renaming Old Export Collection!')
#                 # print ("Removing existing export collection")
#                 # bpy.data.scenes[currSceneIndex].collection.children.unlink(c)
#                 # bpy.data.collections.remove(c)
#                 # bpy.ops.outliner.orphans_purge()


#         wip_collection = bpy.data.collections.new(wip_collection_name)
#         export_collection =  bpy.data.collections.new(export_collection_name)
#         letters_collection =  bpy.data.collections.new(letters_collection_name)
#         bpy.context.scene.collection.children.link(wip_collection)
#         bpy.context.scene.collection.children.link(export_collection)
#         bpy.context.scene.collection.children.link(letters_collection)
#         # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[wip_collection_name]

#         # load selected scene
#         load_resource(self, context, "panel_default.blend", False)

#         # link imported collection to scene so it shows up in outliner
#         loaded_export_collection_name =  "Export.TEMPLATE"
#         loaded_export_collection = bpy.data.collections.get(loaded_export_collection_name)

#         loaded_letter_collection_name =  "Letters.TEMPLATE"
#         loaded_letter_collection = bpy.data.collections.get(loaded_letter_collection_name)

#         # bpy.data.scenes[currSceneIndex].collection.children.link(export_collection_name)

#         objects = bpy.context.scene.objects
#         # objects = loaded_export_collection.all_objects
#         for obj in objects:
#             # try :
#             #     # loaded_export_collection.objects.unlink(obj)
#             #     bpy.data.collections[loaded_export_collection_name].objects.unlink(obj)
#             # except:
#             #     pass
#             try:
#                 bpy.context.scene.collection.objects.unlink(obj)
#             except:
#                 pass
            
#             for c in bpy.data.collections:
#                 try:
#                     c.objects.unlink(obj)
#                 except:
#                     pass
#             if "Letters_" not in obj.name:
#                 export_collection.objects.link(obj)
#             else:
#                 letters_collection.objects.link(obj)
#             # bpy.data.collections[export_collection_name].objects.link(obj)
#         objects = export_collection.objects
#         pcamera = []
#         pcamera_aim = []
#         for obj in objects:
#             if obj.type == 'CAMERA':
#                 pcamera.append(obj)
#             if "Camera_aim." in obj.name:
#                 pcamera_aim.append(obj)


#         if pcamera:
#             obj = pcamera[0]
#             # if "Camera." in obj.name:


#             # if active_camera:
#             #     active_camera.name = 'Camera.'+ str(sceneNumber)
#             #     bpy.data.objects[obj.name]
#             #     export_collection.objects.link(active_camera)

#             #     bpy.ops.object.select_all(action='DESELECT')
#             #     bpy.data.objects['Letters_eng.'+ str(sceneNumber)].select = True
#             #     active_camera.select = True
#             #     bpy.context.view_layer.objects.active = active_camera
#             #     bpy.ops.object.parent_set(type='OBJECT', keep_transform=False)

#             #     bpy.data.objects.remove(bpy.data.objects[obj.name], do_unlink=True)
#             #     # bpy.ops.object.delete(use_global=False)
#             # else:
#             bpy.context.scene.camera = bpy.data.objects[obj.name]

#             if active_camera:
#                 obj.name = 'Camera.'+ str(panelNumber)
#                 obj.location[0] = active_camera.location[0]
#                 obj.location[1] = active_camera.location[1]
#                 obj.location[2] = active_camera.location[2]
#                 bpy.data.objects.remove(bpy.data.objects[active_camera.name], do_unlink=True)

            
#             if pcamera_aim:
#                 obj = pcamera_aim[0]
#                 obj.name = 'Camera_aim.'+ str(panelNumber)

#         letters_objects = letters_collection.objects
#         for obj in letters_objects:
#             if "Letters_english." in obj.name:
#                 obj.name = 'Letters_english.'+ str(panelNumber)
#             if "Letters_spanish." in obj.name:
#                 obj.name = 'Letters_spanish.'+ str(panelNumber)
#             if "Letters_japanese." in obj.name:
#                 obj.name = 'Letters_japanese.'+ str(panelNumber)
#             if "Letters_korean." in obj.name:
#                 obj.name = 'Letters_korean.'+ str(panelNumber)  
#             if "Letters_german." in obj.name:
#                 obj.name = 'Letters_german.'+ str(panelNumber)  
#             if "Letters_french." in obj.name:
#                 obj.name = 'Letters_french.'+ str(panelNumber)  
#             if "Letters_dutch." in obj.name:
#                 obj.name = 'Letters_dutch.'+ str(panelNumber)  


#         # library = bpy.data.libraries['panel_default.blend']
#         # for usid in  library.users_id:
#         #     usid.user_clear()

#         # for library in bpy.data.libraries:
#         #     bpy.data.libraries.

#         bpy.context.scene.render.resolution_x = 1024
#         bpy.context.scene.render.resolution_y = 1024
#         bpy.context.scene.frame_start = 1 
#         bpy.context.scene.frame_end = 72
#         bpy.context.scene.cursor.location[2] = 1.52


#         #cleanup
#         for c in scene_collections:
#             if c.name == old_export_collection_name:
#                 bpy.data.scenes[currSceneIndex].collection.children.unlink(c)
#                 bpy.data.collections.remove(c)
#                 bpy.ops.outliner.orphans_purge()


#         return {'FINISHED'}


class BR_OT_panel_init_workshop_lighting(bpy.types.Operator):
    """initialize with workshop lighting"""
    bl_idname = "view3d.spiraloid_3d_comic_init_workshop_lighting"
    bl_label ="工作室光照（Lightkit）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        currSceneIndex = getCurrentSceneIndex()
        numString = getCurrentPanelNumber(False)
        sceneNumber = "%04d" % numString

        bpy.ops.object.select_all(action='DESELECT')

        lighting_collection_name =  "Lighting." + str(sceneNumber) 
        lighting_collection = bpy.data.collections.get(lighting_collection_name)
        if lighting_collection:
            bpy.data.collections.remove(lighting_collection)
            empty_trash(self, context)

        lighting_collection = bpy.data.collections.new(lighting_collection_name)
        bpy.context.scene.collection.children.link(lighting_collection)


        active_camera = bpy.context.scene.camera
        if active_camera:
            active_camera_name = active_camera.name

        # load_resource("lighting_workshop.blend")

        # if objects is not None :
        #     bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        # letter = objects[0]
        # letter_group = getCurrentLetterGroup()


        lighting_group_name = "Lighting." + str(sceneNumber)

        keylight_name = "Key." + str(sceneNumber)
        rim_name = "Rim." + str(sceneNumber)
        back_name = "Back." + str(sceneNumber)
        fill_name = "Fill." + str(sceneNumber)
        bouncelight_name = "Bounce." + str(sceneNumber)
        sky_name = "Sky." + str(sceneNumber)


        bpy.ops.object.select_all(action='DESELECT')
        for obj in bpy.data.scenes[currSceneIndex].objects:
            if lighting_group_name in obj.name: 
                bpy.ops.object.select_all(action='DESELECT')
                obj.select = True
                for c in obj.children:
                    c.select = True
                bpy.ops.object.delete(use_global=False)
                empty_trash(self, context)
                self.report({'INFO'}, 'Deleted Previous Lighting!')

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.empty_add(type='SPHERE', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        lighting_group = bpy.context.active_object
        lighting_group.name = lighting_group_name

        lighting_group.show_in_front = True
        lighting_group.empty_display_size = 0.1

        if active_camera:
            active_camera.select_set(state=True)
            bpy.context.view_layer.objects.active = active_camera
            bpy.ops.object.parent_no_inverse_set()
        lighting_collection.objects.link(lighting_group)
        bpy.context.collection.objects.unlink(lighting_group)

        bpy.ops.object.select_all(action='DESELECT')
        lighting_group.select_set(state=True)

        for obj in bpy.data.scenes[currSceneIndex].objects:
            if "Camera_aim." in obj.name:
                lighting_group.select_set(state=True)
                bpy.context.view_layer.objects.active = lighting_group
                constraint = bpy.ops.object.constraint_add(type='COPY_LOCATION')
                bpy.context.object.constraints["Copy Location"].target = bpy.data.objects[obj.name]


        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        keylight = bpy.context.active_object
        keylight.name = keylight_name
        lighting_group.select_set(state=True)
        bpy.context.view_layer.objects.active = lighting_group
        bpy.ops.object.parent_no_inverse_set()
        keylight.rotation_euler[0] = -3.5
        keylight.rotation_euler[1] = -3.5
        keylight.rotation_euler[2] = 3.5
        keylight.data.energy = 1
        keylight.data.color = (1, 1, 1)
        _b52_set_light_use_shadow(keylight, True)
        keylight.data.shadow_buffer_bias = 0.0100001
        keylight.data.angle = 0
        keylight.data.shadow_cascade_max_distance = 10
        lighting_collection.objects.link(keylight)
        bpy.context.collection.objects.unlink(keylight) 

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        rim = bpy.context.active_object
        rim.name = rim_name
        lighting_group.select_set(state=True)
        bpy.context.view_layer.objects.active = lighting_group
        bpy.ops.object.parent_no_inverse_set()
        rim.rotation_euler[0] = -3.50811
        rim.rotation_euler[1] = -5.93412
        rim.rotation_euler[2] = 2.96706
        rim.data.energy = 5
        rim.data.specular_factor = 3
        rim.data.color = (0.132868, 0.367247, 1)
        _b52_set_light_use_shadow(rim, True)
        rim.data.shadow_buffer_bias = 0.0100001
        rim.data.angle = 0
        rim.data.shadow_cascade_max_distance = 10
        lighting_collection.objects.link(rim)
        bpy.context.collection.objects.unlink(rim) 


        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        back = bpy.context.active_object
        back.name = back_name
        lighting_group.select_set(state=True)
        bpy.context.view_layer.objects.active = lighting_group
        bpy.ops.object.parent_no_inverse_set()
        back.rotation_euler[0] = -3.49066
        back.rotation_euler[1] = -6.28319
        back.rotation_euler[2] = 5.06145
        back.data.energy = 0.6
        back.data.specular_factor = 1
        back.data.color = (0.955095, 0.669994, 0.399015)
        _b52_set_light_use_shadow(back, True)
        back.data.shadow_buffer_bias = 0.0100001
        back.data.angle = 0
        back.data.shadow_cascade_max_distance = 10
        lighting_collection.objects.link(back)
        bpy.context.collection.objects.unlink(back) 



        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        fill = bpy.context.active_object
        fill.name = fill_name
        lighting_group.select_set(state=True)
        bpy.context.view_layer.objects.active = lighting_group
        bpy.ops.object.parent_no_inverse_set()
        fill.rotation_euler[0] = -6.73697
        fill.rotation_euler[1] = -5.95157
        fill.rotation_euler[2] = 7.45256
        fill.data.energy = 0.1
        fill.data.color = (1, 1, 1)
        _b52_set_light_use_shadow(fill, True)
        fill.data.shadow_buffer_bias = 0.0100001
        fill.data.angle = 0
        fill.data.shadow_cascade_max_distance = 10
        lighting_collection.objects.link(fill)
        bpy.context.collection.objects.unlink(fill) 







        # #unparent light kit
        # bpy.ops.object.select_all(action='DESELECT')
        # lighting_group.select_set(state=True)
        # bpy.context.view_layer.objects.active = lighting_group
        # bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

        if active_camera:
            active_camera.select_set(state=True)
        else:
            lighting_group.rotation_euler[1] = 0
            lighting_group.rotation_euler[0] = 1.36136
            lighting_group.rotation_euler[2] = 0.331613

        

        # set viewport display
        for area in  bpy.context.screen.areas:  # iterate through areas in current screen
            if area.type == 'VIEW_3D':
                for space in area.spaces:  # iterate through spaces in current VIEW_3D area
                    if space.type == 'VIEW_3D':  # check if space is a 3D view
                        space.shading.type = 'MATERIAL'  # set the viewport shading to material
                        space.shading.use_scene_world = True
                        space.shading.use_scene_lights = True

                        space.overlay.show_floor = False
                        space.overlay.show_axis_x = False
                        space.overlay.show_axis_y = False
                        space.overlay.show_cursor = False
                        space.overlay.show_relationship_lines = False
                        space.overlay.show_bones = False
                        space.overlay.show_motion_paths = False
                        space.overlay.show_object_origins = False
                        space.overlay.show_annotation = False
                        space.overlay.show_text = False
                        space.overlay.show_text = False
                        space.overlay.show_outline_selected = False
                        space.overlay.show_extras = False
                        space.overlay.show_overlays = True
                        space.show_gizmo = False
                        space.overlay.wireframe_threshold = 1

        scene = bpy.data.scenes[currSceneIndex]
        if scene.world is None:
            # create a new world
            new_world = bpy.data.worlds.new(sky_name)
            scene.world = new_world
            
            new_world.use_nodes = True
            new_world.node_tree.nodes["Background"].inputs[0].default_value = (0.00393594, 0.00393594, 0.00393594, 1)

        #setup renderer.
        # Blender 5.2: eevee legacy properties removed (taa_samples, use_bloom, use_ssr, etc.)
        # try:
        #     bpy.context.scene.eevee.taa_samples = 1
        #     bpy.context.scene.eevee.use_taa_reprojection = False
        #     bpy.context.scene.eevee.use_gtao = False
        #     bpy.context.scene.eevee.use_bloom = False
        #     bpy.context.scene.eevee.use_ssr = False
        #     bpy.context.scene.eevee.use_soft_shadows = True
        #     bpy.context.scene.eevee.shadow_cube_size = '64'
        #     bpy.context.scene.eevee.shadow_cascade_size = '4096'
        #     bpy.context.scene.eevee.sss_samples = 1
        # except AttributeError:
        #     pass



        # bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
        # keylight = bpy.context.active_object
        # keylight.name = "Keylight"

        # bpy.ops.object.parent_set(type='OBJECT', keep_transform=False)



        # keylight.rotation_euler[0] = -2.00713
        # keylight.rotation_euler[1] = -2.61799
        # keylight.rotation_euler[2] = 3.66519
        # keylight.data.energy = 1
        # keylight.data.color = (1, 1, 1)

        # bpy.ops.outliner.item_activate(extend=True, deselect_all=True)




        return {'FINISHED'}







class BR_OT_panel_cycle_sky(bpy.types.Operator):
    """initialize with Ink and Shade All lighting"""
    bl_idname = "view3d.spiraloid_3d_comic_cycle_sky"
    bl_label ="循环天空球（Cycle Sky）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        backstage_collection = getCurrentBackstageCollection()
        objects = bpy.context.selected_objects
        currSceneIndex = getCurrentSceneIndex()
        currPanelIndex = getCurrentPanelNumber(True)

        scene = bpy.data.scenes[currSceneIndex]
        sky_name = "Sky." + str(currPanelIndex)

        if objects is not None :
            for obj in objects:
                starting_mode = bpy.context.object.mode
                if "OBJECT" not in starting_mode:
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  


        if not backstage_collection:
            self.report({'INFO'}, 'No Backstage Collection found, initializng as 3D Comic Panel!')
            BR_OT_panel_init.execute(self, context)
            backstage_collection = getCurrentBackstageCollection()

        scene = bpy.data.scenes[currSceneIndex]
        if scene.world is not None:
            current_world = scene.world
            bpy.data.worlds.remove(current_world, do_unlink=True)
            empty_trash(self, context)

        # if backstage_collection:
        #     backstage_objects = backstage_collection.objects
        #     for mobj in backstage_objects:
        #         if "Materials." in mobj.name:
        #             sky_color = mobj["Sky"]
        #             print(":::::::::::::::" + str(sky_color[0]) + ":::::::::::::::::::")
        #             if sky_color:
        #                 # col = [(1 - sky_color[i]) for i in range(4)]
        #                 # mobj["Sky"] = col
        #                 mobj["Sky"] = sky_color

                    # bpy.context.scene.frame_set(bpy.context.scene.frame_current)
                    # bpy.context.view_layer.update()
                    # context = bpy.context
                    # scene = context.scene
                    # frame_current = scene.frame_current

                    # scene.frame_set(frame_current)
                    # context.view_layer.update()

                    # for area in bpy.context.screen.areas:
                    #     if area.type == 'VIEW_3D':
                    #         area.tag_redraw()
                    # bpy.context.view_layer.update()
                    # bpy.context.scene.update()


        # if scene.world is not None:
        #     if scene.world.name != sky_name:


        
        colorSwatch = [(1.0,1.0,1.0,1.0), (0.0,0.0,0.0,1.0), (0.05,0.08,0.11,1.0) ]
        # # 13, 21, 29
        # global previous_sky_color_index
        # if (previous_sky_color_index != 1):
        #     nextColorIndex = previous_sky_color_index + 1
        # else:
        #     nextColorIndex = 0
        # previous_sky_color_index = nextColorIndex 
        # sky_color = colorSwatch[nextColorIndex]
        # if backstage_collection:
        #     backstage_objects = backstage_collection.objects
        #     for mobj in backstage_objects:
        #         if "Materials." in mobj.name:
        #             mobj["Sky"] = sky_color

        bpy.ops.object.select_all(action='DESELECT')
        # set viewport display
        for area in  bpy.context.screen.areas:  # iterate through areas in current screen
            if area.type == 'VIEW_3D':
                for space in area.spaces:  # iterate through spaces in current VIEW_3D area
                    if space.type == 'VIEW_3D':  # check if space is a 3D view
                        space.shading.type = 'MATERIAL'  # set the viewport shading to material
                        space.shading.use_scene_world = True
                        space.shading.use_scene_lights = True

                        space.overlay.show_floor = False
                        space.overlay.show_axis_x = False
                        space.overlay.show_axis_y = False
                        space.overlay.show_cursor = False
                        space.overlay.show_relationship_lines = False
                        space.overlay.show_bones = False
                        space.overlay.show_motion_paths = False
                        space.overlay.show_object_origins = False
                        space.overlay.show_annotation = False
                        space.overlay.show_text = False
                        space.overlay.show_text = False
                        space.overlay.show_outline_selected = False
                        space.overlay.show_extras = False
                        space.overlay.show_overlays = True
                        space.show_gizmo = False
                        space.overlay.wireframe_threshold = 1
                        # if space.local_view is not None:
                        #     bpy.ops.view3d.localview()


        # create a new world
        mat_world = bpy.data.worlds.new(sky_name)
        scene.world = mat_world
        
        mat_world.use_nodes = True
        bg_node = mat_world.node_tree.nodes.get("Background")
        if bg_node is not None:
            bg_node.inputs[0].default_value = (0.00393594, 0.00393594, 0.00393594, 1)
        world_output = mat_world.node_tree.nodes.get('World Output')
        if world_output is None:
            world_output = mat_world.node_tree.nodes.new(type='ShaderNodeOutputWorld')
        background_shader = _b52_safe_world_background_shader(mat_world)
        if background_shader is None:
            background_shader = mat_world.node_tree.nodes.new(type='ShaderNodeBackground')
            if world_output.inputs and len(world_output.inputs) > 0:
                mat_world.node_tree.links.new(background_shader.outputs[0], world_output.inputs[0])
        background_color = mat_world.node_tree.nodes.new(type='ShaderNodeRGB')
        light_path = mat_world.node_tree.nodes.new(type='ShaderNodeLightPath')
        mix_shader = mat_world.node_tree.nodes.new(type='ShaderNodeMixShader')

        mat_world.node_tree.links.new(background_color.outputs[0], background_shader.inputs[0])
        mat_world.node_tree.links.new(background_shader.outputs[0], mix_shader.inputs[2])
        mat_world.node_tree.links.new(light_path.outputs[0], mix_shader.inputs[0])
        mat_world.node_tree.links.new(mix_shader.outputs[0], world_output.inputs[0])

        # background_color.outputs[0].default_value = sky_color

        if backstage_collection:
            _b52_set_lc_exclude(backstage_collection.name, False)
            backstage_objects = backstage_collection.objects
            for mobj in backstage_objects:
                if "Materials." in mobj.name:
                    sky_color = mobj["Sky"]
                    if sky_color:
                        if sky_color == colorSwatch[0]:
                            mobj["Sky"] = colorSwatch[1]

                        if sky_color == colorSwatch[1]:
                            mobj["Sky"] = colorSwatch[0]                     

                        colorDriverRed = background_color.outputs[0].driver_add("default_value")[0] 
                        colorDriverGreen = background_color.outputs[0].driver_add("default_value")[1] 
                        colorDriverBlue = background_color.outputs[0].driver_add("default_value")[2] 

                        colorDriverRed.driver.type = 'SUM'
                        newVar = colorDriverRed.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = mobj
                        newVar.targets[0].data_path = '["Sky"][0]' 

                        colorDriverGreen.driver.type = 'SUM'
                        newVar = colorDriverGreen.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = mobj
                        newVar.targets[0].data_path = '["Sky"][1]' 

                        colorDriverBlue.driver.type = 'SUM'
                        newVar = colorDriverBlue.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = mobj
                        newVar.targets[0].data_path = '["Sky"][2]' 

        # shader_to_rgb_A = mat_world.node_tree.nodes.new(type='ShaderNodeShaderToRGB')
        # shader_to_rgb_B = mat_world.node_tree.nodes.new(type='ShaderNodeShaderToRGB')
        # ramp_A = mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
        # ramp_B = mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
        # ramp_A.color_ramp.elements[0].position = 0.00
        # ramp_A.color_ramp.elements[1].position = 0.2
        # ramp_A.color_ramp.interpolation = 'CONSTANT'
        # ramp_B.color_ramp.elements[0].position = 0.00
        # ramp_B.color_ramp.elements[1].position = 0.2
        # ramp_B.color_ramp.interpolation = 'CONSTANT'

        # bpy.context.scene.cycles.max_bounces = 0
        # bpy.context.scene.cycles.preview_start_resolution = 1024

        # bpy.context.scene.eevee.use_gtao = False
        # bpy.context.scene.eevee.use_bloom = False
        # bpy.context.scene.eevee.use_ssr = False
        # bpy.context.scene.eevee.use_taa_reprojection = False
        # bpy.context.scene.eevee.taa_samples = 8
        # bpy.context.scene.eevee.shadow_cube_size = '512'
        # bpy.context.scene.eevee.shadow_cascade_size = '64'
        # bpy.context.scene.eevee.use_soft_shadows = False



        _b52_set_lc_exclude(backstage_collection.name, True)
        return {'FINISHED'}






class BR_OT_panel_clear_ink_lighting(bpy.types.Operator):
    """Clear all Ink and Toonshading"""
    bl_idname = "wm.spiraloid_3d_comic_clear_all_ink_lighting"
    bl_label ="清除墨线·卡通光照（Clear Ink Toonshade All）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        panel_settings = bpy.context.scene.panel_settings
        toonfill_mode = panel_settings.s3dc_toonfill_mode
        toonfill_type = panel_settings.s3dc_toonfill_type
        selected_objects = bpy.context.selected_objects
        currSceneIndex = getCurrentSceneIndex()
        sceneNumber = getCurrentPanelNumber(True)
        lighting_group = ""
        export_collection = getCurrentExportCollection(self, context)
        export_objects = export_collection.all_objects
        lighting_collection = getCurrentLightingCollection(self, context)
        backstage_collection = getCurrentBackstageCollection()
        panel_material_swatch = getMaterialSwatch(False)
        material_swatch_object = getCurrentMaterialSwatch()

        if selected_objects:
            starting_mode = bpy.context.object.mode
            if "OBJECT" not in starting_mode:
                if "POSE" in starting_mode:
                    selected_bones = bpy.context.selected_pose_bones
                if "EDIT" in starting_mode:
                    selected_elementes = bpy.context.selected
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)   

        if "Visible" in toonfill_mode or "Lighting" in toonfill_mode:
            if lighting_collection:
                obs = [o for o in lighting_collection.objects]
                while obs:
                    bpy.data.objects.remove(obs.pop())
                bpy.data.collections.remove(lighting_collection)
                empty_trash(self, context)


        # backstage_collection = getCurrentBackstageCollection()

        if "Visible" in toonfill_mode:
            for obj in export_objects:
                if obj is not None:
                    if bpy.context.object:
                        starting_mode = bpy.context.object.mode
                        if "OBJECT" not in starting_mode:
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                            bpy.ops.object.select_all(action='DESELECT')
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(state=True)
                bpy.context.view_layer.objects.active = obj

                is_insensitive = False
                if obj.type == 'MESH' or obj.type == 'CURVE' :
                    try:
                        del obj["is_toon_shaded"]
                    except:
                        pass 

                    if obj.hide_select:
                        obj.hide_select = False
                        is_insensitive = True

                    try:
                        drivers_data = obj.animation_data.drivers
                        for dr in drivers_data:  
                            obj.driver_remove(dr.data_path, -1) # need to add only relevant drivers test.
                    except:
                        pass

                    for mod in obj.modifiers:
                        # print("-----------------------------")
                        mod_name = mod.name
                        if "InkThickness" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        if "WhiteOutline" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        if "BlackOutline" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)


                    for vgroup in obj.vertex_groups:
                        vgroup_name = vgroup.name
                        if 'Ink_Thickness' in vgroup_name:
                            obj.vertex_groups.remove(vgroup)

                    if obj.active_material:
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 obj 全部材质槽
                        obj.data.materials.clear()


                if is_insensitive:
                    obj.hide_select = True


        if "Selected" in toonfill_mode:
            for obj in selected_objects:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(state=True)
                bpy.context.view_layer.objects.active = obj

                is_insensitive = False
                obj_type = obj.type
                if obj_type == 'MESH' or obj_type == 'CURVE' :
                    try:
                        del obj["is_toon_shaded"]
                    except:
                        pass 

                    if obj.hide_select:
                        obj.hide_select = False
                        is_insensitive = True

                    try:
                        drivers_data = obj.animation_data.drivers
                        for dr in drivers_data:  
                            obj.driver_remove(dr.data_path, -1) # need to add only relevant drivers test.
                    except:
                        pass

                    for mod in obj.modifiers:
                        # print("-----------------------------")
                        mod_name = mod.name
                        if "InkThickness" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        if "WhiteOutline" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        if "BlackOutline" in mod_name:
                            bpy.ops.object.modifier_remove(modifier=mod.name)


                    for vgroup in obj.vertex_groups:
                        vgroup_name = vgroup.name
                        if 'Ink_Thickness' in vgroup_name:
                            obj.vertex_groups.remove(vgroup)

                    if obj.active_material:
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 obj 全部材质槽
                        obj.data.materials.clear()


                if is_insensitive:
                    obj.hide_select = True


        return {'FINISHED'}


class BR_OT_panel_init_ink_lighting(bpy.types.Operator):
    """initialize with Ink and Shade All lighting"""
    bl_idname = "view3d.spiraloid_3d_comic_init_ink_lighting"
    bl_label ="墨线卡通光照（Ink Toonshade Visible）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global material_swatch_object
        currSceneIndex = getCurrentSceneIndex()
        sceneNumber = getCurrentPanelNumber(True)
        lighting_group = ""
        export_collection = getCurrentExportCollection(self, context)
        lighting_collection = getCurrentLightingCollection(self, context)
        backstage_collection = getCurrentBackstageCollection()
        panel_material_swatch = getMaterialSwatch(False)
        global_material_swatch = getMaterialSwatch(True)

        if bpy.context.object:
            starting_mode = bpy.context.object.mode
            if "OBJECT" not in starting_mode:
                if "POSE" in starting_mode:
                    selected_bones = bpy.context.selected_pose_bones
                if "EDIT" in starting_mode:
                    selected_elementes = bpy.context.selected
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)                

        if not backstage_collection:
            self.report({'INFO'}, 'No Backstage Collection found, initializng as 3D Comic Panel!')
            BR_OT_panel_init.execute(self, context)
            backstage_collection = getCurrentBackstageCollection()

        # if backstage_collection:
        #     backstage_objects = backstage_collection.objects
        #     for obj in backstage_objects:
        #         if "Materials" in obj.name:
        #             material_swatch_object = obj
        
        toonfill_use_global = bpy.context.scene.panel_settings.s3dc_toonfill_use_global
        if toonfill_use_global:
            material_swatch_object = global_material_swatch
        else:
            material_swatch_object = panel_material_swatch


        if material_swatch_object:

            # sky_color = (1, 1, 1, 1)
            sky_color = (0, 0, 0, 1)

            # lighting_collection = bpy.data.collections.get(lighting_collection_name)
            # if lighting_collection:
            #     bpy.data.collections.remove(lighting_collection)
            #     empty_trash(self, context)


            # existing_lighting_collection = lighting_collection
            # if existing_lighting_collection:
            #     obs = [o for o in existing_lighting_collection.objects if o.users == 1]
            #     while obs:
            #         bpy.data.objects.remove(obs.pop())
            #     bpy.data.collections.remove(existing_lighting_collection)
            #     empty_trash(self, context)
            #     self.report({'INFO'}, 'Deleted Previous Lighting!')
            # lighting_collection = getCurrentLightingCollection(self, context)

            bpy.ops.object.select_all(action='DESELECT')


            visible_objects = []
            for obj in bpy.context.view_layer.objects:
                if obj.visible_get: 
                    if obj.type == 'MESH' or obj.type == 'CURVE' :
                        material_swatch_object_name = material_swatch_object.name
                        if not "ground" in obj.name and not material_swatch_object_name in obj.name: 
                            visible_objects.append(obj)
                        else:
                            tmp_array = [obj]
                            # outline(self,context,tmp_array, "toon")
            outline(self, context, visible_objects)

            active_camera = bpy.context.scene.camera
            if active_camera:
                active_camera_name = active_camera.name


            lighting_collection_name =  "Lighting." + str(sceneNumber) 
            lighting_group_name = lighting_collection_name
            keylight_name = "Key." + str(sceneNumber)
            sky_name = "Sky." + str(sceneNumber)

            # if (currSceneIndex > 0):
            #     lighting_collection_name =  "Lighting." + str(sceneNumber) 
            #     lighting_group_name = lighting_collection_name
            #     keylight_name = "Key." + str(sceneNumber)
            #     sky_name = "Sky." + str(sceneNumber)
            # else:
            #     lighting_group_name = "Lighting"
            #     lighting_collection_name =  lighting_group_name
            #     keylight_name = "Key"
            #     sky_name = "Sky"

            scene = bpy.data.scenes[currSceneIndex]
            scene_objects = scene.objects
            for obj in scene_objects:
                if lighting_collection_name in obj.name:
                    lighting_group = obj
                if keylight_name in obj.name:
                    keylight = obj

            # else:

            if not lighting_collection:
                lighting_collection = bpy.data.collections.new(lighting_collection_name)
                bpy.ops.object.select_all(action='DESELECT')
                bpy.ops.object.empty_add(type='SPHERE', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
                lighting_group = bpy.context.active_object
                lighting_group.name = lighting_group_name
                lighting_group.show_in_front = True
                lighting_group.empty_display_size = 0.1
                lighting_collection.objects.link(lighting_group)
                try:
                    export_collection.objects.unlink(lighting_group)
                except:
                    pass

                if export_collection:
                    export_collection.children.link(lighting_collection)
                    bpy.context.scene.collection.children.link(lighting_collection)

                    



            # rim_name = "Rim." + str(sceneNumber)
            # back_name = "Back." + str(sceneNumber)
            # fill_name = "Fill." + str(sceneNumber)
            # bouncelight_name = "Bounce." + str(sceneNumber)


            # bpy.ops.object.select_all(action='DESELECT')
            # for obj in bpy.data.scenes[currSceneIndex].objects:
            #     if lighting_group_name in obj.name: 
            #         existing_lighting_group_name = obj.name
            #         bpy.ops.object.select_all(action='DESELECT')
            #         obj.select = True
            #         for c in obj.children:
            #             c.select = True
            #         bpy.ops.object.delete(use_global=False)
            #         empty_trash(self, context)
            #         self.report({'INFO'}, 'Deleted Previous Lighting!')








            # if currSceneIndex != 0:
            #     lighting_group = bpy.context.active_object
            #     lighting_group.name = lighting_group_name
            # else:
            #     lighting_collection_name =  "Lighting.Main" 
            #     lighting_collection = bpy.data.collections.get(lighting_collection_name)
            #     if lighting_collection:
            #         bpy.data.collections.remove(lighting_collection)
            #         empty_trash(self, context)

            #     lighting_collection = bpy.data.collections.new(lighting_collection_name)
            #     bpy.context.scene.collection.children.link(lighting_collection)


            #     bpy.ops.object.select_all(action='DESELECT')
            #     bpy.ops.object.empty_add(type='SPHERE', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
            #     lighting_group = bpy.context.active_object
            #     lighting_group.name = "Lighting_group"
            #     lighting_group.show_in_front = True
            #     lighting_group.empty_display_size = 0.1

            #     if active_camera:
            #         active_camera.select_set(state=True)
            #         bpy.context.view_layer.objects.active = active_camera
            #         bpy.ops.object.parent_no_inverse_set()


            # lighting_group.show_in_front = True
            # lighting_group.empty_display_size = 0.1

            # if active_camera:
            #     active_camera.select_set(state=True)
            #     bpy.context.view_layer.objects.active = active_camera
            #     bpy.ops.object.parent_no_inverse_set()
            # lighting_collection.objects.link(lighting_group)
            # bpy.context.collection.objects.unlink(lighting_group)

                bpy.ops.object.select_all(action='DESELECT')
                lighting_group.select_set(state=True)

                for obj in bpy.data.scenes[currSceneIndex].objects:
                    if "Camera_aim." in obj.name:
                        if active_camera:
                            active_camera.select_set(state=True)
                            bpy.context.view_layer.objects.active = active_camera
                            bpy.ops.object.parent_no_inverse_set()

                        # lighting_group.select_set(state=True)
                        # bpy.context.view_layer.objects.active = lighting_group
                        # constraint = bpy.ops.object.constraint_add(type='COPY_LOCATION')
                        # bpy.context.object.constraints["Copy Location"].target = bpy.data.objects[obj.name]


                bpy.ops.object.select_all(action='DESELECT')
                bpy.ops.object.light_add(type='SPOT', align='WORLD', location=(5, -5, 10), scale=(1, 1, 1))
                keylight = bpy.context.active_object
                keylight.name = keylight_name
                lighting_group.select_set(state=True)
                bpy.context.view_layer.objects.active = lighting_group
                # bpy.ops.object.parent_no_inverse_set()
                # bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)

                keylight.location[0] = 2.5
                keylight.location[1] = -2.5
                keylight.location[2] = 5
                keylight.rotation_euler[0] = -2.61799
                keylight.rotation_euler[1] = -2.61799
                keylight.rotation_euler[2] = -1.5708
                keylight.data.energy = 10000
                keylight.data.color = (1, 1, 1)
                _b52_set_light_use_shadow(keylight, False)
                keylight.data.shadow_buffer_clip_start = .1
                keylight.data.spot_size =  2.26893
                keylight.data.shadow_soft_size = 0
                # keylight.data.shadow_buffer_bias = 0.001  # 5.2 FIX: 属性已移除
                keylight.data.use_custom_distance = True
                keylight.data.cutoff_distance = 100


                bpy.context.collection.objects.unlink(keylight) 
                lighting_collection.objects.link(keylight)

                # keylight.rotation_euler[0] = -3.5
                # keylight.rotation_euler[1] = -3.5
                # keylight.rotation_euler[2] = 3.5



                # Sun settings
                # keylight.rotation_euler[0] = -3.31613
                # keylight.rotation_euler[1] = -3.83972
                # keylight.rotation_euler[2] = 4.18879
                # keylight.data.energy = 1
                # keylight.data.color = (1, 1, 1)
                # legacy shadow toggle kept behind compatibility wrapper
                # keylight.data.contact_shadow_distance = 10
                # keylight.data.shadow_buffer_bias = 0.001
                # keylight.data.contact_shadow_bias = 0.001
                # keylight.data.angle = 0



                # bpy.context.collection.objects.unlink(lighting_group) 
                # lighting_collection.objects.link(lighting_group)

                # lighting_collection.objects.link(lighting_group)
                # bpy.context.collection.objects.unlink(lighting_group) 

                # bpy.ops.object.select_all(action='DESELECT')
                # bpy.ops.object.light_add(type='SUN', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
                # rim = bpy.context.active_object
                # rim.name = rim_name
                # lighting_group.select_set(state=True)
                # bpy.context.view_layer.objects.active = lighting_group
                # bpy.ops.object.parent_no_inverse_set()
                # rim.rotation_euler[0] = -3.50811
                # rim.rotation_euler[1] = -5.93412
                # rim.rotation_euler[2] = 2.96706
                # rim.data.energy = 5
                # rim.data.specular_factor = 3
                # rim.data.color = (0.132868, 0.367247, 1)
                # export_collection.objects.link(rim)
                # bpy.context.collection.objects.unlink(rim) 




                # #unparent light kit
                # bpy.ops.object.select_all(action='DESELECT')
                # lighting_group.select_set(state=True)
                # bpy.context.view_layer.objects.active = lighting_group
                # bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

                # if active_camera:
                #     active_camera.select_set(state=True)
                # else:
                #     lighting_group.rotation_euler[1] = 0
                #     lighting_group.rotation_euler[0] = 1.36136
                #     lighting_group.rotation_euler[2] = 0.331613
            
            try:
                bpy.context.scene.collection.children.unlink(lighting_collection)
            except:
                pass

            # set viewport display
            for area in  bpy.context.screen.areas:  # iterate through areas in current screen
                if area.type == 'VIEW_3D':
                    for space in area.spaces:  # iterate through spaces in current VIEW_3D area
                        if space.type == 'VIEW_3D':  # check if space is a 3D view
                            space.shading.type = 'MATERIAL'  # set the viewport shading to material
                            space.shading.use_scene_world = True
                            space.shading.use_scene_lights = True

                            space.overlay.show_floor = False
                            space.overlay.show_axis_x = False
                            space.overlay.show_axis_y = False
                            space.overlay.show_cursor = False
                            space.overlay.show_relationship_lines = False
                            space.overlay.show_bones = False
                            space.overlay.show_motion_paths = False
                            space.overlay.show_object_origins = False
                            space.overlay.show_annotation = False
                            space.overlay.show_text = False
                            space.overlay.show_text = False
                            space.overlay.show_outline_selected = False
                            space.overlay.show_extras = False
                            space.overlay.show_overlays = True
                            space.show_gizmo = False
                            space.overlay.wireframe_threshold = 1
                            # if space.local_view is not None:
                            #     bpy.ops.view3d.localview()

            scene = bpy.data.scenes[currSceneIndex]
            if scene.world is not None:
                scene.world.node_tree.nodes.clear
                empty_trash(self, context)


            # create a new world
            mat_world = bpy.data.worlds.new(sky_name)
            scene.world = mat_world
            
            mat_world.use_nodes = True
            _bg_node = mat_world.node_tree.nodes.get("Background")
            if _bg_node is not None:
                _bg_node.inputs[0].default_value = (0.00393594, 0.00393594, 0.00393594, 1)
            world_output = mat_world.node_tree.nodes.get('World Output')
            if world_output is None:
                world_output = mat_world.node_tree.nodes.new(type='ShaderNodeOutputWorld')
            background_shader = _b52_safe_world_background_shader(mat_world)
            if background_shader is None:
                background_shader = mat_world.node_tree.nodes.new(type='ShaderNodeBackground')
                if world_output.inputs and len(world_output.inputs) > 0:
                    mat_world.node_tree.links.new(background_shader.outputs[0], world_output.inputs[0])
            background_color = mat_world.node_tree.nodes.new(type='ShaderNodeRGB')
            light_path = mat_world.node_tree.nodes.new(type='ShaderNodeLightPath')
            mix_shader = mat_world.node_tree.nodes.new(type='ShaderNodeMixShader')

            mat_world.node_tree.links.new(background_color.outputs[0], background_shader.inputs[0])
            mat_world.node_tree.links.new(background_shader.outputs[0], mix_shader.inputs[2])
            mat_world.node_tree.links.new(light_path.outputs[0], mix_shader.inputs[0])
            mat_world.node_tree.links.new(mix_shader.outputs[0], world_output.inputs[0])

            background_color.outputs[0].default_value = sky_color


            # shader_to_rgb_A = mat_world.node_tree.nodes.new(type='ShaderNodeShaderToRGB')
            # shader_to_rgb_B = mat_world.node_tree.nodes.new(type='ShaderNodeShaderToRGB')
            # ramp_A = mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
            # ramp_B = mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
            # ramp_A.color_ramp.elements[0].position = 0.00
            # ramp_A.color_ramp.elements[1].position = 0.2
            # ramp_A.color_ramp.interpolation = 'CONSTANT'
            # ramp_B.color_ramp.elements[0].position = 0.00
            # ramp_B.color_ramp.elements[1].position = 0.2
            # ramp_B.color_ramp.interpolation = 'CONSTANT'

            # bpy.context.scene.cycles.max_bounces = 0
            # bpy.context.scene.cycles.preview_start_resolution = 1024

            # Blender 5.2: eevee legacy properties removed, wrapped in try/except
            try:
                bpy.context.scene.eevee.use_gtao = False
                bpy.context.scene.eevee.use_bloom = False
                bpy.context.scene.eevee.use_ssr = False
                bpy.context.scene.eevee.use_taa_reprojection = False
                bpy.context.scene.eevee.taa_samples = 8
                # bpy.context.scene.eevee.shadow_cube_size = '512'
                bpy.context.scene.eevee.shadow_cube_size = '4096'
                bpy.context.scene.eevee.shadow_cascade_size = '64'
                bpy.context.scene.eevee.use_soft_shadows = False
            except AttributeError:
                pass


            bpy.ops.object.select_all(action='DESELECT')
            keylight.select_set(state=True)
            bpy.context.view_layer.objects.active = keylight

            # [P0-A] Data API instead of bpy.ops.view3d.snap_cursor_to_center():
            # the operator needs a VIEW_3D context and fails when run from a
            # menu/script.  Resetting the cursor is all that was intended.
            context.scene.cursor.location = (0.0, 0.0, 0.0)
            context.scene.cursor.rotation_euler = (0.0, 0.0, 0.0)
            context.scene.tool_settings.transform_pivot_point = 'CURSOR'


        return {'FINISHED'}


# class BR_OT_add_ground(bpy.types.Operator):
#     """Add a new ground disc with falloff"""
#     bl_idname = "view3d.spiraloid_3d_comic_add_ground"
#     bl_label ="Add Ground Disc"
#     bl_options = {'REGISTER', 'UNDO'}

#     def execute(self, context):
#         # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
#         bpy.ops.object.select_all(action='DESELECT')
#         load_resource("ground_disc.blend")
#         selected_objects = bpy.context.selected_objects
#         for ob in selected_objects:
#             ob.hide_select = True

#         return {'FINISHED'}

class BR_OT_add_outline( bpy.types.Operator):
    """create a polygon outline for selected objects."""
    bl_idname = "view3d.spiraloid_3d_comic_ink"
    bl_label = "墨线处理选中物体（Ink Selected）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        selected_objects = bpy.context.selected_objects
        for ob in selected_objects:
            try:
                del ob["is_toon_shaded"]
            except:
                pass 
        outline(self,context,selected_objects)
        return {'FINISHED'}


class BR_OT_add_toonshade(bpy.types.Operator):
    """create a polygon outline for selected objects."""
    bl_idname = "view3d.spiraloid_3d_comic_toonshade"
    bl_label = "卡通材质选中物体（Toonshade Selected）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        selected_objects = bpy.context.selected_objects
        for ob in selected_objects:
            try:
                del ob["is_toon_shaded"]
            except:
                pass 
        outline(self,context,selected_objects )
        return {'FINISHED'}


class BR_OT_add_blackout(bpy.types.Operator):
    """make object material white for selected objects."""
    bl_idname = "view3d.spiraloid_3d_comic_blackout"
    bl_label = "选中物体变黑（Blackout Selected）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        material_swatch_object = getCurrentMaterialSwatch()
        selected_objects = bpy.context.selected_objects
        if bpy.context.mode == 'OBJECT':
        # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
            for mesh_object in selected_objects:
                if mesh_object.type == 'MESH' or mesh_object.type == 'CURVE' :
                    try:
                        del mesh_object["is_toon_shaded"]
                    except:
                        pass 

                    is_insensitive = False
                    if mesh_object.hide_select:
                        mesh_object.hide_select = False
                        is_insensitive = True

                        for mod in mesh_object.modifiers:
                            mod_name = mod.name
                            if 'InkThickness' in mod_name:
                                bpy.ops.object.modifier_remove(modifier=mod.name)
                            if 'WhiteOutline' in mod_name:
                                bpy.ops.object.modifier_remove(modifier=mod.name)
                            if 'BlackOutline' in mod_name:
                                bpy.ops.object.modifier_remove(modifier=mod.name)

                        for vgroup in mesh_object.vertex_groups:
                            if 'Ink_Thickness' in vgroup.name:
                                mesh_object.vertex_groups.remove(vgroup)

                        try:
                            drivers_data = mesh_object.animation_data.drivers
                            for dr in drivers_data:  
                                mesh_object.driver_remove(dr.data_path, -1)
                        except:
                            pass

                    if mesh_object.active_material:
                        mesh_object.active_material.node_tree.nodes.clear()
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                        mesh_object.data.materials.clear()

                    if mesh_object.active_material is None:
                        assetName = mesh_object.name
                        matName = (assetName + "Mat")
                        mat = bpy.data.materials.new(name=matName)
                        mat.use_nodes = True
                        mat_output = mat.node_tree.nodes.get('Material Output')
                        shader = mat_output.inputs[0].links[0].from_node
                        nodes = mat.node_tree.nodes
                        for node in nodes:
                            if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                                nodes.remove(node) 

                        shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                        shader.name = "Background"
                        shader.label = "Background"
                        shader.inputs[0].default_value = (0, 0, 0, 1)
                        mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])
                        mat.use_backface_culling = True
                        mat.shadow_method = 'NONE'

                        # Assign it to object
                        if mesh_object.data.materials:
                            mesh_object.data.materials[0] = mat
                        else:
                            mesh_object.data.materials.append(mat)
                        mesh_object["is_toon_shaded"] = 1


                    if is_insensitive:
                        mesh_object.hide_select = True

        if bpy.context.mode == 'EDIT_MESH':
            for mesh_object in selected_objects:
                if mesh_object.type == 'MESH':
                    try:
                        del mesh_object["is_toon_shaded"]
                    except:
                        pass 

                    if material_swatch_object:
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            material_swatch_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = material_swatch_object
                            bpy.ops.object.material_slot_copy()
                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = mesh_object
                            for i, mat in reversed(list(enumerate(mesh_object.data.materials))):
                                if "L_BlackShadow." not in mat.name:
                                    # letter.data.materials.pop(index=i)
                                    mesh_object.active_material_index = i
                                    bpy.ops.object.material_slot_remove()
                            mesh_object.active_material_index =  len(mesh_object.data.materials) - 1
                            mesh_object.select_set(state=True)
                            bpy.context.view_layer.objects.active = mesh_object
                            bpy.ops.object.mode_set(mode='EDIT_MESH', toggle=False)  
                            bpy.ops.object.material_slot_assign()


        return {'FINISHED'}


class BR_OT_add_whiteout(bpy.types.Operator):
    """make object material white for selected objects."""
    bl_idname = "view3d.spiraloid_3d_comic_whiteout"
    bl_label = "选中物体变白（Whiteout Selected）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        selected_objects = bpy.context.selected_objects
        for mesh_object in selected_objects:
            if mesh_object.type == 'MESH' or mesh_object.type == 'CURVE' :
                hasVertexColor = False

                try:
                    del mesh_object["is_toon_shaded"]
                except:
                    pass 

                is_insensitive = False
                if mesh_object.hide_select:
                    mesh_object.hide_select = False
                    is_insensitive = True

                for mod in mesh_object.modifiers:
                    mod_name = mod.name
                    if 'InkThickness' in mod_name:
                        bpy.ops.object.modifier_remove(modifier=mod.name)
                    if 'WhiteOutline' in mod_name:
                        bpy.ops.object.modifier_remove(modifier=mod.name)
                    if 'BlackOutline' in mod_name:
                        bpy.ops.object.modifier_remove(modifier=mod.name)

                for vgroup in mesh_object.vertex_groups:
                    if 'Ink_Thickness' in vgroup.name:
                        mesh_object.vertex_groups.remove(vgroup)

                try:
                    drivers_data = mesh_object.animation_data.drivers
                    for dr in drivers_data:  
                        mesh_object.driver_remove(dr.data_path, -1)
                except:
                    pass

                if mesh_object.active_material:
                    mesh_object.active_material.node_tree.nodes.clear()
                    # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 mesh_object 全部材质槽
                    mesh_object.data.materials.clear()

                if mesh_object.active_material is None:
                    if mesh_object.type == 'MESH':
                        if mesh_object.data.vertex_colors:
                            hasVertexColor = True
                    assetName = mesh_object.name
                    matName = (assetName + "Mat")
                    mat = bpy.data.materials.new(name=matName)
                    mat.use_nodes = True
                    mat_output = mat.node_tree.nodes.get('Material Output')
                    shader = mat_output.inputs[0].links[0].from_node
                    nodes = mat.node_tree.nodes
                    for node in nodes:
                        if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                            nodes.remove(node) 

                    shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                    shader.name = "Background"
                    shader.label = "Background"
                    shader.inputs[0].default_value = (1, 1, 1, 1)
                    mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])
                    mat.use_backface_culling = True
                    mat.shadow_method = 'NONE'

                    # Assign it to object
                    if mesh_object.data.materials:
                        mesh_object.data.materials[0] = mat
                    else:
                        mesh_object.data.materials.append(mat)

                    mesh_object["is_toon_shaded"] = 1

                    if (hasVertexColor):
                        vertexColorName = mesh_object.data.vertex_colors[0].name
                        colorNode = mat.node_tree.nodes.new('ShaderNodeAttribute')
                        colorNode.attribute_name = vertexColorName
                        mat.node_tree.links.new(shader.inputs[0], colorNode.outputs[0])


                if is_insensitive:
                    mesh_object.hide_select = True




        return {'FINISHED'}



class BR_OT_add_toon_outline(bpy.types.Operator):
    """create a polygon outline for selected objects."""
    bl_idname = "view3d.spiraloid_3d_comic_ink_toonshade"
    bl_label = "墨线+卡通选中物体（Ink and Toonshade Selected）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        selected_objects = bpy.context.selected_objects
        for ob in selected_objects:
            try:
                del ob["is_toon_shaded"]
            except:
                pass 
        outline(self,context,selected_objects )
        return {'FINISHED'}

class BR_OT_toonfill(bpy.types.Operator):
    """Toonfill obects in scene."""
    bl_idname = "wm.spiraloid_3d_comic_toonfill"
    bl_label = "卡通上色填充（Toonfill）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        panel_settings = bpy.context.scene.panel_settings
        toonfill_mode = panel_settings.s3dc_toonfill_mode
        toonfill_type = panel_settings.s3dc_toonfill_type
        selected_objects = bpy.context.selected_objects
        currSceneIndex = getCurrentSceneIndex()
        scene = bpy.data.scenes[currSceneIndex]
        sceneNumber = getCurrentPanelNumber(True)
        lighting_group = ""
        export_collection = getCurrentExportCollection(self, context)
        lighting_collection = getCurrentLightingCollection(self, context)
        backstage_collection = getCurrentBackstageCollection()
        panel_material_swatch = getMaterialSwatch(False)
        panel_material_swatch_name = panel_material_swatch.name
        global_material_swatch = getMaterialSwatch(True)
        global_material_swatch_name = global_material_swatch.name
        material_swatch_object = getCurrentMaterialSwatch()

        if backstage_collection:
            _b52_set_lc_exclude(backstage_collection.name, False)

        if bpy.context.mode != 'EDIT_MESH':
            if "Visible" == toonfill_mode:
                if "clear" == toonfill_type:
                    BR_OT_panel_clear_ink_lighting.execute(self, context)
                else:
                    if bpy.context.object:
                        starting_mode = bpy.context.object.mode
                        if "OBJECT" not in starting_mode:
                            if "POSE" in starting_mode:
                                selected_bones = bpy.context.selected_pose_bones
                            if "EDIT" in starting_mode:
                                selected_elementes = bpy.context.selected
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)                


                    if not backstage_collection:
                        self.report({'INFO'}, 'No Backstage Collection found, initializng as 3D Comic Panel!')
                        BR_OT_panel_init.execute(self, context)
                        backstage_collection = getCurrentBackstageCollection()

                    # if backstage_collection:
                    #     backstage_objects = backstage_collection.objects
                    #     for obj in backstage_objects:
                    #         if "Materials" in obj.name:
                    #             material_swatch_object = obj
            

                    if material_swatch_object:
                        bpy.ops.object.select_all(action='DESELECT')
                        visible_objects = []
                        for obj in bpy.context.view_layer.objects:
                            if obj.visible_get: 
                                obj_type = obj.type
                                if obj_type == 'MESH' or obj_type == 'CURVE' :
                                    obj_name = obj.name
                                    if obj_name != panel_material_swatch_name and  obj_name != global_material_swatch_name:
                                        visible_objects.append(obj)
                                    else:
                                        tmp_array = [obj]
                                        # outline(self,context,tmp_array, "toon")
                        outline(self, context, visible_objects )

            if "Lighting" == toonfill_mode or "toon" in toonfill_type:
                active_camera = bpy.context.scene.camera
                if active_camera:
                    active_camera_name = active_camera.name

                keylight_name = "Key." + str(sceneNumber)

                if lighting_collection:
                    lighting_collection_name =  lighting_collection.name
                    obs = [o for o in lighting_collection.objects]
                    while obs:
                        bpy.data.objects.remove(obs.pop())
                    bpy.data.collections.remove(lighting_collection)
                    empty_trash(self, context)
                else:
                    lighting_collection_name =  "Lighting." + str(sceneNumber) 

                if "clear" != toonfill_type:
                    scene_objects = scene.objects
                    for obj in scene_objects:
                        obj_name = obj.name
                        if lighting_collection_name in obj_name:
                            lighting_group = obj
                        if keylight_name in obj_name:
                            keylight = obj

                    if not lighting_collection:
                        lighting_collection = bpy.data.collections.new(lighting_collection_name)
                        
                        bpy.ops.object.select_all(action='DESELECT')
                        bpy.ops.object.empty_add(type='SPHERE', align='WORLD', location=(0, 0, 1.52), scale=(1, 1, 1))
                        lighting_group = bpy.context.active_object
                        lighting_group.name = lighting_collection_name
                        lighting_group.show_in_front = True
                        lighting_group.empty_display_size = 0.1
                        lighting_collection.objects.link(lighting_group)
                        try:
                            export_collection.objects.unlink(lighting_group)
                        except:
                            pass

                        if export_collection:
                            export_collection.children.link(lighting_collection)
                            bpy.context.scene.collection.children.link(lighting_collection)

                        bpy.ops.object.select_all(action='DESELECT')
                        lighting_group.select_set(state=True)

                        for obj in bpy.data.scenes[currSceneIndex].objects:
                            obj_name = obj.name
                            if "Camera_aim." in obj_name:
                                if active_camera:
                                    active_camera.select_set(state=True)
                                    bpy.context.view_layer.objects.active = active_camera
                                    bpy.ops.object.parent_no_inverse_set()

                        bpy.ops.object.select_all(action='DESELECT')
                        bpy.ops.object.light_add(type='SPOT', align='WORLD', location=(5, -5, 10), scale=(1, 1, 1))
                        keylight = bpy.context.active_object
                        keylight.name = keylight_name
                        lighting_group.select_set(state=True)
                        bpy.context.view_layer.objects.active = lighting_group
                        keylight.location[0] = 2.5
                        keylight.location[1] = -2.5
                        keylight.location[2] = 5
                        keylight.rotation_euler[0] = -2.61799
                        keylight.rotation_euler[1] = -2.61799
                        keylight.rotation_euler[2] = -1.5708
                        keylight.data.energy = 10000
                        keylight.data.color = (1, 1, 1)
                        _b52_set_light_use_shadow(keylight, False)
                        keylight.data.shadow_buffer_clip_start = .1
                        keylight.data.spot_size =  2.26893
                        keylight.data.shadow_soft_size = 0
                        # keylight.data.shadow_buffer_bias = 0.001  # 5.2 FIX: 属性已移除
                        keylight.data.use_custom_distance = True
                        keylight.data.cutoff_distance = 100
                        bpy.context.collection.objects.unlink(keylight) 
                        lighting_collection.objects.link(keylight)
                    try:
                        bpy.context.scene.collection.children.unlink(lighting_collection)
                    except:
                        pass

                bpy.ops.object.select_all(action='DESELECT')
                keylight.select_set(state=True)
                bpy.context.view_layer.objects.active = keylight

            if "World" == toonfill_mode or "Lighting" == toonfill_mode or "toon" in toonfill_type:
                sky_name = "Sky." + str(sceneNumber)

                # create a new world
                if scene.world is not None:
                    current_world = scene.world
                    bpy.data.worlds.remove(current_world, do_unlink=True)
                    empty_trash(self, context)
                colorSwatch = [(1.0,1.0,1.0,1.0), (0.0,0.0,0.0,1.0), (0.05,0.08,0.11,1.0) ]
                mat_world = bpy.data.worlds.new(sky_name)
                scene.world = mat_world

                mat_world.use_nodes = True
                bg_node = mat_world.node_tree.nodes.get("Background")
                if bg_node is not None:
                    bg_node.inputs[0].default_value = (0.00393594, 0.00393594, 0.00393594, 1)
                world_output = mat_world.node_tree.nodes.get('World Output')
                if world_output is None:
                    world_output = mat_world.node_tree.nodes.new(type='ShaderNodeOutputWorld')
                background_shader = _b52_safe_world_background_shader(mat_world)
                if background_shader is None:
                    background_shader = mat_world.node_tree.nodes.new(type='ShaderNodeBackground')
                    if world_output.inputs and len(world_output.inputs) > 0:
                        mat_world.node_tree.links.new(background_shader.outputs[0], world_output.inputs[0])
                background_color = mat_world.node_tree.nodes.new(type='ShaderNodeRGB')
                light_path = mat_world.node_tree.nodes.new(type='ShaderNodeLightPath')
                mix_shader = mat_world.node_tree.nodes.new(type='ShaderNodeMixShader')
                mat_world.node_tree.links.new(background_color.outputs[0], background_shader.inputs[0])
                mat_world.node_tree.links.new(background_shader.outputs[0], mix_shader.inputs[2])
                mat_world.node_tree.links.new(light_path.outputs[0], mix_shader.inputs[0])
                mat_world.node_tree.links.new(mix_shader.outputs[0], world_output.inputs[0])

                if backstage_collection:
                    _b52_set_lc_exclude(backstage_collection.name, False)
                    sky_color = material_swatch_object["Sky"]
                    if sky_color:
                        if sky_color == colorSwatch[0]:
                            material_swatch_object["Sky"] = colorSwatch[1]

                        if sky_color == colorSwatch[1]:
                            material_swatch_object["Sky"] = colorSwatch[0]                     

                        colorDriverRed = background_color.outputs[0].driver_add("default_value")[0] 
                        colorDriverGreen = background_color.outputs[0].driver_add("default_value")[1] 
                        colorDriverBlue = background_color.outputs[0].driver_add("default_value")[2] 

                        colorDriverRed.driver.type = 'SUM'
                        newVar = colorDriverRed.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = material_swatch_object
                        newVar.targets[0].data_path = '["Sky"][0]' 

                        colorDriverGreen.driver.type = 'SUM'
                        newVar = colorDriverGreen.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = material_swatch_object
                        newVar.targets[0].data_path = '["Sky"][1]' 

                        colorDriverBlue.driver.type = 'SUM'
                        newVar = colorDriverBlue.driver.variables.new()
                        newVar.name = "Sky"
                        newVar.type = 'SINGLE_PROP'
                        newVar.targets[0].id = material_swatch_object
                        newVar.targets[0].data_path = '["Sky"][2]' 

                # Blender 5.2: eevee legacy properties removed, wrapped in try/except
                try:
                    bpy.context.scene.eevee.use_gtao = False
                    bpy.context.scene.eevee.use_bloom = False
                    bpy.context.scene.eevee.use_ssr = False
                    bpy.context.scene.eevee.use_taa_reprojection = False
                    bpy.context.scene.eevee.taa_samples = 8
                    bpy.context.scene.eevee.shadow_cube_size = '4096'
                    bpy.context.scene.eevee.shadow_cascade_size = '64'
                    bpy.context.scene.eevee.use_soft_shadows = False
                except AttributeError:
                    pass


                # [P0-A] Data API instead of bpy.ops.view3d.snap_cursor_to_center()
                context.scene.cursor.location = (0.0, 0.0, 0.0)
                context.scene.cursor.rotation_euler = (0.0, 0.0, 0.0)
                context.scene.tool_settings.transform_pivot_point = 'CURSOR'

            if "Selected" == toonfill_mode:
                if "clear" == toonfill_type:
                    BR_OT_panel_clear_ink_lighting.execute(self, context)
                else:
                    if bpy.context.object:
                        starting_mode = bpy.context.object.mode
                        if "OBJECT" not in starting_mode:
                            if "POSE" in starting_mode:
                                selected_bones = bpy.context.selected_pose_bones
                            if "EDIT" in starting_mode:
                                selected_elementes = bpy.context.selected
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)                
                        selected_objects = bpy.context.selected_objects


                    if not backstage_collection:
                        self.report({'INFO'}, 'No Backstage Collection found, initializng as 3D Comic Panel!')
                        BR_OT_panel_init.execute(self, context)
                        backstage_collection = getCurrentBackstageCollection()


                    if material_swatch_object:
                        sky_color = (0, 0, 0, 1)
                        bpy.ops.object.select_all(action='DESELECT')
                        visible_objects = []
                        for obj in selected_objects:
                            if obj.visible_get: 
                                obj_type = obj.type
                                if obj_type == 'MESH' or obj_type == 'CURVE' :
                                    obj_name = obj.name
                                    if obj_name != panel_material_swatch_name and  obj_name != global_material_swatch_name:
                                        visible_objects.append(obj)
                                    else:
                                        tmp_array = [obj]
                                        # outline(self,context,tmp_array, "toon")

                        outline(self, context, visible_objects )

        else:
            if material_swatch_object:
                for mesh_object in selected_objects:
                    if mesh_object.type == 'MESH':
                        #if in edge select mode
                        if tuple(bpy.context.scene.tool_settings.mesh_select_mode) == (False, True, False):
                            current_parent = bpy.context.selected_objects[0].parent
                            bpy.ops.mesh.duplicate_move(MESH_OT_duplicate={"mode":1})
                            bpy.ops.mesh.separate(type='SELECTED')
                            bpy.ops.object.editmode_toggle()
                            stroke_mesh = bpy.context.selected_objects[1]
                            bpy.ops.object.select_all(action='DESELECT')
                            stroke_mesh.select_set(state=True)
                            bpy.context.view_layer.objects.active = stroke_mesh
                            stroke_mesh.modifiers.clear()
                            startFrame = bpy.context.scene.frame_start
                            bpy.context.scene.frame_set(startFrame)
                            bpy.ops.object.convert(target='GPENCIL')
                            stroke_mesh = bpy.context.selected_objects[0]
                            if current_parent:
                                current_parent.select_set(state=True)
                                bpy.context.view_layer.objects.active = current_parent
                                bpy.ops.object.parent_set()
                                bpy.context.view_layer.objects.active = stroke_mesh




                        #if in face select mode
                        if tuple(bpy.context.scene.tool_settings.mesh_select_mode) == (False, False, True):
                            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            for i, mat in reversed(list(enumerate(material_swatch_object.data.materials))):
                                if "blackout" in toonfill_type:
                                    if "L_BlackShadow." in mat.name:
                                        fill_mat = mat
                                if "whiteout" in toonfill_type:
                                    if "L_WhiteShadow." in mat.name:
                                        fill_mat = mat
                            
                            
                            bpy.ops.object.material_slot_add()
                            new_material_slot_index =  len(mesh_object.data.materials) -1
                            if fill_mat:
                                mesh_object.data.materials[new_material_slot_index] = fill_mat

                            bpy.ops.object.select_all(action='DESELECT')
                            mesh_object.select_set(state=True)
                            mesh_object.active_material_index =  len(mesh_object.data.materials) - 1
                            bpy.context.view_layer.objects.active = mesh_object
                            bpy.ops.object.mode_set(mode='EDIT', toggle=False)  
                            bpy.ops.object.material_slot_assign()


        # set viewport display
        for area in  bpy.context.screen.areas:  # iterate through areas in current screen
            if area.type == 'VIEW_3D':
                for space in area.spaces:  # iterate through spaces in current VIEW_3D area
                    if space.type == 'VIEW_3D':  # check if space is a 3D view
                        space.shading.type = 'MATERIAL'  # set the viewport shading to material
                        space.shading.use_scene_world = True
                        space.shading.use_scene_lights = True

                        space.overlay.show_floor = False
                        space.overlay.show_axis_x = False
                        space.overlay.show_axis_y = False
                        space.overlay.show_cursor = False
                        space.overlay.show_relationship_lines = False
                        space.overlay.show_bones = False
                        space.overlay.show_motion_paths = False
                        space.overlay.show_object_origins = False
                        space.overlay.show_annotation = False
                        space.overlay.show_text = False
                        space.overlay.show_text = False
                        space.overlay.show_outline_selected = False
                        space.overlay.show_extras = False
                        space.overlay.show_overlays = True
                        space.show_gizmo = False
                        space.overlay.wireframe_threshold = 1
                        # if space.local_view is not None:
                        #     bpy.ops.view3d.localview()


        if backstage_collection:
            _b52_set_lc_exclude(backstage_collection.name, True)
        toggle_workmode(self, context, True)

        return {'FINISHED'}



class BR_OT_regenerate_3d_comic_preview(bpy.types.Operator):
    """remake video sequencer scene strip from all scenes"""
    bl_idname = "view3d.spiraloid_3d_comic_preview"
    bl_label = "生成漫画视频预览（Generate Comic Video）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        main_scene = bpy.context.scene
        count = 0
        original_type = bpy.context.area.type

        for a in bpy.context.screen.areas:
            if a.type == 'SEQUENCE_EDITOR':
                if a.spaces[0].view_type == 'SEQUENCER':  
                    bpy.context.area.type ="SEQUENCE_EDITOR"
                    for scene in bpy.data.scenes :
                        if scene is not main_scene :
                            bpy.ops.sequencer.scene_strip_add(frame_start=count, channel=1, scene=bpy.data.scenes[count].name)
                            activeStrip = bpy.context.scene.sequence_editor.active_strip            
                            bpy.context.scene.sequence_editor.sequences_all[activeStrip.name].frame_final_duration = 1
                        count = count + 1
                    bpy.context.area.type = original_type
        return {'FINISHED'}

class BR_OT_spiraloid_3d_comic_workshop(bpy.types.Operator):
    """Visit the spiraloid workshop for updates and goodies!"""
    bl_idname = "view3d.spiraloid_3d_comic_workshop"
    bl_label = "访问工坊 / 获取更多…（Visit Workshop / Get More）"
    def execute(self, context):                
        subprocess.Popen('start '+ 'http://www.spiraloid.net')
        return {'FINISHED'}

#------------------------------------------------------

class BuildComicSettings(bpy.types.PropertyGroup):
    comic_name : bpy.props.StringProperty(name="Comic Name", description="Name of 3D Comic Site", default=True)
    panel_bake_all : bpy.props.BoolProperty(name="Panel Bake All", description="Bake each scene into an Export Collection, with every mesh lightmapped w unlit shader", default=True)

    # bake_distance : bpy.props.FloatProperty(name="Bake Distance Scale",  description="raycast is largest dimension * this value ", min=0, max=3, default=0.02 )
    # bakeSize : bpy.props.EnumProperty(
    #     name="Size", 
    #     description="Width in pixels for baked texture size", 
    #     items={
    #         ("size_128", "128","128 pixels", 1),
    #         ("size_512", "512","512 pixels", 2),
    #         ("size_1024","1024", "1024 pixels", 3)
    #         },
    #     default="size_1024"
    # )
    # bakeTargetObject : bpy.props.PointerProperty(
    #     type=bpy.types.Object,
    #     poll=scene_mychosenobject_poll,
    #     name="Target Mesh",         
    #     description="If no target mesh specified, a new automesh will be created from all meshes in collection"
    # )

class BR_MT_export_3d_comic_all(bpy.types.Operator):
    """Print to Audience.  Export all 3D Comic panels and start a local server.  Existing panels will be overwritten"""
    bl_idname = "view3d.spiraloid_export_3d_comic_all"
    bl_label ="构建漫画（Build 3D Comic）"
    bl_options = {'REGISTER', 'UNDO'}
    # config: bpy.props.PointerProperty(type=BuildComicSettings)

    # def draw(self, context):
        # bpy.types.Scene.bake_panel_settings = bpy.props.CollectionProperty(type=BakePanelSettings)
        # scene = bpy.data.scene[0]
        # layout = self.layout
        # scene = context.scene
        # build_panel_settings = scene.build_panel_settings

    # def execute(self, context):
    #     if bpy.data.is_dirty:
    #         # self.report({'WARNING'}, "You must save your file first!")
    #         # bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
    #         self.report({'WARNING'}, "You must save your file first!")
    #     else:
    #         export_panel(self, context,False, True)
    #         # export_letters(self, context,False)



    def execute(self, context):
        file_path = bpy.data.filepath

        if bpy.data.is_dirty:
            self.report({'WARNING'}, "You must save your file first!")
            return {'CANCELLED'}

        if not file_path:
            self.report({'ERROR'}, "Please save your .blend file first!")
            return {'CANCELLED'}

        # ============================================================
        # Modern Pipeline - 唯一的网页导出后端
        # ============================================================
        try:
            export_to_modern_web = _load_modern_pipeline()

            print("[3DComicToolkit] Using Modern Export Pipeline")
            result = export_to_modern_web(context, export_only_current=False)

            self.report({'INFO'}, f"Export completed: {result['pages_count']} pages")

            # 打开浏览器预览（如果不是后台模式）
            if not bpy.app.background:
                try:
                    from . import preview_server
                    from .core.utils import _get_publish_root
                    # 强制结束现有端口占用并重启，确保 Root 指向项目目录
                    preview_server.stop_server()
                    preview_server.preview_comic(directory=_get_publish_root(), port=8000, auto_start=True)
                except Exception:
                    pass

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            print(f"[3DComicToolkit] Export error: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

# class BR_MT_export_3d_comic_letters_all(bpy.types.Operator):
#     """Export all 3D Comic letters and start a local server.  Existing panels will be overwritten"""
#     bl_idname = "view3d.spiraloid_export_3d_comic_letters_all"
#     bl_label ="Export All Letters"
#     bl_options = {'REGISTER', 'UNDO'}
#     # config: bpy.props.PointerProperty(type=BuildComicSettings)

#     def execute(self, context):
#         if bpy.data.is_dirty:
#             # self.report({'WARNING'}, "You must save your file first!")
#             bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
#         else:
#             export_letters(self, context, False)
#         return {'FINISHED'}



# class BR_MT_export_3d_comic_letters_current(bpy.types.Operator):
#     """Export current scedne 3D Comic letters and start a local server.  Existing letters will be overwritten"""
#     bl_idname = "view3d.spiraloid_export_3d_comic_letters_current"
#     bl_label ="Export Current Letters"
#     bl_options = {'REGISTER', 'UNDO'}
#     # config: bpy.props.PointerProperty(type=BuildComicSettings)

#     def execute(self, context):
#         if bpy.data.is_dirty:
#             # self.report({'WARNING'}, "You must save your file first!")
#             bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
#         else:
#             export_letters(self, context,True)
#         return {'FINISHED'}

 
import bpy
from .core.utils import _get_publish_root
from .exporter import modern_pipeline

class BR_MT_quick_save_export_3d_comic_current(bpy.types.Operator):
    """快速导出当前画格 (Modern Pipeline 内置版)"""
    bl_idname = "wm.spiraloid_quicks_save_export_3d_comic_current"
    bl_label = "快速导出当前画格"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        print("\n[Operator] --- 触发快速导出当前画格 (Modern Pipeline) ---")
        
        if bpy.data.is_dirty:
            self.report({'WARNING'}, "You must save your file first!")
            return {'CANCELLED'}

        if not bpy.data.filepath:
            self.report({'ERROR'}, "Please save your .blend file first!")
            return {'CANCELLED'}

        try:
            # 1. 加载 Modern Pipeline 入口函数
            export_to_modern_web = _load_modern_pipeline()
            
            # 2. 调用 Modern Pipeline (仅导出当前画格)
            print("[3DComicToolkit] Using Modern Export Pipeline (Quick Export)")
            result = export_to_modern_web(context, export_only_current=True)
            
            if result.get("status") == "ERROR":
                self.report({'ERROR'}, f"导出失败: {result.get('message')}")
                return {'CANCELLED'}
            
            self.report({'INFO'}, "快速导出完成")

            # 3. 自动开启播放窗
            if not bpy.app.background:
                from . import preview_server
                # 使用 _get_publish_root() 获取项目隔离目录
                preview_server.preview_comic(directory=_get_publish_root(), port=8000, auto_start=True)
            
            return {"FINISHED"}

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"快速导出异常: {str(e)}")
            return {"CANCELLED"}



class BR_MT_explore_3d_comic(bpy.types.Operator):
    """Open 3D Comic Folder"""
    bl_idname = "view3d.spiraloid_explore_3d_comic"
    bl_label ="打开漫画文件夹（Open 3D Comic Folder）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .core.utils import _get_publish_root
        publish_root = _get_publish_root()
        if os.path.exists(publish_root):
            os.startfile(publish_root)
        else:
            self.report({'ERROR'}, f"导出目录未找到: {publish_root}")
        return {'FINISHED'}


class BR_MT_read_3d_comic(bpy.types.Operator):
    """Build and export 3D Comic"""
    bl_idname = "view3d.spiraloid_read_3d_comic"
    bl_label ="浏览器预览漫画（Read 3D Comic）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            from . import preview_server
            from .core.utils import _get_publish_root
            publish_root = _get_publish_root()
        except ImportError as e:
            self.report({'ERROR'}, f'Import error: {e}')
            return {'CANCELLED'}

        index_path = os.path.join(publish_root, "index.html")
        if not os.path.isfile(index_path):
            self.report({'ERROR'}, f'No index.html in {publish_root}. Run Build 3D Comic first.')
            return {'CANCELLED'}

        try:
            from . import preview_server
            # 强制结束现有端口占用并重启，确保 Root 指向项目隔离目录
            preview_server.stop_server()
            # 注意：_start_http_server 现在自带了 kill PID 逻辑
            success = preview_server.preview_comic(directory=publish_root, port=8000, auto_start=True)
            if success:
                self.report({'INFO'}, 'Modern Viewer opened: http://localhost:8000/')
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, 'Failed to open Modern Viewer')
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class BR_OT_spiraloid_3d_comic_workshop(bpy.types.Operator):
    """Visit the spiraloid workshop for updates and goodies!"""
    bl_idname = "view3d.spiraloid_3d_comic_workshop"
    bl_label = "访问工坊 / 获取更多…（Visit Workshop / Get More）"
    def execute(self, context):                
        subprocess.Popen('start '+ 'http://www.spiraloid.net')
        return {'FINISHED'}

#------------------------------------------------------


# class ComicSettings(bpy.types.PropertyGroup):
#     language : bpy.props.EnumProperty(
#         name="Language", 
#         description="The currently active language", 
#         items={
#             ("english", "english", "english", 0),
#             ("spanish", "spanish", "spanish", 1),
#             ("japanese", "japanese", "japanese", 2),
#             ("korean", "korean", "korean", 3),
#             ("german", "german", "german", 4),
#             ("french", "french", "french", 5),
#             ("dutch", "dutch", "dutch", 5)
#             },
#         default=0,
#         update = set_active_language,
#     )





def bake_collection_composite():
    if bake_ao_applied and bake_ao and bake_albedo:
        if os.path.exists(file_dir):
            materials_dir = file_dir+"\\Materials\\"
            if os.path.exists(materials_dir):
                assetName = target_object.name
                texName_albedo = (assetName + "_albedo")
                outBakeFileName = (texName_albedo + "_w_ao")
                outRenderFileNamePadded = materials_dir+outBakeFileName+"0001.png"
                outRenderFileName = materials_dir+outBakeFileName+".png"

                if os.path.exists(outRenderFileName):
                    os.remove(outRenderFileName)
                os.rename(outRenderFileNamePadded, outRenderFileName)

                self.report({'INFO'},"Composited texture saved to: " + outRenderFileName )

                texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                try:
                    img = bpy.data.images.load(outRenderFileName)
                    texture.image = img
                    mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])
                except:
                    raise NameError("Cannot load image %s" % path)




class BakePanelSettings(bpy.types.PropertyGroup):
    target_automesh : bpy.props.BoolProperty(name="Automesh", description="Generate a new mesh to recieve textures", default=True)
    target_existing : bpy.props.BoolProperty(name="Existing", description="Use an existing UV mapped mesh to recieve textures", default=True)
    target_duplicate : bpy.props.BoolProperty(name="Duplicate", description="Duplicate objects in collection to recieve textures", default=True)

    bakeSourceCollection : bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Source",         
        description="The collection to bake"
    )


    bakeTargetObject : bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=scene_mychosenobject_poll,
        name="Target Mesh",         
        description="If no target mesh specified, a new automesh will be created from all meshes in collection"
    )
    
    target_strategy : bpy.props.EnumProperty(
        name="Target", 
        description="Type of object to recieve baked textures", 
        items={
            ("target_automesh", "Combined Mesh","Automesh", 0),
            ("target_duplicate","Duplicate Meshes", "Duplicate", 1),
            ("target_existing", "Existing Mesh","Existing", 2),
            },
        default="target_automesh"
    )

    bakeSize : bpy.props.EnumProperty(
        name="Size", 
        description="Width in pixels for baked texture size", 
        items={
            ("size_128", "128","128 pixels", 0),
            ("size_128", "256","256 pixels", 1),
            ("size_512", "512","512 pixels", 2),
            ("size_1024","1024", "1024 pixels", 3),
            ("size_2048", "2048","2048 pixels", 4),
            ("size_4096", "4096","4096 pixels", 5),
            ("size_8192", "8192","8192 pixels", 6),
            },
        default="size_1024"
    )

    bake_distance : bpy.props.FloatProperty(name="Bake Distance Scale",  description="raycast is largest dimension * this value ", min=0, max=3, default=0.02 )
    bake_to_unlit : bpy.props.BoolProperty(name="Bake Lighting", description="Bake Collection to new mesh with lightmap texture and unlit shader", default=True)
    bake_to_pbr : bpy.props.BoolProperty(name="Bake Texture Maps", description="Bake Collection to new mesh with a Principled BSDF shader", default=False)
    bake_albedo : bpy.props.BoolProperty(name="Bake Albedo", description="Bake Collection to mesh with Albedo Texture", default=True)
    bake_normal : bpy.props.BoolProperty(name="Bake Normal", description="Bake Collection to mesh with Normal Texture", default=True)
    bake_metallic : bpy.props.BoolProperty(name="Bake Metallic", description="Bake Collection to mesh with Metallic Texture", default=True)
    bake_roughness : bpy.props.BoolProperty(name="Bake Roughness", description="Bake Collection to mesh with Roughness Texture", default=True)
    bake_emission : bpy.props.BoolProperty(name="Bake Emission", description="Bake Collection to mesh with Emission Texture", default=True)
    bake_opacity : bpy.props.BoolProperty(name="Bake Transparency", description="Bake Collection to mesh with Opacity Texture", default=True)
    bake_ao : bpy.props.BoolProperty(name="Bake AO", description="Bake Collection to mesh with Ambient Occlusion Texture", default=False)
    bake_ao_LoFi : bpy.props.BoolProperty(name="Lowpoly", description="Use target for Ambient Occlusion, otherwise use source meshes (slower).", default=True)
    bake_ao_applied : bpy.props.BoolProperty(name="Apply", description="Composite Ambient Occlusion into Albedo Texture", default=False)
    bake_curvature : bpy.props.BoolProperty(name="Curvature", description="Bake Collection to mesh with Curvature Texture", default=False)
    bake_curvature_applied : bpy.props.BoolProperty(name="Apply", description="Bake Curvature into Albedo Texture", default=False)
    bake_cavity : bpy.props.BoolProperty(name="Cavity*", description="Bake Collection to mesh with Cavity Texture", default=False)
    bake_cavity_applied : bpy.props.BoolProperty(name="Apply", description="Bake Cavity into Albedo Texture", default=False)
    bake_w_decimate : bpy.props.BoolProperty(name="Decimate", description="Bake and Emission Textures", default=True)
    bake_w_decimate_ratio : bpy.props.FloatProperty(name="Decimate Ratio",  description="Amount to decimate target mesh", min=0, max=1, default=0.5 )
    bake_outline : bpy.props.BoolProperty(name="Outline", description="Add ink outline to bake mesh", default=False)
    bake_background : bpy.props.BoolProperty(name="Background", description="Bake all but collection to skyball", default=False)

class BR_OT_save_check(bpy.types.Operator):
    """Merge all meshes in active collection, unwrap and toggle_workmodeing and textures into a new "Export" collection"""
    bl_idname = "wm.spiraloid_save_check_bake_panel"
    bl_label = "保存检查·烘焙集合…（Bake Collection）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Blender 5.2 fix: add missing return statement
        if bpy.data.is_dirty:
            bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
        else:
            BR_OT_bake_collection.execute(self, context)
        return {'FINISHED'}

    def invoke(self, context, event):
        # Blender 5.2 fix: invoke bake collection dialog directly instead of undefined dialog_operator
        if bpy.data.is_dirty:
            bpy.context.window_manager.popup_menu(warn_not_saved, title="Warning", icon='ERROR')
            return {'CANCELLED'}
        return bpy.ops.wm.spiraloid_bake_collection('INVOKE_DEFAULT')




class BR_OT_bake_collection(bpy.types.Operator):
    """Merge all meshes in active collection, unwrap and toggle_workmodeing and textures into a new "Export" collection"""
    bl_idname = "wm.spiraloid_bake_collection"
    bl_label = "烘焙集合…（Bake Collection）"
    bl_options = {'REGISTER', 'UNDO'}
    # config: bpy.props.PointerProperty(type=BakePanelSettings)


    def draw(self, context):
        global developer_mode
        # bpy.types.Scene.bake_panel_settings = bpy.props.CollectionProperty(type=BakePanelSettings)
        # scene = bpy.data.scene[0]

        # if bpy.data.is_dirty:
        #     bpy.types.Operator.report({'WARNING'}, "Unsaved changes, save?")

        layout = self.layout
        scene = context.scene
        bake_panel_settings = scene.bake_panel_settings

        strategy_row = layout.row(align=True)

        layout.prop(bake_panel_settings, "bakeSourceCollection" )

        layout.prop(bake_panel_settings, "target_strategy")

        row = layout.row(align=True)
        row.prop(bake_panel_settings, "bakeTargetObject" )


        if bake_panel_settings.target_strategy == "target_existing":
            row.enabled = True
        else :
            row.enabled = False


        layout.prop(bake_panel_settings, "bakeSize")
        layout.prop(bake_panel_settings, "bake_distance")

        layout.separator()
        layout.prop(bake_panel_settings, "bake_to_unlit")
        layout.prop(bake_panel_settings, "bake_to_pbr")
        pbr_row = layout.row(align=True)
        if bake_panel_settings.bake_to_pbr:
            pbr_row.enabled = True
            pbr_split = layout.split(factor=0.5)
            col_1 = pbr_split.column()
            col_2 = pbr_split.column()
            col_2.prop(bake_panel_settings, "bake_albedo")
            col_2.prop(bake_panel_settings, "bake_normal")
            col_2.prop(bake_panel_settings, "bake_metallic")
            col_2.prop(bake_panel_settings, "bake_roughness")
            col_2.prop(bake_panel_settings, "bake_emission")
            col_2.prop(bake_panel_settings, "bake_opacity")
            layout.separator()
            split = layout.split(factor=0.05)
            col_1 = split.column()
            col_2 = split.column()
            col_3 = split.column()
            col_4 = split.column()
            col_2.prop(bake_panel_settings, "bake_curvature")
            if developer_mode:
                if bake_panel_settings.bake_curvature:
                    col_3.enabled = True
                    col_3.prop(bake_panel_settings, "bake_curvature_applied")

            split = layout.split(factor=0.05)
            col_1 = split.column()
            col_2 = split.column()
            col_3 = split.column()
            col_4 = split.column()
            col_2.prop(bake_panel_settings, "bake_ao")
            if developer_mode:
                if bake_panel_settings.bake_ao:
                    col_3.enabled = True
                    col_3.prop(bake_panel_settings, "bake_ao_applied")
                    col_4.prop(bake_panel_settings, "bake_ao_LoFi")

        if developer_mode:
            normal_cavity_row = layout.row(align=True)
            if bake_panel_settings.bake_normal:
                normal_cavity_row.enabled = True
                normal_cavity_row.prop(bake_panel_settings, "bake_cavity")
                normal_cavity_row.prop(bake_panel_settings, "bake_cavity_applied")
            ao_row = layout.row(align=True)
            if bake_panel_settings.bake_ao:
                ao_row.enabled = True
                ao_row.prop(bake_panel_settings, "bake_ao_applied")
            else:
                ao_row.enabled = False
            layout.separator()
            layout.prop(bake_panel_settings, "bake_outline")
            layout.separator()
            layout.prop(bake_panel_settings, "bake_background")
            layout.separator()


        layout.separator()
        layout.prop(bake_panel_settings, "bake_w_decimate")
        pbr_row = layout.row(align=True)
        if bake_panel_settings.bake_w_decimate:
            pbr_row.enabled = True
            layout.prop(bake_panel_settings, "bake_w_decimate_ratio")
        else :
            pbr_row.enabled = False







    def execute(self, context):  
        settings = context.scene.bake_panel_settings
        if bpy.context.object:
            if "OBJECT" not in bpy.context.object.mode:
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
        scene_name = bpy.context.window.scene.name
        currSceneIndex = getCurrentSceneIndex()

        isComicPanel = False
        if "p." in context.scene.name:
            isComicPanel = True
            export_collection = getCurrentExportCollection(self, context)
            if (export_collection):
                export_collection_name = export_collection.name
            else:
                if settings.target_strategy != "target_existing":
                    export_collection_name = "Export"
                    e_collection = bpy.data.collections.new(export_collection_name)
                    bpy.context.scene.collection.children.link(e_collection)  
                    export_collection = bpy.data.collections.get(export_collection_name)

        # panel_number = "0000"
        # panels = []

        # for scene in bpy.data.scenes:
        #     if "p." in scene.name:
        #         panels.append(scene.name)
        # for panel in panels :
        #     for i in range(len(bpy.data.scenes)):
        #         if bpy.data.scenes[currSceneIndex].name == panel:
        #             stringFragments = panel.split('.')
        #             export_collection_name = "Export." + stringFragments[1]
        #             panel_number = stringFragments[1]




        # layer_collection = bpy.context.view_layer.layer_collection

        # [P0-C] bakeSourceCollection is frequently unset -> .name crashed with
        # AttributeError.  Fall back to the active/selected collection, then
        # report a clean error instead of raising.
        source_collection = settings.bakeSourceCollection
        if source_collection is None:
            source_collection = _b52_resolve_bake_source_collection(context)
        if source_collection is None:
            self.report({'ERROR'}, 'Bake Source Collection not found. Set it in the Bake panel, or select an object first.')
            return {'CANCELLED'}
        source_collection_name = source_collection.name
        print('[3DComicToolkit] Bake source collection: ' + source_collection_name)
        scene_collection = bpy.context.view_layer.layer_collection
        bake_collection_name =  (source_collection_name  + "_baked")
        bake_mesh_name = (source_collection_name  + "_baked")

        hasMultires = False



        # if source_collection is None :
        #     selected_objects = bpy.context.selected_objects
        #     if len(selected_objects) > 0:
        #         source_collection = selected_objects[0].users_collection[0]            
        #         source_collection_name = source_collection.name  
        #     else:
        #         # source_collection = scene_collection
        #         collections =  context.view_layer.objects.active.users_collection          
        #         if len(collections) > 2:
        #             self.report({'ERROR'}, 'You must select a collection!')
        #     return {'FINISHED'} 


        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')



        # cleanup previous bake collection 
        if bpy.data.collections.get(bake_collection_name) : 
            old_bake_collection = bpy.data.collections.get(bake_collection_name)
            if isComicPanel:
                bpy.context.view_layer.active_layer_collection = export_collection.children[bake_collection_name]
            bpy.data.collections.remove(old_bake_collection)
            empty_trash(self, context)
            self.report({'INFO'}, 'Deleted Previous Export collection!')


        # manage export collection 
        layer_collection = bpy.context.view_layer.layer_collection
        # source_collection_name = bpy.context.view_layer.active_layer_collection.collection.name
        # source_collection = bpy.data.collections.get(source_collection_name)
        scene_collection = bpy.context.view_layer.layer_collection

        if settings.target_strategy != "target_existing":
                bake_collection = bpy.data.collections.new(bake_collection_name)
                if isComicPanel:
                    export_collection.children.link(bake_collection)
                else:
                    bpy.context.scene.collection.children.link(bake_collection)

        else:
            bake_collection = settings.bakeTargetObject.users_collection[0] 
            bake_collection_name = bake_collection.name 


        obj = bpy.context.object
        # print ("::::::::::::::::::::::::::::::::::::::::::::::")

        # bpy.ops.object.select_all(action='DESELECT')

        # path to the folder
        file_path = bpy.data.filepath
        file_name = bpy.path.display_name_from_filepath(file_path)
        file_ext = '.blend'
        file_dir = file_path.replace(file_name+file_ext, '')
        # materials_dir = file_dir+"\Materials\"
        materials_dir = file_dir+"\\Materials\\"
        if not os.path.exists(materials_dir):
            os.makedirs(materials_dir)
        
        settings = context.scene.bake_panel_settings

        if settings.bakeSize == "size_128":
            width = 128
            height = 128
            pixelMargin = 4
        if settings.bakeSize == "size_256":
            width = 256
            height = 256
            pixelMargin = 4
        if  settings.bakeSize == "size_512":
            width = 512
            height = 512
            pixelMargin = 4
        if  settings.bakeSize == "size_1024":
            width = 1024
            height = 1024
            pixelMargin = 4
        if  settings.bakeSize == "size_2048":
            width = 2048
            height = 2048
            pixelMargin = 4
        if  settings.bakeSize == "size_4096":
            width = 4096
            height = 4096
            pixelMargin = 4
        if  settings.bakeSize == "size_8192":
            width = 8192
            height = 8192
            pixelMargin = 4


        bake_to_unlit = settings.bake_to_unlit
        bake_to_pbr = settings.bake_to_pbr
        bake_albedo = settings.bake_albedo
        bake_normal = settings.bake_normal
        bake_metallic = settings.bake_metallic
        bake_roughness = settings.bake_roughness
        bake_emission = settings.bake_emission
        bake_opacity = settings.bake_opacity
        bake_ao = settings.bake_ao
        bake_ao_applied = settings.bake_ao_applied
        bake_curvature = settings.bake_curvature
        bake_curvature_applied = settings.bake_curvature_applied
        bake_cavity = settings.bake_cavity
        bake_cavity_applied = settings.bake_cavity_applied            
        bake_ao_LoFi = settings.bake_ao_LoFi
        decimate = settings.bake_w_decimate
        ratio = settings.bake_w_decimate_ratio
        bake_distance = settings.bake_distance
        bake_background = settings.bake_background
        bake_outline = settings.bake_outline

        wm = context.window_manager
        tot = 1
        wm.progress_begin(0,tot)       
        progress_current = 0.0
        process_count =   bake_to_pbr + bake_to_unlit + bake_albedo + bake_normal + bake_roughness + bake_metallic + bake_emission +  bake_opacity + bake_ao + bake_outline + bake_background
        progress_step = tot/process_count
        progress_current += progress_step
        wm.progress_update(progress_current)
        # for i in range(tot):
        #     wm.progress_update(i)

        visible_objects = []
        visible_objects=[ob for ob in bpy.context.scene.objects if ob.visible_get()]


        # # select all source meshes
        # bpy.ops.object.select_all(action='DESELECT')
        # for ob in source_collection.objects :
        #     if ob.type == 'MESH' : 
        #         print (ob.name)
        #         ob.select_set(state=True)
        #         bpy.context.view_layer.objects.active = ob
        # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        # source_meshes = bpy.context.selected_objects

        # select all source meshes
        source_meshes = []
        for ob in source_collection.objects :
            if ob.type == 'MESH' : 
                if ob.visible_get() :
                    source_meshes.append(ob)


        bake_meshes = []
        tmp_meshes = []

        if settings.bake_w_decimate :
            ratio = settings.bake_w_decimate_ratio
        else:
            ratio = 1


        if settings.target_strategy == "target_automesh":
            # duplicate all collection objects and put into one collection.
            for ob in source_meshes :
                bpy.ops.object.select_all(action='DESELECT')
                ob.select_set(state=True)
                bpy.context.view_layer.objects.active = ob
                bpy.ops.object.duplicate_move()
                target_object = bpy.context.selected_objects[0]
                bpy.data.collections[source_collection_name].objects.unlink(target_object)
                bpy.data.collections[bake_collection_name].objects.link(target_object)
                tmp_meshes.append(target_object)

            #apply all modifiers
            for tmp_ob in tmp_meshes:
                if bpy.context.object:
                    if "OBJECT" not in bpy.context.object.mode:
                        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  
                bpy.ops.object.select_all(action='DESELECT')
                tmp_ob.select_set(state=True)
                bpy.context.view_layer.objects.active = tmp_ob
                for mod in [m for m in tmp_ob.modifiers]:
                    bpy.ops.object.modifier_apply( modifier=mod.name)            
                bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=True, type='FACE')
                bpy.ops.mesh.select_all(action='TOGGLE')
                bpy.ops.mesh.delete_loose()
                bpy.ops.mesh.dissolve_degenerate()
                bpy.ops.mesh.remove_doubles()
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)


            # # UV maps any objects that do not have UV's
            automap(tmp_meshes, ratio)

            #boolean objects into one mesh
            bpy.ops.object.select_all(action='DESELECT')
            for ob in tmp_meshes :
                ob.select_set(state=True)
                bpy.context.view_layer.objects.active = ob
            bpy.ops.object.booltool_auto_union()           
            bm = bpy.context.object
            bm.name = bake_mesh_name
            bake_meshes.append(bm)

            # Triangulate
            bpy.ops.object.mode_set(mode='EDIT', toggle=False)
            bpy.ops.mesh.select_mode(use_extend=False, use_expand=True, type='FACE')
            bpy.ops.mesh.select_all(action='TOGGLE')
            bpy.ops.mesh.remove_doubles()
            bpy.ops.mesh.quads_convert_to_tris(quad_method='FIXED', ngon_method='BEAUTY')
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)




        # if settings.target_strategy == "target_duplicate":



        # duplicate and move to bake collection
        if settings.target_strategy == "target_duplicate":
            for source_object in source_meshes :
                bpy.ops.object.select_all(action='DESELECT')
                source_object.select_set(state=True)
                bpy.context.view_layer.objects.active = source_object
                target_object_name = source_object.name + "_baked"
                

                bpy.ops.object.duplicate_move()
                target_object = bpy.context.selected_objects[0]
                automap(bpy.context.selected_objects, ratio)
                bpy.ops.object.select_all(action='DESELECT')
                target_object.select_set(state=True)
                bpy.context.view_layer.objects.active = target_object
                target_object.name = target_object_name

                # UV maps any objects if it does not have UV's

                bpy.data.collections[source_collection_name].objects.unlink(target_object)
                bpy.data.collections[bake_collection_name].objects.link(target_object)
                bake_meshes.append(target_object)


                # self.report({'ERROR'}, '======================================================')

        if settings.target_strategy == "target_existing":
            # bpy.ops.object.duplicate_move(OBJECT_OT_duplicate={"linked":False, "mode":'TRANSLATION'}, TRANSFORM_OT_translate={"value":(0, 0, 0), "orient_type":'GLOBAL', "orient_matrix":((-4.37114e-08, -1, 0), (1, -4.37114e-08, 0), (0, 0, 1)), "orient_matrix_type":'GLOBAL', "constraint_axis":(False, False, False), "mirror":True, "use_proportional_edit":False, "proportional_edit_falloff":'INVERSE_SQUARE', "proportional_size":0.101089, "use_proportional_connected":False, "use_proportional_projected":False, "snap":False, "snap_target":'CLOSEST', "snap_point":(0, 0, 0), "snap_align":False, "snap_normal":(0, 0, 0), "gpencil_strokes":False, "cursor_transform":False, "texture_space":False, "remove_on_cancel":False, "release_confirm":False, "use_accurate":False})
            # bpy.ops.object.move_to_collection(collection_index=0, is_new=True, new_collection_name=bake_collection_name)
            # bakemesh = bpy.context.object
            # bake_mesh_name = bm.name
            # bake_meshes.append(bm)
            # target_object = settings.bakeTargetObject
            bake_meshes.append(settings.bakeTargetObject)


            # bpy.ops.object.duplicate_move()
            # target_object = bpy.context.selected_objects[0]
            # target_object.name = target_object_name
            # bpy.data.collections[source_collection_name].objects.unlink(target_object)
            # bpy.data.collections[bake_collection_name].objects.link(target_object)

        if settings.target_strategy == "target_automesh":
            # bake_mesh_name = ("BakeMesh  " + source_collection.name )
            # bakemesh.name = bake_mesh_name
            target_object = bake_meshes[0]
            # bakemesh = bake_meshes[0]



        if bake_to_unlit :
            ## old collection logic
            # layer_collection = bpy.context.view_layer.layer_collection
            # source_collection_name = bpy.context.view_layer.active_layer_collection.collection.name
            # source_collection = bpy.data.collections.get(source_collection_name)
            # scene_collection = bpy.context.view_layer.layer_collection
            # if source_collection is None :
            #     if context.view_layer.objects.active is not None :
            #         collections =  context.view_layer.objects.active.users_collection
            #         if len(collections) > 0:
            #             bpy.context.view_layer.active_layer_collection = collections()
            #             source_collection_name = bpy.context.view_layer.active_layer_collection.collection.name
            #             source_collection = bpy.data.collections.get(source_collection_name)
            #         else:
            #             source_collection = scene_collection
            #             self.report({'ERROR'}, 'You must select a collection!')
            #             return {'FINISHED'} 

            # bake_collection_name = ("Lightmap Bake " + source_collection.name )
            # bake_mesh_name = ("Lightmap BakeMesh  " + source_collection.name )




            # bake_to_unlit = True
            # decimate = True



            # # verify all objects have UV's, if not create some.
            # bpy.ops.object.select_all(action='DESELECT')
            # for ob in source_collection.objects :
            #     if ob.type == 'MESH' : 
            #         print (ob.name)
            #         ob.select_set(state=True)
            #         bpy.context.view_layer.objects.active = ob
            #         if not len( ob.data.uv_layers ):
            #             bpy.ops.uv.smart_project()
            #             bpy.ops.uv.smart_project(angle_limit=66)
            #             bpy.ops.uv.smart_project(island_margin=0.05, user_area_weight=0)

            if settings.target_strategy == "target_automesh" or settings.target_strategy == "target_duplicate" : 
                if decimate:
                    bpy.ops.object.modifier_add(type='REMESH')
                    bpy.context.object.modifiers["Remesh"].voxel_size = 0.007
                    bpy.context.object.modifiers["Remesh"].adaptivity = 0.015
                    bpy.context.object.modifiers["Remesh"].use_smooth_shade = True

                    bpy.ops.object.modifier_add(type='DECIMATE')
                    bpy.context.object.modifiers["Decimate"].decimate_type = 'DISSOLVE'
                    bpy.context.object.modifiers["Decimate"].angle_limit = 0.0523599
                    bpy.context.object.modifiers["Decimate"].delimit = {'UV'}
                    bpy.ops.object.modifier_apply( modifier="Decimate")

                    bpy.ops.object.modifier_add(type='TRIANGULATE')
                    bpy.context.object.modifiers["Triangulate"].keep_custom_normals = True
                    bpy.context.object.modifiers["Triangulate"].quad_method = 'FIXED'
                    bpy.ops.object.modifier_apply( modifier="Triangulate")

                    bpy.ops.object.modifier_add(type='DECIMATE')
                    print (ratio)
                    bpy.context.object.modifiers["Decimate"].ratio = ratio
                    bpy.ops.object.modifier_apply( modifier="Decimate")

                    for mod in [m for m in bm.modifiers]:
                        bpy.ops.object.modifier_apply( modifier=mod.name)  

                    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=True, type='FACE')
                    bpy.ops.mesh.select_all(action='TOGGLE')
                    bpy.ops.mesh.delete_loose()
                    bpy.ops.mesh.dissolve_degenerate()
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

                # area = bpy.context.area
                # old_type = area.type
                # area.type = 'VIEW_3D'

                
                # if old_type != "":
                    # area.type = old_type
                # area.type = 'INFO'







            # bpy.ops.object.move_to_collection(collection_index=0, is_new=True, new_collection_name= bake_collection_name)

            # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[-1]
            
            
            # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[source_collection_name]
            
            
            # bpy.context.view_layer.active_layer_collection.exclude = False

            automap(bake_meshes, ratio)


            for bakemesh in bake_meshes :
                if (bpy.context.mode != 'OBJECT'):
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

                bpy.ops.object.select_all(action='DESELECT')
                bakemesh.select_set(state=True)
                bpy.context.view_layer.objects.active = bakemesh
                # selected_objects = bpy.context.selected_objects

                # nuke_flat_texture(selected_objects, width, height)

                if bakemesh.active_material is not None:

                    # bakemesh.active_material.node_tree.nodes.clear()
                    # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 bakemesh 全部材质槽
                    bakemesh.data.materials.clear()
                bpy.ops.object.shade_smooth()

                assetName = bakemesh.name
                matName = (assetName + "Mat")
                texName_lightmap = (assetName + "_lightmap")
                mat = bpy.data.materials.new(name=matName)
                mat.use_nodes = True
                mat.node_tree.nodes.clear()
                mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                texture.image = bpy.data.images.new(texName_lightmap, width=width, height=height)

                mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])

                shader.name = "Background"
                shader.label = "Background"

                mat_output = mat.node_tree.nodes.get('Material Output')
                mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])



                # Assign it to object
                if bakemesh.data.materials:
                    bakemesh.data.materials[0] = mat
                else:
                    bakemesh.data.materials.append(mat)  


                # Select Objects for Bake
                bpy.ops.object.select_all(action='DESELECT')
                for ob in source_meshes :
                    ob.select_set(state=True)
                    bpy.context.view_layer.objects.active = ob
                bakemesh.select_set(state=True)
                bpy.context.view_layer.objects.active = bakemesh

                #set Redner bake settings
                bpy.context.scene.render.engine = 'CYCLES'
                # Blender 3.0+: render.tile_x/tile_y removed (Cycles X auto-manages)
                # bpy.context.scene.render.tile_x =  width
                # bpy.context.scene.render.tile_y =  height
                bpy.context.scene.cycles.max_bounces = 4
                bpy.context.scene.cycles.diffuse_bounces = 4
                bpy.context.scene.cycles.glossy_bounces = 4
                bpy.context.scene.cycles.transparent_max_bounces = 4
                bpy.context.scene.cycles.transmission_bounces = 4
                bpy.context.scene.cycles.volume_bounces = 0

                bpy.context.scene.cycles.bake_type = 'COMBINED'
                bpy.context.scene.render.bake.use_selected_to_active = True
                bpy.context.scene.render.bake.use_cage = True
                ray_length = bakemesh.dimensions[1] * bake_distance
                bpy.context.scene.render.bake.cage_extrusion = ray_length
                bpy.context.scene.render.bake.use_pass_direct = True
                bpy.context.scene.render.bake.use_pass_indirect = True
                bpy.context.scene.cycles.samples = 256  

                #select the output texture node and bake
                matnodes = bpy.context.active_object.material_slots[0].material.node_tree.nodes
                imgnodes = [n for n in matnodes if n.type == 'TEX_IMAGE']
                for n in imgnodes:
                    if n.image.name == texName_lightmap:
                        n.select = True
                        matnodes.active = n
                        # if os.path.exists(file_dir) and os.path.exists(materials_dir):
                        #         outBakeFileName = n.image.name+".png"
                        #         outRenderFileName = materials_dir+outBakeFileName
                        #         n.image.file_format = 'PNG'
                        #         n.image.filepath = outRenderFileName
                        #         bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                        #         n.image.save()
                        #         self.report({'INFO'},"Baked lightmap texture saved to: " + outRenderFileName )
                        # else:
                        bpy.ops.object.bake(type='COMBINED')
                        n.image.pack()




                # bpy.ops.object.bake('INVOKE_DEFAULT', type='COMBINED')
                # bpy.ops.object.bake("INVOKE_SCREEN", type='COMBINED')
                
                # bpy.context.view_layer.layer_collection.children[bake_collection_name].exclude = False
                # bpy.context.view_layer.layer_collection.children[source_collection_name].exclude = True

                if isComicPanel:
                    _b52_set_lc_exclude(export_collection_name, False)
                _b52_set_lc_exclude(source_collection_name, False)
                _b52_set_active_layer_collection(source_collection_name)

            progress_current += progress_step
            wm.progress_update(progress_current)

        if bake_to_pbr:
            if bake_albedo or bake_normal or bake_roughness or bake_metallic or bake_emission or bake_opacity or bake_ao or bake_curvature:
                for target_object in bake_meshes :
                    if target_object is not None:
                            
                        # bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                        bpy.ops.object.select_all(action='DESELECT')
                        target_object.select_set(state=True)
                        bpy.context.view_layer.objects.active = target_object

                        # # UV if none exist
                        # if not len(source_object.data.uv_layers):
                        #     bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                        #     bpy.ops.mesh.select_all(action='SELECT')
                        #     # bpy.ops.uv.smart_project()
                        #     # bpy.ops.uv.smart_project(angle_limit=66)
                        #     bpy.ops.uv.smart_project(angle_limit=66, island_margin=0.01, user_area_weight=0.75)
                        #     bpy.ops.uv.average_islands_scale()

                        #     # select all faces
                        #     # bpy.ops.mesh.select_all(action='SELECT')
                        #     bpy.ops.uv.pack_islands(margin=0.017)

                        #     # bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.1)
                        #     bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

                        #     if decimate:
                        #         bpy.ops.object.modifier_add(type='DECIMATE')
                        #         bpy.context.object.modifiers["Decimate"].decimate_type = 'DISSOLVE'
                        #         bpy.context.object.modifiers["Decimate"].angle_limit = 0.0523599
                        #         bpy.context.object.modifiers["Decimate"].delimit = {'UV'}
                        #         bpy.ops.object.modifier_apply( modifier="Decimate")

                        #         bpy.ops.object.modifier_add(type='TRIANGULATE')
                        #         bpy.context.object.modifiers["Triangulate"].keep_custom_normals = True
                        #         bpy.context.object.modifiers["Triangulate"].quad_method = 'FIXED'
                        #         bpy.ops.object.modifier_apply( modifier="Triangulate")

                        #         bpy.ops.object.modifier_add(type='DECIMATE')
                        #         bpy.context.object.modifiers["Decimate"].ratio = ratio
                        #         bpy.ops.object.modifier_apply( modifier="Decimate")

                        #     # area = bpy.context.area
                        #     # old_type = area.type
                        #     # area.type = 'VIEW_3D'
                        #     bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                        #     bpy.ops.mesh.select_all(action='SELECT')
                        #     # if bakemesh.data.uv_layers:
                        #         # area.type = 'IMAGE_EDITOR'
                        #     bpy.ops.uv.seams_from_islands()

                        #     # bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
                        #     bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)

                        #     bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                            
                        #     # if old_type != "":
                        #         # area.type = old_type
                        #     # area.type = 'INFO'


                        # bpy.ops.object.select_all(action='DESELECT')
                        # bakemesh.select_set(state=True)
                        # bpy.context.view_layer.objects.active = bakemesh




                        # selected_objects = bpy.context.selected_objects
                        # nuke_bsdf_textures(selected_objects, self.width, self.height)

                        # for ob in selected_objects:
                        #         if ob.type == 'MESH':


                        if target_object.active_material is not None:
                            for i in range(len(target_object.material_slots)):
                                bpy.ops.object.material_slot_remove()

                        # raise Exception('stopping script')

                        # bpy.ops.object.shade_smooth()
                        # bpy.context.object.data.use_auto_smooth = False
                        # bpy.ops.mesh.customdata_custom_splitnormals_clear()

                        blend_filename = os.path.basename(bpy.data.filepath)
                        stringFragments = blend_filename.split('_v')
                        if stringFragments[0]:
                            assetName = stringFragments[0] + "_" + target_object.name
                        else:
                            assetName = target_object.name
                        matName = (assetName + "Mat")
                        mat = bpy.data.materials.new(name=matName)
                        
                        mat.use_nodes = True
                        texName_albedo = (assetName + "_albedo")
                        texName_roughness = (assetName + "_roughness")
                        texName_metal = (assetName + "_metallic")
                        texName_emission = (assetName + "_emission")
                        texName_opacity = (assetName + "_opacity")
                        texName_normal = (assetName + "_normal") 
                        texName_ao = (assetName + "_ao") 
                        texName_curvature = (assetName + "_curvature")
                        # texName_orm = (assetName + "_orm")

                        mat.node_tree.nodes.clear()
                        # bpy.ops.object.shade_smooth()
                        mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                        shader = mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
                        shader.inputs[0].default_value = (1, 1, 1, 1)
                        mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])

                        albedo_texture = ""
                        ao_texture = ""
                        curvature_texture = ""

                        if bake_albedo:
                            albedo_texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            albedo_texture.image = bpy.data.images.new(texName_albedo,  width=width, height=height)
                            mat.node_tree.links.new(albedo_texture.outputs[0], shader.inputs[0])


                        if bake_ao:
                            ao_texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            ao_texture.image = bpy.data.images.new(texName_ao,  width=width, height=height)
                            mat.node_tree.links.new(ao_texture.outputs[0], shader.inputs[0])

                            if bake_albedo and not bake_curvature and not bake_ao_applied:
                                albedo_mixer = mat.node_tree.nodes.new(type="ShaderNodeMixRGB")
                                mat.node_tree.links.new(albedo_mixer.outputs[0], shader.inputs[0])
                                mat.node_tree.links.new(albedo_texture.outputs[0], albedo_mixer.inputs[1])
                                mat.node_tree.links.new(ao_texture.outputs[0], albedo_mixer.inputs[2])
                                albedo_mixer.blend_type = 'OVERLAY'
                                albedo_mixer.inputs[0].default_value = 0.5

                        if bake_roughness:
                            texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            texture.image = bpy.data.images.new(texName_roughness,  width=width, height=height)
                            mat.node_tree.links.new(texture.outputs[0], shader.inputs[7])

                        if bake_metallic:
                            texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            texture.image = bpy.data.images.new(texName_metal,  width=width, height=height)
                            mat.node_tree.links.new(texture.outputs[0], shader.inputs[4])

                        if bake_curvature:
                            curvature_texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            curvature_texture.image = bpy.data.images.new(texName_curvature,  width=width, height=height)
                            mat.node_tree.links.new(curvature_texture.outputs[0], shader.inputs[0])

                            if bake_albedo and not bake_ao and not bake_curvature_applied:
                                albedo_mixer = mat.node_tree.nodes.new(type="ShaderNodeMixRGB")
                                mat.node_tree.links.new(albedo_mixer.outputs[0], shader.inputs[0])
                                mat.node_tree.links.new(albedo_texture.outputs[0], albedo_mixer.inputs[1])
                                mat.node_tree.links.new(curvature_texture.outputs[0], albedo_mixer.inputs[2])
                                albedo_mixer.blend_type = 'OVERLAY'
                                albedo_mixer.inputs[0].default_value = 0.5

                        if bake_curvature and not bake_ao_applied and not bake_curvature_applied:
                                albedo_mixer = mat.node_tree.nodes.new(type="ShaderNodeMixRGB")
                                if bake_albedo:
                                    albedo_color_input = albedo_texture
                                    mat.node_tree.links.new(albedo_color_input.outputs[0], albedo_mixer.inputs[1])
                                else:
                                    existing_albedo_color = shader.inputs[0].default_value
                                    albedo_mixer.inputs[1].default_value = existing_albedo_color

                                curvature_ao_mixer = mat.node_tree.nodes.new(type="ShaderNodeMixRGB")
                                mat.node_tree.links.new(curvature_ao_mixer.outputs[0], shader.inputs[0])
                                mat.node_tree.links.new(ao_texture.outputs[0], curvature_ao_mixer.inputs[1])
                                mat.node_tree.links.new(curvature_texture.outputs[0], curvature_ao_mixer.inputs[2])
                                curvature_ao_mixer.blend_type = 'MULTIPLY'
                                curvature_ao_mixer.inputs[0].default_value = 0.5
                                mat.node_tree.links.new(albedo_mixer.outputs[0], shader.inputs[0])

                                mat.node_tree.links.new(curvature_ao_mixer.outputs[0], albedo_mixer.inputs[2])
                                albedo_mixer.blend_type = 'OVERLAY'
                                albedo_mixer.inputs[0].default_value = 0.5


                        if bake_emission:
                            texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            texture.image = bpy.data.images.new(texName_emission,  width=width, height=height)
                            mat.node_tree.links.new(texture.outputs[0], shader.inputs[17])

                        if bake_opacity:
                            texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            texture.image = bpy.data.images.new(texName_opacity,  width=width, height=height)
                            mat.node_tree.links.new(texture.outputs[0], shader.inputs[19])
                            mat.blend_method = 'BLEND'


                        if bake_normal:
                            texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                            texture.image = bpy.data.images.new(texName_normal, width=width, height=height)
                            texture.image.colorspace_settings.name = 'Non-Color'
                            bump = mat.node_tree.nodes.new(type='ShaderNodeNormalMap')
                            mat.node_tree.links.new(texture.outputs[0], bump.inputs[1])
                            mat.node_tree.links.new(bump.outputs[0], shader.inputs[20])
                            bpy.ops.object.shade_smooth()
                            bpy.context.object.data.use_auto_smooth = False
                            bpy.ops.mesh.customdata_custom_splitnormals_clear()


                        # Assign it to object
                        if target_object.data.materials:
                            target_object.data.materials[0] = mat
                        else:
                            target_object.data.materials.append(mat)             

                        # Blender 3.0+: render.tile_x/tile_y removed
                        # bpy.context.scene.render.tile_x =  width
                        # bpy.context.scene.render.tile_y =  height
                        bpy.context.scene.cycles.max_bounces = 4
                        bpy.context.scene.cycles.diffuse_bounces = 4
                        bpy.context.scene.cycles.glossy_bounces = 4
                        bpy.context.scene.cycles.transparent_max_bounces = 4
                        bpy.context.scene.cycles.transmission_bounces = 4
                        bpy.context.scene.cycles.volume_bounces = 0

                        # bpy.ops.object.move_to_collection(collection_index=0, is_new=True, new_collection_name= bake_collection_name)

                        # bake_collection = bpy.data.collections.get(bake_collection_name)
                        # bpy.context.view_layer.active_layer_collection = bake_collection
                        # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[-1]

                        # bpy.context.view_layer.layer_collection.children[source_collection_name].exclude = False
                        # bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[source_collection_name]

                        # bpy.context.view_layer.active_layer_collection.exclude = False

                        bpy.ops.object.select_all(action='DESELECT')
                        if (settings.target_strategy == "target_automesh") or (settings.target_strategy == "target_duplicate") :
                            for ob in source_collection.objects :
                                if ob.type == 'MESH' : 
                                    bpy.context.view_layer.objects.active = ob
                                    ob.select_set(state=True)
                        target_object.select_set(state=True)                       
                        bpy.context.view_layer.objects.active = target_object

                        #bake the textures
                        bpy.context.scene.render.engine = 'CYCLES'

                        # if not len(target_object.material_slots):
                        #     bpy.ops.object.material_slot_add()

                        # if target_object.material_slots[0].material is None:
                        #     bpy.ops.material.new()

                        # matName = (target_object_name + "Mat")
                        # texName_lightmap = (target_object_name + "_lightmap")
                        # mat = bpy.data.materials.new(name=matName)
                        # mat.use_nodes = True
                        # mat.node_tree.nodes.clear()
                        # mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                        # shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                        # texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                        # texture.image = bpy.data.images.new(texName_lightmap, width=width, height=height)

                        # mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])

                        # shader.name = "Background"
                        # shader.label = "Background"

                        # mat_output = mat.node_tree.nodes.get('Material Output')
                        # mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])

                        matnodes = target_object.material_slots[0].material.node_tree.nodes
                        imgnodes = [n for n in matnodes if n.type == 'TEX_IMAGE']

                        tmp_flat_shader = ""
                        mat_output = ""
                        existing_mat_output_connection = ""
                        geometry_node = ""
                        curvature_colorramp = ""
                        ao_node = ""
                        
                        # for n in imgnodes:
                        #     if n.image.name == texName_ao:
                        #         n.select = True
                        #         matnodes.active = n
                        #         bpy.context.scene.cycles.bake_type = 'AO'
                        #         bpy.context.scene.render.image_settings.file_format = 'PNG'
                        #         bpy.context.scene.render.image_settings.color_depth = '8'
                        #         bpy.context.scene.render.image_settings.color_mode = 'BW'
                        #         if bake_ao_LoFi :
                        #             bpy.context.scene.render.bake.use_selected_to_active = False
                        #             bpy.context.view_layer.layer_collection.children[source_collection_name].exclude = True
                        #         else :
                        #             bpy.context.scene.render.bake.use_selected_to_active = True
                        #             bpy.context.scene.render.bake.use_cage = True
                        #             ray_length = target_object.dimensions[1] * bake_distance
                        #             bpy.context.scene.render.bake.cage_extrusion = ray_length
                        #         bpy.context.scene.cycles.samples = 128
                        #         bpy.context.scene.render.bake.margin = pixelMargin
                        #         if os.path.exists(file_dir):
                        #             if os.path.exists(materials_dir):
                        #                 outBakeFileName = n.image.name+".png"
                        #                 outRenderFileName = materials_dir+outBakeFileName
                        #                 n.image.file_format = 'PNG'
                        #                 n.image.filepath = outRenderFileName
                        #                 bpy.ops.object.bake(type='AO', filepath=outRenderFileName, save_mode='EXTERNAL')
                        #                 n.image.save()
                        #                 self.report({'INFO'},"Ambient Oclusion texture saved to: " + outRenderFileName )
                        #         else:
                        #             bpy.ops.object.bake(type='AO')
                        #             n.image.pack()
                        #         bpy.context.view_layer.layer_collection.children[source_collection_name].exclude = False
                        #         progress_current += progress_step
                        #         wm.progress_update(int(progress_current))


                        for n in imgnodes:
                            if n.image.name == texName_ao:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)
                                existing_metal_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'EMIT'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 8
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node
                                            tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                            ao_node = src_mat.node_tree.nodes.new(type='ShaderNodeAmbientOcclusion')
                                            ao_node.inputs[1].default_value = 60
                                            ao_node.samples = 64

                                            src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.links.new(ao_node.outputs[0], tmp_flat_shader.inputs[0])

                                    tmp_src.select_set(state=True)

                                temp_stored_selection = bpy.context.selected_objects

                                try:
                                    bpy.ops.object.select_all(action='DESELECT')

                                    # Define the path to the ink texture
                                    ink_texture_path = "C:\\Users\\86159\\AppData\\Roaming\\Blender Foundation\\Blender\\5.2\\scripts\\addons\\Blender-3DComicToolkit\\Resources\\Reader\\images\\black.jpg"

                                    # --- Create Ground Plane ---
                                    bpy.ops.mesh.primitive_plane_add(size=100, enter_editmode=False, align='WORLD', location=(0, 0, 0))
                                    ground_plane = bpy.context.selected_objects[0]
                                    ground_plane.name = "ZenGround"
                                    
                                    # Create and assign material for ground
                                    ground_mat = bpy.data.materials.new(name="ZenInkGroundMat")
                                    ground_mat.use_nodes = True
                                    ground_plane.data.materials.append(ground_mat)
                                    nodes = ground_mat.node_tree.nodes
                                    links = ground_mat.node_tree.links

                                    # Clear existing nodes
                                    for node in nodes:
                                        nodes.remove(node)

                                    # Create new nodes
                                    principled_node = nodes.new(type='ShaderNodeBsdfPrincipled')
                                    texture_node = nodes.new(type='ShaderNodeTexImage')
                                    material_output_node = nodes.new(type='ShaderNodeOutputMaterial')
                                    
                                    # Load image texture
                                    if os.path.basename(ink_texture_path) not in bpy.data.images:
                                        bpy.data.images.load(ink_texture_path)
                                    texture_node.image = bpy.data.images[os.path.basename(ink_texture_path)]
                                    
                                    # Connect nodes for ground material (basic for now, will add transparency later if needed)
                                    links.new(texture_node.outputs['Color'], principled_node.inputs['Base Color'])
                                    links.new(principled_node.outputs['BSDF'], material_output_node.inputs['Surface'])
                                    
                                    # --- Create Background Plane 1 ---
                                    bpy.ops.mesh.primitive_plane_add(size=50, enter_editmode=False, align='WORLD', location=(-25, 50, 25), rotation=(math.radians(90), 0, 0))
                                    bg_plane1 = bpy.context.selected_objects[0]
                                    bg_plane1.name = "ZenBackground1"

                                    # Create and assign material for background 1
                                    bg_mat1 = bpy.data.materials.new(name="ZenInkBgMat1")
                                    bg_mat1.use_nodes = True
                                    bg_plane1.data.materials.append(bg_mat1)
                                    nodes = bg_mat1.node_tree.nodes
                                    links = bg_mat1.node_tree.links

                                    # Clear existing nodes
                                    for node in nodes:
                                        nodes.remove(node)
                                    
                                    # Create new nodes
                                    principled_node_bg1 = nodes.new(type='ShaderNodeBsdfPrincipled')
                                    texture_node_bg1 = nodes.new(type='ShaderNodeTexImage')
                                    material_output_node_bg1 = nodes.new(type='ShaderNodeOutputMaterial')

                                    # Load image texture (using the same for now)
                                    texture_node_bg1.image = bpy.data.images[os.path.basename(ink_texture_path)]

                                    # Connect nodes for background material 1
                                    links.new(texture_node_bg1.outputs['Color'], principled_node_bg1.inputs['Base Color'])
                                    links.new(principled_node_bg1.outputs['BSDF'], material_output_node_bg1.inputs['Surface'])

                                    # --- Create Background Plane 2 ---
                                    bpy.ops.mesh.primitive_plane_add(size=50, enter_editmode=False, align='WORLD', location=(25, 50, 25), rotation=(math.radians(90), 0, 0))
                                    bg_plane2 = bpy.context.selected_objects[0]
                                    bg_plane2.name = "ZenBackground2"
                                    
                                    # Create and assign material for background 2
                                    bg_mat2 = bpy.data.materials.new(name="ZenInkBgMat2")
                                    bg_mat2.use_nodes = True
                                    bg_plane2.data.materials.append(bg_mat2)
                                    nodes = bg_mat2.node_tree.nodes
                                    links = bg_mat2.node_tree.links

                                    # Clear existing nodes
                                    for node in nodes:
                                        nodes.remove(node)

                                    # Create new nodes
                                    principled_node_bg2 = nodes.new(type='ShaderNodeBsdfPrincipled')
                                    texture_node_bg2 = nodes.new(type='ShaderNodeTexImage')
                                    material_output_node_bg2 = nodes.new(type='ShaderNodeOutputMaterial')

                                    # Load image texture (using the same for now)
                                    texture_node_bg2.image = bpy.data.images[os.path.basename(ink_texture_path)]
                                    
                                    # Connect nodes for background material 2
                                    links.new(texture_node_bg2.outputs['Color'], principled_node_bg2.inputs['Base Color'])
                                    links.new(principled_node_bg2.outputs['BSDF'], material_output_node_bg2.inputs['Surface'])
                                    
                                    # Ensure scene name is p.01
                                    bpy.context.scene.name = "p.01"

                                except Exception as e:
                                    import traceback
                                    self.report({'ERROR'}, "Error in creating Zen scene: " + traceback.format_exc())
                                    print("Error in creating Zen scene: " + traceback.format_exc())


                                bpy.ops.object.select_all(action='DESELECT')
                                # Placeholder for new Zen scene geometry
                                ao_cube = bpy.context.selected_objects[0]
                                ao_cube_mat = bpy.data.materials.new(name="aoMatName")
                                ao_cube_mat.use_nodes = True
                                ao_cube.data.materials.append(ao_cube_mat)
                                ao_mat_output = ao_cube_mat.node_tree.nodes.get('Material Output')

                                ao_nodes = ao_cube_mat.node_tree.nodes
                                for node in ao_nodes:
                                    if node.type != 'OUTPUT_MATERIAL': # skip the material output node as we'll need it later
                                        ao_nodes.remove(node) 

                                tmp_black_shader = ao_cube_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                tmp_black_shader.inputs[0].default_value = (0, 0, 0, 1)
                                ao_cube_mat.node_tree.links.new(tmp_black_shader.outputs[0], ao_mat_output.inputs[0])


                                # delete top and bottom face
                                bm = bmesh.new()
                                bm.from_mesh( ao_cube.data )
                                bm.faces.ensure_lookup_table()
                                faces = [f for f in bm.faces if GoingUp( f.normal )]
                                bmesh.ops.delete( bm, geom = faces, context = 'FACES_ONLY' )
                                faces = [f for f in bm.faces if GoingDown( f.normal )]
                                bm.to_mesh( ao_cube.data )

                                # warp cube to tune ground and toplight
                                # m_taper = bpy.ops.object.modifier_add(type='SIMPLE_DEFORM')
                                m_taper = ao_cube.modifiers.new(name="SIMPLE_DEFORM", type='SIMPLE_DEFORM')
                                m_taper.deform_method = 'TAPER'
                                m_taper.deform_axis = 'Z'
                                m_taper.factor = -1.7
                                # m_stretcher = bpy.ops.object.modifier_add(type='SIMPLE_DEFORM')
                                m_stretcher = ao_cube.modifiers.new(name="SIMPLE_DEFORM", type='SIMPLE_DEFORM')
                                m_stretcher.deform_method = 'STRETCH'
                                m_stretcher.deform_axis = 'Z'
                                m_stretcher.factor = -0.55

                                # raise KeyboardInterrupt()


                                for mod in [m for m in ao_cube.modifiers]:
                                    bpy.ops.object.modifier_apply( modifier=mod.name)   




                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='EMIT', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked ao texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='EMIT')
                                    n.image.pack()

                                # raise KeyboardInterrupt()



                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)
                                            src_mat.node_tree.nodes.remove(ao_node)
                                bpy.ops.object.select_all(action='DESELECT')
                                ao_cube.select_set(state=True)
                                bpy.context.view_layer.objects.active = ao_cube
                                bpy.ops.object.delete(use_global=False)
                                if isComicPanel:
                                    _b52_set_lc_exclude(export_collection_name, False)


                                # reselect objects
                                target_object.select_set(state=True)
                                bpy.ops.object.select_all(action='DESELECT')
                                for o in temp_stored_selection:
                                    o.select_set(state=True)
                                target_object.select_set(state=True)
                                bpy.context.view_layer.objects.active = target_object
                                            

                        if bake_ao_applied and bake_ao and bake_albedo:
                            if os.path.exists(file_dir):
                                if os.path.exists(materials_dir):
                                    outBakeFileName = (texName_albedo + "_w_ao")
                                    outRenderFileName = outBakeFileName

                                    # switch on nodes and get reference
                                    bpy.context.scene.use_nodes = True
                                    tree = bpy.context.scene.node_tree

                                    #clear default nodes
                                    for node in tree.nodes:
                                            tree.nodes.remove(node)
                                    
                                    for image in bpy.data.images:
                                        if (texName_ao) in image.name:
                                            ao_image = image
                                            ao_image_node = tree.nodes.new('CompositorNodeImage')
                                            ao_image_node.image = ao_image

                                        if (texName_albedo) in image.name:
                                            albedo_image = image
                                            albedo_image_node = tree.nodes.new('CompositorNodeImage')
                                            albedo_image_node.image = albedo_image


                                    # image = bpy.data.images.load(filepath= albedo_image)
                                    # viewer_node = bpy.context.scene.node_tree.nodes.new('CompositorNodeViewer')
                                    comp_node = tree.nodes.new('CompositorNodeComposite')   
                                    output_node = tree.nodes.new("CompositorNodeOutputFile")


                                    mix_node =  bpy.context.scene.node_tree.nodes.new("CompositorNodeMixRGB")
                                    mix_node.blend_type = 'MULTIPLY'


                                    gamma_node =  bpy.context.scene.node_tree.nodes.new("CompositorNodeGamma")
                                    gamma_node.inputs[1].default_value = 2
                                    tree.links.new(ao_image_node.outputs['Image'], gamma_node.inputs[0])
                                    tree.links.new(gamma_node.outputs['Image'], mix_node.inputs[1])
                                    treeF(albedo_image_node.outputs['Image'], mix_node.inputs[2])


                                    # bpy.context.scene.node_tree.links.new(mix_node.outputs[0], viewer_node.inputs[0])

                                    # baked_ao_image = bpy.data.images.new(texName_albedo + "_w_ao",  width=width, height=height)


                                    output_node.base_path =  materials_dir
                                    output_node.file_slots[0].path = outBakeFileName
                                    output_node.format.file_format = 'PNG'
                                    output_node.format.color_mode = 'RGB'

                                    tree.links.new(mix_node.outputs[0], output_node.inputs[0])
                                    tree.links.new(mix_node.outputs[0], comp_node.inputs[0])

                                    bpy.context.scene.render.use_file_extension = True
                                    bpy.context.scene.render.use_compositing = True
                                    
                                    bpy.ops.render.render(animation=False, write_still=True)

                                    # bpy.app.handlers.render_complete(bake_collection_composite)

                                    outRenderFileNamePadded = materials_dir+outBakeFileName+"0001.png"
                                    outRenderFileName = materials_dir+outBakeFileName+".png"
                                    if os.path.exists(outRenderFileName):
                                        os.remove(outRenderFileName)
                                    os.rename(outRenderFileNamePadded, outRenderFileName)

                                    self.report({'INFO'},"Composited texture saved to: " + outRenderFileName )

                                    texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                                    try:
                                        img = bpy.data.images.load(outRenderFileName)
                                        texture.image = img
                                        mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])
                                    except:
                                        raise NameError("Cannot load image %s" % path)



                                    # baked_ao_image.image.pack()




                        for n in imgnodes:
                            if n.image.name == texName_albedo:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'COMBINED'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'RGBA'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                bpy.context.scene.render.bake.use_pass_color = True
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 1
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node
                                            shandernode = src_mat.node_tree.nodes.get("Principled BSDF")
                                            if shandernode:
                                                tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                                src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])
                                                if not shandernode.inputs[0].links:
                                                    existing_metal_color = shandernode.inputs[0].default_value
                                                    tmp_flat_shader.inputs[0].default_value = existing_metal_color
                                                else:
                                                    existing_metal_color_input = shandernode.inputs[0].links[0].from_node
                                                    src_mat.node_tree.links.new(existing_metal_color_input.outputs[0], tmp_flat_shader.inputs[0])
                                    tmp_src.select_set(state=True)

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked albedo texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='COMBINED')
                                    n.image.pack()

                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)




                        for n in imgnodes:
                            if n.image.name == texName_normal:
                                n.select = True
                                matnodes.active = n
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '16'
                                bpy.context.scene.render.image_settings.color_mode = 'RGB'
                                bpy.context.scene.cycles.samples = 64
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for mod in [m for m in target_object.modifiers if m.type == 'MULTIRES']:
                                    hasMultires = True
                                    mod.levels = 0
                                
                                if not hasMultires :
                                    # bpy.context.scene.render.use_bake_multires = True
                                    # bpy.context.scene.render.bake_type = 'NORMALS'
                                    # bpy.context.view_layer.objects.active = target_object
                                # else :
                                    bpy.context.scene.render.use_bake_multires = False
                                    bpy.context.scene.cycles.bake_type = 'NORMAL'
                                    bpy.context.scene.render.bake.use_selected_to_active = True
                                    bpy.context.scene.render.bake.use_cage = True
                                    ray_length = target_object.dimensions[1] * bake_distance
                                    bpy.context.scene.render.bake.cage_extrusion = ray_length

                                for tmp_src in source_meshes:
                                    tmp_src.select_set(state=True)

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        if hasMultires :
                                            # error here because the soruce meshes might not have UV's   the logic should probably not have them selected.
                                            bpy.ops.object.bake(type='NORMAL', filepath=outRenderFileName, save_mode='EXTERNAL', use_selected_to_active=False)
                                        else:
                                            bpy.ops.object.bake(type='NORMAL', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked normal texture saved to: " + outRenderFileName )
                                else:
                                    if hasMultires :
                                        bpy.ops.object.bake(type='NORMAL', use_selected_to_active=False)
                                    else :
                                        bpy.ops.object.bake(type='NORMAL')
                                    n.image.pack()

                                # apply modifiers
                                for mod in [m for m in target_object.modifiers if m.type == 'MULTIRES']:
                                    mod.levels = 0
                                    bpy.ops.object.modifier_apply( modifier=mod.name)     
                                # for mod in [m for m in target_object.modifiers]:

                                progress_current += progress_step
                                wm.progress_update(int(progress_current))

                        for n in imgnodes:
                            if n.image.name == texName_metal:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)
                                existing_metal_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'COMBINED'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                # bpy.context.scene.render.bake.use_pass_color = True
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 1
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node
                                            shandernode = src_mat.node_tree.nodes.get("Principled BSDF")
                                            if shandernode:
                                                tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                                src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])

                                                if not shandernode.inputs[4].links:
                                                    existing_metal_color = shandernode.inputs[4].default_value
                                                    tmp_flat_shader.inputs[0].default_value = (existing_metal_color, existing_metal_color, existing_metal_color, 1)
                                                else:
                                                    existing_metal_color_input = shandernode.inputs[4].links[0].from_node
                                                    src_mat.node_tree.links.new(existing_metal_color_input.outputs[0], tmp_flat_shader.inputs[0])
                                    tmp_src.select_set(state=True)

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked metal texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='COMBINED')
                                    n.image.pack()

                                # raise KeyboardInterrupt()

                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)

                        for n in imgnodes:
                            if n.image.name == texName_curvature:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)
                                existing_metal_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'EMIT'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                # bpy.context.scene.render.bake.use_pass_color = True
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 1
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node

                                            tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                            geometry_node = src_mat.node_tree.nodes.new(type='ShaderNodeNewGeometry')
                                            curvature_colorramp = src_mat.node_tree.nodes.new(type='ShaderNodeValToRGB')
                                            src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])
                                            curvature_colorramp.color_ramp.elements[1].position = 0.6
                                            curvature_colorramp.color_ramp.elements[0].position = 0.45
                                            curvature_colorramp.color_ramp.interpolation = 'EASE'


                                            src_mat.node_tree.links.new(geometry_node.outputs[7], curvature_colorramp.inputs[0])
                                            src_mat.node_tree.links.new(curvature_colorramp.outputs[0], tmp_flat_shader.inputs[0])

                                    tmp_src.select_set(state=True)


                                # raise KeyboardInterrupt()

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='EMIT', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked curvature texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='EMIT')
                                    n.image.pack()

                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)
                                            src_mat.node_tree.nodes.remove(geometry_node)
                                            src_mat.node_tree.nodes.remove(curvature_colorramp)



                        for n in imgnodes:
                            if n.image.name == texName_roughness:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)
                                existing_roughness_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'COMBINED'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                # bpy.context.scene.render.bake.use_pass_color = True
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 1
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node
                                            shandernode = src_mat.node_tree.nodes.get("Principled BSDF")
                                            if shandernode:
                                                tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                                src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])

                                                if not shandernode.inputs[7].links:
                                                    existing_roughness_color = shandernode.inputs[7].default_value
                                                    tmp_flat_shader.inputs[0].default_value = (existing_roughness_color, existing_roughness_color, existing_roughness_color, 1)
                                                else:
                                                    existing_roughness_color = shandernode.inputs[7].links[0].from_node
                                                    src_mat.node_tree.links.new(existing_roughness_color.outputs[0], tmp_flat_shader.inputs[0])
                                    tmp_src.select_set(state=True)

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked roughness texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='COMBINED')
                                    n.image.pack()

                                # raise KeyboardInterrupt()


                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)


                        for n in imgnodes:
                            if n.image.name == texName_emission:
                                n.select = True
                                matnodes.active = n
                                bpy.context.scene.cycles.bake_type = 'EMIT'
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 64
                                bpy.context.scene.render.bake.margin = pixelMargin
                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='EMIT', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked emission texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='EMIT')
                                    n.image.pack()
                                progress_current += progress_step
                                wm.progress_update(int(progress_current))


                        # bpy.context.scene.cycles.bake_type = 'NORMAL'
                        # bpy.context.scene.cycles.bake_type = 'AO'
                        # bpy.context.scene.cycles.bake_type = 'ROUGHNESS'
                        # bpy.context.scene.cycles.bake_type = 'GLOSSY'
                        # if self.bake_emmision :
                        #     bpy.context.scene.cycles.bake_type = 'EMIT'
                        

                        # for image in bpy.data.images:
                        #     if (bake_mesh_name + "_albedo") in image.name:
                        #         image.pack()



                        for n in imgnodes:
                            if n.image.name == texName_opacity:
                                n.select = True
                                matnodes.active = n
                                existing_albedo_color = (0, 0, 0, 1)
                                existing_opacity_color = (0, 0, 0, 1)

                                bpy.context.scene.cycles.bake_type = 'COMBINED'  #('COMBINED', 'AO', 'SHADOW', 'NORMAL', 'UV', 'ROUGHNESS', 'EMIT', 'ENVIRONMENT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION')
                                bpy.context.scene.render.image_settings.file_format = 'PNG'
                                bpy.context.scene.render.image_settings.color_depth = '8'
                                bpy.context.scene.render.image_settings.color_mode = 'BW'
                                bpy.context.scene.render.bake.use_pass_indirect = False
                                bpy.context.scene.render.bake.use_pass_direct = False
                                # bpy.context.scene.render.bake.use_pass_color = True
                                bpy.context.scene.render.bake.use_selected_to_active = True
                                bpy.context.scene.render.bake.use_cage = True
                                ray_length = target_object.dimensions[1] * bake_distance
                                bpy.context.scene.render.bake.cage_extrusion = ray_length
                                bpy.context.scene.cycles.samples = 1
                                bpy.context.scene.render.bake.margin = pixelMargin

                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            mat_output = src_mat.node_tree.nodes.get('Material Output')
                                            existing_mat_output_connection = mat_output.inputs[0].links[0].from_node
                                            shandernode = src_mat.node_tree.nodes.get("Principled BSDF")
                                            if shandernode:
                                                tmp_flat_shader = src_mat.node_tree.nodes.new(type='ShaderNodeBackground')
                                                src_mat.node_tree.links.new(tmp_flat_shader.outputs[0], mat_output.inputs[0])

                                                if not shandernode.inputs[19].links:
                                                    existing_opacity_color = shandernode.inputs[19].default_value
                                                    tmp_flat_shader.inputs[0].default_value = (existing_opacity_color, existing_opacity_color, existing_opacity_color, 1)
                                                else:
                                                    existing_opacity_color = shandernode.inputs[19].links[0].from_node
                                                    src_mat.node_tree.links.new(existing_opacity_color.outputs[0], tmp_flat_shader.inputs[0])
                                    tmp_src.select_set(state=True)

                                if os.path.exists(file_dir):
                                    if os.path.exists(materials_dir):
                                        outBakeFileName = n.image.name+".png"
                                        outRenderFileName = materials_dir+outBakeFileName
                                        n.image.file_format = 'PNG'
                                        n.image.filepath = outRenderFileName
                                        bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                                        n.image.save()
                                        self.report({'INFO'},"Baked opacity texture saved to: " + outRenderFileName )
                                else:
                                    bpy.ops.object.bake(type='COMBINED')
                                    n.image.pack()

                                # raise KeyboardInterrupt()


                                # cleanup
                                for tmp_src in source_meshes:
                                    if tmp_src.data.materials:
                                        for src_mat in tmp_src.data.materials:
                                            src_mat.node_tree.links.new(existing_mat_output_connection.outputs[0], mat_output.inputs[0])
                                            src_mat.node_tree.nodes.remove(tmp_flat_shader)





        _b52_set_lc_exclude(source_collection_name, True)

        if settings.target_strategy != "target_existing" and isComicPanel:
            _b52_set_lc_nested_exclude(export_collection_name, bake_collection_name, False)
        
        # export_collection.children[bake_collection_name].exclude = False
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'


        if bake_outline :
            outline(self,context,bake_meshes )
            progress_current += progress_step
            wm.progress_update(int(progress_current))



        if bake_background :
            active_camera = bpy.context.scene.camera
            skyball_cam = bpy.context.scene.camera
            skyball_cam_object = bpy.context.selected_objects[0]
            bpy.context.scene.render.engine = 'CYCLES'



            if active_camera is not None :
                camera_collection = active_camera.users_collection[0]
                if isComicPanel:
                    if camera_collection is not export_collection:
                        export_collection.objects.link(active_camera)
                bpy.ops.object.select_all(action='DESELECT')
                active_camera.select_set(state=True)
                bpy.context.view_layer.objects.active = active_camera
            else :
                skyball_cam = bpy.data.cameras.new("MirrorBallCamera")
                skyball_cam_object = bpy.data.objects.new("MirrorBallCamera",skyball_cam)
                bpy.ops.object.select_all(action='DESELECT')
                skyball_cam_object.select_set(state=True)
                bpy.context.view_layer.objects.active = skyball_cam_object

            bpy.context.scene.camera = skyball_cam_object
            bpy.context.object.data.type = 'PANO'
            bpy.context.object.data.cycles.panorama_type = 'MIRRORBALL'
            bpy.context.object.rotation_euler[0] = 1.5708
            # bpy.context.object.rotation_euler[2] = 3.14159 #180
            bpy.context.object.rotation_euler[2] = 0

            skyball_cam_object.location[2] = 1.61
            bpy.context.scene.render.resolution_x = 4096
            bpy.context.scene.render.resolution_y = 4096
            bpy.context.scene.render.resolution_percentage = 100
            bpy.context.scene.cycles.samples = 32
            bpy.ops.render.render( animation=False, write_still=False )

            img_name = "skyball.png"

            # Render to Packed image.
            file_path = bpy.data.filepath
            file_name = bpy.path.display_name_from_filepath(file_path)
            file_ext = '.blend'
            file_dir = file_path.replace(file_name+file_ext, '')
            outRenderFileName = file_dir + "/" + img_name

            if os.path.exists(outRenderFileName):
                os.remove(outRenderFileName)

            bpy.data.images['Render Result'].save_render(outRenderFileName)

            if os.path.exists(outRenderFileName):
                bpy.ops.image.open(filepath = outRenderFileName)
                bpy.data.images[img_name].pack()
                os.remove(outRenderFileName)

            if isComicPanel:
                _b52_set_lc_nested_exclude(export_collection_name, bake_collection_name, False)


            #reset active camera
            bpy.context.scene.camera = active_camera
            bpy.ops.object.select_all(action='DESELECT')
            skyball_cam_object.select_set(state=True)
            bpy.context.view_layer.objects.active = skyball_cam_object
            bpy.ops.object.delete(use_global=False)

            bpy.ops.object.select_all(action='DESELECT')
            load_resource(self, context, "skyball.blend", False)
            skyball_objects = bpy.context.selected_objects
            for ob in skyball_objects:
                if ob.type == 'MESH':
                    if ob.active_material is not None:
                        ob.active_material.node_tree.nodes.clear()
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 ob 全部材质槽
                        ob.data.materials.clear()
                    bpy.ops.object.shade_smooth()

                    assetName = ob.name
                    matName = (assetName + "Mat")
                    mat = bpy.data.materials.new(name=matName)
                    mat.use_nodes = True
                    mat.node_tree.nodes.clear()
                    mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                    shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                    texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                    texture.image = bpy.data.images[img_name]

                    mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])

                    shader.name = "Background"
                    shader.label = "Background"

                    mat_output = mat.node_tree.nodes.get('Material Output')
                    mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])



                    # Assign it to object
                    if ob.data.materials:
                        ob.data.materials[0] = mat
                    else:
                        ob.data.materials.append(mat)

                    bake_collection.objects.link(ob)
                    bpy.context.scene.collection.objects.unlink(ob)



                    

            bpy.ops.object.select_all(action='DESELECT')
            load_resource(self, context, "skyball_warp.blend", False)
            skyball_warp_objects = bpy.context.selected_objects
            for ob in skyball_warp_objects:
                if ob.type == 'MESH':
                    if ob.active_material is not None:
                        ob.active_material.node_tree.nodes.clear()
                        # [Blender5.x兼容V3] 原 for+material_slot_remove(override字典) → 直接API 清除 ob 全部材质槽
                        ob.data.materials.clear()
                    bpy.ops.object.shade_smooth()

                    assetName = ob.name
                    matName = (assetName + "Mat")
                    mat = bpy.data.materials.new(name=matName)
                    mat.use_nodes = True
                    mat.node_tree.nodes.clear()
                    mat_output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
                    shader = mat.node_tree.nodes.new(type='ShaderNodeBackground')
                    texture = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
                    texture.image = bpy.data.images.new("skyball_warp.png", width=width, height=height)

                    mat.node_tree.links.new(texture.outputs[0], shader.inputs[0])

                    shader.name = "Background"
                    shader.label = "Background"

                    mat_output = mat.node_tree.nodes.get('Material Output')
                    mat.node_tree.links.new(shader.outputs[0], mat_output.inputs[0])



                    # Assign it to object
                    if ob.data.materials:
                        ob.data.materials[0] = mat
                    else:
                        ob.data.materials.append(mat)
                    bake_collection.objects.link(ob)
                    bpy.context.scene.collection.objects.unlink(ob)
                    

            bpy.ops.object.select_all(action='DESELECT')
            skyball_objects[0].select_set(state=True)
            skyball_warp_objects[0].select_set(state=True)
            bpy.context.view_layer.objects.active = skyball_warp_objects[0]

            #bake the textures
            # Blender 3.0+: render.tile_x/tile_y removed
            # bpy.context.scene.render.tile_x =  width
            # bpy.context.scene.render.tile_y =  height
            bpy.context.scene.cycles.max_bounces = 1
            bpy.context.scene.cycles.diffuse_bounces = 1
            bpy.context.scene.cycles.glossy_bounces = 1
            bpy.context.scene.cycles.transparent_max_bounces = 1
            bpy.context.scene.cycles.transmission_bounces = 1
            bpy.context.scene.cycles.volume_bounces = 0

            bpy.context.scene.render.engine = 'CYCLES'
            bpy.context.scene.cycles.samples = 1

            matnodes = bpy.context.active_object.material_slots[0].material.node_tree.nodes
            imgnodes = [n for n in matnodes if n.type == 'TEX_IMAGE']

            for n in imgnodes:
                n.select = True
                matnodes.active = n
                bpy.context.scene.cycles.bake_type = 'COMBINED'
                bpy.context.scene.render.image_settings.color_depth = '8'
                bpy.context.scene.render.image_settings.color_mode = 'RGB'
                bpy.context.scene.render.image_settings.file_format = 'PNG'
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_color = True
                bpy.context.scene.render.bake.use_selected_to_active = True
                bpy.context.scene.render.bake.use_cage = True
                ray_length = skyball_warp_objects[0].dimensions[1] * bake_distance
                bpy.context.scene.render.bake.cage_extrusion = ray_length
                if os.path.exists(file_dir):
                    if os.path.exists(materials_dir):
                        outBakeFileName = n.image.name+".png"
                        outRenderFileName = materials_dir+outBakeFileName
                        n.image.file_format = 'PNG'
                        n.image.filepath = outRenderFileName
                        bpy.ops.object.bake(type='COMBINED', filepath=outRenderFileName, save_mode='EXTERNAL')
                        n.image.save()
                        self.report({'INFO'},"Baked skyball texture saved to: " + outRenderFileName )
                else:
                    bpy.ops.object.bake(type='COMBINED')
                    n.image.pack()
                progress_current += progress_step
                wm.progress_update(int(progress_current))


            # bpy.ops.object.move_to_collection(collection_index=0, is_new=True, new_collection_name= bake_collection_name)
            _b52_set_active_layer_collection(source_collection_name)

        wm.progress_end()

        return {'FINISHED'}

    def invoke(self, context, event):

        return context.window_manager.invoke_props_dialog(self)




class BR_OT_pose_cycle_next(bpy.types.Operator):
    """make first panel scene the active scene"""
    bl_idname = "wm.spiraloid_pose_cycle_next"
    bl_label ="下一姿势（Pose Cycle Next）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        is_armature_selected = False
        objects = bpy.context.selected_objects
        for obj in objects:
            if obj.type == 'ARMATURE':
                is_armature_selected = True
            else:
                for mod in obj.modifiers:
                    mod_name = mod.name
                    if 'Skeleton' in mod_name:
                        is_armature_selected = True
        if is_armature_selected:
            cycle_pose(self, objects, "next")
        return {'FINISHED'}


class BR_OT_pose_cycle_previous(bpy.types.Operator):
    """make first panel scene the active scene"""
    bl_idname = "wm.spiraloid_pose_cycle_previous"
    bl_label ="上一姿势（Pose Cycle Previous）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        is_armature_selected = False
        objects = bpy.context.selected_objects
        for obj in objects:
            if obj.type == 'ARMATURE':
                is_armature_selected = True
            else:
                for mod in obj.modifiers:
                    mod_name = mod.name
                    if 'Skeleton' in mod_name:
                        is_armature_selected = True
        if is_armature_selected:
            cycle_pose(self, objects, "previous")
        return {'FINISHED'}


class BR_OT_add_pose(bpy.types.Operator):
    """Add new pose"""
    bl_idname = "wm.spiraloid_pose_add"
    bl_label ="保存新姿势（Add Pose）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        add_full_pose(self)
        return {'FINISHED'}

class BR_OT_subcollection_cycler(bpy.types.Operator):
    """add property to active object to cycle the child objects of the active collection"""
    bl_idname = "wm.spiraloid_subcollection_cycler"
    bl_label ="子集合循环器（subcollection cycler）"
    bl_options = {'REGISTER', 'UNDO'}



    def execute(self, context):
        backstage_collection = getCurrentBackstageCollection()
        try:
            active_collection = bpy.context.collection
            active_collection_name = active_collection.name
            active_collection_parent_collection = get_parent_collection(active_collection)
            active_collection_parent_collection_name = active_collection_parent_collection.name  
        except:
            pass 

        try:
            control_object = bpy.context.selected_objects[0]
        except:
            if active_collection:
              
                control_object_name = active_collection_name + "_Cycler"
                control_object = bpy.data.objects.new(control_object_name, None)
                control_object["is_cycler"] = 1

                if 'Master Collection' in active_collection_parent_collection_name:
                    scene = bpy.context.scene
                    scene.collection.objects.link(control_object)
                else:
                    bpy.data.collections[active_collection_parent_collection_name].objects.link(control_object)

        active_collection_children = active_collection.children
        if len(active_collection_children) == 0:
            collection_objects = active_collection.all_objects
            for obj in collection_objects:
                new_subcollection_name = obj.name 
                new_subcollection =  bpy.data.collections.new(new_subcollection_name)
                active_collection.children.link(new_subcollection)
                bpy.data.collections[new_subcollection_name].objects.link(obj)
                try:
                    bpy.data.collections[active_collection_name].objects.unlink(obj)
                except:
                    pass
                # bpy.context.scene.collection.children.unlink(new_subcollection)

            try:
                bpy.data.collections[active_collection_name].objects.link(control_object)
            except:
                pass




        if control_object and active_collection:
            active_collection_name = active_collection.name 
            control_property = "[\"" + active_collection_name + "\"]"
            control_property_name =  active_collection.name
            active_collection_children = active_collection.children
            collection_count = len(active_collection.children)
            print(collection_count)
            try:
                del control_object[control_property_name]
            except:
                pass 
            control_object[control_property_name] = 1 

            if '_RNA_UI' not in control_object.keys():
                control_object['_RNA_UI'] = {}
                

            control_object['_RNA_UI'][control_property_name]  = { "default": 1,
                                                                    "soft_min": 1,
                                                                    "soft_max": collection_count,
                                                                    "is_overridable_library":0,
                                                                }
                
            count = 1 
            collection_instances = []
            control_object_collection = control_object.users_collection[0]
            
            for col in active_collection_children:
                col_name = col.name + "_inst"
                bpy.ops.object.collection_instance_add(collection=col.name, align='WORLD', location=(0, 0, 0), scale=(1, 1, 1))
                i_col = bpy.context.selected_objects[0]
                i_col.name = col_name
                collection_instances.append(i_col)
                
                #need to figure out how to exclude nested collections.


                
            count = 1   
            for icol in collection_instances:
                if 'Master Collection' in active_collection_parent_collection_name:
                    scene = bpy.context.scene
                    scene.collection.objects.link(icol)
                else:
                    bpy.data.collections[active_collection_parent_collection_name].objects.link(icol)


                bpy.ops.object.select_all(action='DESELECT')
                icol.select_set(state=True)
                control_object.select_set(state=True)
                bpy.context.view_layer.objects.active = control_object
                bpy.ops.object.parent_set()


                visibilityDriver = icol.driver_add('hide_viewport')
                visibilityDriver.driver.type = 'SCRIPTED'
                newVar = visibilityDriver.driver.variables.new()
                newVar.name = "var"
                newVar.type = 'SINGLE_PROP'
                newVar.targets[0].id = control_object
                newVar.targets[0].data_path = control_property
                visibilityDriver.driver.expression =  ("var != " + str(count))

                # the switcher int can be driven by camera to switcher distance using this logic for LOD
                # 1 if (var <= lod_1_dist) else 2 if (var >= lod_1_dist) else (lod_1_dist - var)

                count += 1


            try:
                bpy.data.collections[active_collection_name].objects.unlink(control_object)                
                active_collection_parent_collection.children.unlink(active_collection)
                if backstage_collection:
                    backstage_collection.children.link(active_collection)



            except:
                pass

        else:
             self.report({'WARNING'}, "You must have an active collection!")
        return {'FINISHED'}


class BR_OT_subcollection_cycler_exportable(bpy.types.Operator):
    """add property to active object to cycle the child objects of the active collection"""
    bl_idname = "wm.spiraloid_subcollection_cycler_exportable"
    bl_label ="子集合循环器（可导出）"
    bl_options = {'REGISTER', 'UNDO'}



    def execute(self, context):
        try:
            control_object = bpy.context.selected_objects[0]
        except:
            pass 

        try:
            active_collection = bpy.context.collection
        except:
            pass 

        if control_object and active_collection:
            active_collection_name = active_collection.name 
            control_property = "[\"" + active_collection_name + "\"]"
            control_property_name =  active_collection.name
            active_collection_children = active_collection.children
            collection_count = len(active_collection.children)
            print(collection_count)
            try:
                del control_object[control_property_name]
            except:
                pass 
            control_object[control_property_name] = 1 

            if '_RNA_UI' not in control_object.keys():
                control_object['_RNA_UI'] = {}
                

            control_object['_RNA_UI'][control_property_name]  = { "default": 1,
                                                                    "soft_min": 1,
                                                                    "soft_max": collection_count,
                                                                    "is_overridable_library":0,
                                                                }
                
            count = 1   
            for icol in active_collection_children:
                cobjs = icol.objects
                for obj in cobjs:
                    try:
                        obj.driver_remove('location', 2)
                    except:
                        pass
                    visibilityDriver = obj.driver_add('location', 2)
                    visibilityDriver.driver.type = 'SCRIPTED'
                    newVar = visibilityDriver.driver.variables.new()
                    newVar.name = "var"
                    newVar.type = 'SINGLE_PROP'
                    newVar.targets[0].id = control_object
                    newVar.targets[0].data_path = control_property
                    visibilityDriver.driver.expression = "(var != " + str(count) + ") * (-1000000) "
                count += 1
        else:
             self.report({'WARNING'}, "You must have an active control object and an active collection!")
        return {'FINISHED'}



class BR_OT_overwrite_pose(bpy.types.Operator):
    """Overwrite last cycled pose"""
    bl_idname = "wm.spiraloid_pose_overwrite"
    bl_label ="覆盖当前姿势（Overwrite Pose）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        overwrite_full_pose(self)
        return {'FINISHED'}

class BR_OT_remove_pose(bpy.types.Operator):
    """Add new pose"""
    bl_idname = "wm.spiraloid_pose_remove"
    bl_label ="删除姿势（Remove Pose）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        remove_full_pose(self)
        return {'FINISHED'}

class BR_OT_toggle_child_lock(bpy.types.Operator):
    """Toggle if child bones inherit rotation or not"""
    bl_idname = "wm.spiraloid_toggle_child_lock"
    bl_label ="切换子对象锁定（Toggle Child Lock）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global isChildLock
        # if not isChildLock:
        #     self.report({'INFO'}, 'Bone Rotations Locked!')
        # else:
        #     self.report({'INFO'}, 'Bone Rotations Unlocked!')
        obj = bpy.context.object
        selected_bones = bpy.context.selected_pose_bones
        isSymmetryActive = bpy.context.selected_objects[0].pose.use_mirror_x
        # if obj is not None :
        #     if obj.type == 'ARMATURE':
        #         bpy.ops.pose.select_all(action='DESELECT')
        #         for s_bone in selected_bones:
        #             for poseBone in obj.pose.bones:
        #                 if poseBone.parent:
        #                     if s_bone.name in poseBone.parent.name :
        #                         poseBone.bone.select = True
        #                         matrix_final = obj.matrix_world @ poseBone.matrix
        #                         if not isChildLock:
        #                             bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='DISABLE')
        #                             poseBone.matrix_world = matrix_final
        #                         else:
        #                             bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='ENABLE')
        #                             poseBone.matrix_world = matrix_final

        if obj is not None :
            if obj.type == 'ARMATURE':
                if selected_bones is None:
                    for poseBone in obj.pose.bones:
                        bpy.ops.pose.select_all(action='DESELECT')
                        poseBone.bone.select = True
                        
                        matrix_final = obj.matrix_world @ poseBone.matrix
                        if not isChildLock:
                            self.report({'INFO'}, 'Bone Rotations Locked!')
                            bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='DISABLE')
                            poseBone.matrix = matrix_final
                        else:
                            self.report({'INFO'}, 'Bone Rotations Unlocked!')
                            bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='ENABLE')
                            poseBone.matrix = matrix_final
                else:
                    child_bones = []
                    for SelectedPoseBone in selected_bones:
                        for poseBone in obj.pose.bones:
                            if poseBone.parent ==  SelectedPoseBone:
                                child_bones.append(poseBone)
                    for c in child_bones:
                        bpy.ops.pose.select_all(action='DESELECT')
                        c.bone.select = True
                        # matrix_final = obj.matrix_world @ c.matrix
                        world_final = obj.convert_space(pose_bone=c, 
                                            matrix=c.matrix, 
                                            from_space='POSE', 
                                            to_space='WORLD')
                        if not isChildLock:
                            self.report({'INFO'}, 'Bone Rotations Locked!')
                            bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='DISABLE')
                            local_matrix = obj.convert_space(pose_bone=c, 
                                            matrix=world_final, 
                                            from_space='WORLD', 
                                            to_space='POSE')
                            c.matrix = local_matrix
                        else:
                            self.report({'INFO'}, 'Bone Rotations Unlocked!')
                            bpy.ops.wm.context_collection_boolean_set(data_path_iter="selected_pose_bones", data_path_item="bone.use_inherit_rotation", type='ENABLE')
                            # c.matrix = matrix_final
                            local_matrix = obj.convert_space(pose_bone=c, 
                                            matrix=world_final, 
                                            from_space='WORLD', 
                                            to_space='POSE')
                            c.matrix = local_matrix

                if selected_bones is not None:
                    bpy.ops.pose.select_all(action='DESELECT')
                    for b in selected_bones:
                        b.bone.select = True


            isChildLock = not isChildLock

        return {'FINISHED'}





class OBJECT_OT_add_inkbot(Operator, AddObjectHelper):
    """Create a new InkBot Object"""
    bl_idname = "mesh.spiraloid_add_inkbot"
    bl_label = "添加墨线机器人（Inkbot）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "inkbot_mesh.blend", False)
        return {'FINISHED'}



class OBJECT_OT_3d_comic_add_dog(Operator, AddObjectHelper):
    """Create Random Object"""
    bl_idname = "mesh.add_random_dog"
    bl_label = "添加小狗（Dog）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        load_resource(self, context, "robopup.000.blend", True)

        # aim at viewport camera.
        objects = bpy.context.selected_objects
        _b52_snap_selected_to_cursor(bpy.context, use_offset=False)
        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                M = v.spaces[0].region_3d.view_matrix
                view_position = camera_position(M)
        target = bpy.data.objects.new("Empty", None)
        bpy.context.scene.collection.objects.link(target)
        target.location = view_position
        bpy.ops.object.select_all(action='DESELECT')
        objects[0].select_set(state=True)
        bpy.context.view_layer.objects.active = objects[0]
        c = None
        for con in objects[0].constraints:
            if con.type == 'TRACK_TO':
                c = con
                break
        if c is None:
            c = objects[0].constraints.new(type='TRACK_TO')
        c.target = bpy.data.objects[target.name]
        c.track_axis = 'TRACK_NEGATIVE_Y'
        c.up_axis = 'UP_Z'
        bpy.ops.object.visual_transform_apply()
        objects[0].constraints.remove(c)
        bpy.context.object.rotation_euler[0] = 0
        bpy.context.object.rotation_euler[1] = 0
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(state=True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.delete() 
        bpy.ops.object.select_all(action='DESELECT')
        objects[0].select_set(state=True)
        bpy.context.view_layer.objects.active = objects[0]

        return {'FINISHED'}





class OBJECT_OT_add_inkbot_puppet(Operator, AddObjectHelper):
    """Create a new InkBot Object"""
    bl_idname = "mesh.spiraloid_add_inkbot_puppet"
    bl_label = "添加墨线机器人（绑定）（Inkbot Puppet）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "inkbot_puppet.blend", False)
        return {'FINISHED'}

def camera_position(matrix):
    t= (matrix[0][3],matrix[1][3],matrix[2][3])
    r=((matrix[0][0],matrix[0][1],matrix[0][2]),
        (matrix[1][0],matrix[1][1],matrix[1][2]),
        (matrix[2][0],matrix[2][1],matrix[2][2]))

    rp=((-r[0][0],-r[1][0],-r[2][0]),
        (-r[0][1],-r[1][1],-r[2][1]),
        (-r[0][2],-r[1][2],-r[2][2]))

    output=(rp[0][0]*t[0]+rp[0][1]*t[1]+rp[0][2]*t[2],
            rp[1][0]*t[0]+rp[1][1]*t[1]+rp[1][2]*t[2],
            rp[2][0]*t[0]+rp[2][1]*t[1]+rp[2][2]*t[2])
    return output

class OBJECT_OT_add_inkbot_shuffle(Operator, AddObjectHelper):
    """Create a new InkBot Object"""
    bl_idname = "mesh.spiraloid_add_inkbot_shuffle"
    bl_label = "添加墨线机器人（变体）（Inkbot）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        load_resource(self, context, "inkbot.000.blend", True)

        # aim at viewport camera.
        objects = bpy.context.selected_objects
        _b52_snap_selected_to_cursor(bpy.context, use_offset=False)
        for v in bpy.context.window.screen.areas:
            if v.type=='VIEW_3D':
                M = v.spaces[0].region_3d.view_matrix
                view_position = camera_position(M)
        target = bpy.data.objects.new("Empty", None)
        bpy.context.scene.collection.objects.link(target)
        target.location = view_position
        bpy.ops.object.select_all(action='DESELECT')
        objects[0].select_set(state=True)
        bpy.context.view_layer.objects.active = objects[0]
        c = None
        for con in objects[0].constraints:
            if con.type == 'TRACK_TO':
                c = con
                break
        if c is None:
            c = objects[0].constraints.new(type='TRACK_TO')
        c.target = bpy.data.objects[target.name]
        c.track_axis = 'TRACK_NEGATIVE_Y'
        c.up_axis = 'UP_Z'
        bpy.ops.object.visual_transform_apply()
        objects[0].constraints.remove(c)
        bpy.context.object.rotation_euler[0] = 0
        bpy.context.object.rotation_euler[1] = 0
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(state=True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.delete() 
        bpy.ops.object.select_all(action='DESELECT')
        objects[0].select_set(state=True)
        bpy.context.view_layer.objects.active = objects[0]

        return {'FINISHED'}


class OBJECT_OT_add_omnibot_shared(Operator, AddObjectHelper):
    """Create a new InkBot Object"""
    bl_idname = "mesh.spiraloid_add_omnibot_shared"
    bl_label = "添加全能机器人（共享）（Omnibot）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        load_shared_resource(self, context, "omnibot.blend", False)

        # # aim at viewport camera.
        # objects = bpy.context.selected_objects
        # legacy cursor snap kept behind compatibility wrapper
        # for v in bpy.context.window.screen.areas:
        #     if v.type=='VIEW_3D':
        #         M = v.spaces[0].region_3d.view_matrix
        #         view_position = camera_position(M)
        # target = bpy.data.objects.new("Empty", None)
        # bpy.context.scene.collection.objects.link(target)
        # target.location = view_position
        # bpy.ops.object.select_all(action='DESELECT')
        # objects[0].select_set(state=True)
        # bpy.context.view_layer.objects.active = objects[0]
        # bpy.ops.object.constraint_add(type='TRACK_TO')
        # c = bpy.context.object.constraints["Track To"]
        # c.target = bpy.data.objects[target.name]
        # c.track_axis = 'TRACK_NEGATIVE_Y'
        # c.up_axis = 'UP_Z'
        # bpy.ops.object.visual_transform_apply()
        # objects[0].constraints.remove(c)
        # bpy.context.object.rotation_euler[0] = 0
        # bpy.context.object.rotation_euler[1] = 0
        # bpy.ops.object.select_all(action='DESELECT')
        # target.select_set(state=True)
        # bpy.context.view_layer.objects.active = target
        # bpy.ops.object.delete() 
        # bpy.ops.object.select_all(action='DESELECT')
        # objects[0].select_set(state=True)
        # bpy.context.view_layer.objects.active = objects[0]

        return {'FINISHED'}



class OBJECT_OT_add_bonus(Operator, AddObjectHelper):
    """Add Bonus for Panel"""
    bl_idname = "mesh.spiraloid_add_bonus"
    bl_label = "添加奖励物（Bonus）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        numString = getCurrentPanelNumber(False)
        paddedNumString = "%04d" % numString
        bonus_name = "Bonus_" + paddedNumString
        load_resource(self, context, "panel_bonus.blend", False)


        # aim at viewport camera.
        objects = bpy.context.selected_objects
        bonusObject = objects[0]
        bonusObject.name = bonus_name
        _b52_snap_selected_to_cursor(bpy.context, use_offset=False)
        active_camera = bpy.context.scene.camera
        bpy.ops.object.select_all(action='DESELECT')
        bonusObject.select_set(state=True)
        bpy.context.view_layer.objects.active = bonusObject
        c = None
        for con in bonusObject.constraints:
            if con.type == 'TRACK_TO':
                c = con
                break
        if c is None:
            c = bonusObject.constraints.new(type='TRACK_TO')
        c.target = bpy.data.objects[active_camera.name]
        c.track_axis = 'TRACK_NEGATIVE_Y'
        c.up_axis = 'UP_Z'
        bpy.ops.object.select_all(action='DESELECT')
        bonusObject.select_set(state=True)
        bpy.context.view_layer.objects.active = bonusObject

        return {'FINISHED'}

class OBJECT_OT_add_bonus_shared(Operator, AddObjectHelper):
    """Add Bonus for Panel"""
    bl_idname = "mesh.spiraloid_add_bonus_shared"
    bl_label = "添加奖励物（共享）（Bonus）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        numString = getCurrentPanelNumber(False)
        paddedNumString = "%04d" % numString
        bonus_name = "Bonus_" + paddedNumString
        load_shared_resource(self, context, "panel_bonus.blend", False)


        # aim at viewport camera.
        objects = bpy.context.selected_objects
        bonusObject = objects[0]
        bonusObject.name = bonus_name
        _b52_snap_selected_to_cursor(bpy.context, use_offset=False)
        active_camera = bpy.context.scene.camera
        bpy.ops.object.select_all(action='DESELECT')
        bonusObject.select_set(state=True)
        bpy.context.view_layer.objects.active = bonusObject
        c = None
        for con in bonusObject.constraints:
            if con.type == 'TRACK_TO':
                c = con
                break
        if c is None:
            c = bonusObject.constraints.new(type='TRACK_TO')
        c.target = bpy.data.objects[active_camera.name]
        c.track_axis = 'TRACK_NEGATIVE_Y'
        c.up_axis = 'UP_Z'
        bpy.ops.object.select_all(action='DESELECT')
        bonusObject.select_set(state=True)
        bpy.context.view_layer.objects.active = bonusObject

        return {'FINISHED'}

class OBJECT_OT_add_inksplat(Operator, AddObjectHelper):
    """Create a new inksplat Object"""
    bl_idname = "mesh.spiraloid_add_inksplat"
    bl_label = "添加墨点泼溅（Inksplat）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        load_resource(self, context, "inksplat.blend", False)
        return {'FINISHED'}

class OBJECT_OT_add_ground(Operator, AddObjectHelper):
    """Create a new exterior street Object"""
    bl_idname = "mesh.spiraloid_add_ground"
    bl_label = "添加地面（Ground）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        # export_collection = getCurrentExportCollection(self, context)
        # bpy.context.view_layer.active_layer_collection = export_collection

        # objects = bpy.context.selected_objects
        # if objects:
        #     bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        # load_resource(self, context, "ground_disc.blend", False)

        # imported_objects = bpy.context.selected_objects
        # if not export_collection:
        #     self.report({'WARNING'}, "Export Collection " + export_collection.name + "was not found in scene, skipping export of" + scene.name)
        # else:
        #     for obj in imported_objects:
        #         bpy.context.collection.objects.unlink(obj) 
        #         export_collection.objects.link(obj)

        load_resource(self, context, "ground_disc.blend", False)
        return {'FINISHED'}




class OBJECT_OT_add_speedlines(Operator, AddObjectHelper):
    """Create a new exterior street Object"""
    bl_idname = "mesh.spiraloid_add_speedlines"
    bl_label = "添加速度线（Speedlines）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "speedlines.blend", False)
        return {'FINISHED'}

class OBJECT_OT_add_speedlines_radial(Operator, AddObjectHelper):
    """Create a new exterior street Object"""
    bl_idname = "mesh.spiraloid_add_speedlines_radial"
    bl_label = "添加放射速度线（Speedlines Radial）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "speedlines_radial.blend", False)
        return {'FINISHED'}

class OBJECT_OT_add_speedlines_ground(Operator, AddObjectHelper):
    """Create a new exterior street Object"""
    bl_idname = "mesh.spiraloid_add_speedlines_ground"
    bl_label = "添加地面速度线（Speedlines Ground）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "speedlines_ground.blend", False)
        return {'FINISHED'}


class OBJECT_OT_add_ground_rocks(Operator, AddObjectHelper):
    """Drop rocks on the active object"""
    bl_idname = "mesh.spiraloid_add_ground_rocks"
    bl_label = "投放地面岩石（Drop Rocks）"
    bl_options = {'REGISTER', 'UNDO'}


    ##### POLL #####
    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) >= 1


    def execute(self, context):
        active_ground = bpy.context.view_layer.objects.active
        if active_ground:
            load_resource(self, context, "ground_rocks.blend", False)
            active_ground.select_set(state=True)
            bpy.context.view_layer.objects.active = active_ground
            drop_objects(self, context,  False, True)
            bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
            bpy.ops.object.join()
            bpy.context.selected_objects[0].name = "Dropped_Rocks"

        return {'FINISHED'}
       
class OBJECT_OT_add_sprite_card(Operator, AddObjectHelper):
    """Create a new animated Sprite Card Object"""
    bl_idname = "mesh.spiraloid_add_sprite_card"
    bl_label = "添加精灵卡（Sprite Card）"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        load_resource(self, context, "sprite_card.blend", False)
        return {'FINISHED'}




class BR_OT_spiraloid_automap(bpy.types.Operator):
    """Automatically UV unwrap selected objects"""
    bl_idname = "wm.spiraloid_automap"
    bl_label = "自动映射 UV（Automap）"
    bl_options = {'REGISTER', 'UNDO'}

    # @classmethod
    # def poll(cls, context):
    #     return True #context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        automap(bpy.context.selected_objects, 1)
        return {'FINISHED'}





class BR_OT_spiraloid_toggle_workmode(bpy.types.Operator):
    """Toggle Workmode"""
    bl_idname = "wm.spiraloid_toggle_workmode"
    bl_label = "Toggle Workmode"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True #context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        toggle_workmode(self, context, False)
        return {'FINISHED'}


class BR_OT_spiraloid_toggle_developer_mode(bpy.types.Operator):
    """Toggle developer mode"""
    bl_idname = "wm.spiraloid_toggle_developer_mode"
    bl_label = "切换开发者模式（Toggle Developer）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global developer_mode
        developer_mode = not developer_mode
        return {'FINISHED'}




#------------------------------------------------------

def populate_coll(scene):
    bpy.app.handlers.scene_update_pre.remove(populate_coll)
    scene.coll.clear()
    for identifier, name, description in enum_items:
        scene.coll.add().name = name

def menu_draw_bake(self, context):
    self.layout.operator("wm.spiraloid_save_check_bake_panel", 
        text="Bake Panel...")
    # Blender 5.2 fix: removed call to undefined bpy.ops.object.dialog_operator

def menu_draw_view(self, context):
    layout = self.layout
    layout.separator()
    self.layout.operator(BR_OT_spiraloid_toggle_workmode.bl_idname)

# ============================================================
# 17:28 基线 UI-A：导出网站 ▼ + 导出数字漫画 ▼ 双下拉子菜单
# ============================================================
class BR_OT_quick_export_holo(bpy.types.Operator):
    """快速导出当前画格 → HOLO 包（推荐）"""
    bl_idname  = "wm.spiraloid_quick_export_holo"
    bl_label   = "HOLO 包（推荐）"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            from .publisher import export_holo as _eh
            r = _eh(context)
            self.report({"INFO"}, "HOLO 包：" + str(r))
        except Exception as e:
            self.report({"WARNING"}, "HOLO 导出暂未完全实现（占位·不影响原版）：" + str(e))
        return {"FINISHED"}

class BR_OT_quick_export_mobile(bpy.types.Operator):
    """快速导出当前画格 → 手机版（Android / iOS PWA）"""
    bl_idname  = "wm.spiraloid_quick_export_mobile"
    bl_label   = "手机版（Android/iOS）"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            from .publisher import export_mobile as _em
            r = _em(context)
            self.report({"INFO"}, "手机版：" + str(r))
        except Exception as e:
            self.report({"WARNING"}, "手机版导出暂未完全实现（占位·不影响原版）：" + str(e))
        return {"FINISHED"}

class BR_OT_quick_export_vr(bpy.types.Operator):
    """快速导出当前画格 → VR 版（WebXR）"""
    bl_idname  = "wm.spiraloid_quick_export_vr"
    bl_label   = "VR 版（WebXR）"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            from .publisher import export_vr as _ev
            r = _ev(context)
            self.report({"INFO"}, "VR 版：" + str(r))
        except Exception as e:
            self.report({"WARNING"}, "VR 导出暂未完全实现（占位·不影响原版）：" + str(e))
        return {"FINISHED"}

class BR_MT_export_web_submenu(bpy.types.Menu):
    """导出网站 ▼（对接 Comic-books / jypding / 3dcomic.shop）"""
    bl_idname  = "BR_MT_export_web_submenu"
    bl_label   = "导出网站 ▼"
    def draw(self, context):
        print("[Quick Export Web Menu] draw 执行")
        layout = self.layout
        layout.operator(
            "wm.spiraloid_quicks_save_export_3d_comic_current",
            text="原版 HTML（兼容）",
            icon="FILE_TEXT",
        )

class BR_MT_export_digital_submenu(bpy.types.Menu):
    """导出数字漫画 ▼ → HOLO / 手机 / VR（新增格式，不破坏原流程）"""
    bl_idname  = "BR_MT_export_digital_submenu"
    bl_label   = "导出数字漫画 ▼"
    def draw(self, context):
        print("[Quick Export Digital Menu] draw 执行")
        layout = self.layout
        try:
            layout.operator(BR_OT_quick_export_holo.bl_idname,     icon="FILE_BLANK")
        except Exception:
            layout.operator("wm.spiraloid_quick_export_holo",     icon="FILE_BLANK")
        try:
            layout.operator(BR_OT_quick_export_mobile.bl_idname,  icon="IMGDISPLAY")
        except Exception:
            layout.operator("wm.spiraloid_quick_export_mobile",  icon="IMGDISPLAY")
        try:
            layout.operator(BR_OT_quick_export_vr.bl_idname,      icon="ORIENTATION_VIEW")
        except Exception:
            layout.operator("wm.spiraloid_quick_export_vr",      icon="ORIENTATION_VIEW")

def _quick_submenu_register():
    """兜底注册：防止热更后类找不到（重复注册自动跳过）"""
    for c in (BR_OT_quick_export_holo, BR_OT_quick_export_mobile, BR_OT_quick_export_vr,
              BR_MT_export_web_submenu, BR_MT_export_digital_submenu):
        try:
            if not hasattr(bpy.types, c.__name__):
                bpy.utils.register_class(c)
        except Exception:
            pass

# ============================================================
# 最终连环画结构【右侧顶面板】：替代原版 场景·分镜导航（BR_MT_3d_comic_panels）
# 内容 A 区：原左上【新建漫画工程】框内全部 → 迁移成大按钮
# 内容 B 区：原场景·分镜导航 全部功能（全中文 UI 显示；算子 ID / bl_idname 仍英文原版）
# ============================================================
# ============================================================
# 右侧顶 极简 新建漫画工程 面板（v3 极简 · 不塞分镜导航 · 避免排序到中心）
# 分镜首末/前后/新建拆分复制黑屏删除 → 全部由 原版【3D 漫画：场景·分镜导航】面板承载（用户要"下面首末图形按钮都有"）
# ============================================================
class SCENE_PT_3d_comic_panel_NEW_TOP(bpy.types.Panel):
    """【极简】右侧顶：新建漫画工程（原左上入口迁移到这里；不包含分镜导航，避免 Blender 排序错到中心）"""
    bl_label   = "新建漫画工程"
    bl_idname  = "SCENE_PT_3d_comic_panel_NEW_TOP"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "3D Comics"
    bl_order    = 0  # Blender 2.9x+/5.x 支持；强制让本面板在 "3D Comics" 分类【排第一个】→ 顶位置（不跑到中心）
    @classmethod
    def poll(cls, context):
        return True  # 常显（未初始化时也能看到【新建漫画工程】按钮，对应原左上入口位置）
    def draw(self, context):
        layout = self.layout
        # ==== 只 1 个【新建漫画工程】大按钮（用户原话："只需在右顶添加新建漫画工程按钮"）====
        box = layout.box()
        box.label(text="新建项目", icon="FILE_NEW")
        
        # 新建漫画工程 (Cinematic)
        row = box.row()
        row.scale_y = 1.5
        op = row.operator("comic.new_comic_project", text="新建漫画工程...", icon="FILE_NEW")
        op.project_mode = "cinematic"
        
        # 新建语音书 (Voice)
        row = box.row()
        row.scale_y = 1.5
        op_voice = row.operator("comic.new_comic_project", text="新建语音书...", icon='SOUND')
        op_voice.project_mode = "voice"

        # ==== 小按钮：打开漫画导出目录（辅助，尺寸极小，不影响排序）====
        row2 = box.row(align=True)
        try:
            row2.operator("view3d.spiraloid_explore_3d_comic",
                          text="打开导出目录", icon="FILE_FOLDER")
        except Exception:
            row2.label(text="打开目录算子未注册", icon="INFO")

class BR_MT_3d_comic_menu(bpy.types.Menu):
    bl_idname = "BR_MT_3d_comic_menu"
    bl_label = "3D 连环画"

    def draw(self, context):
        global developer_mode
        layout = self.layout
        if developer_mode:
            layout.menu(BR_MT_3d_comic_submenu_panels.bl_idname, icon="VIEW_ORTHO")
            layout.menu(BR_MT_3d_comic_submenu_letters.bl_idname, icon="INFO")
            layout.menu(BR_MT_3d_comic_submenu_assets.bl_idname, icon="FILE_3D")
            layout.menu(BR_MT_3d_comic_submenu_disk_assets.bl_idname, icon='FILE_3D')
        if developer_mode:
            layout.menu(BR_MT_3d_comic_submenu_assets_shared.bl_idname, icon="LINKED")

        if developer_mode:
            layout.menu(BR_MT_3d_comic_submenu_lighting.bl_idname, icon="COLORSET_13_VEC")
            layout.separator()
        layout.menu(BR_MT_3d_comic_submenu_utilities.bl_idname, icon="PREFERENCES")
        layout.separator()
        if developer_mode:
            layout.operator("view3d.spiraloid_export_3d_comic_all", icon="NODE_COMPOSITING")
            layout.menu(BR_MT_export_web_submenu.bl_idname,     text="导出网站 ▼",     icon="WORLD")
            layout.menu(BR_MT_export_digital_submenu.bl_idname, text="导出数字漫画 ▼", icon="OUTLINER_OB_ARMATURE")
            layout.separator()
        
        row = layout.row()
        row.scale_y = 2.0
        row.operator("wm.spiraloid_quicks_save_export_3d_comic_current", icon="SOLO_ON")
        row.operator("view3d.spiraloid_read_3d_comic", icon="HIDE_OFF")

try:
    material_swatch_object = getCurrentMaterialSwatch()
except:
    pass


class PanelSettings(PropertyGroup):
    s3dc_toonfill_use_global :  bpy.props.BoolProperty(
                    name='s3dc_toonfill_use_global',
                    default=True,
                    description='Use global materials for toonshading')

    s3dc_toonfill_use_global_ink :  bpy.props.BoolProperty(
                    name='s3dc_toonfill_use_global_ink',
                    default=False,
                    description='Use global ink texture for ink wobble')

    s3dc_dynamic_shadows :  bpy.props.BoolProperty(
                    name='s3dc_dynamic_shadows',
                    default=False,
                    description='Use per frame shadowmaps in browser (warning perf cost)') 

    s3dc_apply_armatures :  bpy.props.BoolProperty(
                    name='s3dc_apply_armatures',
                    default=True,
                    description='Apply Armatures and Shape Keys to all meshes') 


    s3dc_animation_mode : bpy.props.EnumProperty(
                    name='s3dc_animation_mode',
                    description='should time scroll or loop',
                    items={
                        ("Scroll", "Scroll", "Scroll", 0),
                        ("Loop", "Loop", "Loop", 1)
                        },
                    default='Scroll')

    s3dc_toonfill_mode : bpy.props.EnumProperty(
                    name='s3dc_toonfill_mode',
                    description='How to apply toonfill.',
                    items={
                        ("Visible", "Visible", "Visible", 0),
                        ("Selected", "Selected", "Selected", 1),
                        ("Lighting", "Lighting", "Lighting", 2),
                        ("World", "World", "World", 3)
                        },
                    default='Visible')

    s3dc_toonfill_type : bpy.props.EnumProperty(
                    name='s3dc_toonfill_type',
                    description='type of toonfill.',
                    items={
                        ("ink_toon", "ink_toon", "ink_toon", 0),
                        ("toon", "toon", "toon", 1),
                        ("ink", "ink", "ink", 2),
                        ("whiteout", "whiteout", "whiteout", 3),
                        ("blackout", "blackout", "blackout", 4),
                        ("clear", "clear", "clear", 5)
                        },
                    default='ink_toon')

    s3dc_language : bpy.props.EnumProperty(
                    name="Language", 
                    description="The currently active language", 
                    items={
                        ("english", "english", "english", 0),
                        ("spanish", "spanish", "spanish", 1),
                        ("japanese", "japanese", "japanese", 2),
                        ("korean", "korean", "korean", 3),
                        ("german", "german", "german", 4),
                        ("french", "french", "french", 5),
                        ("dutch", "dutch", "dutch", 5)
                        },
                    default=0,
                    update = set_active_language)

    s3dc_camera_strategy : bpy.props.EnumProperty(
        name="Camera Move", 
        description="Type of camera movement for new panels", 
        items={
            ("camera_random", "Random","Random", 0),
            ("camera_slide_up", "Slide Up","SlideUp", 1),
            ("camera_slide_down","Slide Down", "SlideDown", 2),
            ("camera_truck_in", "Truck In","TruckIn", 3),
            ("camera_truck_out", "Truck Out","TruckOut", 4),
            ("camera_pan_left", "Pan Left","PanLeft", 5),
            ("camera_pan_right", "Pan Right","PanRight", 6),
            ("turntable_cw", "Turntable CW","RandomCw", 7),
            ("turntable_ccw", "Turntable CCW","RandomCCW", 8),
            ("Static", "Static","Static", 9),
            },
        default=0)

    s3dc_wordballoon_anim_strategy : bpy.props.EnumProperty(
        name="Wordballoon Anim Strategy", 
        description="Type of movement for new Letters", 
        items={
            ("bounce_in", "Bounce In","BounceIn", 0),
            ("Static", "Static","Static", 1),
            ("slide_up", "Slide Up","SlideUp", 2),
            ("slide_down","Slide Down", "SlideDown", 3),
            ("pan_left", "Pan Left","PanLeft", 4),
            ("pan_right", "Pan Right","PanRight", 5),
            },
        default=3)

    s3dc_wordballoon_count :  bpy.props.IntProperty(
        name='s3dc_wordballoon_count',
        default=1,
        description='Number of Wordballoons to add')

    s3dc_shared_actor_blend_filenames : bpy.props.EnumProperty(
        name="Actors",
        description="Shared Actor Blendfilenames",
        # items argument required to initialize, just filled with empty values
        items = getSharedActorBlendFilenames,
        default=0,
        update = swapSelectSharedActorUpdate
    )

class BR_MT_3d_comic_panels(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "3D 漫画：画格场景（原版）"
    bl_idname = "SCENE_PT_3d_comic_panelss"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "3D Comics"

    @classmethod 
    def poll(self, context):
        backstage_collection = getCurrentBackstageCollection()
        return backstage_collection
    def draw(self, context):
        global material_swatch_object
        layout = self.layout
        scene = context.scene
        material_swatch_object = getCurrentMaterialSwatch()
        panel_settings = scene.panel_settings

        if material_swatch_object:
            layout.label(text="分镜导航：")
            layout.separator()
            row = layout.row()
            row.operator("screen.spiraloid_3d_comic_first_panel", icon="TRIA_UP")
            row.operator("screen.spiraloid_3d_comic_previous_panel", icon="TRIA_LEFT", text="")
            row.operator("screen.spiraloid_3d_comic_next_panel", icon="TRIA_RIGHT", text="")
            row.operator("screen.spiraloid_3d_comic_last_panel", icon="TRIA_DOWN")
            layout.separator()

            row = layout.row()
            row.operator("screen.spiraloid_3d_comic_reorder_scene_earlier", icon="REW", text="前移场景")
            row.operator("screen.spiraloid_3d_comic_reorder_scene_later", icon="FF", text="后移场景")

            layout.separator()


            layout.operator("screen.spiraloid_3d_comic_new_panel", text="新建分镜", icon="FILE_BLANK")
            layout.operator("screen.spiraloid_3d_comic_new_panel_split", text="拆分分镜…", icon="MOD_TRIANGULATE")
            layout.operator("view3d.spiraloid_3d_comic_clone_panel", text="复制分镜", icon="DUPLICATE")
            layout.operator("view3d.spiraloid_3d_comic_blank_panel", text="插入黑屏", icon="COLORSET_16_VEC")
            layout.separator()
            layout.operator("view3d.spiraloid_3d_comic_delete_panel", text="删除分镜", icon="TRASH")


            layout.separator()

        else:
            self.layout.label(text= 'Comic Panel Not Found')



class BR_MT_3d_comic_panel_color(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "3D 漫画：色彩（原版）"
    bl_idname = "SCENE_PT_3d_comic_panel_color"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "3D Comics"
    # bl_space_type = 'PROPERTIES'
    # bl_context = "scene"
    # config: bpy.props.PointerProperty(type=PanelSettings)

    @classmethod 
    def poll(self, context):
        backstage_collection = getCurrentBackstageCollection()
        return backstage_collection


    def draw(self, context):
        global material_swatch_object
        layout = self.layout
        scene = context.scene
        material_swatch_object = getCurrentMaterialSwatch()
        panel_material_swatch = getMaterialSwatch(False)

        panel_settings = scene.panel_settings
        backstage_collection_name = getCurrentBackstageCollectionName()
        if "Backstage.Global" not in backstage_collection_name:
            if material_swatch_object:
                
                layout.prop(panel_settings, "s3dc_toonfill_use_global", text="使用全局分镜颜色")

                # Create a simple row.
                layout.label(text="天空：")
                row = layout.row()
                row.prop(material_swatch_object, '["Sky"]', text="")



                # Create an row where the buttons are aligned to each other.
                # Create two columns, by using a split layout.
                split = layout.split()
                # First column
                col = split.column()
                col.prop(material_swatch_object, '["ToonWhite"]', text="卡通亮部")

                # Second column, aligned
                col = split.column(align=True)
                col.prop(material_swatch_object, '["ToonBlack"]', text="卡通阴影")


                split = layout.split()
                col = split.column()
                col.prop(material_swatch_object, '["OutlineNoShadowDark"]', text="墨线·内侧")
                col = split.column(align=True)
                col.prop(material_swatch_object, '["OutlineNoShadowLight"]', text="墨线·外侧")

                layout.separator()
                layout.prop(panel_settings, "s3dc_toonfill_use_global_ink", text="使用全局墨线粗细")
                layout.prop(panel_material_swatch, '["OutlineThickness"]', text="墨线粗细")
                layout.prop(panel_material_swatch, '["OutlineWobble"]', text="墨线抖动")
                layout.prop(panel_material_swatch, '["OutlineSmooth"]', text="墨线平滑度")
                layout.separator()
                        
                layout.label(text="动作：")
                layout.use_property_split = True
                layout.prop(panel_settings, "s3dc_toonfill_mode", text="填色模式")
                layout.prop(panel_settings, "s3dc_toonfill_type", text="填色类型")

                row = layout.row()
                row.scale_y = 2.0
                row.operator("wm.spiraloid_3d_comic_toonfill", text="一键填色")
                # layout.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="Clear")
                layout.separator()

            else:
                self.layout.label(text= '未找到漫画分镜')

class BR_MT_3d_comic_panel_letters(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "3D 漫画：文字·气泡（原版）"
    bl_idname = "SCENE_PT_3d_comic_letters"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "3D Comics"

    @classmethod 
    def poll(self, context):
        backstage_collection = getCurrentBackstageCollection()
        return backstage_collection


    def draw(self, context):
        backstage_collection_name = getCurrentBackstageCollectionName()
        if "Backstage.Global" not in backstage_collection_name:
            global material_swatch_object
            layout = self.layout
            scene = context.scene
            material_swatch_object = getCurrentMaterialSwatch()
            panel_settings = scene.panel_settings

            if material_swatch_object:
                layout = self.layout
                layout.use_property_split = True
                layout.prop(panel_settings, "s3dc_language", text="语言")
                layout.separator()

                layout.operator("view3d.spiraloid_3d_comic_add_letter_wordballoon", icon="INFO")
                layout.operator("view3d.spiraloid_3d_comic_add_letter_caption", icon="INFO")
                layout.operator("view3d.spiraloid_3d_comic_add_letter_sfx", icon="INFO")
                layout.operator("view3d.spiraloid_3d_comic_add_letter_border", icon="SNAP_FACE")
                layout.separator()

                if developer_mode:
                    layout.use_property_split = True
                    layout.prop(panel_settings, "s3dc_wordballoon_count", text="气泡数量")
                    layout.prop(panel_settings, "s3dc_wordballoon_anim_strategy", text="动画策略")
                    layout.separator()

            else:
                self.layout.label(text= '未找到文字·气泡')




class BR_MT_3d_comic_panel_contents(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_label = "3D 漫画：目录（原版）"
    bl_idname = "SCENE_PT_3d_comic_panel_contents"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "3D Comics"


    # @classmethod 
    # def poll(self, context):
    #     backstage_collection_name = getCurrentBackstageCollectionName()
    #     return backstage_collection_name


    @classmethod 
    def poll(self, context):
        # return developer_mode
        backstage_collection = getCurrentBackstageCollection()
        return backstage_collection

    def draw(self, context):
        backstage_collection_name = getCurrentBackstageCollectionName()
        if "Backstage.Global" not in backstage_collection_name:
            global material_swatch_object
            layout = self.layout
            scene = context.scene
            material_swatch_object = getCurrentMaterialSwatch()
            panel_settings = scene.panel_settings

            layout.prop(panel_settings, "s3dc_dynamic_shadows", text="动态阴影")
            layout.prop(panel_settings, "s3dc_apply_armatures", text="应用骨骼·形态键")
            layout.prop(panel_settings, "s3dc_animation_mode", text="时间轴模式")
            if material_swatch_object:
                layout.label(text="洗牌：")
                row = layout.row()
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="<")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="全部")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text=">")
                row = layout.row()
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="<")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="位置")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text=">")
                row = layout.row()
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="<")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="角色库")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text=">")
                row = layout.row()
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="<")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="文字·气泡")
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text=">")

                layout.label(text="角色：")
                row = layout.row()
                row.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="洗牌角色")
                row = layout.row(translate=True)
                # row.use_property_split = False
                row.prop(panel_settings, "s3dc_shared_actor_blend_filenames", text="交换所选")
                row = layout.row()
                row.operator("view3d.spiraloid_explore_3d_comic", text="编辑所选角色", icon="FILE_FOLDER")


            else:
                self.layout.label(text= '未找到漫画分镜')




class BR_MT_3d_comic_submenu_panels(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_panels'
    bl_label = '分镜（Panels）'

    def draw(self, context):
        layout = self.layout
        layout.operator("view3d.spiraloid_3d_comic_inject_panel", icon="IMPORT", text="导入场景")
        layout.operator("view3d.spiraloid_3d_comic_extract_panel", icon="EXPORT", text="提取场景")

class BR_MT_3d_comic_submenu_letters(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_letters'
    bl_label = '文字·气泡（Letters）'
    

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        panel_settings = scene.panel_settings

        layout.operator("view3d.spiraloid_3d_comic_add_letter_wordballoon", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_wordballoon_double", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_wordballoon_triple", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_wordballoon_quadruple", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_caption", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_sfx", icon="INFO")
        layout.operator("view3d.spiraloid_3d_comic_add_letter_border", icon="SNAP_FACE")

        layout.separator()
        layout.prop(panel_settings, "s3dc_language", text="Active Language")






# def add_items_from_collection_callback(self, context):
#     global working_folder
#     scene = context.scene
#     path =  working_folder + "\\shared\\"
#     shared_disk_assets = []
#     if path.is_file():
#         with bpy.data.libraries.load(str(path)) as (data_from, data_to):
#             object_names = [ob for ob in data_from.objects]
#         for object_name in object_names:
#             shared_disk_assets.append((object_name, object_name, ""))
#     else:
#         shared_disk_assets.append(("MISSING","Library is Missing",""))
#     return shared_disk_assets

# class MyEnumItems(bpy.types.PropertyGroup):
#     shared_disk_assets : bpy.props.EnumProperty(
#         name="shared_disk_assets",
#         description="disk_assets",
#         # items argument required to initialize, just filled with empty values
#         items = add_items_from_collection_callback,
#     )

class BR_MT_3d_comic_submenu_disk_assets(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_disk_assets'
    bl_label = '磁盘资源（Disk Assets）'

    def draw(self, context):
        layout = self.layout
        chosen_disk_asset = bpy.context.scene.shared_disk_assets
        layout.operator(OBJECT_OT_3d_comic_add_dog.bl_idname, icon='HEART')
        layout.prop(chosen_disk_asset, "0")
        layout.operator(OBJECT_OT_3d_comic_add_dog.bl_idname, icon='HEART')


# class MY_OT_add_disk_item(bpy.types.Operator):
#     ''' add item to bpy.context.scene.shared_disk_assets '''
#     bl_label = "Workshop Empty"
#     bl_idname = "wm.add_item"

#     def execute(self, context):
#         current_scene = bpy.context.scene
#         disk_asset_file = current_scene["SharedDiskAsset"]["shared_disk_assets"]
#         print("----------------------" + disk_asset_file + "------------------------------------")
#         return {'FINISHED'}

# preview_collections = {}

# def enum_previews_from_directory_items(self, context):

#     category = context.scene.my_tool.cat
    
#     #Extensions
#     extensions = ('.jpeg', '.jpg', '.png')

#     # Icons Directory    
#     # directory = bpy.utils.user_resource('SCRIPTS', "addons\\Icons\\")
#     global working_folder
#     directory =  working_folder + "\\shared\\"

#     enum_items = []

#     if context is None:
#         return enum_items

#     pcoll = preview_collections["main"]

#     if directory == pcoll.my_previews_dir:
#         return pcoll.my_previews

#     if directory and os.path.exists(directory):
#         # Scan the directory for png files
#         image_paths = []
#         for fn in os.listdir(directory):
#             if fn.lower().endswith(extensions):
#                 image_paths.append(fn)

#         for i, name in enumerate(image_paths):
#             # generates a thumbnail preview for a file.
#             filepath = os.path.join(directory, name)
#             icon = pcoll.get(name)
#             if filepath in pcoll:
#                 enum_items.append((name, name, "", pcoll[filepath].icon_id, i))
#             else:
#                 thumb = pcoll.load(filepath, filepath, 'IMAGE')
#                 enum_items.append((name, name, "", thumb.icon_id, i))

#     pcoll.my_previews = enum_items
#     pcoll.my_previews_dir = directory
#     return pcoll.my_previews


def update_selected(self, context):
    # get_shared_disk_assets(self, context)
    print("loading item : ", context.scene.shared_disk_assets)
    return None

def get_shared_disk_assets(self, context):
    global working_folder
    scene = context.scene
    path =  working_folder + "\\shared\\"
    disk_assets = []
    if context is None:
        return disk_assets
    if path and os.path.exists(path):
        print(path + "--------------------------")
        for fn in os.listdir(path):
            if fn.lower().endswith(".blend"):
                disk_assets.append(fn)
    return disk_assets



class SharedDiskAsset(bpy.types.PropertyGroup):
    # disk_assets = [
    #     ("shared_disk_assets", "shared_disk_assets", '', 0),
    # ]
    bpy.types.Scene.shared_disk_assets = bpy.props.EnumProperty(
        name = "shared_disk_assets",
        items = get_shared_disk_assets,
        description="Files in Shared Folder",
        default=0,
        update= update_selected,
    )

class BR_MT_3d_comic_submenu_disk_assets(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_disk_assets'
    bl_label = '磁盘资源（Disk Assets）'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        shared_disk_assets = scene.shared_disk_assets
        layout.operator(OBJECT_OT_3d_comic_add_dog.bl_idname, icon='HEART')
        layout.prop(shared_disk_assets, "disk_asset", text="Shared Asset")



class BR_MT_3d_comic_submenu_assets(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_assets'
    bl_label = '资源（Assets）'

    def draw(self, context):
        layout = self.layout
        layout.operator(OBJECT_OT_3d_comic_add_dog.bl_idname, icon='HEART')
        layout.separator()
        layout.operator(OBJECT_OT_add_bonus.bl_idname, icon='KEYTYPE_BREAKDOWN_VEC')
        layout.separator()
        layout.operator(OBJECT_OT_add_inkbot_shuffle.bl_idname, icon='FILE_3D')
        # layout.operator(OBJECT_OT_add_inkbot.bl_idname, icon='FILE_3D')
        # layout.operator(OBJECT_OT_add_inkbot_puppet.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_ground.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_speedlines.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_speedlines_radial.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_speedlines_ground.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_inksplat.bl_idname, icon='FILE_3D')
        layout.separator()
        layout.operator(OBJECT_OT_add_ground_rocks.bl_idname, icon='OUTLINER_DATA_POINTCLOUD')
        layout.operator(OBJECT_OT_add_sprite_card.bl_idname, icon='OUTLINER_DATA_POINTCLOUD')
        layout.operator("view3d.spiraloid_3d_comic_workshop")


class BR_MT_3d_comic_submenu_assets_shared(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_assets_shared'
    bl_label = '共享资源（Assets Shared）'

    def draw(self, context):
        global developer_mode
        layout = self.layout
        layout.operator(OBJECT_OT_add_bonus_shared.bl_idname, icon='KEYTYPE_BREAKDOWN_VEC')
        layout.separator()
        layout.operator(OBJECT_OT_add_omnibot_shared.bl_idname, icon='FILE_3D')
        layout.operator(OBJECT_OT_add_ground.bl_idname, icon='FILE_3D')
        if developer_mode:
            layout.operator("view3d.spiraloid_3d_comic_workshop")



class BR_MT_3d_comic_submenu_key_camera(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_key_camera'
    bl_label = '相机策略（Key Camera）'

    def draw(self, context):
        layout = self.layout
        layout.operator("wm.spiraloid_3d_comic_key_camera_random", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_slide_up", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_slide_down", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_pan_left", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_pan_right", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_truck_in", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_camera_truck_out", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_world_spin_CW", icon="CON_CAMERASOLVER")
        layout.operator("wm.spiraloid_3d_comic_key_world_spin_CCW", icon="CON_CAMERASOLVER")



class BR_MT_3d_comic_submenu_utilities(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_utilities'
    bl_label = '工具（Utilities）'

    def draw(self, context):
        global developer_mode

        layout = self.layout
        layout.operator("wm.spiraloid_toggle_workmode", icon="SEQ_PREVIEW")
        layout.separator()
        layout.operator(BR_OT_bake_collection.bl_idname, icon="TEXTURE_DATA")
        layout.operator("wm.spiraloid_automap", icon="UV_VERTEXSEL")
        layout.separator()
        layout.operator("wm.spiraloid_subcollection_cycler", icon="MATCLOTH")
        if developer_mode:
            layout.operator("wm.spiraloid_subcollection_cycler_exportable", icon="MATCLOTH")
        if operator_exists("BakeMeshFlipbook"):
            layout.operator("view3d.bake_mesh_flipbook", icon="MATCLOTH")
        if developer_mode:
            if operator_exists("KeyCollectionTreadmill"):
                layout.operator("wm.spiraloid_key_collection_readmill", icon="MATCLOTH")
        layout.separator()
        layout.operator("wm.spiraloid_pose_cycle_next", icon="ARMATURE_DATA")
        layout.operator("wm.spiraloid_pose_cycle_previous", icon="ARMATURE_DATA")

        if developer_mode:
            layout.separator()
            layout.operator("wm.spiraloid_pose_add", icon="ARMATURE_DATA")
            layout.operator("wm.spiraloid_pose_overwrite", icon="ARMATURE_DATA")
            layout.operator("wm.spiraloid_pose_remove", icon="ARMATURE_DATA")
            layout.operator("wm.spiraloid_toggle_child_lock", icon="RESTRICT_INSTANCED_OFF")
        layout.separator()
        layout.operator("wm.spiraloid_3d_comic_key_scale_hide", icon="HIDE_ON")
        layout.menu(BR_MT_3d_comic_submenu_key_camera.bl_idname, icon="CON_CAMERASOLVER")
        layout.separator()
        if developer_mode:
            layout.operator("view3d.spiraloid_3d_comic_preview", icon= "FILE_MOVIE")
            layout.separator()
            layout.operator("view3d.spiraloid_3d_comic_panel_init")
            layout.operator("view3d.spiraloid_3d_comic_panel_validate_naming")
            layout.operator("view3d.spiraloid_3d_comic_panel_validate_naming_all")
        layout.operator("wm.spiraloid_toggle_developer_mode")
        


        # layout.operator("view3d.spiraloid_export_3d_comic_letters_current", icon="RENDER_RESULT")
        # layout.operator("view3d.spiraloid_export_3d_comic_letters_all", icon="RENDER_RESULT")


class BR_MT_3d_comic_submenu_lighting(bpy.types.Menu):
    bl_idname = 'BR_MT_3d_comic_submenu_lighting'
    bl_label = '色彩·光照（Color）'

    def draw(self, context):
        layout = self.layout
        layout.operator("view3d.spiraloid_3d_comic_init_ink_lighting", text="Ink Toonshade Visible", icon="MATSHADERBALL")
        layout.separator()
        layout.operator("view3d.spiraloid_3d_comic_ink_toonshade", text="Ink Toonshade Selected", icon="NODE_MATERIAL")
        layout.operator("view3d.spiraloid_3d_comic_toonshade", text="Toonshade Selected", icon="SHADING_SOLID")
        layout.operator("view3d.spiraloid_3d_comic_ink", text="Ink Selected", icon="MESH_CIRCLE")
        layout.separator()
        layout.operator("view3d.spiraloid_3d_comic_whiteout", text="Whiteout Selected", icon="SNAP_FACE")
        layout.operator("view3d.spiraloid_3d_comic_blackout", text="Blackout Selected", icon="COLORSET_20_VEC")
        layout.separator()
        if developer_mode:
            layout.operator("view3d.spiraloid_3d_comic_init_workshop_lighting", text="Studio Lights", icon="BRUSH_DATA")
        layout.separator()
        layout.operator("view3d.spiraloid_3d_comic_cycle_sky", text="循环天空球", icon="FILE_IMAGE")
        layout.separator()
        layout.operator("wm.spiraloid_3d_comic_clear_all_ink_lighting", text="Clear Ink Toonshade all", icon="MATSHADERBALL")

        # layout.operator("view3d.spiraloid_3d_comic_init_vehicle_lighting")
        # layout.operator("view3d.spiraloid_3d_comic_init_magic_hour_lighting")



def add_object_button(self, context):
    layout = self.layout
    layout.separator()
    layout.operator(OBJECT_OT_add_inkbot.bl_idname, icon='GHOST_DISABLED')
    layout.operator(OBJECT_OT_add_ground.bl_idname, icon='AXIS_TOP')
    layout.operator(OBJECT_OT_add_speedlines.bl_idname, icon='AXIS_TOP')
    layout.operator(OBJECT_OT_add_speedlines_radial.bl_idname, icon='AXIS_TOP')
    layout.operator(OBJECT_OT_add_speedlines_ground.bl_idname, icon='AXIS_TOP')
    layout.separator()
    layout.operator(OBJECT_OT_add_ground_rocks.bl_idname, icon='AXIS_TOP')


def add_3dcomic_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(BR_MT_3d_comic_menu.bl_idname, text="3D 连环画", icon='GHOST_ENABLED')
    layout.separator()

def draw_item(self, context):
    layout = self.layout
    layout.menu(BR_MT_3d_comic_menu.bl_idname)



#------------------------------------------------------

classes = (
    BakePanelSettings,
    NewComicSettings,
    NewPanelRowSettings,
    SharedDiskAsset,
    PanelSettings,
    BR_OT_spiraloid_toggle_developer_mode,
    BR_OT_add_pose,
    OBJECT_OT_3d_comic_add_dog,
    BR_OT_subcollection_cycler,
    BR_OT_subcollection_cycler_exportable,
    BR_OT_overwrite_pose,
    BR_OT_remove_pose,
    BR_OT_toggle_child_lock,
    BR_OT_panel_init,
    BR_OT_panel_validate_naming,
    BR_OT_panel_validate_naming_all,
    BR_MT_3d_comic_menu,
    BR_MT_3d_comic_submenu_panels,
    BR_MT_3d_comic_submenu_letters,
    BR_OT_spiraloid_3d_comic_workshop,
    BR_OT_key_scale_hide,
    BR_OT_key_camera_random,
    BR_OT_key_camera_slide_up,
    BR_OT_key_camera_slide_down,
    BR_OT_key_camera_pan_left,
    BR_OT_key_camera_pan_right,
    BR_OT_key_camera_truck_in,
    BR_OT_key_camera_truck_out,
    BR_OT_key_world_spin_cw,
    BR_OT_key_world_spin_ccw,
    BR_OT_add_outline,
    BR_OT_add_toonshade,
    BR_OT_add_whiteout,
    BR_OT_add_blackout,
    BR_OT_add_toon_outline,
    BR_OT_toonfill,
    BR_OT_save_check,
    BR_OT_bake_collection,
    BR_OT_new_3d_comic,
    BR_OT_next_panel_scene,
    BR_OT_previous_panel_scene,
    BR_OT_first_panel_scene,
    BR_OT_last_panel_scene,
    BR_OT_panel_init_workshop_lighting,
    BR_OT_panel_init_ink_lighting,
    BR_OT_panel_clear_ink_lighting,
    BR_OT_panel_cycle_sky,
    BR_MT_3d_comic_submenu_lighting,
    BR_MT_3d_comic_submenu_utilities,
    BR_OT_reorder_scene_later,
    BR_OT_reorder_scene_earlier,
    BR_OT_new_panel_row,
    BR_OT_new_panel,
    BR_OT_insert_comic_scene,
    BR_OT_clone_comic_scene,
    BR_OT_blank_comic_scene,
    BR_OT_add_letter_border,
    BR_OT_add_letter_caption,
    BR_OT_add_letter_wordballoon,
    BR_OT_add_letter_wordballoon_double,
    BR_OT_add_letter_wordballoon_triple,
    BR_OT_add_letter_wordballoon_quadruple,
    BR_OT_add_letter_sfx,
    # BR_OT_add_ground,
    BR_MT_3d_comic_submenu_assets,
    BR_MT_3d_comic_submenu_assets_shared,
    BR_OT_regenerate_3d_comic_preview,
    BR_OT_delete_comic_scene,
    BR_MT_export_3d_comic_all,
    BR_MT_quick_save_export_3d_comic_current,
    # BR_MT_export_3d_comic_letters_all,
    # BR_MT_export_3d_comic_letters_current,
    BR_MT_read_3d_comic,
    BR_OT_inject_comic_scene,
    BR_OT_extract_comic_scene,
    OBJECT_OT_add_inksplat,
    OBJECT_OT_add_ground,
    OBJECT_OT_add_speedlines,
    OBJECT_OT_add_speedlines_radial,
    OBJECT_OT_add_speedlines_ground,
    OBJECT_OT_add_ground_rocks,
    OBJECT_OT_add_sprite_card,
    # OBJECT_OT_add_inkbot,  
    # OBJECT_OT_add_inkbot_puppet,
    OBJECT_OT_add_inkbot_shuffle,
    OBJECT_OT_add_bonus_shared,
    OBJECT_OT_add_bonus,
    OBJECT_OT_add_omnibot_shared,
    BR_OT_pose_cycle_next,
    BR_OT_pose_cycle_previous,
    BR_OT_spiraloid_toggle_workmode,
    BR_OT_spiraloid_automap,
    OBJECT_OT_drop_to_ground,
    BR_MT_3d_comic_submenu_key_camera,
    BR_MT_3d_comic_submenu_disk_assets,
    BR_MT_explore_3d_comic,
    BR_MT_3d_comic_panels,
    BR_MT_3d_comic_panel_color,
    BR_MT_3d_comic_panel_letters,
    BR_MT_3d_comic_panel_contents,
    BR_OT_quick_export_holo,
    BR_OT_quick_export_mobile,
    BR_OT_quick_export_vr,
    BR_MT_export_web_submenu,
    BR_MT_export_digital_submenu,
    SCENE_PT_3d_comic_panel_NEW_TOP,
)



def register():
    # bpy.app.handlers.depsgraph_update_post.append(scene_update_handler)

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


    bpy.types.Scene.bake_panel_settings = bpy.props.PointerProperty(type=BakePanelSettings)
    bpy.types.Scene.new_3d_panel_settings = bpy.props.CollectionProperty(type=NewComicSettings)
    # bpy.types.Scene.panel_settings = bpy.props.PointerProperty(type=ComicSettings)
    bpy.types.Scene.new_panel_row_settings = bpy.props.PointerProperty(type=NewPanelRowSettings)
    bpy.types.Scene.shared_disk_assets = bpy.props.PointerProperty(type=SharedDiskAsset)
    bpy.types.Scene.panel_settings = bpy.props.PointerProperty(type=PanelSettings)




    bpy.types.TOPBAR_MT_editor_menus.append(draw_item)
    bpy.types.VIEW3D_MT_add.prepend(add_3dcomic_menu)
    bpy.types.VIEW3D_MT_view.append(menu_draw_view)  





def unregister():
    # bpy.app.handlers.depsgraph_update_post.remove(scene_update_handler)

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_item)
    bpy.types.VIEW3D_MT_add.remove(add_3dcomic_menu)
    bpy.types.VIEW3D_MT_view.remove(menu_draw_view)  

    del bpy.types.Scene.bake_panel_settings
    del bpy.types.Scene.new_3d_panel_settings
    # del bpy.types.Scene.panel_settings
    del bpy.types.Scene.new_panel_row_settings
    del bpy.types.Scene.shared_disk_assets
    del bpy.types.Scene.panel_settings

    if __name__ != "__main__":
        bpy.types.TOPBAR_MT_editor_menus.remove(menu_draw_bake)


if __name__ == "__main__":
    register()


# def register():
#     bpy.utils.register_class(BR_OT_panel_init)
#     bpy.utils.register_class(BR_MT_3d_comic_menu)
#     bpy.utils.register_class(BR_MT_3d_comic_submenu_panels)
#     bpy.utils.register_class(BR_MT_3d_comic_submenu_letters)
#     bpy.utils.register_class(BR_OT_spiraloid_3d_comic_workshop)
#     bpy.utils.register_class(BR_OT_add_outline)

#     bpy.utils.register_class(BR_OT_bake_collection)
#     bpy.utils.register_class(BR_OT_new_3d_comic) 

#     bpy.utils.register_class(BR_OT_next_panel_scene)      
#     bpy.utils.register_class(BR_OT_previous_panel_scene)
#     bpy.utils.register_class(BR_OT_first_panel_scene)
#     bpy.utils.register_class(BR_OT_last_panel_scene)

#     bpy.utils.register_class(BR_OT_panel_init_workshop_lighting)
#     bpy.utils.register_class(BR_OT_panel_init_ink_lighting)
#     bpy.utils.register_class(BR_MT_3d_comic_submenu_lighting)
#     bpy.utils.register_class(BR_MT_3d_comic_submenu_utilities)

#     bpy.utils.register_class(BR_OT_reorder_scene_later)   
#     bpy.utils.register_class(BR_OT_reorder_scene_earlier)   
#     bpy.utils.register_class(BR_OT_insert_comic_scene)       
#     bpy.utils.register_class(BR_OT_clone_comic_scene)       
#     bpy.utils.register_class(BR_OT_add_letter_caption) 
#     bpy.utils.register_class(BR_OT_add_letter_wordballoon) 
#     bpy.utils.register_class(BR_OT_add_letter_sfx) 

#     bpy.utils.register_class(BR_OT_add_ground) 
#     bpy.utils.register_class(BR_MT_3d_comic_submenu_assets) 


#     bpy.utils.register_class(BR_OT_regenerate_3d_comic_preview) 
#     bpy.utils.register_class(BR_OT_delete_comic_scene)      
#     bpy.utils.register_class(BR_OT_export_3d_comic_all) 
#     bpy.utils.register_class(BR_OT_read_3d_comic) 

#     bpy.utils.register_class(BakePanelSettings)
    

#     bpy.utils.register_class(ComicPreferences)

#     bpy.types.Scene.bake_panel_settings = bpy.props.PointerProperty(type=BakePanelSettings)
#     bpy.types.TOPBAR_MT_editor_menus.append(draw_item)

# def unregister():
#     bpy.utils.unregister_class(BR_OT_panel_init)
#     bpy.utils.unregister_class(BR_MT_3d_comic_menu)
#     bpy.utils.unregister_class(BR_MT_3d_comic_submenu_panels)
#     bpy.utils.unregister_class(BR_MT_3d_comic_submenu_letters)
#     bpy.utils.unregister_class(BR_OT_spiraloid_3d_comic_workshop) 
#     bpy.utils.unregister_class(BR_OT_add_outline) 
#     bpy.utils.unregister_class(BR_OT_bake_collection) 
#     bpy.utils.unregister_class(BR_OT_new_3d_comic)
#     bpy.utils.unregister_class(BR_OT_next_panel_scene)      
#     bpy.utils.unregister_class(BR_OT_previous_panel_scene)  
#     bpy.utils.unregister_class(BR_OT_first_panel_scene)
#     bpy.utils.unregister_class(BR_OT_last_panel_scene)
#     bpy.utils.unregister_class(BR_OT_panel_init_workshop_lighting)
#     bpy.utils.unregister_class(BR_OT_panel_init_ink_lighting)
#     bpy.utils.unregister_class(BR_MT_3d_comic_submenu_lighting)
#     bpy.utils.unregister_class(BR_MT_3d_comic_submenu_utilities)
#     bpy.utils.unregister_class(BR_OT_reorder_scene_later)   
#     bpy.utils.unregister_class(BR_OT_reorder_scene_earlier)   
#     bpy.utils.unregister_class(BR_OT_insert_comic_scene)      
#     bpy.utils.unregister_class(BR_OT_clone_comic_scene)      
#     bpy.utils.unregister_class(BR_OT_add_letter_caption) 
#     bpy.utils.unregister_class(BR_OT_add_letter_wordballoon) 
#     bpy.utils.unregister_class(BR_OT_add_letter_sfx) 
#     bpy.utils.unregister_class(BR_OT_add_ground) 
#     bpy.utils.unregister_class(BR_MT_3d_comic_submenu_assets) 
#     bpy.utils.unregister_class(BR_OT_regenerate_3d_comic_preview) 
#     bpy.utils.unregister_class(BR_OT_delete_comic_scene)      
#     bpy.utils.unregister_class(BR_OT_export_3d_comic_all) 
#     bpy.utils.unregister_class(BR_OT_read_3d_comic) 
#     bpy.utils.unregister_class(BakePanelSettings)
#     bpy.utils.unregister_class(ComicPreferences)
    
#     bpy.types.TOPBAR_MT_editor_menus.remove(draw_item)

#     if __name__ != "__main__":
#         bpy.types.TOPBAR_MT_editor_menus.remove(menu_draw_bake)
# #    bpy.types.SEQUENCER_MT_add.remove(add_object_button)


    # The menu can also be called from scripts
#bpy.ops.wm.call_menu(name=BR_MT_3d_comic_menu.bl_idname)

#debug console
#__import__('code').interact(local=dict(globals(), **locals()))
# pauses wherever this line is:
# code.interact
