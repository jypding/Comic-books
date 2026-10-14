@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cd /d "D:\GitRepos\Comic-books"

set "PROJECT_ID=%~1"
set "LOG_FILE=%~dp0jyp_publish_3d.log"

echo. > "%LOG_FILE%"
echo [%date% %time%] jyp_publish_3d start: PROJECT_ID=%PROJECT_ID% >> "%LOG_FILE%"

if "%PROJECT_ID%"=="" (
    echo [ERROR] Missing project ID. Usage: jyp_publish_3d.bat ^<project_id^>
    echo [ERROR] Missing project ID. >> "%LOG_FILE%"
    exit /b 1
)

echo ============================================
echo   jyp_publish_3d: %PROJECT_ID%
echo ============================================

if not exist "projects\%PROJECT_ID%" (
    echo [ERROR] Project not found: projects\%PROJECT_ID%
    echo [ERROR] Project not found: projects\%PROJECT_ID% >> "%LOG_FILE%"
    exit /b 1
)

set "SRC_ROOT="
if exist "projects\%PROJECT_ID%\s01e01\manifest.json" (
    set "SRC_ROOT=projects\%PROJECT_ID%\s01e01"
    echo [INFO] Detected 3D comic structure: s01e01
) else if exist "projects\%PROJECT_ID%\book\manifest.json" (
    set "SRC_ROOT=projects\%PROJECT_ID%\book"
    echo [INFO] Detected voice book structure: book
)

if "%SRC_ROOT%"=="" (
    echo [ERROR] No manifest.json found in projects\%PROJECT_ID%\s01e01\ or projects\%PROJECT_ID%\book\
    echo [ERROR] No manifest.json found >> "%LOG_FILE%"
    exit /b 1
)

echo [INFO] Source root: %SRC_ROOT%

if exist "%SRC_ROOT%\assets\js\vendors\three.min.js" (
    echo [INFO] vendor three.min.js present
) else (
    echo [WARN] vendor three.min.js missing
)

echo [INFO] Calling Deploy-ComicToViewer.ps1 -ProjectId "%PROJECT_ID%"
powershell -ExecutionPolicy Bypass -File "Deploy-ComicToViewer.ps1" -ProjectId "%PROJECT_ID%"
set "DEPLOY_RC=%ERRORLEVEL%"

if not "%DEPLOY_RC%"=="0" (
    echo [ERROR] Deploy-ComicToViewer.ps1 failed with exit code %DEPLOY_RC%
    echo [ERROR] Deploy failed, exit=%DEPLOY_RC% >> "%LOG_FILE%"
    exit /b %DEPLOY_RC%
)

if not exist "books\%PROJECT_ID%\book\manifest.json" (
    echo [ERROR] Deploy verification failed: books\%PROJECT_ID%\book\manifest.json not found
    echo [ERROR] Deploy verification failed >> "%LOG_FILE%"
    exit /b 1
)

echo [SUCCESS] Publish complete: %PROJECT_ID%
echo [INFO]  Target: books\%PROJECT_ID%\book\
echo [SUCCESS] Publish complete >> "%LOG_FILE%"
exit /b 0
