"""Checks on the verify-app skill's own files: how it and its template trigger, that the folder stands
alone, that the copied files match CHECKSUMS, and that no private name reaches this public repo
(stdlib only, no browser, no model calls)."""
import glob
import hashlib
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "verify-app")
TEMPLATE = os.path.join(SKILL, "template")
DENYLISTS = glob.glob(os.path.expanduser("~/scratch/*/denylist.txt"))
EM_DASH = chr(0x2014)
COPIED = ("verify.py", "browser.py", "LICENSE-pstack-claude", "CHECKSUMS")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def skill_files():
    for root, dirs, files in os.walk(SKILL):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            yield os.path.join(root, name)


def frontmatter(path):
    match = re.match(r"---\n(.*?)\n---\n", read(path), re.S)
    return match.group(1) if match else ""


class Trigger(unittest.TestCase):
    def test_it_loads_on_its_own(self):
        for path in (os.path.join(SKILL, "SKILL.md"), os.path.join(TEMPLATE, "SKILL.md")):
            with self.subTest(path=path):
                self.assertNotIn("disable-model-invocation", frontmatter(path))

    def test_the_description_names_triggers_and_near_misses(self):
        text = frontmatter(os.path.join(SKILL, "SKILL.md"))
        self.assertIn("name: verify-app", text)
        for word in ("verify", "launches", "health check", "evidence", "cleans up", "MAINTAIN.md",
                     "Not for unit tests", "test mocks", "/run"):
            self.assertIn(word, text)

    def test_the_generated_skill_says_launch_and_drive(self):
        text = frontmatter(os.path.join(TEMPLATE, "SKILL.md"))
        self.assertRegex(text, r"(?m)^name: verify$")
        for word in ("Launch and drive", "run", "start", "commit"):
            self.assertIn(word, text)

    def test_the_descriptions_fit_the_limit(self):
        for path in (os.path.join(SKILL, "SKILL.md"), os.path.join(TEMPLATE, "SKILL.md")):
            with self.subTest(path=path):
                self.assertLessEqual(len(frontmatter(path)), 1024)


