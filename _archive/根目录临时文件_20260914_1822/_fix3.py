import io
path = r"D:\GitRepos\Comic-books\.gitignore"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "_archive/" not in content:
    content += """

# ===== 备份 / 归档目录（不进 git） =====
_archive/
_backups/
"""
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK - 已排除 _archive/ 和 _backups/")
else:
    print("已存在")
