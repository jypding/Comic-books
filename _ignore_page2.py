import io
path = r"D:\GitRepos\Comic-books\.gitignore"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()
if "books/page2" not in content:
    content += "\n# 临时排除超大 GLB 项目\nbooks/page2/\n"
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK - page2 已加入 .gitignore")
else:
    print("已存在")
