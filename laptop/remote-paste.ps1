<#
remote-paste.ps1: send this laptop's clipboard image to the PC's paste inbox (dotclaude
tmux/paste-inbox), so Alt+V in the PC's tmux pastes it into Claude Code.

  powershell -NoProfile -Sta -File remote-paste.ps1             the clipboard's image, or one
                                                                copied image file
  powershell -NoProfile -Sta -File remote-paste.ps1 -SelfTest   a 1x1 PNG, to check the link

remote-paste.ahk runs it on Ctrl+V in a PC tmux tab; install-remote-paste.ps1 runs -SelfTest.
It reads remote-paste.ini beside it (target, port, distro, laptopDistro) and sends the bytes on
stdin through this laptop's WSL ssh (`wsl.exe -e ssh`: the key and known_hosts behind a
`ssh -p 2222 <target>` alias) to the PC's Windows shell port, whose cmd.exe runs
`wsl.exe -d <distro> --cd ~ --exec .local/bin/paste-inbox receive <COMPUTERNAME>`. The process
is started through ProcessStartInfo with no argument holding a space or a quote, since Windows
PowerShell 5.1 mangles native arguments with embedded quotes. BatchMode: a key that needs a
passphrase fails at once instead of waiting in a hidden window; ConnectTimeout 5 s, 60 s in all.

Exit 0: stored; prints the PC's path. Exit 3: no image (text, nothing, or not one image file),
so the caller pastes as usual. Exit 1: failed; the reason goes to stderr and to
%TEMP%\remote-paste.err, which remote-paste.ahk shows.
#>
param([switch]$SelfTest)
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$errFile = Join-Path $env:TEMP 'remote-paste.err'
Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue

function Fail([string]$why) {
    Set-Content -LiteralPath $errFile -Value $why -Encoding UTF8
    [Console]::Error.WriteLine("remote-paste: $why")
    exit 1
}

$ini = Join-Path $PSScriptRoot 'remote-paste.ini'
if (-not (Test-Path -LiteralPath $ini)) { Fail "no $ini (run install-remote-paste.ps1)" }
$cfg = @{ port = '2222'; distro = 'Ubuntu'; laptopDistro = ''; target = '' }
foreach ($line in Get-Content -LiteralPath $ini) {
    if ($line -match '^\s*([A-Za-z]+)\s*=(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
}
if ($cfg.target -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$') { Fail "bad target in $ini" }
if ($cfg.port -notmatch '^\d+$') { Fail "bad port in $ini" }
if ($cfg.distro -notmatch '^[A-Za-z0-9._-]+$') { Fail "bad distro in $ini" }
if ($cfg.laptopDistro -notmatch '^[A-Za-z0-9._-]*$') { Fail "bad laptopDistro in $ini" }

# The bytes, assigned in place: a function returning a byte[] would unroll it.
$bytes = $null
$clip = [System.Windows.Forms.Clipboard]
if ($SelfTest) {
    $device = 'selftest'
    $img = New-Object System.Drawing.Bitmap 1, 1
} else {
    $device = $env:COMPUTERNAME -replace '[^A-Za-z0-9-]', ''
    $img = $null
    if ($clip::ContainsText()) { exit 3 }
    if ($clip::ContainsImage()) {
        $img = $clip::GetImage()
    } elseif ($clip::ContainsFileDropList()) {
        $files = $clip::GetFileDropList()
        if ($files.Count -ne 1 -or $files[0] -notmatch '\.(png|jpe?g|gif|webp)$') { exit 3 }
        $bytes = [System.IO.File]::ReadAllBytes($files[0])
    } else {
        exit 3
    }
}
if ($img) {
    $ms = New-Object System.IO.MemoryStream
    $img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    $bytes = $ms.ToArray()
}
if ($bytes.Length -gt 50MB) { Fail 'image over 50 MB' }

$wsl = @()
if ($cfg.laptopDistro) { $wsl += '-d', $cfg.laptopDistro }
$wsl += '-e', 'ssh', '-p', $cfg.port, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '--',
    $cfg.target, 'wsl.exe', '-d', $cfg.distro, '--cd', '~', '--exec', '.local/bin/paste-inbox',
    'receive', $device
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'wsl.exe'
$psi.Arguments = $wsl -join ' '
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
try {
    $p = [System.Diagnostics.Process]::Start($psi)
} catch {
    Fail "can't start wsl.exe: $($_.Exception.Message)"
}
$out = $p.StandardOutput.ReadToEndAsync()
$err = $p.StandardError.ReadToEndAsync()
try {
    $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $p.StandardInput.Close()
} catch {
    # ssh ended before reading it all (no route, refused): its exit code and stderr say why
}
if (-not $p.WaitForExit(60000)) {
    $p.Kill()
    Fail 'no answer from the PC within 60 s'
}
$path = $out.Result.Trim()
if ($p.ExitCode -ne 0 -or -not $path) {
    $why = ($err.Result -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    if (-not $why) { $why = "ssh exited $($p.ExitCode)" }
    Fail $why.Trim()
}
Write-Output $path
exit 0
