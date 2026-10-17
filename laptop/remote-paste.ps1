<#
remote-paste.ps1: send this laptop's clipboard image, or one copied file, to the PC's paste
inbox (dotclaude tmux/paste-inbox), so Alt+V in the PC's tmux pastes it into Claude Code.

  powershell -NoProfile -Sta -File remote-paste.ps1             the clipboard's image, or one
                                                                copied file of any type
  powershell -NoProfile -Sta -File remote-paste.ps1 -SelfTest   a 1x1 PNG, to check the link

remote-paste.ahk runs it on Ctrl+V in a PC tmux tab; install-remote-paste.ps1 runs -SelfTest.
It reads remote-paste.ini beside it (target, port, distro, laptopDistro) and sends the bytes on
stdin through this laptop's WSL ssh (`wsl.exe -e ssh`, so the key, known_hosts and any ssh config
Host the target names are the ones `ssh -p <port> <target>` uses there) to the PC's Windows
shell port, whose cmd.exe runs `wsl.exe -d <distro> --cd ~ --exec .local/bin/paste-inbox receive
<COMPUTERNAME> <bytes> [<name64>]`; the byte count makes the PC refuse a cut upload. A copied
file that isn't a .png, .jpg, .jpeg, .gif or .webp also sends its name as base64url of its
UTF-8 (<name64>), the one form that crosses this PowerShell's argument joining, the PC's cmd.exe
and wsl.exe untouched; an image sends none, so a PC that predates files still takes it. A
hidden file goes too, and so does a document open in Office (Read-CopiedFile). -SelfTest sends
a 1x1 PNG named selftest.png with `receive --check`, which validates it and keeps nothing, and
so also checks the PC takes names. The process is started through
ProcessStartInfo with no argument holding a space or a quote, since Windows PowerShell 5.1
mangles native arguments with embedded quotes, and with a BOM-free console input encoding (put
back right after), since .NET Framework writes the encoding's preamble into a child's stdin at
start (a UTF-8 code page would put EF BB BF before the image). WSL_UTF8=1 makes the laptop
wsl.exe's own errors (it prints them on stdout) UTF-8 like ssh's; the PC's wsl.exe doesn't get
it through ssh, so NULs are dropped from whatever comes back.
BatchMode: a key that needs a passphrase fails at once instead of waiting in a hidden window.
ConnectTimeout 5 s, keepalives every 5 s (a link that dies ends ssh within about 15 s). The
upload is written asynchronously in 256 KB pieces, each given 30 s, so a stalled pipe fails;
then, since ssh and TCP may still hold the end of the file, the PC gets 30 s plus 1 s per 16 KB
(at most 10 minutes) to answer. So any file up to 50 MB goes over a link that keeps moving at
about 16 KB/s or more.

Exit 0: stored; prints the PC's path. Exit 3: nothing to send (text, nothing, several files or
a folder), so the caller pastes as usual. Exit 1: failed; the reason goes to stderr and to
%TEMP%\remote-paste.err, which remote-paste.ahk shows: ssh's last stderr line, or wsl.exe's
message, with a plain line instead for a PC without paste-inbox or with a different version.
#>
param([switch]$SelfTest)
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$errFile = Join-Path $env:TEMP 'remote-paste.err'
Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue

function Fail([string]$why) {
    Set-Content -LiteralPath $errFile -Value $why -Encoding UTF8
    [Console]::Error.WriteLine("remote-paste: $why")
    exit 1
}
# Anything else that throws (the clipboard held by another app, a locked file) fails the same
# way, so the reason still reaches the tooltip.
trap { Fail $_.Exception.Message }
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

# A file name as base64url of its UTF-8, unpadded: [A-Za-z0-9_-] only.
function Get-Name64([string]$name) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($name))
    return $b64.TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# One copied file's bytes into $into; returns its FileInfo. -Force, or Get-Item -LiteralPath
# can't see a hidden file. Opened shared for writing and deleting too, as Explorer copies, so a
# document open in Office still goes (a read that shares only reading would refuse it). The size
# is the opened stream's, checked before any byte is read: a symlink's FileInfo says 0 while
# File.Open follows the link.
function Read-CopiedFile([string]$path, [System.IO.MemoryStream]$into) {
    $file = Get-Item -LiteralPath $path -Force
    $stream = [System.IO.File]::Open($file.FullName, 'Open', 'Read', 'ReadWrite, Delete')
    try {
        if ($stream.Length -gt 50MB) { Fail "$($file.Name) is over 50 MB" }
        $stream.CopyTo($into)
    } finally {
        $stream.Dispose()
    }
    return $file
}

