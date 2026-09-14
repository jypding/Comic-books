import io

path = r"D:\GitRepos\Comic-books\New-ComicProject.ps1"

with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 备份
with io.open(path + ".bak_lnk", "w", encoding="utf-8") as f:
    f.write(content)
print("已备份: New-ComicProject.ps1.bak_lnk")

# 检查是否已经有快捷方式代码
if "CreateShortcut" in content:
    print("已有快捷方式代码，无需修改")
else:
    # 找到 "Next step" 那一行
    marker = 'Write-Host "Next step:'
    idx = content.find(marker)
    if idx < 0:
        print("未找到 Next step 标记")
    else:
        # 在它之前插入快捷方式代码
        shortcut_code = '''# === 在用户选择的目录生成 Blender 快捷方式 ===
if ($UserDir -and (Test-Path $UserDir)) {
    $targetBlend = "$destination/blender/$ProjectId.blend"
    $blenderExe = "D:\\blender\\blender-5.2.0\\blender.exe"
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

'''
        content = content[:idx] + shortcut_code + content[idx:]
        
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("已插入快捷方式代码")
