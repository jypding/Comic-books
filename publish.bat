@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   Publish to JYP GitHub Pages
echo ============================================
echo.

echo [1/4] Clean old cache index...
git rm -r --cached _archive 2>nul
git rm -r --cached _backups 2>nul
git rm -r --cached --ignore-unmatch "books/*/blender/*.blend" 2>nul

echo [2/4] Stage all changes...
git add -A

echo [3/4] Commit...
git commit -m "publish %date% %time%"

echo [4/4] Push to GitHub...
git push origin main

echo.
echo ============================================
echo   DONE
echo   GitHub Pages: https://jyp.github.io/Comic-books/
echo   (1-2 minutes to update)
echo ============================================
pause