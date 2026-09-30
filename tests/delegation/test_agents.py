"""Static checks on the role definitions. Claude Code ignores an unrecognized frontmatter
field without an error, so a typo would silently drop a restriction. The field list is the
v2.1.285 table in code.claude.com/docs/en/sub-agents ("Supported frontmatter fields")."""
import glob
import os
import unittest

from _paths import AGENTS, frontmatter

DOCUMENTED = {"name", "description", "tools", "disallowedTools", "model", "permissionMode",
              "maxTurns", "skills", "mcpServers", "hooks", "memory", "background",
              "omitClaudeMd", "effort", "isolation", "color", "initialPrompt", "experimental"}
KNOWN_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "Bash", "Edit", "Write",
               "NotebookEdit", "Agent", "Skill", "Monitor", "PowerShell"}
WRITE_TOOLS = {"Bash", "Edit", "Write", "NotebookEdit", "PowerShell"}
REPORT_KEYS = ('"status"', '"summary"', '"artifacts"', '"blocked_actions"')


def tools(fields, key="tools"):
    return {t.strip() for t in fields.get(key, "").split(",") if t.strip()}


class AgentFiles(unittest.TestCase):
    def setUp(self):
        self.files = {os.path.basename(p): frontmatter(p)
                      for p in glob.glob(os.path.join(AGENTS, "*.md"))}

    def test_expected_roles_exist(self):
        self.assertEqual(set(self.files),
                         {"Explore.md", "researcher.md", "reviewer.md", "writer.md"})

    def test_only_documented_fields(self):
        for name, (fields, _) in self.files.items():
            self.assertLessEqual(set(fields), DOCUMENTED, name)

    def test_names_and_descriptions(self):
        for name, (fields, _) in self.files.items():
            self.assertTrue(fields.get("name"), name)
            self.assertNotIn(":", fields["name"], name)
            self.assertTrue(fields.get("description"), name)

    def test_tool_names_are_real(self):
        for name, (fields, _) in self.files.items():
            for key in ("tools", "disallowedTools"):
                self.assertLessEqual(tools(fields, key), KNOWN_TOOLS, f"{name} {key}")

    def test_explore_is_a_no_shell_reader(self):
        fields, _ = self.files["Explore.md"]
        self.assertEqual(fields["name"], "Explore")
        self.assertEqual(tools(fields), {"Read", "Grep", "Glob", "WebFetch", "WebSearch"})
        self.assertEqual(fields["model"], "sonnet")
        self.assertEqual(fields["omitClaudeMd"], "true")

    def test_reviewer_is_read_only(self):
        fields, _ = self.files["reviewer.md"]
        self.assertEqual(tools(fields), {"Read", "Grep", "Glob"})

    def test_researcher_has_a_shell_but_no_edit_tools(self):
        t = tools(self.files["researcher.md"][0])
        self.assertIn("Bash", t)
        self.assertFalse(t & {"Edit", "Write", "NotebookEdit", "Agent"})

    def test_no_shell_roles_get_grep_and_glob(self):
        # On Linux/WSL, Grep and Glob exist only for an agent that lists them and omits Bash.
        for name in ("Explore.md", "reviewer.md"):
            t = tools(self.files[name][0])
            self.assertFalse(t & WRITE_TOOLS, name)
            self.assertLessEqual({"Grep", "Glob"}, t, name)

    def test_writer_is_isolated_and_cannot_fan_out(self):
        fields, _ = self.files["writer.md"]
        self.assertEqual(fields["isolation"], "worktree")
        self.assertIn("Agent", tools(fields, "disallowedTools"))
        self.assertNotIn("tools", fields)

    def test_every_role_ends_with_the_report_shape(self):
        for name, (_, body) in self.files.items():
            for key in REPORT_KEYS:
                self.assertIn(key, body, f"{name} lacks {key}")


if __name__ == "__main__":
    unittest.main()
