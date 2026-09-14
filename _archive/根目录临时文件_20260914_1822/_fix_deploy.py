import io

path = r"D:\GitRepos\Comic-books\Deploy-ComicToViewer.ps1"

with io.open(path, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

with io.open(path + ".bak", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份")

# 找问题行：包含 "预览" 或乱码
lines = content.split("\n")
for i, line in enumerate(lines):
    if "cd viewer-needle" in line and "npm run dev" in line:
        print("找到第", i+1, "行:", line[:100])
        # 整行替换为简单英文
        lines[i] = 'Write-Host "  预览: cd viewer-needle ; npm run dev"'
        print("已替换")

new_content = "\n".join(lines)
with io.open(path, "w", encoding="utf-8") as f:
    f.write(new_content)
print("done")
