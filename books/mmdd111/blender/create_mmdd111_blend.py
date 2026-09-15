# -*- coding: utf-8 -*-
"""
create_mmdd111_blend.py
================================================================================
生成天门书 Joshu's Dog (mmdd111) 的水墨 Blender 场景 + GLB。

关键认知：templates/voice_book/blender/voice_book_template.blend 并非空白工程，
而是含 40 个对象(含 .001/.002/.003 重复件、字体对象、占位相机/灯光) + 24 材质
+ 12 图片的成品模板。因此本脚本第一步必须把所有已存在 datablock 清空，
再按需重建，否则 GLB 会被模板残留污染。

约束(全部满足)：
  1. 场景名 p.01 —— 快速导出插件用 startswith("p.") 过滤场景。
  2. 禁用 bmesh.ops：全部几何体走 primitive_xxx_add。
  3. 按名称获取对象，不依赖 active_object；新建对象用 bpy.data.objects.new + link。
  4. 打开模板后只清空 datablock 重建内容，不调用 read_factory_settings 销毁顶层集合。
  5. 产物输出到 books/mmdd111/book/pages/joshu_dog_sample/ 下的 scene.blend / scene.glb
     (与 build.py reading/voice 模式读取路径一致)；
     同时把 .blend 副本写到本脚本同目录备份。
  6. 全部几何体是面片 + 透明水墨贴图，不使用方块/圆球占位。
  7. 所有逻辑包裹 try-except，异常输出完整栈。

用法:
  blender -b templates/voice_book/blender/voice_book_template.blend -P create_mmdd111_blend.py
"""
import bpy
import os
import sys
import traceback
from math import radians

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_repo_root(start_dir):
    d = os.path.abspath(start_dir)
    for _ in range(12):
        if os.path.isfile(os.path.join(d, "build.py")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


REPO_ROOT = _find_repo_root(SCRIPT_DIR) or SCRIPT_DIR
TEMPLATE_BLEND = os.path.join(REPO_ROOT, "templates", "voice_book", "blender", "voice_book_template.blend")
IMAGES_DIR = os.path.join(REPO_ROOT, "templates", "voice_book", "images")

# 贴图资源 (必须存在)
IMAGE_SILHOUETTE_ELDER = os.path.join(IMAGES_DIR, "master_silhouette.png")
IMAGE_SILHOUETTE_MONK = os.path.join(IMAGES_DIR, "monk_silhouette.png")
IMAGE_SILHOUETTE_DOG = os.path.join(IMAGES_DIR, "joshu_dog.png")
IMAGE_PAPER = os.path.join(IMAGES_DIR, "paper_texture.webp")

# 所需对象名 (保留既有命名体系，供前端/导出引用)
OBJ_ELDER = "Joshu_Elder"
OBJ_DOG = "JoshuDog"
OBJ_MONK = "Questioning_Monk"
OBJ_PATH = "ZenPath"
OBJ_PAPER = "Background_Paper"
OBJ_UI = "UI_Panel_Guide"
CAM_MAIN = "Camera_Main"
CAM_BOOK = "BookCamera"

REQUIRED_NAMES = [OBJ_ELDER, OBJ_DOG, OBJ_MONK, OBJ_PATH, OBJ_PAPER, OBJ_UI,
                  CAM_MAIN, CAM_BOOK]

# 执行成功后的产物
SAMPLE_DIR = os.path.join(REPO_ROOT, "books", "mmdd111", "book", "pages", "joshu_dog_sample")
BLEND_OUT = os.path.join(SAMPLE_DIR, "scene.blend")
GLB_OUT = os.path.join(SAMPLE_DIR, "scene.glb")
BLEND_BACKUP = os.path.join(SCRIPT_DIR, "mmdd111_book.blend")


def purge_all_datablocks():
    """清空模板工程里所有已存在的对象/材质/图片/网格等，只保留集合骨架。"""
    # 1. 删除所有对象 (含重复件与字体/空物体)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # 3. 孤儿数据块批量清除 (网格/曲线/字体/相机/灯光/材质/图片等)
    def _purge():
        # 反复清除直到没有可清除的孤儿
        while True:
            # 不删除集合(保留骨架)，删除其余孤儿
            before = _orphan_count()
            for data in list(bpy.data.meshes):
                if data.users == 0:
                    bpy.data.meshes.remove(data)
            for data in list(bpy.data.curves):
                if data.users == 0:
                    bpy.data.curves.remove(data)
            for data in list(bpy.data.cameras):
                if data.users == 0:
                    bpy.data.cameras.remove(data)
            for data in list(bpy.data.lights):
                if data.users == 0:
                    bpy.data.lights.remove(data)
            for img in list(bpy.data.images):
                if img.users == 0 or img.name.endswith(('.001', '.002', '.003')):
                    bpy.data.images.remove(img)
            for data in list(bpy.data.materials):
                if data.users == 0:
                    bpy.data.materials.remove(data)
            for data in list(bpy.data.images):
                if data.users == 0 and data.name not in ("Render Result", "Viewer Node"):
                    bpy.data.images.remove(data)
            for data in list(bpy.data.fonts):
                if data.users == 0:
                    bpy.data.fonts.remove(data)
            after = _orphan_count()
            if after >= before:
                break

    def _orphan_count():
        return (sum(1 for d in bpy.data.meshes if d.users == 0)
                + sum(1 for d in bpy.data.curves if d.users == 0)
                + sum(1 for d in bpy.data.cameras if d.users == 0)
                + sum(1 for d in bpy.data.lights if d.users == 0)
                + sum(1 for d in bpy.data.materials if d.users == 0)
                + sum(1 for d in bpy.data.images if d.users == 0));

    _purge()
    print("[mmdd111] 已清空模板残留对象与孤儿数据块(保留集合骨架)")
    print("[mmdd111] 剩余 对象=%d 材质=%d 网格=%d 相机=%d 灯光=%d" % (
        len(bpy.data.objects), len(bpy.data.materials),
        len(bpy.data.meshes), len(bpy.data.cameras), len(bpy.data.lights)))


def find_collection(scene, name):
    """在场景顶层集合及其子集合中按名字找集合，找不到则新建。"""
    def _walk(coll):
        if coll.name == name:
            return coll
        for child in coll.children:
            r = _walk(child)
            if r is not None:
                return r
        return None

    c = _walk(scene.collection)
    if c is not None:
        return c
    new_c = bpy.data.collections.new(name)
    scene.collection.children.link(new_c)
    return new_c


def load_image(path):
    if not os.path.isfile(path):
        raise RuntimeError("贴图不存在: %s" % path)
    name = os.path.basename(path)
    if name in bpy.data.images:
        img = bpy.data.images[name]
    else:
        img = bpy.data.images.load(path, check_existing=True)
        img.name = name
    img.name = os.path.basename(path)
    try:
        img.pack()
    except Exception as e:
        print("[mmdd111] 打包贴图失败(继续用外部引用): %s | %s" % (path, e))
    return img


def _find_bsdf(mat):
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def ink_material(name, img_path, alpha=True):
    """水墨透明材质。透明贴图用 BLENDED；纸面/UI(不透明)用 DITHERED。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = _find_bsdf(mat)
    if bsdf is None:
        raise RuntimeError("材质 %s 缺少 Principled BSDF" % name)
    if alpha:
        mat.surface_render_method = 'BLENDED'
    else:
        mat.surface_render_method = 'DITHERED'
    img = load_image(img_path)
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf.inputs["Roughness"].default_value = 1.0
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha:
        mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    return mat


def new_plane(name, size, location, scale=None, rotation=None, coll=None):
    """primitive_plane_add 后立刻按名获取对象，避免依赖 active_object。
    Blender 中 primitive_plane_add 放置于尺寸为 size 的单位平面。"""
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    if obj.data:
        obj.data.name = name + "_Mesh"
    if scale is not None:
        obj.scale = scale
    if rotation is not None:
        obj.rotation_euler = rotation
    if coll is not None:
        # 从当前集合移动到指定集合
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        coll.objects.link(obj)
    return obj


def build_scene():
    if not os.path.isfile(TEMPLATE_BLEND):
        raise RuntimeError("找不到模板工程: %s" % TEMPLATE_BLEND)

    # 打开模板(作为基座工程，不毁集合骨架)
    bpy.ops.wm.open_mainfile(filepath=TEMPLATE_BLEND)
    scene = bpy.context.scene
    scene.name = "p.01"

    # 先从模板残留中彻底清场
    purge_all_datablocks()

    # 在需要的地方按名字拿/建集合
    coll_characters = find_collection(scene, "Characters")
    coll_environment = find_collection(scene, "Environment")
    coll_interactive = find_collection(scene, "Interactive_Objects")
    coll_production = find_collection(scene, "Production")
    coll_camera = find_collection(scene, "Camera")
    coll_scene = scene.collection

    # 4.6 UI 面板参考 (UI_Panel_Guide) -> Production
    mat_ui = bpy.data.materials.new("Mat_UI_Guide")
    mat_ui.use_nodes = True
    bsdf_ui = _find_bsdf(mat_ui)
    if bsdf_ui is None:
        raise RuntimeError("材质 Mat_UI_Guide 缺少 Principled BSDF")
    bsdf_ui.inputs["Base Color"].default_value = (0.1, 0.1, 0.1, 1.0)
    mat_ui.surface_render_method = 'DITHERED'

    # 4.1 水墨背景纸面 (不透明, DITHERED)
    mat_paper = ink_material("Mat_Background_Paper", IMAGE_PAPER, alpha=False)
    paper = new_plane(OBJ_PAPER, 20, (0, 0, -0.1), coll=coll_environment)
    paper.data.materials.append(mat_paper)

    # 4.2 禅意地面 ZenPath (不透明, DITHERED)
    mat_path = ink_material("Mat_ZenPath", IMAGE_PAPER, alpha=False)
    path = new_plane(OBJ_PATH, 40, (0, 0, 0.0), scale=(1.0, 5.0, 1.0), coll=coll_environment)
    path.data.materials.append(mat_path)

    # 4.3 赵州法师 (Joshu_Elder, 透明水墨)
    mat_elder = ink_material("Mat_Joshu_Elder", IMAGE_SILHOUETTE_ELDER, alpha=True)
    elder = new_plane(OBJ_ELDER, 2.4, (-2.0, 2.0, 0.85), rotation=(radians(90), 0, 0), coll=coll_characters)
    elder.data.materials.append(mat_elder)

    # 4.4 提问僧 (Questioning_Monk, 透明水墨)
    mat_monk = ink_material("Mat_Questioning_Monk", IMAGE_SILHOUETTE_MONK, alpha=True)
    monk = new_plane(OBJ_MONK, 2.0, (1.0, 2.0, 0.8), rotation=(radians(90), 0, 0), coll=coll_characters)
    monk.data.materials.append(mat_monk)

    # 4.5 狗子 (JoshuDog, 透明水墨)
    mat_dog = ink_material("Mat_Dog_Sample", IMAGE_SILHOUETTE_DOG, alpha=True)
    dog = new_plane(OBJ_DOG, 1.6, (2.0, 0.0, 0.5), rotation=(radians(90), 0, 0), coll=coll_interactive)
    dog.data.materials.append(mat_dog)

    # 4.6 UI 面板参考 (UI_Panel_Guide, 不透明 DITHERED)
    ui = new_plane(OBJ_UI, 10, (-6.0, 0.0, 0.1), scale=(4.0, 10.0, 1.0), rotation=(radians(90), 0, 0), coll=coll_production)
    ui.data.materials.append(mat_ui)

    print("[mmdd111] 几何体创建完成: elder/dog/monk/path/paper/ui")

    # 5. 相机与灯光 (按名创建, 塞进 Camera/Production 集合)
    # 数据块名与对象名保持一致，保证 GLB 导出的 camera.name 能被前端按名切换
    cam_data_main = bpy.data.cameras.new(CAM_MAIN)
    cam_main = bpy.data.objects.new(CAM_MAIN, cam_data_main)
    coll_camera.objects.link(cam_main)
    cam_main.location = (0, -15, 10)
    cam_main.rotation_euler = (1.1, 0, 0)
    scene.camera = cam_main
    print("[mmdd111] 主相机 Camera_Main 已创建")

    cam_data_book = bpy.data.cameras.new(CAM_BOOK)
    cam_book = bpy.data.objects.new(CAM_BOOK, cam_data_book)
    coll_camera.objects.link(cam_book)
    cam_book.location = (8, -8, 4)
    cam_book.rotation_euler = (1.2, 0, 0.78)
    print("[mmdd111] 书页相机 BookCamera 已创建")


    # 6. 时间标记
    scene.timeline_markers.clear()
    scene.timeline_markers.new('Case_Start', frame=1)
    scene.timeline_markers.new('Mu_Moment', frame=50)
    scene.timeline_markers.new('Comment_Start', frame=100)
    scene.frame_start = 1
    scene.frame_end = 150
    print("[mmdd111] 时间标记: Case_Start/Mu_Moment/Comment_Start")


def save_and_export():
    scene = bpy.context.scene
    scene.name = "p.01"

    # 确保输出目录存在
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    os.makedirs(SCRIPT_DIR, exist_ok=True)

    # 备份一份 .blend 到本脚本目录
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_BACKUP)
    print("[mmdd111] 已保存 .blend 副本 -> %s" % BLEND_BACKUP)

    # 正式产物写到 sample 目录 (与 build.py 读取路径对齐)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_OUT)
    print("[mmdd111] 已保存 .blend -> %s" % BLEND_OUT)

    bpy.ops.export_scene.gltf(
        filepath=GLB_OUT,
        export_format='GLB',
        use_selection=False,
        export_cameras=True,
        export_animations=True,
        export_nla_strips=True,
        export_def_bones=True,
        export_apply=False,
        export_image_format='AUTO',
    )
    print("[mmdd111] 已导出 .glb -> %s" % GLB_OUT)


def main():
    try:
        build_scene()
        save_and_export()
        print("[mmdd111] 完成。")
    except Exception:
        print("[mmdd111] FATAL: 脚本执行失败")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
