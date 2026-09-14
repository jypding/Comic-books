@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   一键修复
echo ============================================
echo.

echo [1/5] 杀掉卡住的 cmd 和 blender...
taskkill /F /IM cmd.exe 2>nul
taskkill /F /IM blender.exe 2>nul

echo [2/5] 修复 _get_publish_root...
python -c "import io; p=r'C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Blender-3DComicToolkit\core\utils.py'; c=io.open(p,'r',encoding='utf-8').read(); c=c.replace('base = r\"D:\\GitRepos\\Comic-books\\projects\"','base = r\"D:\\GitRepos\\Comic-books\"'); c=c.replace('return os.path.join(base, project_name, episode_name)','return os.path.join(base, \"projects\", project_name, episode_name)'); c=c.replace('return os.path.join(base, fallback_name)','return os.path.join(base, \"projects\", fallback_name)'); io.open(p,'w',encoding='utf-8').write(c); print('  OK')"

echo [3/5] 清理错误目录...
if exist "projects\projects" rmdir /s /q "projects\projects"
if exist "projects\a01111111" rmdir /s /q "projects\a01111111"
if exist "a01111111" rmdir /s /q "a01111111"

echo [4/5] 清 Python 缓存...
for /d /r "C:\Users\86159\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons" %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"

echo [5/5] 完成!
echo.
echo   现在重新打开 Blender 测试
echo.
pause