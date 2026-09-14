import io
path = r"C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\3DComicToolkit.py"
with io.open(path, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

for i, line in enumerate(lines, 1):
    if "New-ComicProject" in line or "-ProjectId" in line or "-Mode" in line or "-UserDir" in line:
        print(i, ":", line.rstrip())
