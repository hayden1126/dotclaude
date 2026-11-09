"""Checks on the hackathon mode's skill files: how each is triggered, that each stands alone when
copied to another machine, that ported text keeps its attribution and loses what was dropped, and
that no private name leaks into this public repo (stdlib only, no model calls)."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# demo-video loads by itself: a plain "make a demo video" once went off-skill and offered
# recording routes outside the sandbox (Shodo test, 2026-11-08).
MANUAL = ("interview", "hackathon", "demo-first-scope", "pitch", "public-ready")
AUTO = ("frontend-motion", "demo-video")
READS_THE_PROFILE = ("demo-first-scope", "demo-video", "pitch", "public-ready")
DENYLIST = os.path.expanduser("~/scratch/hackathon/denylist.txt")
EM_DASH = chr(0x2014)


def skill_path(name, *rest):
    return os.path.join(REPO, "skills", name, *rest)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def frontmatter(name):
    match = re.match(r"---\n(.*?)\n---\n", read(skill_path(name, "SKILL.md")), re.S)
    return match.group(1) if match else ""


def text_files(name):
    for root, dirs, files in os.walk(skill_path(name)):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__")]
        for f in files:
            if not f.startswith("LICENSE"):
                yield os.path.join(root, f)


class Triggers(unittest.TestCase):
    def test_the_mode_skills_run_only_when_the_user_types_them(self):
        for name in MANUAL:
            with self.subTest(name):
                self.assertRegex(frontmatter(name), r"(?m)^disable-model-invocation: true$")
                self.assertRegex(frontmatter(name), rf"(?m)^name: {name}$")

    def test_demo_video_triggers_on_a_demo_video_not_on_any_demo(self):
        description = re.search(r"(?m)^description: (.*)$", frontmatter("demo-video")).group(1)
        self.assertIn("demo video", description)
        self.assertRegex(description, r"Not for a live demo, a pitch, or writing a demo script or DEMO\.md\.$")

    def test_frontend_motion_fires_by_itself_in_any_mode(self):
        for name in AUTO:
            with self.subTest(name):
                self.assertNotIn("disable-model-invocation", frontmatter(name))
                self.assertRegex(frontmatter(name), r"(?m)^description: Use when")


class StandsAlone(unittest.TestCase):
    """Each folder works copied to another machine, macOS included."""

    def test_no_path_or_name_from_this_machine(self):
        bad = re.compile(r"hayden|haypc|/home/|~/\.claude/|\.claude/(hooks|agents)/|\bwsl\b|/mnt/c", re.I)
        for name in MANUAL + AUTO:
            for path in text_files(name):
                for n, line in enumerate(read(path).splitlines(), 1):
                    with self.subTest(path=path, line=n):
                        self.assertIsNone(bad.search(line), line)

    def test_no_em_dashes(self):
        for name in MANUAL + AUTO:
            for path in text_files(name):
                with self.subTest(path=path):
                    self.assertNotIn(EM_DASH, read(path))

    def test_no_em_dashes_in_what_this_mode_added_elsewhere(self):
        lines = [line for line in read(skill_path("frontend-ui-discipline", "SKILL.md")).splitlines()
                 if "frontend-motion" in line or line.startswith("- **Reference first:**")]
        lines += [line for line in read(os.path.join(REPO, "README.md")).splitlines()
                  if line.startswith("| `tests/hackathon/`")]
        self.assertGreaterEqual(len(lines), 3)
        for line in lines:
            self.assertNotIn(EM_DASH, line)

    def test_nothing_unpinned_or_unguarded_is_suggested(self):
        for name in MANUAL + AUTO:
            for path in text_files(name):
                with self.subTest(path=path):
                    self.assertNotIn("npx -y", read(path))
                    for line in read(path).splitlines():
                        if "dangerously-skip-permissions" in line:
                            self.assertRegex(line.lower(), r"never|don't|do not")


class EventProfile(unittest.TestCase):
    """Nothing event-shaped is hardcoded: each skill reads the profile the kickoff writes."""

    def test_the_kickoff_ships_the_profile_template_with_its_fields(self):
        text = read(skill_path("hackathon", "templates", "EVENT.md")).lower()
        for field in ("schedule", "deadline", "judging", "what must run live", "venue screen size",
                      "video", "submission", "third-party", "licence", "hardware", "work allowed before"):
            with self.subTest(field):
                self.assertIn(field, text)

    def test_every_other_mode_skill_reads_it(self):
        for name in READS_THE_PROFILE:
            with self.subTest(name):
                self.assertIn("EVENT.md", read(skill_path(name, "SKILL.md")))

    def test_the_script_is_planned_for_its_audience_and_checked_before_recording(self):
        # The Shodo test (2026-11-08) filmed a DEMO.md word for word: nothing asked who judges or
        # what the video had to cover, and one line ran longer than its beat.
        scope = read(skill_path("demo-first-scope", "SKILL.md"))
        for needle in ("## Audience and coverage", "**Who judges.**", "**What the demo must cover.**",
                       "how it was built", "the difficulties", "| Must cover | Asked by | Beat or written field |",
                       "2 to 2.3 words a second", "| Time | On screen | Said | Words | Label | Real or seeded |",
                       "6 words or fewer", "## Before recording", "`/demo-first-scope before recording`",
                       "do only the Before recording section", "Don't reopen the idea", "`Checked before recording: <date and time>, at commit <hash>`",
                       # The second Shodo run (2026-11-08) took the judges from a pick-list, changed no line for
                       # them, and never raised how it was built or what was hard.
                       "ask the user in plain questions, not a list of options", "**Write for them.**",
                       "Ask the user how it was built and what was hardest", "asking the user its questions rather than guessing",
                       "Propose each change with its reason; the user decides.",
                       'Once the said lines are written, go over them for the judge, as "Write for them" says.'):
            with self.subTest(needle):
                self.assertIn(needle, scope)
        video = read(skill_path("demo-video", "SKILL.md"))
        self.assertIn("**Check the script first.**", video)
        self.assertIn("type `/demo-first-scope before recording`", video)
        self.assertIn("`Checked before recording:` line", video)
        # A closed table: every state of DEMO.md has a row, so none falls between branches.
        for row in ("| The user said to skip this check", "| No script at all |", "a beat has neither a said line nor a silent mark",
                    "| A script, but no audience and coverage section", "| A script, but no `Checked before recording:` line |",
                    "| Every piece is there, but the product moved |", "| Every piece is there, and the product hasn't moved | Write the beats. |"):
            with self.subTest(row):
                self.assertIn(row, video)
        self.assertIn("Give every beat a said line or mark it silent.", scope)
        hackathon = read(skill_path("hackathon", "SKILL.md"))
        self.assertLess(hackathon.index("`/demo-first-scope before recording`"), hackathon.index("| At feature freeze | `/demo-video`"))

    def test_the_live_capability_check_is_where_a_live_demo_is_planned(self):
        for name in ("demo-first-scope", "pitch"):
            with self.subTest(name):
                text = read(skill_path(name, "SKILL.md")).lower()
                self.assertIn("fallback", text)
                self.assertIn("rate limit", text)

    def test_manual_skills_ask_for_each_other_rather_than_read_them(self):
        # The Skill tool refuses a manual skill and tells the model not to replicate it.
        for name in MANUAL:
            for other in MANUAL:
                if other != name:
                    with self.subTest(name=name, other=other):
                        self.assertNotIn(f"{other}/SKILL.md", read(skill_path(name, "SKILL.md")))

    def test_a_skill_that_points_at_another_asks_the_user_to_type_it(self):
        for name in MANUAL:
            text = read(skill_path(name, "SKILL.md"))
            if any(f"`/{other}`" in text for other in MANUAL if other != name):
                with self.subTest(name):
                    self.assertRegex(text, r"(?i)\b(?:user|them|you|asks?)\b[^.\n]{0,60}\btypes?\b|\btypes? (?:it|`/)|\buser types\b")

    def test_a_no_pre_work_rule_is_held_where_building_starts(self):
        for text in (read(skill_path("hackathon", "SKILL.md")),
                     read(skill_path("hackathon", "templates", "project-CLAUDE.md"))):
            self.assertIn("forbids work before the start", text)
            self.assertIn("design only", text)

    def test_public_ready_undoes_the_mode_after_its_commits_and_cuts_history_last(self):
        after = read(skill_path("public-ready", "SKILL.md")).split("## After judging")[1]
        steps = re.findall(r"(?m)^(\d)\. \*\*(.*?)\*\*", after)
        self.assertEqual([number for number, _ in steps], list("123456"))
        self.assertIn("Undo the mode", steps[4][1])
        self.assertIn("clean history", steps[5][1])

    def test_pitch_does_not_assume_a_video(self):
        text = read(skill_path("pitch", "SKILL.md"))
        self.assertIn("if there is one", text)
        self.assertIn("when there's no video", text)


class Attribution(unittest.TestCase):
    def test_interview_keeps_its_seed_license(self):
        self.assertIn("Johnathan Mo", read(skill_path("interview", "LICENSE")))
        self.assertIn("Permission is hereby granted", read(skill_path("interview", "LICENSE")))
        self.assertIn("Johnathan Mo", read(skill_path("interview", "SKILL.md")))

    def test_frontend_motion_keeps_both_licenses_and_pins_its_sources(self):
        for name, author in (("LICENSE-animate", "Emil Kowalski"), ("LICENSE-better-ui", "Jakub Krehel")):
            with self.subTest(name):
                text = read(skill_path("frontend-motion", name))
                self.assertIn(author, text)
                self.assertIn("Permission is hereby granted", text)
        notice = read(skill_path("frontend-motion", "NOTICE"))
        for pin in ("e8a175d", "d574cc8"):
            with self.subTest(pin):
                self.assertIn(pin, notice)

    def test_what_the_port_dropped_stays_out(self):
        for path in (skill_path("frontend-motion", "SKILL.md"), skill_path("frontend-motion", "references", "recipes.md")):
            text = read(path)
            for gone in ("as a menu", "Initial Response", "review-animations", "pick-ui-library", "playful"):
                with self.subTest(path=path, gone=gone):
                    self.assertNotIn(gone, text)

    def test_no_bare_custom_property_at_a_stylesheets_top_level(self):
        # A declaration outside a rule swallows the rule after it, so a pasted .card silently vanishes.
        recipes = read(skill_path("frontend-motion", "references", "recipes.md"))
        for block in re.findall(r"```css\n(.*?)```", recipes, re.S):
            depth = 0
            for line in block.splitlines():
                if depth == 0:
                    with self.subTest(line=line):
                        self.assertNotRegex(line, r"^\s*--[\w-]+\s*:")
                depth += line.count("{") - line.count("}")


@unittest.skipUnless(os.path.exists(DENYLIST), "the private denylist isn't on this machine")
class PrivateNames(unittest.TestCase):
    def test_no_denylisted_string_in_the_mode_files(self):
        terms = [t.strip().lower() for t in read(DENYLIST).splitlines() if t.strip()]
        paths = [os.path.join(REPO, "README.md"), skill_path("frontend-ui-discipline", "SKILL.md")]
        for name in MANUAL + AUTO:
            paths += list(text_files(name))
        for root, dirs, files in os.walk(os.path.dirname(os.path.abspath(__file__))):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            paths += [os.path.join(root, f) for f in files]
        for path in paths:
            text = read(path).lower()
            for term in terms:
                with self.subTest(path=path, term="(private)"):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
