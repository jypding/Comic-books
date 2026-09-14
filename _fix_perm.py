import io

path = r"D:\GitRepos\Comic-books\.github\workflows\pages.yml"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

with io.open(path + ".bak2", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份: pages.yml.bak2")

# 在 jobs: 之前插入 permissions
old = "jobs:\n"
new = """permissions:
  contents: write

jobs:
"""

if "permissions:" not in content:
    content = content.replace(old, new, 1)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("已加 permissions: contents: write")
else:
    print("已存在 permissions")
