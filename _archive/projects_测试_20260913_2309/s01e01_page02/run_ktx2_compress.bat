@echo off
cd /d "%~dp0"
echo ��ʼKTX2��ͼӲ��ѹ��
npx @needle-tools/buildpipeline --input assets --output dist/assets
echo ��ɣ������ dist\assets
pause
