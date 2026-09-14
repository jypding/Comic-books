import bpy

def run():
    try:
        # 1. 找到 Camera_Main
        camera_main = bpy.data.objects.get("Camera_Main")
        
        # 2. 找到或创建 GUIDES Collection
        guides_col = bpy.data.collections.get("GUIDES")
        if not guides_col:
            guides_col = bpy.data.collections.new("GUIDES")
            bpy.context.scene.collection.children.link(guides_col)
            
        # 3. 保留已有 Guide_Full, Guide_Left, Guide_Top
        existing_guides = ["Guide_Full", "Guide_Left", "Guide_Top"]
        
        # 4. 在 GUIDES 中新增对象
        new_objects_info = [
            {"name": "Guide_Full_UI", "type": "MESH", "props": {"ui_role": "mask", "ui_layout": "fullscreen", "ui_mask_region": "full", "ui_color": [0.05, 0.05, 0.05, 0.60]}},
            {"name": "Guide_Bottom", "type": "MESH", "props": {"ui_role": "mask", "ui_layout": "image-text-bottom", "ui_mask_region": "bottom_text"}},
            {"name": "Guide_Right", "type": "MESH", "props": {"ui_role": "mask", "ui_layout": "image-text-right", "ui_mask_region": "right_side"}},
            {"name": "TXT_Title", "type": "FONT", "props": {"ui_role": "title", "ui_layout": "image-text-bottom"}},
            {"name": "TXT_Body", "type": "FONT", "props": {"ui_role": "body", "ui_layout": "image-text-bottom"}},
            {"name": "BTN_PREV", "type": "MESH", "props": {"ui_role": "button", "ui_action": "page_prev", "ui_layout": "image-text-bottom"}},
            {"name": "BTN_NEXT", "type": "MESH", "props": {"ui_role": "button", "ui_action": "page_next", "ui_layout": "image-text-bottom"}},
        ]
        
        for info in new_objects_info:
            name = info["name"]
            obj = bpy.data.objects.get(name)
            
            if not obj:
                if info["type"] == "MESH":
                    mesh = bpy.data.meshes.new(name=name)
                    # Create a simple plane mesh
                    mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)], [], [(0,1,2,3)])
                    mesh.update()
                    obj = bpy.data.objects.new(name, mesh)
                elif info["type"] == "FONT":
                    font_curve = bpy.data.curves.new(type="FONT", name=name)
                    font_curve.body = name
                    obj = bpy.data.objects.new(name, font_curve)
                
                guides_col.objects.link(obj)
            else:
                # Ensure it's in GUIDES collection
                if obj.name not in guides_col.objects:
                    # Unlink from all other collections
                    for col in bpy.data.collections:
                        if obj.name in col.objects:
                            col.objects.unlink(obj)
                    if obj.name in bpy.context.scene.collection.objects:
                        bpy.context.scene.collection.objects.unlink(obj)
                    guides_col.objects.link(obj)
            
            # 5. Add custom properties
            for k, v in info["props"].items():
                obj[k] = v
                
            # 6 & 7. Set parent to Camera_Main, rotation (0,0,0), in front of camera
            if camera_main:
                obj.parent = camera_main
                obj.rotation_euler = (0, 0, 0)
                # Ensure it's using local coordinates. We set local location so it's in front of camera (negative Z in local space for camera, usually -Z is forward for blender cameras)
                # But instruction says: "使用 Camera_Main 本地坐标 位于 Camera 前方 跟随 Camera_Main"
                # If we just set location to (0, 0, -2) in local space, it works.
                # Actually, the instructions don't specify the exact distance, just in front.
                # Let's set z = -5.
                if obj.location.length < 0.1: # if not set yet
                    obj.location = (0, 0, -5)
        
        # Save the file
        bpy.ops.wm.save_mainfile()
        
        # 10. 自检
        print("\n=== CAMERA ===")
        print(f"Camera_Main 是否存在: {'Yes' if camera_main else 'No'}")
        
        print("\n=== EXISTING GUIDES ===")
        for eg in existing_guides:
            if bpy.data.objects.get(eg):
                print(eg)
            else:
                print(f"{eg} (Not found)")
                
        print("\n=== NEW GUIDES ===")
        for info in new_objects_info:
            name = info["name"]
            obj = bpy.data.objects.get(name)
            if obj:
                print(f"name: {obj.name}")
                print(f"type: {obj.type}")
                print(f"parent: {obj.parent.name if obj.parent else 'None'}")
                print(f"location: {tuple(obj.location)}")
                print(f"scale: {tuple(obj.scale)}")
                for prop_name in info["props"].keys():
                    if prop_name in obj:
                        val = obj[prop_name]
                        if str(type(val)) == "<class 'IDPropertyArray'>":
                            val = list(val)
                        print(f"{prop_name}: {val}")
                print("---")
            else:
                print(f"{name} (FAILED to create)")
                
        print("\n=== RESULT ===")
        print("SUCCESS")
        
    except Exception as e:
        import traceback
        print("\n=== RESULT ===")
        print("FAILED")
        traceback.print_exc()

if __name__ == "__main__":
    run()
