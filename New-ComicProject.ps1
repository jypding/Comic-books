<#
.SYNOPSIS
New project from template
Usage: .\New-ComicProject.ps1 -ProjectId "mybook01" -Mode voice
Mode: reading / cinematic / voice
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [Parameter(Mandatory = $true)]
    [ValidateSet("reading", "cinematic", "voice")]
    [string]$Mode,
    [string]$UserDir
)

$root = $PSScriptRoot
$projectsRoot = "$root/projects"

# ========== 区分模式设置目标目录 ==========
if ($Mode -eq "voice") {
    $destination = "$root/books/语音书文件夹/$ProjectId"
} else {
    $destination = "$projectsRoot/$ProjectId"
}

# 选择模板
if ($Mode -eq "voice") {
    $srcTmpl = "$root/templates/voice_book"
} else {
    $srcTmpl = "$root/templates/cinematic_3d"
}

# 校验
if (-not (Test-Path $projectsRoot)) {
    New-Item -ItemType Directory -Path $projectsRoot | Out-Null
}
if (Test-Path $destination) {
    Write-Error "Project directory already exists: $destination"
    exit 1
}
if (-not (Test-Path $srcTmpl)) {
    Write-Error "Source template directory does not exist: $srcTmpl"
    exit 1
}

Write-Host "Creating project $ProjectId ($Mode) from template $srcTmpl..."
New-Item -ItemType Directory -Path $destination -Force | Out-Null

$srcTmplAbs = (Get-Item $srcTmpl).FullName
$destAbs = (Get-Item $destination).FullName

# ========== 递归复制模板内容（排除 .blend / .blend1 / .blend2 / _source） ==========
Get-ChildItem -Path $srcTmplAbs -Recurse -Force | Where-Object {
    $name = $_.Name
    $ext = $_.Extension.ToLower()
    # 排除 .blend / .blend1 / .blend2
    if ($ext -in @('.blend', '.blend1', '.blend2')) { return $false }
    # 排除 _source 备份目录
    if ($_.FullName -match '\\_source\\' -or $_.FullName -match '/_source/') { return $false }
    # 排除 .bak
    if ($name -like '*.bak*') { return $false }
    return $true
} | ForEach-Object {
    $rel = $_.FullName.Substring($srcTmplAbs.Length).TrimStart('\', '/')
    $tp = Join-Path $destAbs $rel
    if ($_.PSIsContainer) {
        if (-not (Test-Path $tp)) {
            New-Item -ItemType Directory -Path $tp -Force | Out-Null
        }
    } else {
        $pd = Split-Path -Path $tp -Parent
        if (-not (Test-Path $pd)) {
            New-Item -ItemType Directory -Path $pd -Force | Out-Null
        }
        Copy-Item -Path $_.FullName -Destination $tp -Force
    }
}

# ========== 复制模板 .blend 到项目 blender/ ==========
$dstBlender = Join-Path $destAbs "blender"
if (-not (Test-Path $dstBlender)) {
    New-Item -ItemType Directory -Path $dstBlender -Force | Out-Null
}

if ($Mode -eq "voice") {
    $templateBlend = Join-Path $srcTmplAbs "blender/voice_book_template.blend"
} else {
    $templateBlend = "$root/projects/_template_cinematic/cinematic_nav.blend"
}

if (Test-Path $templateBlend) {
    $targetBlend = Join-Path $dstBlender "$ProjectId.blend"
    Write-Host "Copying template blend to: $targetBlend"
    Copy-Item -Path $templateBlend -Destination $targetBlend -Force
} else {
    Write-Warning "Template blend not found at: $templateBlend"
}

# ========== 更新 manifest.json mode ==========
$manifestPath = Join-Path $destination "book/manifest.json"
if (Test-Path $manifestPath) {
    Write-Host "Updating manifest.json mode to: $Mode"
    $manifest = Get-Content -Path $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.mode = $Mode
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $manifestPath -Encoding UTF8
} else {
    Write-Warning "manifest.json not found, skipping mode update"
}

Write-Host "Project created successfully: $destination"
Write-Host "Mode: $Mode"

# ========== 生成 Blender 快捷方式 ==========
if ($UserDir -and (Test-Path $UserDir)) {
    $targetBlend = Join-Path $dstBlender "$ProjectId.blend"
    $blenderExe = "D:\blender\blender-5.2.0\blender.exe"
    if ((Test-Path $targetBlend) -and (Test-Path $blenderExe)) {
        $lnkPath = Join-Path $UserDir "$ProjectId.lnk"
        try {
            $ws = New-Object -ComObject WScript.Shell
            $sc = $ws.CreateShortcut($lnkPath)
            $sc.TargetPath = $blenderExe
            $sc.Arguments = '"' + $targetBlend + '"'
            $sc.WorkingDirectory = (Split-Path $targetBlend -Parent)
            $sc.IconLocation = "$blenderExe,0"
            $sc.Save()
            Write-Host "Shortcut created: $lnkPath"
        } catch {
            Write-Warning "Failed to create shortcut: $_"
        }
    }
}