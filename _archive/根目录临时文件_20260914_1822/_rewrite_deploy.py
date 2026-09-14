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

$manifestPath = "$srcProj/book/manifest.json"
if (-not (Test-Path $manifestPath)) {
    Write-Error "manifest.json 不存在: $manifestPath"
    exit 1
}

$manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "检测模式: $($manifest.mode)"

# 1. 部署到 /books/<ProjectId>/
if (Test-Path $dstBook) { Remove-Item $dstBook -Recurse -Force }
New-Item -ItemType Directory -Force $dstBook | Out-Null

# book/ (manifest + pages)
New-Item -ItemType Directory -Force "$dstBook/book" | Out-Null
Copy-Item "$srcProj/book/*" "$dstBook/book/" -Recurse -Force

# audio/
if (Test-Path "$srcProj/audio") {
    New-Item -ItemType Directory -Force "$dstBook/audio" | Out-Null
    Copy-Item "$srcProj/audio/*" "$dstBook/audio/" -Recurse -Force
}

# images/
if (Test-Path "$srcProj/images") {
    New-Item -ItemType Directory -Force "$dstBook/images" | Out-Null
    Copy-Item "$srcProj/images/*" "$dstBook/images/" -Recurse -Force
}

# assets/
if (Test-Path "$srcProj/assets") {
    New-Item -ItemType Directory -Force "$dstBook/assets" | Out-Null
    Copy-Item "$srcProj/assets/*" "$dstBook/assets/" -Recurse -Force
}

# styles/
if (Test-Path "$srcProj/styles") {
    New-Item -ItemType Directory -Force "$dstBook/styles" | Out-Null
    Copy-Item "$srcProj/styles/*" "$dstBook/styles/" -Recurse -Force
}

# blender/ (仅拷贝 GLB，不拷源 blend)
if (Test-Path "$srcProj/blender") {
    New-Item -ItemType Directory -Force "$dstBook/blender" | Out-Null
    Get-ChildItem "$srcProj/blender" -Filter "*.glb" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item $_.FullName "$dstBook/blender/" -Force
    }
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

if (Test-Path "$dstBook/assets") {
    if (-not (Test-Path "$viewer/assets")) {
        New-Item -ItemType Directory -Force "$viewer/assets" | Out-Null
    }
    Copy-Item "$dstBook/assets/*" "$viewer/assets/" -Recurse -Force
}

Write-Host "部署完成"
Write-Host "   主路径: $dstBook"
Write-Host "   viewer: $viewer (legacy dev fallback)"
Write-Host "   预览: cd viewer-needle ; npm run dev"
'''

# 写入 UTF-8 with BOM (PowerShell 5.x 需要 BOM 才能正确读中文)
with io.open(path, "w", encoding="utf-8-sig") as f:
    f.write(content)
print("已重写: Deploy-ComicToViewer.ps1 (UTF-8 with BOM)")
