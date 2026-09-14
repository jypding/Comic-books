@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   Publish %~1 to JYP
echo ============================================
echo.

echo [1/2] Deploy to books/...
powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%~1"
if errorlevel 1 (
    echo Deploy failed
    pause
    exit /b 1
)

echo.
echo [2/2] Push to GitHub...
call publish.bat

echo.
echo ============================================
echo   DONE - JYP updates in 1-2 minutes
echo ============================================
timeout /t 5 >nul