<#
.SYNOPSIS
将 projects 下项目部署到项目根 /books/<ProjectId>/（供 viewer-needle 运行时动态 fetch），
同时保留 viewer-needle/book 的本地 dev 兼容回退路径。
Usage: .\Deploy-ComicToViewer.ps1 -ProjectId "mybook01" [-SetCurrent]
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectId,
    [switch]$SetCurrent
)
$root=$PSScriptRoot
$srcProj="$root/projects/$ProjectId"
$viewer="$root/viewer-needle"
$booksRoot="$root/books"
$dstBook="$booksRoot/$ProjectId"

if(-not(Test-Path $srcProj)){
    Write-Error "项目不存在 $srcProj"
    exit 1
}
$manifestPath="$srcProj/book/manifest.json"
if(-not(Test-Path $manifestPath)){
    Write-Error "manifest.json 不存在：$manifestPath"
    exit 1
}
$manifest=Get-Content $manifestPath | ConvertFrom-Json
Write-Host "📘检测模式：$($manifest.mode)"

# 1. 部署到 /books/<ProjectId>/（主路径，viewer 优先 fetch ./books/<书名>/book/manifest.json）
if(Test-Path $dstBook){ Remove-Item $dstBook -Recurse -Force }
New-Item -ItemType Directory -Force $dstBook | Out-Null

# book/ (manifest + pages)
New-Item -ItemType Directory -Force "$dstBook/book" | Out-Null
Copy-Item "$srcProj/book\*" "$dstBook/book\" -Recurse -Force

# audio/ (reading / voice)
if(Test-Path "$srcProj/audio"){
    New-Item -ItemType Directory -Force "$dstBook/audio" | Out-Null
    Copy-Item "$srcProj/audio\*" "$dstBook/audio\" -Recurse -Force
}

# images/ (voice / reading)
if(Test-Path "$srcProj/images"){
    New-Item -ItemType Directory -Force "$dstBook/images" | Out-Null
    Copy-Item "$srcProj/images\*" "$dstBook/images\" -Recurse -Force
}

# reading: assets/ → images/ 或 assets/ 兜底
if($manifest.mode -eq "reading" -or $manifest.mode -eq "voice"){
    if(Test-Path "$srcProj/assets"){
        if(-not(Test-Path "$dstBook/images")){ New-Item -ItemType Directory -Force "$dstBook/images" | Out-Null }
        Copy-Item "$srcProj/assets\*" "$dstBook/images\" -Recurse -Force
        # 保留 assets 兜底（兼容 image:"assets/xxx.jpg" 的旧 page）
        New-Item -ItemType Directory -Force "$dstBook/assets" | Out-Null
        Copy-Item "$srcProj/assets\*" "$dstBook/assets\" -Recurse -Force
    }
}

# cinematic: export_assets/ → book/pages/<page>/scene.glb 跟随 book 已被复制；此外 export_assets 兜底
if($manifest.mode -eq "cinematic"){
    if(Test-Path "$srcProj/export_assets"){
        New-Item -ItemType Directory -Force "$dstBook/assets" | Out-Null
        Copy-Item "$srcProj/export_assets\*" "$dstBook/assets\" -Recurse -Force
    }
}

# 2. SetCurrent：建立 /books/current/ 符号链接或副本（viewer 无 query 时默认加载）
if($SetCurrent){
    $current="$booksRoot/current"
    if(Test-Path $current){
        if((Get-Item $current).LinkType){ Remove-Item $current -Force }
        else { Remove-Item $current -Recurse -Force }
    }
    try {
        New-Item -ItemType Junction -Path $current -Target $dstBook -ErrorAction Stop | Out-Null
        Write-Host "🔗已设置 current 链接 -> $ProjectId"
    } catch {
        Write-Warning "创建 Junction 失败，降级为副本：$_"
        New-Item -ItemType Directory -Force $current | Out-Null
        Copy-Item "$dstBook\*" "$current\" -Recurse -Force
    }
}

# 3. 保留 viewer-needle/book 的 legacy dev 路径（无 ?book= 参数 + /books/current 不存在时回退）
if(Test-Path "$viewer/book"){ Remove-Item "$viewer/book" -Recurse -Force }
New-Item -ItemType Directory -Force "$viewer/book" | Out-Null
Copy-Item "$dstBook/book\*" "$viewer/book\" -Recurse -Force
if(Test-Path "$dstBook/audio"){
    if(Test-Path "$viewer/audio"){ Remove-Item "$viewer/audio" -Recurse -Force }
    New-Item -ItemType Directory -Force "$viewer/audio" | Out-Null
    Copy-Item "$dstBook/audio\*" "$viewer/audio\" -Recurse -Force
}
if(Test-Path "$dstBook/images"){
    if(Test-Path "$viewer/assets"){ Remove-Item "$viewer/assets" -Recurse -Force }
    New-Item -ItemType Directory -Force "$viewer/assets" | Out-Null
    Copy-Item "$dstBook/images\*" "$viewer/assets\" -Recurse -Force
}
if(Test-Path "$dstBook/assets"){
    if(-not(Test-Path "$viewer/assets")){ New-Item -ItemType Directory -Force "$viewer/assets" | Out-Null }
    Copy-Item "$dstBook/assets\*" "$viewer/assets\" -Recurse -Force
}

Write-Host "✅部署完成"
Write-Host "   主路径：$dstBook"
Write-Host "   viewer： $viewer (legacy dev fallback)"
Write-Host "   预览：   cd viewer-needle ; npm run dev (可选 ?book=$ProjectId)"
