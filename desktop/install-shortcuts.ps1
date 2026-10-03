$ErrorActionPreference = 'Stop'
$appDirectory = [System.IO.Path]::GetFullPath($PSScriptRoot)
$electronPath = Join-Path $appDirectory 'node_modules\electron\dist\electron.exe'
$iconPath = Join-Path $appDirectory 'assets\team-logo-rounded.ico'
if (-not (Test-Path -LiteralPath $electronPath)) { throw 'Install the Electron runtime before creating shortcuts.' }
if (-not (Test-Path -LiteralPath $iconPath)) { throw 'The application icon is missing.' }
# Use Unicode code points so this script also works with Windows PowerShell 5.1.
$appName = -join ([char[]]@(0x79D1, 0x7814, 0x5DE5, 0x4F5C, 0x53F0))
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$programsDirectory = Join-Path ([Environment]::GetFolderPath('Programs')) $appName
New-Item -ItemType Directory -Path $programsDirectory -Force | Out-Null
$wsh = New-Object -ComObject WScript.Shell
foreach ($shortcutDirectory in @($desktopDirectory, $programsDirectory)) {
    $shortcutPath = Join-Path $shortcutDirectory ($appName + '.lnk')
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $electronPath
    $shortcut.Arguments = '"' + $appDirectory + '"'
    $shortcut.WorkingDirectory = $appDirectory
    $shortcut.IconLocation = $iconPath + ',0'
    $shortcut.Description = $appName + ' - Local desktop preview'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Output $shortcutPath
}
