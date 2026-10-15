# chrome-bg.ps1: the Windows half of bin/chrome-bg. One supervisor per run starts Windows Chrome
# so that its windows never take the foreground and stay behind all other windows, watches the
# run's windows through WinEvent hooks, and kills the run's Chrome when its owner goes away.
# Usage and background: docs/chrome-devtools-wsl.md. Windows PowerShell 5.1; keep this file ASCII.
#
# Invocation (bin/chrome-bg runs it sandbox-off, one per run):
#   powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File chrome-bg.ps1 -Id <id> [-Keep]
#   ... -File chrome-bg.ps1 -Id <id> -Kill   kill the run's chrome.exe, delete its dir, print one JSON line
#   ... -File chrome-bg.ps1 -Scan            print run dirs, logs and chrome.exe by run id as one JSON line
# <id> is 8 lowercase hex. Under <temp>\chrome-bg\ ([IO.Path]::GetTempPath()): the run dir <id>\ (the
# profile goes in <id>\profile) and the log <id>.log, which outlives the run. A chrome.exe belongs
# to the run when its command line holds \chrome-bg\<id>\ (in any case).
#
# Protocol: one JSON request per stdin line, exactly one compact JSON reply line per request.
#   {"op":"hello"}                      ok, version 1, chrome, runDir, virtualScreen, monitors
#                                       [{rect, work, dpi, hz, primary}], fg, fglock
#   {"op":"launch","args":"..."}        ok, pid. The args must hold the run dir.
#   {"op":"place","x":..,"y":..,"w":..,"h":..}  ok, windows [{hwnd, rect}], rects read after the move
#   {"op":"procs"}                      ok, procs [{pid, ppid, type}]
#   {"op":"fg"}                         ok, fg {hwnd, pid, cls, rect, visible, iconic, cloaked, tagged, idleMs}
#   {"op":"mark","text":"..."}          ok (logs MARK)
#   Failures reply {"ok":false,"error":"..."}. Rects are {x, y, w, h} in physical pixels. Replies
#   are ASCII: other characters go out as \uXXXX escapes.
#   EOF on stdin: kill every chrome.exe of the run, delete the run dir, log, exit. No reply.
# Log lines read t=<ms> KIND ...; bin/chrome-bg's log judge parses the kinds.
#
# Rules from the Phase 0 probes, each pinned by tests/setup/test_chrome_bg_ps1.py:
# - Launch Chrome through WMI (Win32_Process Create), never Start-Process. Started from this
#   console-attached process, Chrome inherited foreground rights and took the foreground from
#   the user's terminal for about 45 s (probes A and K); started through WMI it took none (W).
# - Stdout carries replies only, all through Send-Reply. A stdout write after the owner died
#   killed the supervisor and left 8 chrome.exe running (probe C2). Events go to the log file.
# - No WMI or CIM in the WinEvent callback or anything it calls: the call pumps messages and
#   re-enters the callback, which crashed the first prototype. Run pids come from the launch pid
#   plus a refresh thread.
# - Each new run frame sinks to HWND_BOTTOM, unactivated, at EVENT_OBJECT_CREATE while it is still
#   hidden. Off-screen bounds alone left a 7-9 ms flash on top of the screen.
# - With -Keep, while no run window has the foreground, a run window seen above another on-screen
#   window sinks to HWND_BOTTOM, unactivated (KEEP-SINK), at most 20 times per window per second.
# - Window titles reach the log only for run windows: the repo is public, other titles are not ours.

