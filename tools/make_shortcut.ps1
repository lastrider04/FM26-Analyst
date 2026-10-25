# Create "FM26 Analyst" shortcuts on the Desktop and in the Start menu.
# Run:  powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
$root = Split-Path -Parent $PSScriptRoot
$targets = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $targets) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'FM26 Analyst.lnk'))
    $lnk.TargetPath = Join-Path $root '.venv\Scripts\pythonw.exe'
    $lnk.Arguments = '"' + (Join-Path $root 'launch.py') + '"'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = (Join-Path $root 'web\static\icon.ico') + ',0'
    $lnk.Description = 'FM26 Analyst - dashboard, auto-capture and hotkey'
    $lnk.Save()
    Write-Output "created $($lnk.FullName)"
}
