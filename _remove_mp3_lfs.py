import io

path = r"D:\GitRepos\Comic-books\.gitattributes"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()
with io.open(path + ".bak_mp3", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份")

lines = [l for l in content.splitlines() if not l.strip().startswith("*.mp3")]
new_content = "\n".join(lines) + "\n"

with io.open(path, "w", encoding="utf-8") as f:
    f.write(new_content)
print("已移除 *.mp3 的 LFS 规则")
print("=== 新内容 ===")
print(new_content)
