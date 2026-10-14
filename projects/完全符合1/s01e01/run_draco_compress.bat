@echo off
setlocal
echo === Draco compression (gltf-pipeline) ===
echo Input:  D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized.glb
echo Output: D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized_draco.glb
npx gltf-pipeline -i "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized.glb" -o "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized_draco.glb" -d
if errorlevel 1 echo [FAIL]
echo === Done ===
echo Compare sizes:
dir "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized.glb" "D:\GitRepos\Comic-books\projects\完全符合1\s01e01\assets\scene_optimized_draco.glb"
pause
