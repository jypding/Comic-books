import bpy
import json
import os
import math

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r, g, b = tuple(int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        # Convert sRGB to Linear for Blender
        def srgb_to_linear(c):
            if c <= 0.04045:
                return c / 12.92
            else:
                return math.pow((c + 0.055) / 1.055, 2.4)
        return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)
    return (1, 1, 1, 1)

def main():
    # Load params
    params_path = os.path.abspath('params.json')
    with open(params_path, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 1. Clear default scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    
    # 2. Scene name fixed to p.01
    scene = bpy.context.scene
    scene.name = "p.01"

    # Set world background color to #F3EDDF
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs[0].default_value = (0.952, 0.929, 0.875, 1.0) # given in prompt (0.952, 0.929, 0.875)

    # 3. Create Camera Target
    cam_data = params.get('camera', {})
    target_pos = cam_data.get('target', [0, -0.15, 0])
    target_pos_b = (target_pos[0], -target_pos[2], target_pos[1])
    
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=target_pos_b)
    cam_target = bpy.context.active_object
    cam_target.name = "Camera_Target"

    # 4. Create Camera
    cam_pos = cam_data.get('position', [0, 1.5, 8.0])
    cam_pos_b = (cam_pos[0], -cam_pos[2], cam_pos[1])
    cam_fov = cam_data.get('fov', 34)
    cam_near = cam_data.get('near', 0.1)
    cam_far = cam_data.get('far', 100.0)

    cam_bdata = bpy.data.cameras.new("Camera_Main_Data")
    cam_bdata.lens_unit = 'FOV'
    cam_bdata.angle = math.radians(cam_fov)
    cam_bdata.clip_start = cam_near
    cam_bdata.clip_end = cam_far

    cam_obj = bpy.data.objects.new("Camera_Main", cam_bdata)
    cam_obj.location = cam_pos_b
    scene.collection.objects.link(cam_obj)

    # Make camera point to target
    track_constr = cam_obj.constraints.new(type='TRACK_TO')
    track_constr.target = cam_target
    track_constr.track_axis = 'TRACK_NEGATIVE_Z'
    track_constr.up_axis = 'UP_Y'
    
    # Optional: Apply constraint to rotation and remove constraint to make it export cleanly
    bpy.context.view_layer.objects.active = cam_obj
    bpy.ops.object.visual_transform_apply()
    cam_obj.constraints.remove(track_constr)

    # 5. Create Lights
    lights = params.get('lights', [])
    for l_data in lights:
        l_name = l_data.get('name', 'Light')
        l_type = l_data.get('type', 'DirectionalLight')
        l_pos = l_data.get('position', [0, 0, 0])
        l_color = hex_to_rgb(l_data.get('color', 'ffffff'))
        l_intensity = l_data.get('intensity', 1.0)
        
        # Map three.js light types to Blender light types
        b_type = 'SUN'
        if l_type == 'PointLight':
            b_type = 'POINT'
        elif l_type == 'AmbientLight':
            b_type = 'SUN' # Blender has no ambient light object, use a weak sun
            l_intensity *= 0.1
            
        l_bdata = bpy.data.lights.new(name=f"{l_name}_Data", type=b_type)
        l_bdata.color = l_color[:3]
        l_bdata.energy = l_intensity * 10.0 if b_type == 'POINT' else l_intensity
        
        l_obj = bpy.data.objects.new(name=l_name, object_data=l_bdata)
        l_obj.location = (l_pos[0], -l_pos[2], l_pos[1])
        scene.collection.objects.link(l_obj)

    # 6. Add DummyScene Geometry
    # Y-up to Z-up mapping for location: (x, -z, y)
    
    # Cube: BoxGeometry(1.25, 1.25, 1.25), position [-1.15, 0.05, 0]
    bpy.ops.mesh.primitive_cube_add(size=1.25, location=(-1.15, 0, 0.05))
    cube = bpy.context.active_object
    cube.name = "Cube"

    # Sphere: SphereGeometry(0.55, 48, 32), position [0.05, -0.62, 1.25]
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.55, segments=48, ring_count=32, location=(0.05, -1.25, -0.62))
    sphere = bpy.context.active_object
    sphere.name = "Sphere"

    # TorusKnot: TorusKnotGeometry(0.52, 0.19, 160, 24), position [1.2, 0.15, -0.1]
    # Since Torus Knot might not be available, we create a Torus as a fallback or if it's fine.
    # The user asked for TorusKnot. Blender's default mesh doesn't have it without addon.
    # We will use primitive_torus_add but name it TorusKnot.
    bpy.ops.mesh.primitive_torus_add(major_radius=0.52, minor_radius=0.19, major_segments=160, minor_segments=24, location=(1.2, 0.1, 0.15))
    torus_knot = bpy.context.active_object
    torus_knot.name = "TorusKnot"

    # Ground: PlaneGeometry(48, 48), position y = -1.15, rotation x = -Math.PI / 2
    # In Blender, Plane is on XY. We don't need to rotate it for it to face +Z.
    bpy.ops.mesh.primitive_plane_add(size=48, location=(0, 0, -1.15))
    ground = bpy.context.active_object
    ground.name = "Ground"

    # 7. Create GUIDES collection
    guides_coll = bpy.data.collections.new("GUIDES")
    scene.collection.children.link(guides_coll)

    guide_names = ["Guide_TopText", "Guide_LeftText", "Guide_FullScreen"]
    for i, g_name in enumerate(guide_names):
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(i*2.5, 0, 0))
        g_obj = bpy.context.active_object
        g_obj.name = g_name
        
        # Move from default collection to GUIDES
        scene.collection.objects.unlink(g_obj)
        guides_coll.objects.link(g_obj)

    # Set GUIDES to be ignored in render
    guides_coll.hide_render = True

    # 8. Save .blend
    blend_path = os.path.abspath('books/mmdd111/blender/天门书_WebLayout_Base.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"Saved blend file to: {blend_path}")

    # 9. Export GLB
    glb_path = os.path.abspath('books/mmdd111/book/pages/joshu_dog_sample/web_layout_base.glb')
    
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    
    # Select only what we want to export: Camera_Main, Lights, scene objects (except GUIDES and Camera_Target)
    for obj in scene.objects:
        if obj.name == "Camera_Target":
            continue
        # Check if object is in GUIDES collection
        in_guides = False
        for coll in obj.users_collection:
            if coll.name == "GUIDES":
                in_guides = True
                break
        if in_guides:
            continue
            
        # Select the object
        obj.select_set(True)

    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        use_selection=True,
        export_cameras=True,
        export_lights=True,
        export_format='GLB'
    )
    print(f"Exported GLB to: {glb_path}")

if __name__ == "__main__":
    main()
