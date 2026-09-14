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
    $destination = "$root/books/$ProjectId/blender"
} else {
    $destination = "$projectsRoot/$ProjectId"
}
# Choose template based on mode
if ($Mode -eq "voice") {
    $srcTmpl = "$root/templates/voice_book"
} else {
    $srcTmpl = "$root/templates/cinematic_3d"
}
# Validation and preparation
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
# Create project directory
Write-Host "Creating project $ProjectId ($Mode) from template $srcTmpl..."
if (-not (Test-Path $destination)) {
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
}
# Copy everything except .blend files and backup files
$srcTmplAbs = (Get-Item $srcTmpl).FullName
$destinationAbs = (Get-Item $destination).FullName
Get-ChildItem -Path $srcTmpl -Exclude "*.blend", "*.blend1", "*.blend2" -Recurse | ForEach-Object {
    $targetPath = $_.FullName.Replace($srcTmplAbs, $destinationAbs)
    if ($_.PSIsContainer) {
        if (-not (Test-Path $targetPath)) {
            New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        }
    } else {
        $parentDir = Split-Path -Path $targetPath -Parent
        if (-not (Test-Path $parentDir)) {
            New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
        }
        Copy-Item -Path $_.FullName -Destination $targetPath -Force
    }
}
# Special handling for .blend template
$blenderDir = "$destination/blender"
if (-not (Test-Path $blenderDir)) {
    New-Item -ItemType Directory -Path $blenderDir -Force | Out-Null
}
$templateBlend = "$srcTmpl/blender/voice_book_template.blend"
if ($Mode -ne "voice") {
    $templateBlend = "$root/projects/_template_cinematic/cinematic_nav.blend"
}
if (Test-Path $templateBlend) {
    $targetBlend = "$blenderDir/$ProjectId.blend"
    Write-Host "Copying and renaming template blend to: $targetBlend"
    Copy-Item -Path $templateBlend -Destination $targetBlend -Force
} else {
    Write-Warning "Template blend not found at: $templateBlend"
}
# Update manifest.json mode field
$manifestPath = "$destination/book/manifest.json"
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
# === 在用户选择的目录生成 Blender 快捷方式 ===
if ($UserDir -and (Test-Path $UserDir)) {
    $targetBlend = "$destination/blender/$ProjectId.blend"
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

Write-Host "Next step: Run .\Deploy-ComicToViewer.ps1 -ProjectId $ProjectId after adding content"
