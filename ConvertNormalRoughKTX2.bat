@echo off
chcp 65001 >nul
set TEXTURE_SOURCE=projects
set OUTPUT_DIR=tools\textures_out

echo ======================================
echo   Comic-books 法线/粗糙贴图转KTX2
echo ======================================
echo 源目录: %TEXTURE_SOURCE%
echo.

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

for /r "%TEXTURE_SOURCE%" %%f in (*_normal.png,*_rough.png,*roughness.png,*normal.jpg) do (
    echo 转换: %%~nxf
    toktx --t2 --etc1s --genmipmap "%OUTPUT_DIR%\%%~nf.ktx2" "%%f"
)

echo.
echo ✅ 法线贴图转换完成！
pause