[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
  # (?-i): ValidatePattern ignores case unless told otherwise. \z: $ would accept a trailing newline.
  [Parameter(Mandatory, ParameterSetName = 'Run')]
  [Parameter(Mandatory, ParameterSetName = 'Kill')]
  [ValidatePattern('^(?-i)[0-9a-f]{8}\z')]
  [string]$Id,
  [Parameter(ParameterSetName = 'Run')]
  [switch]$Keep,
  [Parameter(Mandatory, ParameterSetName = 'Kill')]
  [switch]$Kill,
  [Parameter(Mandatory, ParameterSetName = 'Scan')]
  [switch]$Scan
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Join-Path ([IO.Path]::GetTempPath()) 'chrome-bg'

# The one stdout writer. Every reply is a single compact JSON line.
function Send-Reply([System.Collections.IDictionary]$Reply) {
  $json = ConvertTo-Json -InputObject $Reply -Compress -Depth 6
  $json = [regex]::Replace($json, '[^\x00-\x7F]', [Text.RegularExpressions.MatchEvaluator] {
      param($m) '\u{0:x4}' -f [int][char]$m.Value })
  try { [Console]::Out.WriteLine($json); [Console]::Out.Flush() } catch { }
}

function New-ErrorReply([string]$Message) {
  return [ordered]@{ ok = $false; error = $Message }
}

# The lookup chrome-debug.ps1 uses.
function Find-Chrome {
  $candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
  )
  return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Get-TaggedProcs {
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($Tag, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
}

function ConvertTo-ProcInfo($Proc) {
  $type = if ($Proc.CommandLine -match '--type=(\S+)') { $Matches[1] } else { 'browser' }
  return [ordered]@{ pid = [int]$Proc.ProcessId; ppid = [int]$Proc.ParentProcessId; type = $type }
}

# Kills every chrome.exe of the run, for up to about 5 s.
function Stop-RunProcs {
  $killed = [System.Collections.Generic.HashSet[int]]::new()
  foreach ($round in 1..20) {
    $procs = @(Get-TaggedProcs)
    if ($procs.Count -eq 0) { break }
    foreach ($p in $procs) {
      try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; [void]$killed.Add([int]$p.ProcessId) } catch { }
    }
    Start-Sleep -Milliseconds 250
  }
  return [ordered]@{ killed = $killed.Count; left = @(Get-TaggedProcs).Count }
}

# Deletes the run dir, retrying while Chrome's last files close. Returns whether it still exists.
function Remove-RunDir {
  foreach ($round in 1..20) {
    if (-not (Test-Path -LiteralPath $RunDir)) { break }
    try { Remove-Item -LiteralPath $RunDir -Recurse -Force -ErrorAction Stop } catch { Start-Sleep -Milliseconds 250 }
  }
  return (Test-Path -LiteralPath $RunDir)
}

function Close-Run {
  [ChromeBgSup]::Log('EOF')
  try {
    $k = Stop-RunProcs
    [ChromeBgSup]::Log("EOFKILL left=$($k.left) killed=$($k.killed)")
    [ChromeBgSup]::Log("EOFCLEAN dirExists=$(Remove-RunDir)")
  } catch { [ChromeBgSup]::Log('ERROR eof ' + ($_.Exception.Message -replace '[\r\n]+', ' ')) }
}

# Answers one request line. Returns the reply; never writes stdout.
function Invoke-Op([string]$Line) {
  try { $req = ConvertFrom-Json -InputObject $Line } catch { return New-ErrorReply 'bad json' }
  $op = $req.op
  if ($op -isnot [string]) { return New-ErrorReply 'bad request: no op' }
  switch -CaseSensitive ($op) {
    'hello' {
      if (-not $Chrome) { return New-ErrorReply 'chrome.exe not found' }
      return [ordered]@{
        ok = $true; version = 1; chrome = $Chrome; runDir = $RunDir
        virtualScreen = [ChromeBgSup]::VirtualScreen()
        monitors = @([ChromeBgSup]::Monitors())
        fg = [ChromeBgSup]::FgInfo()
        fglock = [long][ChromeBgSup]::FgLock()
      }
    }
    'launch' {
      if (-not $Chrome) { return New-ErrorReply 'chrome.exe not found' }
      $a = $req.args
      if ($a -isnot [string]) { return New-ErrorReply 'launch needs args, a string' }
      # Untagged processes would escape the EOF kill.
      if ($a.IndexOf($Tag, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return New-ErrorReply "launch args must hold the run dir ($Tag)" }
      $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "`"$Chrome`" $a" }
      if ($r.ReturnValue -ne 0) {
        [ChromeBgSup]::Log("LAUNCHED failed rv=$($r.ReturnValue) via=wmi")
        return [ordered]@{ ok = $false; error = 'Win32_Process Create failed'; code = [int]$r.ReturnValue }
      }
      [ChromeBgSup]::AddPid([uint32]$r.ProcessId)
      [ChromeBgSup]::Log("LAUNCHED pid=$($r.ProcessId) via=wmi chrome=$Chrome")
      return [ordered]@{ ok = $true; pid = [int]$r.ProcessId }
    }
    'place' {
      foreach ($key in 'x', 'y', 'w', 'h') {
        if ($null -eq $req.$key) { return New-ErrorReply 'place needs x, y, w and h' }
      }
      if ([int]$req.w -le 0 -or [int]$req.h -le 0) { return New-ErrorReply 'place needs a positive w and h' }
      return [ordered]@{ ok = $true; windows = @([ChromeBgSup]::Place([int]$req.x, [int]$req.y, [int]$req.w, [int]$req.h)) }
    }
    'procs' {
      $list = @(Get-TaggedProcs | ForEach-Object { ConvertTo-ProcInfo $_ })
      foreach ($p in $list) { [ChromeBgSup]::Log("PROC pid=$($p.pid) ppid=$($p.ppid) type=$($p.type)") }
      [ChromeBgSup]::Log("PROCS count=$($list.Count)")
      return [ordered]@{ ok = $true; procs = $list }
    }
    'fg' {
      return [ordered]@{ ok = $true; fg = [ChromeBgSup]::FgInfo() }
    }
    'mark' {
      $text = [string]$req.text -replace '[\r\n]+', ' '
      [ChromeBgSup]::Log("MARK $text idle=$([ChromeBgSup]::Idle())")
      return [ordered]@{ ok = $true }
    }
    default { return New-ErrorReply "unknown op: $op" }
  }
}

function Get-Scan {
  $now = [DateTime]::UtcNow
  $dirs = @()
  $logs = @()
  if (Test-Path -LiteralPath $Root) {
    $dirs = @(Get-ChildItem -LiteralPath $Root -Directory | Where-Object { $_.Name -cmatch '^[0-9a-f]{8}$' } | ForEach-Object {
        [ordered]@{ id = $_.Name; createdUtc = $_.CreationTimeUtc.ToString('o'); ageSec = [long][Math]::Floor(($now - $_.CreationTimeUtc).TotalSeconds) } })
    $logs = @(Get-ChildItem -LiteralPath $Root -File -Filter '*.log' | Where-Object { $_.Name -cmatch '^[0-9a-f]{8}\.log$' } | ForEach-Object {
        [ordered]@{ id = $_.BaseName; ageSec = [long][Math]::Floor(($now - $_.LastWriteTimeUtc).TotalSeconds) } })
  }
  $procs = [ordered]@{}
  foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")) {
    if (-not $p.CommandLine) { continue }
    $m = [regex]::Match($p.CommandLine, '\\chrome-bg\\([0-9a-f]{8})\\', 'IgnoreCase')
    if (-not $m.Success) { continue }
    $runId = $m.Groups[1].Value.ToLowerInvariant()
    if (-not $procs.Contains($runId)) { $procs[$runId] = [System.Collections.Generic.List[object]]::new() }
    $procs[$runId].Add((ConvertTo-ProcInfo $p))
  }
  return [ordered]@{ ok = $true; root = $Root; dirs = $dirs; logs = $logs; procs = $procs }
}

if ($Scan) {
  try { Send-Reply (Get-Scan) } catch { Send-Reply (New-ErrorReply $_.Exception.Message) }
  exit 0
}

$RunDir = Join-Path $Root $Id
$LogFile = Join-Path $Root "$Id.log"
$Tag = "\chrome-bg\$Id\"

if ($Kill) {
  try {
    $k = Stop-RunProcs
    $exists = Remove-RunDir
    Send-Reply ([ordered]@{ ok = ($k.left -eq 0 -and -not $exists); killed = $k.killed; left = $k.left; dirExists = $exists })
  } catch { Send-Reply (New-ErrorReply $_.Exception.Message) }
  exit 0
}

[void](New-Item -ItemType Directory -Path $RunDir -Force)
$Chrome = Find-Chrome

Add-Type -ReferencedAssemblies System.Management -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
using System.Collections.Specialized; using System.Threading; using System.Management; using System.Diagnostics; using System.IO;
public static class ChromeBgSup {
  public delegate void WinEventProc(IntPtr hook, uint ev, IntPtr hwnd, int idObject, int idChild, uint thread, uint time);
  public delegate bool MonitorEnumProc(IntPtr hMon, IntPtr hdc, ref RECT r, IntPtr data);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct MSG { public IntPtr hwnd; public uint message; public IntPtr wParam; public IntPtr lParam; public uint time; public int x; public int y; }
  [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct MONITORINFOEX { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szDevice; }
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra; public int dmFields;
    public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
    public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight; }
  [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr hmod, WinEventProc cb, uint pid, uint tid, uint flags);
  [DllImport("user32.dll")] static extern uint MsgWaitForMultipleObjectsEx(uint n, IntPtr[] h, uint ms, uint wake, uint flags);
  [DllImport("user32.dll")] static extern bool PeekMessage(out MSG m, IntPtr h, uint min, uint max, uint remove);
  [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG m);
  [DllImport("user32.dll")] static extern IntPtr DispatchMessage(ref MSG m);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern IntPtr MonitorFromRect(ref RECT r, uint flags);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] static extern IntPtr GetTopWindow(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr h, uint flags);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int idx);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO l);
  [DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] static extern bool SystemParametersInfo(uint a, uint b, ref uint v, uint c);
  [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc cb, IntPtr data);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool GetMonitorInfo(IntPtr hMon, ref MONITORINFOEX mi);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumDisplaySettings(string dev, int mode, ref DEVMODE dm);
  [DllImport("shcore.dll")] static extern int GetDpiForMonitor(IntPtr hMon, int type, out uint dx, out uint dy);
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int attr, out int v, int size);

  static readonly IntPtr HWND_BOTTOM = (IntPtr)1;
  const uint SWP_NOSIZE = 0x1, SWP_NOMOVE = 0x2, SWP_NOACTIVATE = 0x10;
  // What the stdin reader queues at end of input.
  public const string EofLine = "\u0000EOF";

  static readonly object gate = new object();
  static Stopwatch sw = Stopwatch.StartNew();
  static string tag; static StreamWriter file; static bool keeper;
  static Dictionary<uint, bool> tagged = new Dictionary<uint, bool>();
  static WinEventProc keep; static volatile bool done; static Queue<string> cmds = new Queue<string>();
  static string lastFg = "", lastTop = "", lastRanks = "";

  // Events go to the log file only; this class never writes stdout or stderr.
  public static void Log(string s) {
    string line = "t=" + sw.ElapsedMilliseconds + " " + s;
    lock (gate) { try { if (file != null) { file.WriteLine(line); file.Flush(); } } catch { } }
  }
  static string OneLine(string s) { return s == null ? "" : s.Replace('\r', ' ').Replace('\n', ' '); }
  static uint Pid(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return p; }
  static string Title(IntPtr h) { var s = new StringBuilder(256); GetWindowText(h, s, 256); return s.ToString(); }
  static string Cls(IntPtr h) { var s = new StringBuilder(128); GetClassName(h, s, 128); return s.ToString(); }
  static bool Cloaked(IntPtr h) { int v; return DwmGetWindowAttribute(h, 14, out v, 4) == 0 && v != 0; }
  public static uint Idle() { var l = new LASTINPUTINFO(); l.cbSize = 8; GetLastInputInfo(ref l); return (uint)Environment.TickCount - l.dwTime; }
  public static uint FgLock() { uint v = 0; SystemParametersInfo(0x2000, 0, ref v, 0); return v; }
  // A set lookup only: WMI on the hook thread pumps messages and re-enters the callback.
  public static bool IsTagged(uint pid) { lock (tagged) { return tagged.ContainsKey(pid); } }
  public static void AddPid(uint pid) { lock (tagged) { tagged[pid] = true; } }
  // Tags every chrome.exe holding the run's tag, twice a second, on its own MTA thread.
  static void Refresh() {
    var t = new Thread(delegate() {
      while (!done) {
        try {
          using (var s = new ManagementObjectSearcher("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='chrome.exe'"))
            foreach (ManagementObject o in s.Get()) {
              var cl = o["CommandLine"] as string;
              if (cl != null && cl.IndexOf(tag, StringComparison.OrdinalIgnoreCase) >= 0) AddPid((uint)o["ProcessId"]);
            }
        } catch { }
        Thread.Sleep(500);
      }
    });
    t.IsBackground = true; t.SetApartmentState(ApartmentState.MTA); t.Start();
  }
  static bool OnScreen(IntPtr h, out RECT r) { GetWindowRect(h, out r); return MonitorFromRect(ref r, 0) != IntPtr.Zero; }
  static string Ltrb(RECT r) { return r.L + "," + r.T + "," + r.R + "," + r.B; }
  static string Desc(IntPtr h) {
    RECT r; bool on = OnScreen(h, out r); uint p = Pid(h);
    string s = "hwnd=" + h + " pid=" + p + " cls=" + Cls(h) + " rect=" + Ltrb(r) +
      " onscreen=" + (on ? 1 : 0) + " vis=" + (IsWindowVisible(h) ? 1 : 0) + " iconic=" + (IsIconic(h) ? 1 : 0) +
      " cloaked=" + (Cloaked(h) ? 1 : 0);
    // Titles only for run windows: every other title belongs to the user's own work.
    if (IsTagged(p)) s += " title='" + Title(h) + "'";
    return s;
  }
  // Windows a person can see: visible, titled, not cloaked, not minimized, not a tool window, on a monitor.
  static List<IntPtr> Seen() {
    var l = new List<IntPtr>();
    for (IntPtr h = GetTopWindow(IntPtr.Zero); h != IntPtr.Zero; h = GetWindow(h, 2)) {
      if (!IsWindowVisible(h) || IsIconic(h) || Cloaked(h)) continue;
      if ((GetWindowLong(h, -20) & 0x80) != 0) continue;
      if (Title(h).Length == 0) continue;
      RECT r; if (!OnScreen(h, out r)) continue;
      l.Add(h);
    }
    return l;
  }
  static bool inKeep;
  static Dictionary<IntPtr, long[]> keepRate = new Dictionary<IntPtr, long[]>();   // hwnd -> [window start ms, sinks]
  static void KeepSink(IntPtr h, string why) {
    long now = sw.ElapsedMilliseconds; long[] r;
    if (!keepRate.TryGetValue(h, out r) || now - r[0] >= 1000) { r = new long[] { now, 0 }; keepRate[h] = r; }
    if (++r[1] > 20) { if (r[1] == 21) Log("KEEP-FIGHT hwnd=" + h + " via=" + why); return; }
    bool ok = SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE);
    Log("KEEP-SINK ok=" + ok + " via=" + why + " " + Desc(h));
  }
  static void Check(string why) {
    IntPtr fg = GetForegroundWindow(); uint fp = Pid(fg);
    string f = fg + "/" + fp;
    if (f != lastFg) { lastFg = f; Log("FOREGROUND tagged=" + (IsTagged(fp) ? 1 : 0) + " idle=" + Idle() + " via=" + why + " " + Desc(fg)); }
    var seen = Seen();
    string top = seen.Count > 0 ? seen[0].ToString() : "none";
    if (top != lastTop) { lastTop = top; Log("TOP tagged=" + (seen.Count > 0 && IsTagged(Pid(seen[0])) ? 1 : 0) + " via=" + why + " " + (seen.Count > 0 ? Desc(seen[0]) : "none")); }
    var sb = new StringBuilder();
    var sink = new List<IntPtr>();
    for (int i = 0; i < seen.Count; i++) {
      if (!IsTagged(Pid(seen[i]))) continue;
      int below = 0; for (int j = i + 1; j < seen.Count; j++) if (!IsTagged(Pid(seen[j]))) below++;
      sb.Append(" [" + seen[i] + " rank=" + i + "/" + seen.Count + " aboveOthers=" + below + "]");
      if (keeper && below > 0 && !IsTagged(fp)) sink.Add(seen[i]);
    }
    string ranks = sb.ToString();
    if (ranks != lastRanks) { lastRanks = ranks; Log("RANKS via=" + why + (ranks.Length > 0 ? ranks : " none-onscreen")); }
    // A cross-thread SetWindowPos may dispatch incoming events, so Check can re-enter here.
    if (sink.Count == 0 || inKeep) return;
    inKeep = true;
    try { foreach (var h in sink) KeepSink(h, why); } finally { inKeep = false; }
  }
  static HashSet<IntPtr> sunk = new HashSet<IntPtr>();
  // A browser frame: unowned, with a caption (menus, bubbles and tooltips are owned popups).
  static bool IsFrame(IntPtr h) { return GetWindow(h, 4) == IntPtr.Zero && (GetWindowLong(h, -16) & 0x00C00000) == 0x00C00000; }
  // Events: 0x3 foreground, 0x16/0x17 minimize start/end, 0x8000 create, 0x8001 destroy, 0x8002 show,
  // 0x8003 hide, 0x8004 reorder, 0x800B location change, 0x8017/0x8018 cloak/uncloak.
  static void OnEvent(IntPtr hook, uint ev, IntPtr h, int obj, int child, uint thread, uint time) {
    if (ev == 3) { Check("ev-foreground"); return; }
    if (obj != 0 || child != 0 || h == IntPtr.Zero) { if (ev == 0x8004) Check("ev-reorder"); return; }
    if (GetAncestor(h, 2) != h) return;
    if (!IsTagged(Pid(h))) { if (ev == 0x8002 || ev == 0x8004 || ev == 0x800B) Check("ev-other-" + ev.ToString("x")); return; }
    // Sink a new frame while it is still hidden: an unactivated show keeps its z-order slot.
    if ((ev == 0x8000 || ev == 0x800B) && !IsWindowVisible(h) && !sunk.Contains(h) && IsFrame(h)) {
      sunk.Add(h);
      bool ok = SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE);
      Log("SINK-AT-CREATE ok=" + ok + " ev=" + ev.ToString("x") + " style=" + GetWindowLong(h, -16).ToString("x") + " " + Desc(h));
    }
    string name;
    switch (ev) { case 0x8000: return; case 0x8001: name = "DESTROY"; break; case 0x8002: name = "SHOW"; break;
      case 0x8003: name = "HIDE"; break; case 0x8004: name = "REORDER"; break; case 0x800B: name = "LOCATION"; break;
      case 0x16: name = "MINSTART"; break; case 0x17: name = "MINEND"; break; case 0x8017: name = "CLOAK"; break; case 0x8018: name = "UNCLOAK"; break;
      default: return; }
    if (ev == 0x800B) { RECT r; GetWindowRect(h, out r); Log("EV " + name + " hwnd=" + h + " rect=" + Ltrb(r)); }
    else Log("EV " + name + " " + (ev == 0x8001 ? "hwnd=" + h : Desc(h)));
    Check("ev-" + name);
  }

  class Mon { public string Dev; public RECT Rc, Work; public uint Dpi; public int Hz; public bool Primary; }
  static List<Mon> EnumMonitors() {
    var l = new List<Mon>();
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, delegate(IntPtr m, IntPtr hdc, ref RECT rr, IntPtr d) {
      var mi = new MONITORINFOEX(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX)); GetMonitorInfo(m, ref mi);
      uint dx, dy; GetDpiForMonitor(m, 0, out dx, out dy);
      var dm = new DEVMODE(); dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE)); EnumDisplaySettings(mi.szDevice, -1, ref dm);
      var o = new Mon(); o.Dev = mi.szDevice; o.Rc = mi.rcMonitor; o.Work = mi.rcWork; o.Dpi = dx; o.Hz = dm.dmDisplayFrequency; o.Primary = (mi.dwFlags & 1) != 0;
      l.Add(o);
      return true; }, IntPtr.Zero);
    return l;
  }
  static void Env() {
    Log("VSCREEN " + GetSystemMetrics(76) + " " + GetSystemMetrics(77) + " " + GetSystemMetrics(78) + " " + GetSystemMetrics(79));
    Log("FGLOCK " + FgLock() + " idle=" + Idle());
    foreach (var m in EnumMonitors())
      Log("MONITOR " + m.Dev + " rect=" + Ltrb(m.Rc) + " work=" + Ltrb(m.Work) + " primary=" + (m.Primary ? 1 : 0) + " dpi=" + m.Dpi + " hz=" + m.Hz);
  }

  // Reply pieces, as dictionaries for the script's ConvertTo-Json.
  static OrderedDictionary D(params object[] kv) {
    var d = new OrderedDictionary();
    for (int i = 0; i + 1 < kv.Length; i += 2) d.Add(kv[i], kv[i + 1]);
    return d;
  }
  static OrderedDictionary Xywh(RECT r) { return D("x", r.L, "y", r.T, "w", r.R - r.L, "h", r.B - r.T); }
  public static OrderedDictionary VirtualScreen() { return D("x", GetSystemMetrics(76), "y", GetSystemMetrics(77), "w", GetSystemMetrics(78), "h", GetSystemMetrics(79)); }
  public static object[] Monitors() {
    var l = new List<object>();
    foreach (var m in EnumMonitors()) l.Add(D("rect", Xywh(m.Rc), "work", Xywh(m.Work), "dpi", (long)m.Dpi, "hz", m.Hz, "primary", m.Primary));
    return l.ToArray();
  }
  public static OrderedDictionary FgInfo() {
    IntPtr h = GetForegroundWindow(); RECT r; GetWindowRect(h, out r); uint p = Pid(h);
    return D("hwnd", h.ToInt64(), "pid", (long)p, "cls", Cls(h), "rect", Xywh(r), "visible", IsWindowVisible(h),
      "iconic", IsIconic(h), "cloaked", Cloaked(h), "tagged", IsTagged(p), "idleMs", (long)Idle());
  }
  // Every visible run frame to HWND_BOTTOM at x,y and w by hgt, unactivated.
  public static object[] Place(int x, int y, int w, int hgt) {
    // Collect first: a window moved to the bottom ends a GetWindow(next) walk early.
    var frames = new List<IntPtr>();
    for (IntPtr h = GetTopWindow(IntPtr.Zero); h != IntPtr.Zero; h = GetWindow(h, 2))
      if (IsWindowVisible(h) && IsTagged(Pid(h)) && IsFrame(h)) frames.Add(h);
    var l = new List<object>(); var sb = new StringBuilder();
    foreach (var h in frames) {
      bool ok = SetWindowPos(h, HWND_BOTTOM, x, y, w, hgt, SWP_NOACTIVATE);
      RECT r; GetWindowRect(h, out r);
      l.Add(D("hwnd", h.ToInt64(), "rect", Xywh(r)));
      sb.Append(" [" + ok + " " + Desc(h) + "]");
    }
    Log("PLACE" + sb);
    return l.ToArray();
  }

  static void Push(string c) { lock (cmds) cmds.Enqueue(c); }
  static string Pop() { lock (cmds) return cmds.Count > 0 ? cmds.Dequeue() : null; }
  // Per-monitor DPI awareness (v2) for this thread, which then runs Loop: geometry is in physical pixels.
  public static void Start(string t, string logFile, bool keepOn) {
    tag = t; keeper = keepOn;
    file = new StreamWriter(logFile, true);
    SetThreadDpiAwarenessContext((IntPtr)(-4));
    Env();
    Refresh();
  }
  // Runs on the calling thread: hooks plus a message loop, polling every 50 ms, until EOF.
  public static void Loop(Func<string, bool> handle) {
    keep = new WinEventProc(OnEvent);
    SetWinEventHook(0x3, 0x3, IntPtr.Zero, keep, 0, 0, 2);
    SetWinEventHook(0x16, 0x17, IntPtr.Zero, keep, 0, 0, 2);
    SetWinEventHook(0x8000, 0x800B, IntPtr.Zero, keep, 0, 0, 2);
    SetWinEventHook(0x8017, 0x8018, IntPtr.Zero, keep, 0, 0, 2);
    Log("READY");
    Check("start");
    while (!done) {
      MsgWaitForMultipleObjectsEx(0, null, 50, 0x4FF, 0);
      MSG m; while (PeekMessage(out m, IntPtr.Zero, 0, 0, 1)) { TranslateMessage(ref m); DispatchMessage(ref m); }
      Check("poll");
      string c;
      while ((c = Pop()) != null) {
        bool more;
        try { more = handle(c); } catch (Exception e) { Log("ERROR handler " + e.GetType().Name + " " + OneLine(e.Message)); more = true; }
        // EOF ends the run even if its handler failed: the supervisor must not outlive its owner.
        if (!more || c == EofLine) { done = true; break; }
      }
    }
  }
  public static void ReadStdin() {
    var t = new Thread(delegate() {
      try { string l; while ((l = Console.In.ReadLine()) != null) Push(l); } catch { }
      Push(EofLine);
    });
    t.IsBackground = true; t.Start();
  }
}
'@

[ChromeBgSup]::Start($Tag, $LogFile, [bool]$Keep)
[ChromeBgSup]::ReadStdin()
# Runs on the hook thread between message pumps, never inside the WinEvent callback, so the ops
# may call WMI. Exactly one reply per request line.
$handler = [Func[string, bool]] {
  param([string]$Line)
  if ($Line -ceq [ChromeBgSup]::EofLine) { Close-Run; return $false }
  try { $reply = Invoke-Op $Line } catch { $reply = New-ErrorReply $_.Exception.Message }
  if ($reply -isnot [System.Collections.IDictionary]) { $reply = New-ErrorReply 'internal: an op emitted stray output' }
  Send-Reply $reply
  return $true
}
[ChromeBgSup]::Loop($handler)
[ChromeBgSup]::Log('EXIT')
