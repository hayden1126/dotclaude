; remote-paste.ahk: Ctrl+V of a screenshot in a PC tmux tab sends it to the PC and pastes it.
;
; Claude Code on the PC (WSL) reads the PC's own clipboard on Ctrl+V, so a screenshot copied on
; this laptop never arrives. This takes Ctrl+V only while three things hold: Windows Terminal is
; the active window, its title matches the `title` pattern in remote-paste.ini (default
; ^view-\d+\s: the PC's tmux titles a remote device's session view-<pid>, set-titles-string
; "#S · ..." in dotclaude tmux/claude.conf), and the clipboard holds an image (CF_DIB) or one
; copied .png, .jpg, .jpeg, .gif or .webp file (CF_HDROP), and no text. Otherwise Ctrl+V never
; reaches this script. On a hit it
; runs remote-paste.ps1 hidden, which uploads the image to the PC's inbox; then it sends Alt+V,
; which the PC's tmux turns into a bracketed paste of that image's path (tmux/paste-inbox).
; remote-paste.ps1 exiting 3 (the clipboard changed under it) gives Windows Terminal its own
; paste; a failure shows its reason in a tooltip. Alt+V or that paste goes only to the tab that
; was pressed: if another window or tab (another view-<pid>) took focus during the upload, the
; tooltip says so instead.
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
    if DllCall("IsClipboardFormatAvailable", "UInt", 13)   ; CF_UNICODETEXT: text wins
        return false
    if DllCall("IsClipboardFormatAvailable", "UInt", 8)    ; CF_DIB: an image
        return true
    ; CF_HDROP 15: copied files, whose paths A_Clipboard holds one per line
    return DllCall("IsClipboardFormatAvailable", "UInt", 15)
        && RegExMatch(A_Clipboard, "i)^[^\r\n]+\.(png|jpe?g|gif|webp)$")
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
