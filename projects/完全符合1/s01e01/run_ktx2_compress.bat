@echo off
setlocal
cd /d "D:\GitRepos\Comic-books\viewer-needle"
echo === KTX2 compression ===
echo GLB: D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized.glb
npx @needle-tools/buildpipeline --input "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets" --output "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized_ktx2"
if errorlevel 1 echo [FAIL]
echo === Done ===
pause
