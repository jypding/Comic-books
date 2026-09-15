import io, os, shutil

# 1. 复制为小写
src = r"D:\GitRepos\Comic-books\books\mmdd111\book\pages\joshu_dog_sample\reader_sample\001.MP3"
dst = r"D:\GitRepos\Comic-books\books\mmdd111\book\pages\joshu_dog_sample\reader_sample\001.mp3"
shutil.copy(src, dst)
print("✓ 已复制 001.mp3")

# 2. 改 index.html 里的引用
html_path = r"D:\GitRepos\Comic-books\books\mmdd111\book\pages\joshu_dog_sample\reader_sample\index.html"
with io.open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

before = content.count("001.MP3")
content = content.replace("001.MP3", "001.mp3")
content = content.replace("./001.mp3", "./001.mp3")  # 无变化，只是确认

with io.open(html_path, "w", encoding="utf-8") as f:
    f.write(content)
print("✓ index.html 里 001.MP3 → 001.mp3，共", before, "处")

# 3. 也改 main.js（如果有引用）
js_path = r"D:\GitRepos\Comic-books\books\mmdd111\book\pages\joshu_dog_sample\reader_sample\main.js"
if os.path.exists(js_path):
    with io.open(js_path, "r", encoding="utf-8") as f:
        js = f.read()
    before_js = js.count("001.MP3")
    js = js.replace("001.MP3", "001.mp3")
    with io.open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    print("✓ main.js 里改了", before_js, "处")
