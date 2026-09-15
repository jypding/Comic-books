@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

git add -A
git commit -m "publish %date% %time%" 2>nul
git push origin main

exit /b 0
