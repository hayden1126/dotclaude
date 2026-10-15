; remote-paste.ahk: Ctrl+V of a screenshot in a PC tmux tab sends it to the PC and pastes it.
;
; Claude Code on the PC (WSL) reads the PC's own clipboard on Ctrl+V, so a screenshot copied on
; this laptop never arrives. This takes Ctrl+V only while three things hold: Windows Terminal is
; the active window, its title matches the `title` pattern in remote-paste.ini (default
; ^view-\d+\s: the PC's tmux titles a remote device's session view-<pid>, set-titles-string
; "#S · ..." in dotclaude tmux/claude.conf), and the clipboard holds an image (CF_DIB) or a
; copied file (CF_HDROP) and no text. Otherwise Ctrl+V never reaches this script. On a hit it
; runs remote-paste.ps1 hidden, which uploads the image to the PC's inbox; then it sends Alt+V,
; which the PC's tmux turns into a bracketed paste of that image's path (tmux/paste-inbox).
; remote-paste.ps1 exiting 3 (the file copied isn't one image) gives Windows Terminal its own
; paste; a failure shows its reason in a tooltip. Alt+V goes only to the tab that was pressed:
; if another window or tab (another view-<pid>) took focus during the upload, the tooltip says to
; press Alt+V in the PC's tab instead.
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

ImageOnClipboard() {
    ; CF_UNICODETEXT 13 (text wins: a text paste never comes here), CF_DIB 8, CF_HDROP 15
    return !DllCall("IsClipboardFormatAvailable", "UInt", 13)
        && (DllCall("IsClipboardFormatAvailable", "UInt", 8)
            || DllCall("IsClipboardFormatAvailable", "UInt", 15))
}

#HotIf PcView(ActiveTerminal()) != "" && ImageOnClipboard()
$^v::RemotePaste()
#HotIf

RemotePaste() {
    hwnd := ActiveTerminal()
    view := PcView(hwnd)
    ToolTip "Sending the screenshot to the PC..."
    code := RunWait('powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Sta -File "'
        A_ScriptDir '\remote-paste.ps1"', , "Hide")
    ToolTip
    if (code = 3) {
        Send "^v"
        return
    }
    if (code != 0) {
        Notify("remote-paste: " LastError(code))
        return
    }
    if (ActiveTerminal() = hwnd && PcView(hwnd) == view)
        Send "!v"
    else
        Notify("Sent to the PC: press Alt+V in its tab")
}

LastError(code) {
    file := A_Temp "\remote-paste.err"
    return FileExist(file) ? Trim(FileRead(file, "UTF-8"), " `r`n") : "failed (exit " code ")"
}

Notify(text) {
    ToolTip text
    SetTimer () => ToolTip(), -6000
}
