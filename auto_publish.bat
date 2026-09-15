@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   Publish %~1 to JYP
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
echo [2/3] Push to GitHub...
call publish.bat

echo.
echo [3/3] Open JYP site...
start "" "https://jypding.github.io/Comic-books/index.html?book=%~1"

exit /b 0
