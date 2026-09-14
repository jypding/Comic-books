import io

path = r"D:\GitRepos\Comic-books\Deploy-ComicToViewer.ps1"

content = '''param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectId,
    [switch]$SetCurrent
)

$root = $PSScriptRoot
$srcProj = "$root/projects/$ProjectId"
$viewer = "$root/viewer-needle"
$booksRoot = "$root/books"
$dstBook = "$booksRoot/$ProjectId"

if (-not (Test-Path $srcProj)) {
    Write-Error "项目不存在: $srcProj"
    exit 1
}

# 自动检测源结构: s01e01/ (3D漫画) 或 book/ (语音书)
if (Test-Path "$srcProj/s01e01/manifest.json") {
    $srcRoot = "$srcProj/s01e01"
    Write-Host "检测到 3D 漫画结构 (s01e01)"
} elseif (Test-Path "$srcProj/book/manifest.json") {
    $srcRoot = "$srcProj/book"
    Write-Host "检测到语音书结构 (book)"
} else {
    Write-Error "找不到 manifest.json (checked s01e01/ and book/)"
    exit 1
}

$manifestPath = "$srcRoot/manifest.json"
$manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "检测模式: $($manifest.mode)"

# 1. 部署到 /books/<ProjectId>/book/
if (Test-Path $dstBook) { Remove-Item $dstBook -Recurse -Force }
New-Item -ItemType Directory -Force "$dstBook/book" | Out-Null

# 拷 manifest + pages + assets 到 book/
Get-ChildItem "$srcRoot/*" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName "$dstBook/book/" -Recurse -Force
}

# audio/
if (Test-Path "$srcProj/audio") {
    New-Item -ItemType Directory -Force "$dstBook/audio" | Out-Null
    Copy-Item "$srcProj/audio/*" "$dstBook/audio/" -Recurse -Force
}

# images/
if (Test-Path "$srcRoot/images") {
    New-Item -ItemType Directory -Force "$dstBook/images" | Out-Null
    Copy-Item "$srcRoot/images/*" "$dstBook/images/" -Recurse -Force
}

# styles/
if (Test-Path "$srcProj/styles") {
    New-Item -ItemType Directory -Force "$dstBook/styles" | Out-Null
    Copy-Item "$srcProj/styles/*" "$dstBook/styles/" -Recurse -Force
}

# 2. 如果指定 SetCurrent，写入 viewer-needle/books/current
if ($SetCurrent) {
    $currentPath = "$viewer/books/current"
    if (Test-Path $currentPath) { Remove-Item $currentPath -Recurse -Force }
    New-Item -ItemType Directory -Force $currentPath | Out-Null
    Copy-Item "$dstBook/*" "$currentPath/" -Recurse -Force
    Write-Host "已设为当前书籍: $currentPath"
}

# 3. 保留 viewer-needle/book 的 legacy dev 路径
if (Test-Path "$viewer/book") { Remove-Item "$viewer/book" -Recurse -Force }
New-Item -ItemType Directory -Force "$viewer/book" | Out-Null
Copy-Item "$dstBook/book/*" "$viewer/book/" -Recurse -Force

if (Test-Path "$dstBook/audio") {
    if (Test-Path "$viewer/audio") { Remove-Item "$viewer/audio" -Recurse -Force }
    New-Item -ItemType Directory -Force "$viewer/audio" | Out-Null
    Copy-Item "$dstBook/audio/*" "$viewer/audio/" -Recurse -Force
}

if (Test-Path "$dstBook/images") {
    if (Test-Path "$viewer/assets") { Remove-Item "$viewer/assets" -Recurse -Force }
    New-Item -ItemType Directory -Force "$viewer/assets" | Out-Null
    Copy-Item "$dstBook/images/*" "$viewer/assets/" -Recurse -Force
}

Write-Host "部署完成"
Write-Host "   主路径: $dstBook"
Write-Host "   viewer: $viewer (legacy dev fallback)"
Write-Host "   预览: cd viewer-needle ; npm run dev"
'''

with io.open(path, "w", encoding="utf-8-sig") as f:
    f.write(content)
print("已重写: Deploy-ComicToViewer.ps1")
