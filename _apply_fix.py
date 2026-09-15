import io, os, shutil
from datetime import datetime

print("=" * 60)
print("开始修改 3 个文件（全文覆盖）")
print("=" * 60)

# ============================================================
# 文件 1: publish.bat
# ============================================================
p1 = r"D:\GitRepos\Comic-books\publish.bat"
if os.path.exists(p1):
    shutil.copy(p1, p1 + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M"))
    print("[1/3] 已备份 publish.bat")

content1 = '''@echo off
chcp 65001 >nul
cd /d D:\\GitRepos\\Comic-books

git add -A
git commit -m "publish %date% %time%" 2>nul
git push origin main

exit /b 0
'''

with io.open(p1, "w", encoding="utf-8", newline="\r\n") as f:
    f.write(content1)
print("[1/3] publish.bat 已覆盖")


# ============================================================
# 文件 2: auto_publish.bat
# ============================================================
p2 = r"D:\GitRepos\Comic-books\auto_publish.bat"
if os.path.exists(p2):
    shutil.copy(p2, p2 + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M"))
    print("[2/3] 已备份 auto_publish.bat")

content2 = '''@echo off
chcp 65001 >nul
cd /d D:\\GitRepos\\Comic-books

echo ============================================
echo   Publish %~1 to JYP
echo ============================================
echo.

echo [1/3] Deploy...
if exist "projects\\%~1" (
    powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%~1"
) else if exist "books\\%~1" (
    echo   Already in books\\, skip deploy
) else (
    echo   Project not found: %~1
    exit /b 1
)

echo.
echo [2/3] Push to GitHub...
call publish.bat

echo.
echo [3/3] Open JYP site...
start "" "https://jypding.github.io/Comic-books/index.html?book=%~1"

exit /b 0
'''

with io.open(p2, "w", encoding="utf-8", newline="\r\n") as f:
    f.write(content2)
print("[2/3] auto_publish.bat 已覆盖")


# ============================================================
# 文件 3: 3DComicToolkit.py (只替换 preview_server 段)
# ============================================================
p3 = os.path.expandvars(
    r"%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\3DComicToolkit.py"
)

if not os.path.exists(p3):
    print("[3/3] FAIL: 未找到", p3)
else:
    shutil.copy(p3, p3 + ".bak_open_" + datetime.now().strftime("%Y%m%d_%H%M"))
    print("[3/3] 已备份 3DComicToolkit.py")

    with io.open(p3, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()

    # 精确替换整段
    old_block = """            # 3. 自动开启播放窗
            if not bpy.app.background:
                from . import preview_server
                # 使用 _get_publish_root() 获取项目隔离目录
                preview_server.preview_comic(directory=_get_publish_root(), port=8000, auto_start=True)"""

    new_block = """            # 3. 不再自动开 8000 播放窗（由 auto_publish.bat 打开 JYP 网站）"""

    if old_block in src:
        src = src.replace(old_block, new_block)
        with io.open(p3, "w", encoding="utf-8") as f:
            f.write(src)
        print("[3/3] 3DComicToolkit.py 已替换 preview_server 段")
    else:
        # 尝试更宽泛的匹配
        import re
        pattern = re.compile(
            r"#[^\n]*\u81ea\u52a8\u5f00\u542f\u64ad\u653e\u7a97[^\n]*\n"
            r"(\s*)if not bpy\.app\.background:\n"
            r"\s*from \. import preview_server\n"
            r"([^\n]*\n)*?"
            r"\s*preview_server\.preview_comic\([^\n]*\)\n",
            re.MULTILINE
        )
        m = pattern.search(src)
        if m:
            src = src[:m.start()] + new_block + "\n" + src[m.end():]
            with io.open(p3, "w", encoding="utf-8") as f:
                f.write(src)
            print("[3/3] 3DComicToolkit.py 已用正则替换")
        else:
            print("[3/3] WARN: 未找到 preview_server 段，请手动确认")
            # 打印含 preview_comic 的行号
            for i, line in enumerate(src.splitlines(), 1):
                if "preview_comic" in line:
                    print("  行", i, ":", line.strip())

print()
print("=" * 60)
print("全部完成")
print("=" * 60)