class Files(unittest.TestCase):
    def test_what_the_skill_names_exists(self):
        text = read(os.path.join(SKILL, "SKILL.md")) + read(os.path.join(SKILL, "MAINTAIN.md"))
        named = re.findall(r"<skill dir>/([\w./-]+[\w])", text)
        self.assertIn("template/", " ".join(named))
        for path in named:
            with self.subTest(path=path):
                self.assertTrue(os.path.exists(os.path.join(SKILL, path)), path)

    def test_the_skill_copies_exactly_the_checksummed_files(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        self.assertIn(", ".join(f"`{name}`" for name in COPIED[:3]) + " and `CHECKSUMS`", text)
        self.assertIn("sha256sum -c CHECKSUMS", text)

    def test_checksums_match_the_files(self):
        rows = [line.split() for line in read(os.path.join(TEMPLATE, "CHECKSUMS")).splitlines()]
        self.assertEqual(sorted(name for _, name in rows), sorted(COPIED[:3]))
        for digest, name in rows:
            with open(os.path.join(TEMPLATE, name), "rb") as f:
                with self.subTest(name=name):
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest)

    def test_template_files_are_ascii(self):
        for name in COPIED + ("journeys.py", "SKILL.md"):
            with self.subTest(name=name):
                read(os.path.join(TEMPLATE, name)).encode("ascii")

    def test_the_licence_is_the_pstack_claude_text(self):
        source = os.path.join(REPO, "skills", "technical-writing", "LICENSE-pstack-claude")
        self.assertEqual(read(os.path.join(TEMPLATE, "LICENSE-pstack-claude")), read(source))

    def test_provenance_names_the_sources(self):
        for path in (os.path.join(SKILL, "SKILL.md"), os.path.join(TEMPLATE, "SKILL.md")):
            text = read(path)
            for term in ("github.com/cursor/plugins", "Lauren Tan", "michael-denyer/pstack-claude",
                         "Michael Denyer", "LICENSE-pstack-claude"):
                with self.subTest(path=path, term=term):
                    self.assertIn(term, text)
        text = read(os.path.join(SKILL, "SKILL.md"))
        for commit in ("3fe2823", "4612556", "79b36d9"):
            self.assertIn(commit, text)

    def test_the_template_carries_the_tiers_and_exit_codes(self):
        recipe = read(os.path.join(TEMPLATE, "SKILL.md"))
        for tier in ("full", "quick", "skip"):
            self.assertRegex(recipe, rf"(?m)^\| {tier} \|")
        for text in (recipe, read(os.path.join(TEMPLATE, "verify.py"))):
            for code, meaning in ((0, "Proved"), (1, "The app failed"), (2, "Could not judge"),
                                  (3, "Cleanup failed")):
                self.assertRegex(text, rf"(?m)^\| {code} \| {meaning}")
        rows = [re.findall(r"(?m)^\| [0-3] \|.*$", text)
                for text in (recipe, read(os.path.join(TEMPLATE, "verify.py")))]
        self.assertEqual(rows[0], rows[1], "the recipe's exit table must match verify.py's word for word")

    def test_the_template_ships_with_fill_markers(self):
        for name in ("journeys.py", "SKILL.md"):
            with self.subTest(name=name):
                self.assertIn("<fill: ", read(os.path.join(TEMPLATE, name)))
        for name in COPIED:
            with self.subTest(name=name):
                self.assertNotIn("<fill: ", read(os.path.join(TEMPLATE, name)))

    def test_every_run_command_uses_the_harness_folder_and_no_bytecode(self):
        texts = {name: read(os.path.join(SKILL, name)) for name in ("SKILL.md", "MAINTAIN.md")}
        texts.update({f"template/{name}": read(os.path.join(TEMPLATE, name))
                      for name in ("SKILL.md", "verify.py", "journeys.py")})
        runs = [(name, run) for name, text in texts.items()
                for run in re.findall(r"python3[^\n`]*verify\.py", text)]
        self.assertGreaterEqual(len(runs), 5)
        for name, run in runs:
            with self.subTest(name=name, run=run):
                self.assertRegex(run, r"^python3 -B <(harness|fill: harness folder|harness folder)>/verify\.py$")
        for name, text in texts.items():
            with self.subTest(name=name):
                self.assertNotRegex(text, r"\.claude/skills/verify/(verify|browser|journeys)\.py")

    def test_the_generator_places_the_harness_and_copies_it_once(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        for phrase in ("`scripts/verify/`", "`tools/verify/`", "one sandboxed `cp`",
                       "cp <skill dir>/template/{verify.py,browser.py,LICENSE-pstack-claude,CHECKSUMS} <harness>/",
                       "cd <harness> && sha256sum -c CHECKSUMS", "git add .claude/skills/verify <harness>"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        maintain = read(os.path.join(SKILL, "MAINTAIN.md"))
        self.assertIn("Edit only two places: `journeys.py` in the harness folder, and "
                      "`.claude/skills/verify/SKILL.md`", maintain)

    def test_the_template_folder_holds_exactly_its_files(self):
        """A stray entry fails here, such as the empty .claude/.cc-writes/ a sandbox once left."""
        found = set()
        for root, dirs, files in os.walk(TEMPLATE):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            where = os.path.relpath(root, TEMPLATE)
            found.update(os.path.normpath(os.path.join(where, name)) for name in dirs + files)
        self.assertEqual(found, set(COPIED + ("journeys.py", "SKILL.md")))

    def test_the_commit_step_names_the_gitignore_it_may_have_changed(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        flat = " ".join(text.split())
        self.assertIn("add one line to `.gitignore`", flat, "the step that changes it")
        self.assertIn("when section 2 added an ignore line, `.gitignore`", flat)
        self.assertIn("Drop `.gitignore` from both lines when section 2 left it unchanged", flat)
        for line in ('git diff --cached --name-status > "$TMPDIR/staged-before"',
                     "git add .claude/skills/verify <harness> .gitignore",
                     'git commit --only -m "<message>" -- .claude/skills/verify <harness> .gitignore',
                     'git diff --cached --name-status | diff "$TMPDIR/staged-before" -'):
            with self.subTest(line=line):
                self.assertRegex(text, rf"(?m)^{re.escape(line)}$")

    def test_the_evidence_dir_is_outside_the_watcher_and_every_test_runners_output(self):
        """Playwright empties test-results/ at the start of each run, a spec a journey runs included."""
        generator = " ".join(read(os.path.join(SKILL, "SKILL.md")).split())
        for phrase in ("git-ignored, not watched by the dev server, and no test runner's output folder",
                       "In a repo with `node_modules`, use `node_modules/.cache/verify`",
                       "outside every common dev-server watcher and Tailwind's source scan",
                       "untouched by test runners", "A fresh `npm ci` deletes it",
                       "Otherwise pick a git-ignored folder the dev server doesn't watch",
                       "ask the user before changing app config",
                       "Never a test runner's output folder: Playwright's `test-results/`",
                       "`playwright-report/`", "`cypress/screenshots`", "`cypress/videos`",
                       "Read the first run's `app.log` for reload or rebuild lines",
                       "that start when the journey writes evidence", "move it by section 2's step 6"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, generator)
        self.assertNotIn("Prefer a folder the dev tool ignores by default", generator)
        self.assertNotIn("`**/test-results/**`", generator)
        recipe = " ".join(read(os.path.join(TEMPLATE, "SKILL.md")).split())
        for phrase in ("The evidence dir must be outside the dev server's file watcher as well as git-ignored",
                       "never be a test runner's output folder (Playwright's `test-results/`",
                       "the runner empties it at the start of each run", "lost on a fresh `npm ci`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, recipe)

    def test_the_tier_source_covers_commit_all(self):
        """git commit -a takes the working tree's tracked changes, which --cached doesn't show."""
        recipe = " ".join(read(os.path.join(TEMPLATE, "SKILL.md")).split())
        self.assertIn("For `git commit -a`, which also takes every tracked change in the working tree, use "
                      "`git diff HEAD --name-only` instead", recipe)
        self.assertIn("Otherwise not from `git diff` or `git status`", recipe)

    def test_the_ignore_line_never_sweeps_the_users_gitignore_edits(self):
        """git add .gitignore stages the whole file, so only a clean one is edited and committed."""
        generator = " ".join(read(os.path.join(SKILL, "SKILL.md")).split())
        for phrase in ("If it isn't ignored and `git diff --quiet HEAD -- .gitignore` exits 0 (no uncommitted "
                       "changes there), add one line to `.gitignore` and tell the user",
                       "If `.gitignore` has uncommitted changes, don't edit it: tell the user the line to add, "
                       "and leave `.gitignore` out of the commit",
                       "and when `git diff HEAD -- .gitignore` shows any change beyond the one line it added"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, generator)

    def test_the_measured_line_waits_for_the_first_run_without_a_marker(self):
        """verify.py refuses while any marker remains, and the times only exist after a run."""
        lines = [line for line in read(os.path.join(TEMPLATE, "SKILL.md")).splitlines()
                 if line.startswith("Measured")]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("<fill:", lines[0])
        self.assertEqual(lines[0].count("not measured yet"), 2)
        self.assertIn("full", lines[0])
        self.assertIn("quick", lines[0])
        generator = " ".join(read(os.path.join(SKILL, "SKILL.md")).split())
        self.assertIn("replace each `not measured yet` on the recipe's Measured line with the measured "
                      "`duration_seconds`", generator)
        self.assertIn("`not measured yet`, which is not a marker", generator)

    def test_click_text_is_documented_as_the_rendered_or_source_text(self):
        """innerText applies text-transform and is undefined on SVG; textContent covers both."""
        browser = read(os.path.join(TEMPLATE, "browser.py"))
        script = re.search(r'CLICK_TEXT_JS = """(.*?)"""', browser, re.S).group(1)
        self.assertIn("squash(el.innerText) === text || squash(el.textContent) === text", script)
        self.assertNotIn("el.innerText.", script, "innerText read without a guard throws on SVG")
        for name, text in (("browser.py", browser), ("journeys.py", read(os.path.join(TEMPLATE, "journeys.py"))),
                           ("generator", read(os.path.join(SKILL, "SKILL.md"))),
                           ("recipe", read(os.path.join(TEMPLATE, "SKILL.md")))):
            flat = " ".join(text.split())
            with self.subTest(name=name):
                for phrase in ("rendered text", "innerText", "source text", "textContent", "text-transform",
                               "case-sensitive"):
                    self.assertIn(phrase, flat)
                self.assertRegex(flat, r"whitespace run collapsed to one space and the ends trimmed")

    def test_the_recipe_covers_a_change_no_journey_covers(self):
        recipe = " ".join(read(os.path.join(TEMPLATE, "SKILL.md")).split())
        for phrase in ("Choose the tier from the paths this commit will contain: `git diff --cached --name-only`",
                       "When no journey covers the change, say so in the reply",
                       "do one of two things and report which", "Extend a journey or add one",
                       "Plant a wrong expected value in its new `ctx.check` and see exit 1 first",
                       "Keep the journey when the feature matters to users",
                       "Run a temporary check under the same rule", "then remove it"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, recipe)

    def test_the_generator_never_launches_the_app_by_hand(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        self.assertNotIn("Measure how long", text)
        self.assertNotIn("doesn't start as it is", text)
        for phrase in ("Don't start the app by", "is the measurement", "`ready_seconds`", "`app.log`",
                       "`ready_timeout` from the measured"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_selector_and_hydration_rules_agree(self):
        generator = read(os.path.join(SKILL, "SKILL.md"))
        for name, text in (("generator", generator), ("recipe", read(os.path.join(TEMPLATE, "SKILL.md"))),
                           ("journeys", read(os.path.join(TEMPLATE, "journeys.py")))):
            with self.subTest(name=name):
                self.assertIn("click_text", text)
                self.assertRegex(text, r"[Nn]ever\s+by\s+position\s+alone")
                self.assertIn("hydration", text)
                self.assertIn("wait_for", text)
        self.assertIn("Adding attributes to product code is out of scope", generator)
        self.assertNotIn("over position or text", generator)

    def test_the_generator_reports_and_plants_by_the_manifest(self):
        text = " ".join(read(os.path.join(SKILL, "SKILL.md")).split())
        self.assertIn("see exit 1, with that check's message in the manifest", text)
        self.assertIn("Report the files written, the paths the recipe lists as skip-safe, both measured "
                      "times and the manifest path", text)
        self.assertNotIn("tier table", text)
        self.assertIn("Plant one wrong expected value in a journey's `ctx.check`", text)
        self.assertIn("not in a `wait_for`, which only times out", text)
        recipe = " ".join(read(os.path.join(TEMPLATE, "SKILL.md")).split())
        self.assertIn("plant one wrong expected value in a `ctx.check`", recipe)

    def test_the_template_check_can_fail(self):
        """wait_for returns truthy or raises, so ctx.check around it can never fail with its message."""
        text = read(os.path.join(TEMPLATE, "journeys.py"))
        self.assertNotRegex(text, r"ctx\.check\(\s*ctx\.page\.wait_for")
        self.assertRegex(text, r"value = ctx\.page\.evaluate\(")
        self.assertRegex(text, r"ctx\.check\(value == ")

    def test_clicks_scroll_instantly(self):
        """A smooth scroll moves the element after the rect is read, so the press misses."""
        text = read(os.path.join(TEMPLATE, "browser.py"))
        scrolls = re.findall(r"scrollIntoView\(([^)]*)\)", text)
        self.assertEqual(len(scrolls), 2)
        for args in scrolls:
            self.assertIn('behavior: "instant"', args)

    def test_the_folder_stands_alone(self):
        for path in skill_files():
            with self.subTest(path=path):
                self.assertNotRegex(read(path), r"(?<!\.claude/)skills/(?!verify-app)[\w-]+/|\.\./")

    def test_no_em_dashes(self):
        for path in skill_files():
            with self.subTest(path=path):
                self.assertNotIn(EM_DASH, read(path))

    def test_no_private_paths(self):
        here = os.path.dirname(os.path.abspath(__file__))
        paths = list(skill_files()) + glob.glob(os.path.join(here, "**", "*.py"), recursive=True)
        for path in paths:
            with self.subTest(path=path):
                self.assertNotRegex(read(path), "|".join(("/" + "home/", "/" + "Users/", "~/" + "code/")))

    def test_the_readme_lists_the_skill_and_its_tests(self):
        lines = read(os.path.join(REPO, "README.md")).splitlines()
        skill_rows = [line for line in lines if line.startswith("| `skills/` |")]
        self.assertEqual(len(skill_rows), 1)
        self.assertIn("`verify-app`", skill_rows[0])
        self.assertTrue([line for line in lines if line.startswith("| `tests/verify_app/` |")])


@unittest.skipUnless(DENYLISTS, "no private denylist on this machine")
class PrivateNames(unittest.TestCase):
    def test_no_denylisted_string_in_the_skill_or_its_tests(self):
        terms = [t.strip().lower() for path in DENYLISTS for t in read(path).splitlines() if t.strip()]
        here = os.path.dirname(os.path.abspath(__file__))
        paths = list(skill_files()) + glob.glob(os.path.join(here, "**", "*.py"), recursive=True)
        # The root license's copyright line is required and public; test_license_notices pins it.
        header = "".join(f"# {line}".rstrip() + "\n" for line in read(os.path.join(REPO, "LICENSE")).splitlines())
        for path in paths:
            text = read(path).removeprefix(header).lower()
            for term in terms:
                with self.subTest(path=path, term="(private)"):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
