from pathlib import Path

path = Path(r"D:\GitRepos\Comic-books\books\mmdd111\blender\create_mmdd111_blend.py")
text = path.read_text(encoding="utf-8")

# 1. 背景纸命名
text = text.replace('OBJ_PAPER = "PaperBackground"', 'OBJ_PAPER = "Background_Paper"')

# 2. 删除 LIGHT 定义行
text = text.replace('LIGHT = "AreaLight"\n', '')

# 3. 从 REQUIRED_NAMES 中移除 LIGHT
text = text.replace('CAM_MAIN, CAM_BOOK, LIGHT]', 'CAM_MAIN, CAM_BOOK]')

# 4. 修复图片重复加载（核心：check_existing + 复用已存在图像）
text = text.replace(
    'img = bpy.data.images.load(path, check_existing=False)',
    '''name = os.path.basename(path)
    if name in bpy.data.images:
        img = bpy.data.images[name]
    else:
        img = bpy.data.images.load(path, check_existing=True)
        img.name = name'''
)

# 5. 删除 AreaLight 创建代码块（第 285-291 行那段）
old_block = '''    light_data = bpy.data.lights.new("AreaLight_Data", type='AREA')
    light_data.energy = 500
    light = bpy.data.objects.new(LIGHT, light_data)
    coll_scene.objects.link(light)  # 直接放在主集合下，避免被其他集合过滤
    light.location = (3, -3, 4)
    light.rotation_euler = (0.7, -0.4, 0.8)
    print("[mmdd111] 区域光 AreaLight 已创建")
'''
text = text.replace(old_block, '')

# 6. 在 purge 循环中增加清理孤儿 images（特别是 .001 后缀）
old_purge = '''            for data in list(bpy.data.lights):
                if data.users == 0:
                    bpy.data.lights.remove(data)'''
new_purge = '''            for data in list(bpy.data.lights):
                if data.users == 0:
                    bpy.data.lights.remove(data)
            for img in list(bpy.data.images):
                if img.users == 0 or img.name.endswith(('.001', '.002', '.003')):
                    bpy.data.images.remove(img)'''
text = text.replace(old_purge, new_purge)

path.write_text(text, encoding="utf-8")
print("PATCH DONE")