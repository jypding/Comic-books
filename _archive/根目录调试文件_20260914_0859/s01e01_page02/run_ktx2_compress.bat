@echo off
cd /d "D:\GitRepos\Comic-books\s01e01_page02"
echo 开始KTX2贴图硬件压缩
npx @needle-tools/buildpipeline --input assets --output dist/assets
echo 完成！输出在 dist\assets
pause
