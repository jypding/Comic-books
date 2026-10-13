@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

rem ============================================================
rem  3D book publish line (8000-line output -> JYP site)
rem  Called ONLY by Blender menu: Export Website -> Original HTML
rem  Does NOT touch voice-book 8765 line:
rem  publish.bat / auto_publish.bat / reader_sample stay unchanged
rem ============================================================

echo ============================================
echo   Publish 3D Book %~1 to JYP
echo ============================================
echo.

echo [1/3] Deploy...
if exist "projects\%~1" (
    powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%~1"
) else if exist "books\%~1" (
    echo   Already in books\, skip deploy
) else (
    echo   Project not found: %~1
    exit /b 1
)

echo.
echo [2/3] Push gh-pages (GitHub Pages serves gh-pages)...
git add -A
git commit -m "publish 3d %~1 %date% %time%" 2>nul
git push origin gh-pages

echo.
echo [3/3] Open JYP site...
if exist "books\%~1\book\index.html" (
    start "" "https://jypding.github.io/Comic-books/books/%~1/book/index.html"
) else (
    start "" "https://jypding.github.io/Comic-books/index.html?book=%~1"
)

exit /b 0
