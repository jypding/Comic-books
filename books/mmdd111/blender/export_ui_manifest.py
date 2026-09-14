import bpy
import json
import os
import mathutils

def get_object_screen_bounds(obj, camera):
    """
    将物体包围盒投影到相机视口，返回归一化屏幕bounds (0~1)
    返回: {"x":left, "y":bottom, "width":w, "height":h}
    Blender相机空间：左下角(0,0)，右上角(1,1)
    """
    mat_cam = camera.matrix_world.inverted()
    cam_data = camera.data
    frame = cam_data.view_frame(scene=bpy.context.scene)
    frame_x = [p[0] for p in frame]
    frame_y = [p[1] for p in frame]
    min_x, max_x = min(frame_x), max(frame_x)
    min_y, max_y = min(frame_y), max(frame_y)

    bbox_corners = [obj.matrix_world @ mathutils.Vector(v) for v in obj.bound_box]
    screen_coords = []
    for corner in bbox_corners:
        cam_space = mat_cam @ corner
        if cam_space.z >= 0:
            return None
        ndc_x = cam_space.x / cam_space.z
        ndc_y = cam_space.y / cam_space.z
        sx = (ndc_x - min_x) / (max_x - min_x)
        sy = (ndc_y - min_y) / (max_y - min_y)
        screen_coords.append((sx, sy))
    xs = [p[0] for p in screen_coords]
    ys = [p[1] for p in screen_coords]
    left = min(xs)
    bot = min(ys)
    right = max(xs)
    top = max(ys)
    return {"x0": left, "y0": bot, "x1": right, "y1": top}

def read_custom_props(obj):
    props = {}
    for k in obj.keys():
        if k.startswith("ui_"):
            val = obj[k]
            if str(type(val)) == "<class 'IDPropertyArray'>":
                val = list(val)
            if isinstance(val, list):
                val = [float(v) if isinstance(v, (int, float)) else v for v in val]
            props[k] = val
    return props

def extract_ui_data(collection_name, camera_name):
    coll = bpy.data.collections.get(collection_name)
    cam = bpy.data.objects.get(camera_name)
    if not coll or not cam:
        print(f"Missing collection {collection_name} or camera {camera_name}")
        return None
    ui_layout_data = {
        "layout_type": "image-text-bottom",
        "masks": [],
        "textAreas": [],
        "buttons": []
    }
    for obj in coll.all_objects:
        props = read_custom_props(obj)
        if "ui_role" not in props:
            continue
        bounds = get_object_screen_bounds(obj, cam)
        if bounds is None:
            continue
        role = props["ui_role"]
        entry = {
            "bounds": bounds,
            **props
        }
        # 读取Text物体文字
        if obj.type == 'FONT':
            entry["text"] = obj.data.body.strip()
        if role == "title" or role == "body" or role == "caption":
            # Add name for text areas
            entry["name"] = obj.name
            ui_layout_data["textAreas"].append(entry)
            if "ui_layout" in props:
                ui_layout_data["layout_type"] = props["ui_layout"]
        elif role == "button":
            # Add name for buttons
            entry["name"] = obj.name
            ui_layout_data["buttons"].append(entry)
        elif role == "mask":
            # Add name for masks
            entry["name"] = obj.name
            ui_layout_data["masks"].append(entry)
    return ui_layout_data

def write_manifest(book_folder_path, ui_data):
    manifest_path = os.path.join(book_folder_path, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                content = f.read()
                if content.strip():
                    manifest = json.loads(content)
        except Exception as e:
            print(f"Warning: Could not read existing manifest.json: {e}")
            # Just create a new one if it's corrupted
            manifest = {}
            
    manifest["ui_layout"] = ui_data
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"✅ Manifest saved to {manifest_path}")

if __name__ == "__main__":
    # 配置
    BOOK_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    UI_COLLECTION = "GUIDES"
    CAMERA_NAME = "Camera_Main"
    ui_result = extract_ui_data(UI_COLLECTION, CAMERA_NAME)
    if ui_result:
        write_manifest(BOOK_FOLDER, ui_result)
    else:
        print("❌ Failed to extract UI layout")
