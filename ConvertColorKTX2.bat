@echo off
chcp 65001 >nul
set TEXTURE_SOURCE=projects
set OUTPUT_DIR=tools\textures_out

echo ======================================
echo   Comic-books 批量彩色贴图转KTX2
echo ======================================
echo 源目录: %TEXTURE_SOURCE%
echo 输出目录: %OUTPUT_DIR%
echo.

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

for /r "%TEXTURE_SOURCE%" %%f in (*.png,*.jpg) do (
    echo 转换: %%~nxf
    toktx --t2 --uastc --quality 2 --genmipmap "%OUTPUT_DIR%\%%~nf.ktx2" "%%f"
)

echo.
echo ✅ 彩色贴图转换完成！
pause
