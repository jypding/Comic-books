@echo off
D:
cd D:\GitRepos\Comic-books
taskkill /IM "python.exe" /F
start http://localhost:8000/
python -m http.server 8000
pause
