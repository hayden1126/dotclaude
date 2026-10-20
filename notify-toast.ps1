param([string]$Message = "Input needed", [switch]$Silent)

# Render &, <, > literally instead of letting them break the toast XML below (LoadXml would
# throw and the toast would silently vanish). A no-op on today's plain messages; cheap insurance.
$Message = [System.Security.SecurityElement]::Escape($Message)

# -Silent: notify.sh passes it while the device-wide mute holds the sound. A toast with no
# <audio> element gets Windows' default chime (unless the app's sound is off in Windows'
# notification settings), so a sound mute that only dropped the ring would still chime;
# silent="true" turns that off. Without -Silent the XML is as it always was.
$audio = if ($Silent) { "`n  <audio silent=`"true`"/>" } else { "" }

[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null

$xml = @"
<toast>
  <visual>
    <binding template="ToastText02">
      <text id="1">Claude Code</text>
      <text id="2">$Message</text>
    </binding>
  </visual>$audio
</toast>
"@

$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.PowerShell').Show($toast)
