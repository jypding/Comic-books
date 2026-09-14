import io
path = r"D:\GitRepos\Comic-books\Deploy-ComicToViewer.ps1"
with io.open(path, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()
print("=== 完整内容 ===")
print(content)
print("=== 行数 ===")
print(len(content.splitlines()))
