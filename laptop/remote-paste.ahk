; remote-paste.ahk: Ctrl+V of a screenshot or a copied file in a PC tmux tab sends it to the PC
; and pastes it.
;
; Claude Code on the PC (WSL) reads the PC's own clipboard on Ctrl+V, so a screenshot copied on
; this laptop never arrives. This takes Ctrl+V only while three things hold: Windows Terminal is
; the active window, its title matches the `title` pattern in remote-paste.ini (default
; ^view-\d+\s: the PC's tmux titles a remote device's session view-<pid>, set-titles-string
; "#S · ..." in dotclaude tmux/claude.conf), and the clipboard holds an image (CF_DIB) or one copied
; file of any type (CF_HDROP), and no text. Otherwise Ctrl+V never reaches this script. That check
; reads no disk, since it runs inside the keyboard hook on every Ctrl+V in a PC tab (a dead
; network share can block for seconds, and Windows drops a hook that stalls), so a copied folder
; gets Windows Terminal's own paste from the hotkey. Otherwise it runs remote-paste.ps1 hidden,
; which uploads the image or file to the PC's inbox; then it sends Alt+V, which the PC's tmux
; turns into a bracketed paste of its path there (tmux/paste-inbox): Claude Code attaches an
; image, and reads another file when asked. remote-paste.ps1 exiting 3 (the clipboard changed
; under it, or the file is gone) gives Windows Terminal its own paste; a failure shows its reason
; in a tooltip. Alt+V or that paste goes only to the tab that was pressed: if another window or
; tab (another view-<pid>) took focus during the upload, the tooltip says so instead.
; Installed into %LOCALAPPDATA%\remote-paste, with a Startup shortcut, by
; install-remote-paste.ps1.

#Requires AutoHotkey v2.0
#SingleInstance Force

TitlePattern := IniRead(A_ScriptDir "\remote-paste.ini", "remote-paste", "title", "^view-\d+\s")

; The PC tmux view the window shows (the title's match, e.g. "view-2313 "), or "" for none.
PcView(hwnd) {
    global TitlePattern
    return hwnd && RegExMatch(WinGetTitle(hwnd), TitlePattern, &m) ? m[0] : ""
}

ActiveTerminal() => WinActive("ahk_exe WindowsTerminal.exe")

ImageOnClipboard() => DllCall("IsClipboardFormatAvailable", "UInt", 8)   ; CF_DIB

; The one copied file or folder's path, or "" for none or several; no disk read. CF_HDROP 15
; holds copied files, whose paths A_Clipboard gives one per line (reading it opens the clipboard,
; which throws when another app holds it: then Ctrl+V stays native).
CopiedFile() {
    if !DllCall("IsClipboardFormatAvailable", "UInt", 15)
        return ""
    try
        path := A_Clipboard
    catch
        return ""
    return RegExMatch(path, "^[^\r\n]+$") ? path : ""
}

UploadOnClipboard() {
    if DllCall("IsClipboardFormatAvailable", "UInt", 13)   ; CF_UNICODETEXT: text wins
        return false
    return ImageOnClipboard() || CopiedFile() != ""
}

#HotIf PcView(ActiveTerminal()) != "" && UploadOnClipboard()
$^v::RemotePaste()
#HotIf

RemotePaste() {
    hwnd := ActiveTerminal()
    view := PcView(hwnd)
    path := ImageOnClipboard() ? "" : CopiedFile()
    ; a copied folder: Windows Terminal's own paste, through the same focus check below, since
    ; FileExist on a slow share can take long enough for the focus to move
    if InStr(FileExist(path), "D") {
        code := 3
    } else {
        SplitPath path, &name
        ToolTip "Sending " (name != "" ? name : "the image") " to the PC..."
        code := RunWait('powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Sta '
            '-File "' A_ScriptDir '\remote-paste.ps1"', , "Hide")
        ToolTip
    }
    if (code != 0 && code != 3) {
        Notify("remote-paste: " LastError(code))
        return
    }
    if (ActiveTerminal() != hwnd || PcView(hwnd) != view)
        Notify(code = 3 ? "Nothing pasted: the tab changed"
            : "Sent to the PC: press Alt+V in its tab")
    else
        Send(code = 3 ? "^v" : "!v")
}

LastError(code) {
    file := A_Temp "\remote-paste.err"
    return FileExist(file) ? Trim(FileRead(file, "UTF-8"), " `r`n") : "failed (exit " code ")"
}

Notify(text) {
    ToolTip text
    SetTimer () => ToolTip(), -6000
}
