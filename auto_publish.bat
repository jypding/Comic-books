@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   Publish %~1 to JYP
echo ============================================
echo.

echo [1/2] Deploy...
if exist "projects\%~1" (
    powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%~1"
) else if exist "books\%~1" (
    echo Already in books\
) else (
    echo Project not found: %~1
    pause
    exit /b 1
)

echo.
echo [2/2] Push to GitHub...
call publish.bat

echo.
echo ============================================
echo   Opening JYP site...
echo ============================================
start "" "https://jypding.github.io/Comic-books/index.html?book=%~1"

timeout /t 3 >nul