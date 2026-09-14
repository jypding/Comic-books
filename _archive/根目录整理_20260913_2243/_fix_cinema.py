import io

path = r"C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\3DComicToolkit.py"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''            if mode == "cinematic":
                global addon_resources_dir
                global backstage_collection_name

                # Cinematic 妯″紡淇濇寔鍘熸湁鐨?s01e01 缁撴瀯
                root_folder = os.path.dirname(self.filepath)'''

new = '''            if mode == "cinematic":
                global addon_resources_dir
                global backstage_collection_name

                # Cinematic 模式：输出到 projects/<id>/s01e01/
                root_folder = os.path.join(root, "projects")'''

if old in content:
    content = content.replace(old, new)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK - cinematic 路径已对齐到 projects/")
else:
    print("NOT FOUND")
    for i, line in enumerate(content.splitlines(), 1):
        if 'mode == "cinematic"' in line or 'root_folder = os.path.dirname' in line:
            print(i, ":", line)
