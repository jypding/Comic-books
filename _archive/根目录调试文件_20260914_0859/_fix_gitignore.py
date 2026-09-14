import io

path = r"D:\GitRepos\Comic-books\.gitignore"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

with io.open(path + ".bak", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份: .gitignore.bak")

append = """

# ===== Blender 补充备份 =====
*.blend11
*.blend12

# ===== 临时/调试文件 =====
*.tmp
*.bak
*.bak_*
*.bak-*
*.crash.txt
*.log

# ===== Python 补充 =====
*.pyo

# ===== 构建缓存 =====
.vite/
build/
"""

if "*.blend11" not in content:
    content += append
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK - 已追加")
else:
    print("已包含，跳过")