$ini = Join-Path $PSScriptRoot 'remote-paste.ini'
if (-not (Test-Path -LiteralPath $ini)) { Fail "no $ini (run install-remote-paste.ps1)" }
$cfg = @{ port = '2222'; distro = 'Ubuntu'; laptopDistro = ''; target = '' }
foreach ($line in Get-Content -LiteralPath $ini) {
    if ($line -match '^\s*([A-Za-z]+)\s*=(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
}
if ($cfg.target -notmatch '^([A-Za-z0-9._-]+@)?[A-Za-z0-9._:-]+$') { Fail "bad target in $ini" }
if ($cfg.port -notmatch '^\d+$') { Fail "bad port in $ini" }
if ($cfg.distro -notmatch '^[A-Za-z0-9._-]+$') { Fail "bad distro in $ini" }
if ($cfg.laptopDistro -notmatch '^[A-Za-z0-9._-]*$') { Fail "bad laptopDistro in $ini" }

# The bytes, assigned in place: a function returning a byte[] would unroll it.
$bytes = $null
$name64 = ''
$clip = [System.Windows.Forms.Clipboard]
$ms = New-Object System.IO.MemoryStream
if ($SelfTest) {
    $device = 'selftest'
    $img = New-Object System.Drawing.Bitmap 1, 1
    $name64 = Get-Name64 'selftest.png'
} else {
    $device = $env:COMPUTERNAME -replace '[^A-Za-z0-9-]', ''
    $img = $null
    if ($clip::ContainsText()) { exit 3 }
    if ($clip::ContainsImage()) {
        $img = $clip::GetImage()
        if (-not $img) { exit 3 }
    } elseif ($clip::ContainsFileDropList()) {
        # -LiteralPath throughout: -Path reads notes[1].txt as a wildcard
        $files = $clip::GetFileDropList()
        if ($files.Count -ne 1) { exit 3 }
        if (-not (Test-Path -LiteralPath $files[0] -PathType Leaf)) { exit 3 }
        $file = Read-CopiedFile $files[0] $ms
        if ($file.Extension -notmatch '^\.(png|jpe?g|gif|webp)$') {
            $name64 = Get-Name64 $file.Name
        }
    } else {
        exit 3
    }
}
if ($img) {
    $img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
}
$bytes = $ms.ToArray()
if ($bytes.Length -eq 0) { Fail 'the copied file is empty' }
if ($bytes.Length -gt 50MB) { Fail 'over 50 MB' }

$wsl = @()
if ($cfg.laptopDistro) { $wsl += '-d', $cfg.laptopDistro }
$receive = @('receive')
if ($SelfTest) { $receive += '--check' }
$wsl += '-e', 'ssh', '-p', $cfg.port, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
    '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3', '--', $cfg.target,
    'wsl.exe', '-d', $cfg.distro, '--cd', '~', '--exec', '.local/bin/paste-inbox'
$wsl += $receive + @($device, $bytes.Length)
if ($name64) { $wsl += $name64 }
$oldInput = $null
try {
    $oldInput = [Console]::InputEncoding
    [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false
} catch {
    # no console to set (the encoding then has no preamble either)
}
$utf8 = New-Object System.Text.UTF8Encoding $false
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'wsl.exe'
$psi.Arguments = $wsl -join ' '
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = $utf8
$psi.StandardErrorEncoding = $utf8
$psi.EnvironmentVariables['WSL_UTF8'] = '1'
try {
    $p = [System.Diagnostics.Process]::Start($psi)
} catch {
    Fail "can't start wsl.exe: $($_.Exception.Message)"
} finally {
    # the console may be the caller's (the installer's window): give its code page back
    if ($oldInput) { try { [Console]::InputEncoding = $oldInput } catch { } }
}
$out = $p.StandardOutput.ReadToEndAsync()
$err = $p.StandardError.ReadToEndAsync()
$sent = $true
try {
    $in = $p.StandardInput.BaseStream
    for ($at = 0; $sent -and $at -lt $bytes.Length; $at += 256KB) {
        $n = [Math]::Min(256KB, $bytes.Length - $at)
        $sent = $in.WriteAsync($bytes, $at, $n).Wait(30000)
    }
    if ($sent) { $p.StandardInput.Close() }
} catch {
    # ssh ended before reading it all (no route, refused): its exit code and stderr say why
}
if (-not $sent) {
    try { $p.Kill() } catch { }
    Fail 'the upload stalled: nothing moved for 30 s'
}
# ssh and TCP may still hold up to the whole file after its last piece: 30 s plus 1 s per
# 16 KB to drain it, at most 10 minutes; ssh's keepalives end a dead link long before that
$wait = [int][Math]::Min(600000, 30000 + $bytes.Length / 16KB * 1000)
if (-not $p.WaitForExit($wait)) {
    try { $p.Kill() } catch { }
    Fail "no answer from the PC within $([int]($wait / 1000)) s of the upload"
}
$path = $out.Result.Trim()
if ($p.ExitCode -ne 0 -or -not $path) {
    # ssh's reason is stderr's last line; wsl.exe's own (a bad distro, say) is all of stdout,
    # UTF-16 from the PC's wsl.exe, which WSL_UTF8 doesn't reach
    $stderr = $err.Result -replace "`0", ''
    $stdout = $out.Result -replace "`0", ''
    if ($stderr -match 'execvpe\(\.local/bin/paste-inbox\) failed') {
        Fail 'the PC has no ~/.local/bin/paste-inbox: run setup-tmux.sh there'
    }
    if ($stderr -match '(?m)^usage:') {
        Fail "the PC's paste-inbox doesn't match this laptop's remote-paste: update both"
    }
    $why = $stderr -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1
    if (-not $why) {
        $why = ($stdout -split "`r?`n" | ForEach-Object { $_.Trim() } |
            Where-Object { $_ }) -join ' '
    }
    if (-not $why) { $why = "ssh exited $($p.ExitCode)" }
    Fail $why.Trim()
}
Write-Output $path
exit 0
