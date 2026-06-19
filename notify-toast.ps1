param([string]$Message = "Input needed")

# TODO: XML-escape $Message ([System.Security.SecurityElement]::Escape) if Claude Code's
# Notification message ever carries & < > (generic today, so unreachable; raw markup makes the
# LoadXml below throw and silently drops the toast). Ref Claude Code issue #32952.

[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null

$xml = @"
<toast>
  <visual>
    <binding template="ToastText02">
      <text id="1">Claude Code</text>
      <text id="2">$Message</text>
    </binding>
  </visual>
</toast>
"@

$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.PowerShell').Show($toast)
