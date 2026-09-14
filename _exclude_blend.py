import io

path = r"D:\GitRepos\Comic-books\Deploy-ComicToViewer.ps1"

with io.open(path, "r", encoding="utf-8-sig") as f:
    content = f.read()

# 替换所有 Copy-Item ... -Recurse -Force 为带排除的版本
old = '''Get-ChildItem "$srcRoot/*" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName "$dstBook/book/" -Recurse -Force
}'''

new = '''Get-ChildItem "$srcRoot/*" -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -ne "blender" -and $_.Extension -notin @(".blend", ".blend1", ".blend11")
} | ForEach-Object {
    Copy-Item $_.FullName "$dstBook/book/" -Recurse -Force
}'''

if old in content:
    content = content.replace(old, new)
    with io.open(path, "w", encoding="utf-8-sig") as f:
        f.write(content)
    print("已改: 排除 blender/ 和 .blend 文件")
else:
    print("未匹配 - 打印相关行")
    for i, line in enumerate(content.splitlines(), 1):
        if "Copy-Item" in line and "srcRoot" in line:
            print(i, ":", line)
