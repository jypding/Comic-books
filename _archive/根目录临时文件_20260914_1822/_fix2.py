import io
path = r"D:\GitRepos\Comic-books\.gitignore"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "books/**/*.blend" not in content:
    content += """

# ===== Blender 源文件（网页不需要） =====
books/**/*.blend
books/**/*.blend1
books/**/*.blend11

# ===== 调试脚本 =====
books/**/reader_sample/add_audio.py
books/**/reader_sample/fix_draco.py
books/**/fix_*.py
books/**/_*.py
"""
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK - .gitignore 已更新")
else:
    print("已存在")
