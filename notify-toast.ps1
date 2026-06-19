param([string]$Message = "Input needed")

# Render &, <, > literally instead of letting them break the toast XML below (LoadXml would
# throw and the toast would silently vanish). A no-op on today's plain messages; cheap insurance.
$Message = [System.Security.SecurityElement]::Escape($Message)

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
