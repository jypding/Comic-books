@echo off
cd /d "D:\GitRepos\Comic-books\s01e01_page02"
echo KTX2 texture compression
npx @needle-tools/buildpipeline --input assets --output dist/assets
echo Done
pause
