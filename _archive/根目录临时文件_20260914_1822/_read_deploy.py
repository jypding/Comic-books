import io
path = r"D:\GitRepos\Comic-books\Deploy-ComicToViewer.ps1"
with io.open(path, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()
print(content)
