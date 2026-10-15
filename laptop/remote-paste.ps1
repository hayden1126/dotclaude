<#
remote-paste.ps1: send this laptop's clipboard image to the PC's paste inbox (dotclaude
tmux/paste-inbox), so Alt+V in the PC's tmux pastes it into Claude Code.

  powershell -NoProfile -Sta -File remote-paste.ps1             the clipboard's image, or one
                                                                copied image file
  powershell -NoProfile -Sta -File remote-paste.ps1 -SelfTest   a 1x1 PNG, to check the link

remote-paste.ahk runs it on Ctrl+V in a PC tmux tab; install-remote-paste.ps1 runs -SelfTest.
It reads remote-paste.ini beside it (target, port, distro, laptopDistro) and sends the bytes on
stdin through this laptop's WSL ssh (`wsl.exe -e ssh`, so the key, known_hosts and any ssh config
Host the target names are the ones `ssh -p <port> <target>` uses there) to the PC's Windows
shell port, whose cmd.exe runs `wsl.exe -d <distro> --cd ~ --exec .local/bin/paste-inbox receive
<COMPUTERNAME> <bytes>`; the byte count makes the PC refuse a cut upload. -SelfTest sends a 1x1
PNG with `receive --check`, which validates it and keeps nothing. The process is started through
ProcessStartInfo with no argument holding a space or a quote, since Windows PowerShell 5.1
mangles native arguments with embedded quotes, and with a BOM-free console input encoding (put
back right after), since .NET Framework writes the encoding's preamble into a child's stdin at
start (a UTF-8 code page would put EF BB BF before the image). WSL_UTF8=1 makes the laptop
wsl.exe's own errors (it prints them on stdout) UTF-8 like ssh's; the PC's wsl.exe doesn't get
it through ssh, so NULs are dropped from whatever comes back.
BatchMode: a key that needs a passphrase fails at once instead of waiting in a hidden window.
ConnectTimeout 5 s, keepalives every 5 s (a link that dies ends ssh within about 15 s), and 60 s
in all: the upload is written asynchronously, so a stalled pipe can't hold it past that.

Exit 0: stored; prints the PC's path. Exit 3: no image (text, nothing, or not one image file),
so the caller pastes as usual. Exit 1: failed; the reason goes to stderr and to
%TEMP%\remote-paste.err, which remote-paste.ahk shows: ssh's last stderr line, or wsl.exe's
message, with a plain line instead for a PC without paste-inbox or with a different version.
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
if ($cfg.target -notmatch '^([A-Za-z0-9._-]+@)?[A-Za-z0-9._:-]+$') { Fail "bad target in $ini" }
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
if ($bytes.Length -eq 0) { Fail 'the copied file is empty' }
if ($bytes.Length -gt 50MB) { Fail 'image over 50 MB' }

$wsl = @()
if ($cfg.laptopDistro) { $wsl += '-d', $cfg.laptopDistro }
$receive = @('receive')
if ($SelfTest) { $receive += '--check' }
$wsl += '-e', 'ssh', '-p', $cfg.port, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
    '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3', '--', $cfg.target,
    'wsl.exe', '-d', $cfg.distro, '--cd', '~', '--exec', '.local/bin/paste-inbox'
$wsl += $receive + @($device, $bytes.Length)
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
$deadline = [DateTime]::UtcNow.AddSeconds(60)
$out = $p.StandardOutput.ReadToEndAsync()
$err = $p.StandardError.ReadToEndAsync()
$sent = $true
try {
    $sent = $p.StandardInput.BaseStream.WriteAsync($bytes, 0, $bytes.Length).Wait(60000)
    if ($sent) { $p.StandardInput.Close() }
} catch {
    # ssh ended before reading it all (no route, refused): its exit code and stderr say why
}
$left = [int][Math]::Max(0, ($deadline - [DateTime]::UtcNow).TotalMilliseconds)
if (-not $sent -or -not $p.WaitForExit($left)) {
    try { $p.Kill() } catch { }
    Fail 'no answer from the PC within 60 s'
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
