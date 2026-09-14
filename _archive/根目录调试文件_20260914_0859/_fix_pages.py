import io

path = r"D:\GitRepos\Comic-books\.github\workflows\pages.yml"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 备份
with io.open(path + ".bak", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份: pages.yml.bak")

# 插入步骤（在 Deploy Pages 之前）
marker = "      - name: Deploy Pages"
idx = content.find(marker)

if idx < 0:
    print("NOT FOUND: Deploy Pages")
else:
    insert = '''      - name: Copy books to dist
        run: |
          mkdir -p ./viewer-needle/dist/books
          rsync -av --exclude='*.blend' --exclude='*.blend1' --exclude='*.blend11' --exclude='*.bak_*' --exclude='__pycache__' ./books/ ./viewer-needle/dist/books/

'''
    new_content = content[:idx] + insert + content[idx:]
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("已插入 Copy books 步骤")
