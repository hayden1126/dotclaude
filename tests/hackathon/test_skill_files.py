"""Checks on the hackathon mode's skill files: how each is triggered, that each stands alone when
copied to another machine, that ported text keeps its attribution and loses what was dropped, and
that no private name leaks into this public repo (stdlib only, no model calls)."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANUAL = ("interview", "hackathon", "demo-first-scope", "demo-video", "pitch", "public-ready")
AUTO = ("frontend-motion",)
READS_THE_PROFILE = ("demo-first-scope", "demo-video", "pitch", "public-ready")
DENYLIST = os.path.expanduser("~/scratch/hackathon/denylist.txt")


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
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in files:
            if not f.startswith("LICENSE"):
                yield os.path.join(root, f)


class Triggers(unittest.TestCase):
    def test_the_mode_skills_run_only_when_the_user_types_them(self):
        for name in MANUAL:
            with self.subTest(name):
                self.assertRegex(frontmatter(name), r"(?m)^disable-model-invocation: true$")
                self.assertRegex(frontmatter(name), rf"(?m)^name: {name}$")

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
                    self.assertNotIn("—", read(path))

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
        for field in ("schedule", "deadline", "judging", "video", "submission", "licence", "hardware"):
            with self.subTest(field):
                self.assertIn(field, text)

    def test_every_other_mode_skill_reads_it(self):
        for name in READS_THE_PROFILE:
            with self.subTest(name):
                self.assertIn("EVENT.md", read(skill_path(name, "SKILL.md")))

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


class Attribution(unittest.TestCase):
    def test_interview_keeps_its_seed_license(self):
        self.assertIn("Johnathan Mo", read(skill_path("interview", "LICENSE")))
        self.assertIn("Johnathan Mo", read(skill_path("interview", "SKILL.md")))

    def test_frontend_motion_keeps_both_licenses_and_pins_its_sources(self):
        self.assertIn("Emil Kowalski", read(skill_path("frontend-motion", "LICENSE-animate")))
        self.assertIn("Jakub Krehel", read(skill_path("frontend-motion", "LICENSE-better-ui")))
        notice = read(skill_path("frontend-motion", "NOTICE"))
        for pin in ("e8a175d", "d574cc8"):
            with self.subTest(pin):
                self.assertIn(pin, notice)

    def test_what_the_port_dropped_stays_out(self):
        text = read(skill_path("frontend-motion", "SKILL.md"))
        for gone in ("as a menu", "Initial Response", "review-animations", "pick-ui-library"):
            with self.subTest(gone):
                self.assertNotIn(gone, text)


@unittest.skipUnless(os.path.exists(DENYLIST), "the private denylist isn't on this machine")
class PrivateNames(unittest.TestCase):
    def test_no_denylisted_string_in_the_mode_files(self):
        terms = [t.strip().lower() for t in read(DENYLIST).splitlines() if t.strip()]
        paths = [os.path.abspath(__file__)]
        for name in MANUAL + AUTO:
            paths += list(text_files(name))
        for path in paths:
            if path == os.path.abspath(__file__):
                continue
            text = read(path).lower()
            for term in terms:
                with self.subTest(path=path, term="(private)"):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
