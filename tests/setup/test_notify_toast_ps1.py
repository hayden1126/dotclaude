"""notify-toast.ps1, read statically (powershell.exe can't run in the sandbox): the -Silent switch
adds <audio silent="true"/> inside <toast>, which also stops Windows' default toast chime, and
without it the toast XML is exactly what it was before the device-wide mute (stdlib only). The
here-string is rendered by substituting $Message and $audio's two branches, so a change to
either branch or to the XML around them shows here."""
import os
import re
import unittest
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PS1 = os.path.join(REPO, "notify-toast.ps1")

# The toast XML before -Silent existed, with $Message as "m".
PLAIN = """<toast>
  <visual>
    <binding template="ToastText02">
      <text id="1">Claude Code</text>
      <text id="2">m</text>
    </binding>
  </visual>
</toast>"""
PS_STRING = r'"((?:[^"`]|`.)*)"'   # a double-quoted PowerShell string, backtick escapes kept
AUDIO = re.compile(r"(?m)^\$audio = if \(\$Silent\) \{ %s \} else \{ %s \}$" % (PS_STRING, PS_STRING))
HERE = re.compile(r'(?ms)^\$xml = @"\n(.*?)\n"@$')


def read():
    with open(PS1, encoding="ascii") as f:   # Windows PowerShell 5.1 reads a BOM-less file as ANSI
        return f.read()


def unescape(s):
    """A double-quoted PowerShell string's backtick escapes, as far as this file uses them."""
    return re.sub(r"`(.)", lambda m: {"n": "\n"}.get(m.group(1), m.group(1)), s)


def render(text, silent):
    """The XML the script loads, with $Message as "m"."""
    on, off = AUDIO.search(text).groups()
    xml = HERE.search(text).group(1)
    return xml.replace("$audio", unescape(on if silent else off)).replace("$Message", "m")


def code(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class NotifyToast(unittest.TestCase):
    def setUp(self):
        self.text = read()

    def test_silent_is_a_switch_parameter(self):
        param = re.match(r"param\((.*)\)\n", self.text)
        self.assertIsNotNone(param, "the param block opens the file")
        self.assertRegex(param.group(1), r"\[switch\]\$Silent\b")
        self.assertRegex(param.group(1), r'\[string\]\$Message = "Input needed"')

    def test_without_silent_the_xml_is_unchanged(self):
        self.assertEqual(render(self.text, False), PLAIN)

    def test_silent_adds_the_audio_element_inside_the_toast(self):
        xml = render(self.text, True)
        self.assertEqual(xml, PLAIN.replace("  </visual>\n",
                                            '  </visual>\n  <audio silent="true"/>\n'))
        root = ET.fromstring(xml)
        self.assertEqual([c.tag for c in root], ["visual", "audio"])
        self.assertEqual(root.find("audio").attrib, {"silent": "true"})
        ET.fromstring(render(self.text, False))   # both forms are XML LoadXml accepts

    def test_the_audio_element_appears_only_under_the_switch(self):
        lines = [line for line in code(self.text).splitlines() if "<audio" in line]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], AUDIO)
        self.assertEqual(AUDIO.search(self.text).group(2), "")
        self.assertEqual(code(self.text).count("$audio"), 2)   # set once, used once, in the XML

    def test_the_render_catches_a_changed_branch(self):
        # The check above must see a regression: an always-silent toast, and a moved element.
        always = self.text.replace('} else { "" }', '} else { "`n  <audio silent=`"true`"/>" }')
        self.assertNotEqual(render(always, False), PLAIN)
        moved = self.text.replace("  </visual>$audio\n", "  </visual>\n$audio")
        self.assertNotEqual(render(moved, True), render(self.text, True))


if __name__ == "__main__":
    unittest.main()
