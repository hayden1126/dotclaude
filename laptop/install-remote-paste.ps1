<#
install-remote-paste.ps1: install the laptop side of remote-paste (opt-in: nothing else runs it).

  powershell -ExecutionPolicy Bypass -File install-remote-paste.ps1 -Target <user>@<pc host>
      [-Port 2222] [-Distro Ubuntu] [-LaptopDistro <name>] [-TitlePattern '^view-\d+\s']
  powershell -ExecutionPolicy Bypass -File install-remote-paste.ps1 -Uninstall

Copies remote-paste.ahk and remote-paste.ps1 to %LOCALAPPDATA%\remote-paste and writes
remote-paste.ini there: the target and the rest stay on this laptop (dotclaude is public, so
no host name lives in it). Then it adds a Startup shortcut so the hotkey runs at sign-in,
starts it, and sends a 1x1 PNG to check the whole link. Needs AutoHotkey v2 (winget install
--id AutoHotkey.AutoHotkey), this laptop's WSL ssh reaching the PC's Windows shell port with
a key that needs no typed passphrase, and a known_hosts entry for that port (connect once by
hand: ssh -p 2222 <target>). The PC needs dotclaude's setup-tmux.sh (tmux/paste-inbox).
-Port is the PC's Windows shell port, -Distro the PC's WSL distro, -LaptopDistro this laptop's
WSL distro when ssh isn't in the default one, -TitlePattern the Windows Terminal title of a PC
tmux tab. Rerun to change a setting; -Uninstall stops the hotkey and removes the folder and
the shortcut.
#>
param(
    [string]$Target = '',
    [int]$Port = 2222,
    [string]$Distro = 'Ubuntu',
    [string]$LaptopDistro = '',
    [string]$TitlePattern = '^view-\d+\s',
    [switch]$Uninstall
)
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:LOCALAPPDATA 'remote-paste'
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'remote-paste.lnk'

function Stop-Hotkey {
    Get-CimInstance Win32_Process -Filter "Name LIKE 'AutoHotkey%'" |
        Where-Object { $_.CommandLine -like '*remote-paste.ahk*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

function Find-AutoHotkey {
    $dirs = @()
    foreach ($key in 'HKCU:\Software\AutoHotkey', 'HKLM:\SOFTWARE\AutoHotkey') {
        $item = Get-ItemProperty -LiteralPath $key -Name InstallDir -ErrorAction SilentlyContinue
        if ($item) { $dirs += $item.InstallDir }
    }
    $dirs += (Join-Path $env:ProgramFiles 'AutoHotkey'), (Join-Path $env:LOCALAPPDATA 'Programs\AutoHotkey')
    foreach ($dir in $dirs) {
        foreach ($exe in 'v2\AutoHotkey64.exe', 'v2\AutoHotkey32.exe') {
            $path = Join-Path $dir $exe
            if (Test-Path -LiteralPath $path) { return $path }
        }
    }
    return $null
}

if ($Uninstall) {
    Stop-Hotkey
    Remove-Item -LiteralPath $lnk -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $dest -Recurse -ErrorAction SilentlyContinue
    Write-Host "removed $dest and $lnk"
    exit 0
}

if ($Target -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$') { throw '-Target <user>@<pc host> is required' }
if ($Distro -notmatch '^[A-Za-z0-9._-]+$') { throw "bad -Distro: $Distro" }
if ($LaptopDistro -notmatch '^[A-Za-z0-9._-]*$') { throw "bad -LaptopDistro: $LaptopDistro" }
if ($TitlePattern -match '[\r\n]') { throw 'bad -TitlePattern' }
$ahk = Find-AutoHotkey
if (-not $ahk) {
    Write-Host 'AutoHotkey v2 not found. Install it, then rerun: winget install --id AutoHotkey.AutoHotkey'
    exit 1
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
foreach ($name in 'remote-paste.ahk', 'remote-paste.ps1') {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $dest -Force
}
Set-Content -LiteralPath (Join-Path $dest 'remote-paste.ini') -Encoding ASCII -Value @(
    '[remote-paste]', "target=$Target", "port=$Port", "distro=$Distro",
    "laptopDistro=$LaptopDistro", "title=$TitlePattern")
$script = Join-Path $dest 'remote-paste.ahk'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$shortcut.TargetPath = $ahk
$shortcut.Arguments = '"' + $script + '"'
$shortcut.WorkingDirectory = $dest
$shortcut.Save()
Stop-Hotkey
Start-Process -FilePath $ahk -ArgumentList ('"' + $script + '"')
Write-Host "installed in $dest; the hotkey runs now and at sign-in ($lnk)"

$test = Join-Path $dest 'remote-paste.ps1'
$stored = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Sta -File $test -SelfTest
if ($LASTEXITCODE -ne 0) {
    Write-Host 'self-test failed (the reason is above). Check: Tailscale is up; ssh -p' $Port $Target
    Write-Host 'works by hand from this laptop''s WSL without a passphrase prompt; setup-tmux.sh ran on the PC.'
    exit 1
}
Write-Host "self-test: the PC stored $stored"
