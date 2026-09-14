@echo off
chcp 65001 >nul
cd /d D:\GitRepos\Comic-books

echo ============================================
echo   Publish %~1 to JYP
echo ============================================
echo.

REM 判断：3D漫画在 projects\，语音书在 books\
if exist "projects\%~1" (
    echo [1/2] Deploy from projects\ ...
    powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%~1"
    if errorlevel 1 (
        echo Deploy failed
        pause
        exit /b 1
    )
) else (
    if exist "books\%~1" (
        echo [1/2] Skip deploy - voice book already in books\
    ) else (
        echo [1/2] Project not found in projects\ or books\
        pause
        exit /b 1
    )
)

echo.
echo [2/2] Push to GitHub...
call publish.bat

echo.
echo DONE - JYP updates in 1-2 minutes
timeout /t 3 >nul