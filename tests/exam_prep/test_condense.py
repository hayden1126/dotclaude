"""skills/exam-prep/scripts/condense.py (12-retro step 2).

A synthetic transcript holding one record of each kind condenses to a shard that keeps the student's
typed turn (a pasted wrapper in a typed turn included), a slash command in both forms, a `!`
command, an interrupt, a question dialog's answers and notes, a rejected tool call with what the
student said (with Claude Code's denial marker or only its wording), a message typed mid-turn (a
queued attachment), the assistant's text cut short, a tool call's telling argument and a failed tool
result, each line kind on one line, and drops a successful tool result, a skill body and a peer
message (`isMeta`), every injected wrapper (listed here, not read from the script), a command's
output or IDE context even in a typed turn, a turn whose origin isn't human, a queued peer message
or task notification, a sidechain record, a compaction summary and a line that isn't a JSON record
(a deep one, a list, a bad content type). A turn's blocks are judged one by one. The student's words
survive verbatim and in full up to the cap; the earliest and latest times come only from kept
records, in UTC. A window (--since, --until) keeps only the records at or after since and before
until, a tool result in it naming a call made before it; a record with no timestamp goes; a
transcript with no record inside makes no shard and removes its older one; a time with no offset, or
a window that ends before it starts, is refused, and so is an option after the out dir or `-h`,
which make no directory; a time UTC can't hold counts as unreadable; a `Z` time is read even where
Python can't; a timestamp it can't read is counted and fails the run, and keeps an older shard when
nothing else is in the window. The script refuses an out dir inside a git work tree (a `.git` file,
a symlink into one), an out dir it can't make, two transcripts whose shard names collide, and bad
usage; sets the out dir to 0700 and writes each shard as a new 0600 file renamed into place (a
planted symbolic or hard link is replaced, its target untouched), and goes on past a shard it can't
write; it prints sizes, never text."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONDENSE = os.path.join(REPO, "skills", "exam-prep", "scripts", "condense.py")

spec = importlib.util.spec_from_file_location("condense", CONDENSE)
condense = importlib.util.module_from_spec(spec)
spec.loader.exec_module(condense)

OUTPUTS = ("<bash-stdout>", "<bash-stderr>", "<local-command-stdout>", "<local-command-caveat>")
NEVER_TYPED = OUTPUTS + ("<ide_opened_file>", "<ide_selection>")
WRAPPERS = ("<system-reminder>", "<task-notification>", "<cross-session-message",
            "<agent-message", "<user-prompt-submit-hook>",
            "Another Claude session sent a message:") + NEVER_TYPED
TYPED = "Make the cheat sheet two columns, and why is the proof before the definition?"
REJECTED = ("The user doesn't want to proceed with this tool use. The tool use was rejected. "
            "To tell you how to proceed, the user said:\nREJECTREASON keep the old heading")


def at(sec):
    return f"2026-10-01T10:00:{sec:02d}.000Z"


RECORDS = [
    {"type": "assistant", "timestamp": "2026-09-30T08:00:00.000Z", "isSidechain": True,
     "message": {"content": [{"type": "text", "text": "SIDECHAINTEXT"}]}},
    {"type": "user", "timestamp": at(0), "cwd": "/hub/widgets1001", "origin": {"kind": "human"},
     "message": {"role": "user", "content": TYPED}},
    {"type": "user", "timestamp": at(1), "isMeta": True,
     "message": {"content": [{"type": "text",
                              "text": "Base directory for this skill: SKILLBODY"}]}},
    {"type": "user", "timestamp": at(2), "isMeta": True, "origin": {"kind": "peer"},
     "message": {"content": [{"type": "text", "text": "PEERREPORT from a subagent"}]}},
] + [
    {"type": "user", "timestamp": at(3), "message": {"content": prefix + f"INJECTED{i}"}}
    for i, prefix in enumerate(WRAPPERS)
] + [
    {"type": "assistant", "timestamp": at(4),
     "message": {"content": [{"type": "text", "text": "A" * 500},
                             {"type": "text", "text": "first line\nsecond line"},
                             {"type": "tool_use", "id": "t-bash", "name": "Bash",
                              "input": {"command": "pdfinfo sources/a.pdf\necho done",
                                        "description": "count pages"}},
                             {"type": "tool_use", "id": "t-read", "name": "Read",
                              "input": {"file_path": "/x/" + "p" * 200}}]}},
    {"type": "user", "timestamp": at(5),
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-bash", "is_error": True,
                              "content": [{"type": "text", "text": "Exit code 1: no such file\n"
                                           + "E" * 400}]},
                             {"type": "tool_result", "tool_use_id": "t-read",
                              "content": [{"type": "text", "text": "OKRESULT pages: 12"}]}]}},
    {"type": "user", "timestamp": at(6),
     "message": {"content": "<command-name>/clear</command-name>"}},
    {"type": "user", "timestamp": at(7),
     "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
    {"type": "assistant", "timestamp": at(11),
     "message": {"content": [
         {"type": "tool_use", "id": "t-ask", "name": "AskUserQuestion",
          "input": {"questions": [{"question": "Which layout?", "header": "Layout",
                                   "options": [{"label": "One column"}, {"label": "Two"}]}]}},
         {"type": "tool_use", "id": "t-edit", "name": "Edit",
          "input": {"file_path": "notes/01.md"}},
         {"type": "tool_use", "id": "t-rule", "name": "Bash", "input": {"command": "rm x"}}]}},
    {"type": "user", "timestamp": at(12),
     "toolUseResult": {"questions": [], "answers": {"Which layout?": "ANSWERTEXT two columns"},
                       "annotations": {"Which layout?": {"notes": "NOTETEXT wider margins"}}},
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-ask",
                              "content": "Your questions have been answered: ..."}]}},
    {"type": "user", "timestamp": at(13), "toolDenialKind": "user-rejected",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-edit", "is_error": True,
                              "content": REJECTED}]}},
    {"type": "user", "timestamp": at(14), "toolDenialKind": "permission-rule",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-rule", "is_error": True,
                              "content": "RULEDENIED by a permission rule"}]}},
    {"type": "user", "timestamp": at(15),
     "message": {"content": "<bash-input>ls notes</bash-input>"}},
    {"type": "user", "timestamp": at(16),
     "message": {"content": "<bash-stdout>BASHOUT 01.md</bash-stdout><bash-stderr></bash-stderr>"}},
    {"type": "user", "timestamp": at(17), "origin": {"kind": "human"},
     "message": {"content": "<command-message>exam-prep</command-message>\n<command-name>/exam-prep"
                            "</command-name>\n<command-args>" + "C" * 700 + "</command-args>"}},
    {"type": "user", "timestamp": at(18), "origin": {"kind": "human"},
     "message": {"content": "<system-reminder>PASTEDBYSTUDENT forwarded</system-reminder>"}},
    {"type": "user", "timestamp": at(19), "message": {"content": 5}},
    {"type": "user", "timestamp": at(20), "message": "not a dict"},
    {"type": "user", "timestamp": at(21), "origin": {"kind": "human"},
     "message": {"content": "SURR\ud83d after a split emoji"}},
    {"type": "user", "timestamp": at(22), "message": {"content": "B" * 7000}},
] + [
    {"type": "user", "timestamp": at(23), "origin": {"kind": "human"},
     "message": {"content": prefix + f"TYPEDOUTPUT{i}"}}
    for i, prefix in enumerate(NEVER_TYPED)
] + [
    {"type": "user", "timestamp": at(23), "origin": {"kind": "peer"},
     "message": {"content": "PEERNOMETA with no wrapper"}},
    {"type": "user", "timestamp": at(23), "origin": {},
     "message": {"content": "NOKIND origin with no kind"}},
    {"type": "user", "timestamp": at(24), "promptSource": "typed",
     "message": {"content": "<system-reminder>PSTYPED pasted</system-reminder>"}},
    {"type": "assistant", "timestamp": at(25),
     "message": {"content": [{"type": "tool_use", "id": "t-ask2", "name": "AskUserQuestion",
                              "input": {"questions": [{"question": "Font?"}]}},
                             {"type": "tool_use", "id": [], "name": "Glob", "input": {}},
                             {"type": "tool_use", "id": "t-old", "name": "Write",
                              "input": {"file_path": "notes/02.md"}}]}},
    {"type": "user", "timestamp": at(26),
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-ask2",
                              "content": "Your questions have been answered: FALLBACKANSWER"}]}},
    {"type": "user", "timestamp": at(27),
     "message": {"content": [{"type": "tool_result", "tool_use_id": "t-old", "is_error": True,
                              "content": REJECTED.replace("REJECTREASON", "OLDREASON")}]}},
    {"type": "attachment", "timestamp": at(28),
     "attachment": {"type": "queued_command", "prompt": "QUEUEDTEXT no, two columns",
                    "origin": {"kind": "human"}, "commandMode": "prompt"}},
    {"type": "attachment", "timestamp": at(29),
     "attachment": {"type": "queued_command", "prompt": "<agent-message>QUEUEDPEER</agent-message>",
                    "origin": {"kind": "peer"}, "isMeta": True}},
    {"type": "attachment", "timestamp": at(30),
     "attachment": {"type": "queued_command", "prompt": "<task-notification>QUEUEDTASK"}},
    {"type": "attachment", "timestamp": at(31),
     "attachment": {"type": "queued_command", "prompt": "QUEUEDNOORIGIN plain"}},
    {"type": "attachment", "timestamp": at(32), "attachment": {"type": "hook_success",
                                                               "content": "HOOKTEXT"}},
    {"type": "attachment", "timestamp": at(32),
     "attachment": {"type": "prompt_snapshot", "prompt": "SNAPSHOTPROMPT",
                    "origin": {"kind": "human"}}},
    {"type": "user", "timestamp": at(32),
     "message": {"content": [{"type": "text", "text": "<system-reminder>BLOCKREMINDER"},
                             {"type": "text", "text": "BLOCKSTUDENT after a reminder block"}]}},
    {"type": "user", "timestamp": at(32), "origin": {"kind": "human"},
     "message": {"content": [{"type": "text", "text": "BLOCKTYPED before an output block"},
                             {"type": "text", "text": "<local-command-stdout>BLOCKOUTPUT"}]}},
    {"type": "user", "timestamp": "2026-10-09T08:00:00.000Z", "isCompactSummary": True,
     "message": {"content": "COMPACTSUMMARY"}},
]
JUNK = ["not json", "[1, 2]", "[" * 20000 + "]" * 20000]


class Condense(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.transcript = os.path.join(self.tmp, "0123abcd-ffff-4444-8888-000000000000.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as f:
            for rec in RECORDS:
                f.write(json.dumps(rec) + "\n")
                if rec is RECORDS[4]:
                    f.write("\n".join(JUNK) + "\n")
        self.out = os.path.join(self.tmp, "shards")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = condense.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def shard(self):
        with open(os.path.join(self.out, "0123abcd.md"), encoding="utf-8") as f:
            return f.read()

    def test_the_shard(self):
        code, out, err = self.run_main(self.out, self.transcript)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"^0123abcd\.md \d+K\n$")
        shard = self.shard()
        self.assertIn("- Working directory: /hub/widgets1001", shard)
        self.assertIn("- From 2026-10-01T10:00:00 to 2026-10-01T10:00:32 (UTC)", shard)
        self.assertIn("### [2026-10-01T10:00:00] STUDENT\n" + TYPED, shard)
        self.assertIn("[2026-10-01T10:00:04] CLAUDE: " + "A" * 400 + " [...100 more chars]", shard)
        self.assertIn("CLAUDE: first line second line\n", shard)
        self.assertIn("tool Bash: pdfinfo sources/a.pdf echo done\n", shard)
        self.assertIn("tool Read: /x/" + "p" * 157 + " [...43 more chars]", shard)
        self.assertIn("TOOL ERROR: Exit code 1: no such file " + "E" * 274 + " [...126 more chars]",
                      shard)
        self.assertIn("STUDENT COMMAND: <command-name>/clear</command-name>", shard)
        self.assertIn("[2026-10-01T10:00:07] INTERRUPTED", shard)
        self.assertIn("tool AskUserQuestion: Which layout?", shard)
        self.assertIn("### [2026-10-01T10:00:12] STUDENT ANSWER\nWhich layout? -> ANSWERTEXT two "
                      "columns\n  note: NOTETEXT wider margins", shard)
        self.assertIn("[2026-10-01T10:00:13] STUDENT REJECTED Edit\n\n### [2026-10-01T10:00:13] "
                      "STUDENT\nREJECTREASON keep the old heading", shard)
        self.assertIn("[2026-10-01T10:00:14] TOOL ERROR: RULEDENIED", shard)
        self.assertIn("[2026-10-01T10:00:15] STUDENT BASH: <bash-input>ls notes</bash-input>",
                      shard)
        self.assertIn("STUDENT COMMAND: <command-message>exam-prep</command-message> <command-name>"
                      "/exam-prep</command-name> <command-args>" + "C" * 700 + "</command-args>",
                      shard)
        self.assertIn("### [2026-10-01T10:00:18] STUDENT\n<system-reminder>PASTEDBYSTUDENT", shard)
        self.assertIn("SURR? after a split emoji", shard)
        self.assertIn("B" * 6000 + " [...1000 more chars]", shard)
        self.assertIn("### [2026-10-01T10:00:24] STUDENT\n<system-reminder>PSTYPED", shard)
        self.assertIn("### [2026-10-01T10:00:26] STUDENT ANSWER\nYour questions have been "
                      "answered: FALLBACKANSWER", shard)
        self.assertIn("[2026-10-01T10:00:27] STUDENT REJECTED Write\n\n### [2026-10-01T10:00:27] "
                      "STUDENT\nOLDREASON", shard)
        self.assertIn("### [2026-10-01T10:00:28] STUDENT (sent mid-turn)\nQUEUEDTEXT", shard)
        self.assertIn("### [2026-10-01T10:00:31] STUDENT (sent mid-turn)\nQUEUEDNOORIGIN", shard)
        self.assertIn("### [2026-10-01T10:00:32] STUDENT\nBLOCKSTUDENT", shard)
        self.assertIn("### [2026-10-01T10:00:32] STUDENT\nBLOCKTYPED before an output block\n",
                      shard)
        for dropped in ["SKILLBODY", "PEERREPORT", "SIDECHAINTEXT", "OKRESULT", "BASHOUT",
                        "COMPACTSUMMARY", "Your questions have been answered: ...", "not json",
                        "TYPEDOUTPUT", "QUEUEDPEER", "QUEUEDTASK", "HOOKTEXT", "SNAPSHOTPROMPT",
                        "BLOCKREMINDER", "BLOCKOUTPUT", "PEERNOMETA", "NOKIND"] + [
                            f"INJECTED{i}" for i in range(len(WRAPPERS))]:
            self.assertNotIn(dropped, shard)
        for ln in shard.splitlines():
            if ln and not ln.startswith(("#", "- ", "[")):
                self.assertNotRegex(ln, r"^\S+:", "a continuation line outside a block: " + ln)

    def test_a_window(self):
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                "message": {"content": "NOSTAMP typed"}}) + "\n")
        code, out, err = self.run_main("--since", "2026-10-01T06:00:12-04:00",
                                       "--until", "2026-10-01T10:00:28Z", self.out, self.transcript)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"^0123abcd\.md \d+K\n$")
        shard = self.shard()
        self.assertIn("- Working directory: /hub/widgets1001", shard)
        self.assertIn("- From 2026-10-01T10:00:12 to 2026-10-01T10:00:27 (UTC)", shard)
        self.assertIn("### [2026-10-01T10:00:12] STUDENT ANSWER\nWhich layout? -> ANSWERTEXT",
                      shard)
        self.assertIn("[2026-10-01T10:00:13] STUDENT REJECTED Edit", shard)
        for gone in (TYPED, "tool AskUserQuestion: Which layout?", "QUEUEDTEXT", "NOSTAMP"):
            self.assertNotIn(gone, shard)
        self.run_main("--until", "2026-10-01T10:00:01Z", self.out, self.transcript)
        shard = self.shard()
        self.assertIn(TYPED, shard)
        self.assertNotIn("CLAUDE:", shard)
        self.run_main("--since", "2026-10-01T10:00:30Z", self.out, self.transcript)
        shard = self.shard()
        self.assertIn("QUEUEDNOORIGIN", shard)
        self.assertNotIn("QUEUEDTEXT", shard)
        self.assertNotIn("NOSTAMP", shard)
        self.run_main(self.out, self.transcript)
        self.assertIn("NOSTAMP", self.shard())

    def test_a_transcript_outside_the_window(self):
        self.run_main(self.out, self.transcript)
        later = os.path.join(self.tmp, "fedcba98.jsonl")
        with open(later, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-10-05T09:00:00Z",
                                "origin": {"kind": "human"},
                                "message": {"content": "INWINDOW"}}) + "\n")
        code, out, err = self.run_main("--since", "2026-10-02T00:00:00Z", self.out,
                                       self.transcript, later)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"^0123abcd\.md outside the window\nfedcba98\.md \d+K\n$")
        self.assertEqual(os.listdir(self.out), ["fedcba98.md"])
        empty = os.path.join(self.tmp, "00000000.jsonl")
        with open(empty, "w") as f:
            f.write("not json\n")
        self.assertEqual(self.run_main(self.out, empty)[0], 0)
        with open(os.path.join(self.out, "00000000.md"), encoding="utf-8") as f:
            self.assertIn("- From not recorded to not recorded (UTC)", f.read())

    def test_bad_windows(self):
        for args in (["--since", "2026-10-01T10:00:00"], ["--until", "yesterday"],
                     ["--since", "2026-10-01T10:00:00Z", "--until", "2026-10-01T06:00:00-04:00"],
                     ["--since", "2026-10-01T10:00:01Z", "--until", "2026-10-01T10:00:00Z"]):
            code, _, err = self.run_main(*args, self.out, self.transcript)
            self.assertEqual(code, 2, args)
            self.assertTrue(err, args)
            self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.run_main("--since", self.out, self.transcript)[0], 2)
        self.assertEqual(self.run_main("--until", self.transcript)[0], 2)
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        for args in (["--since=2026-10-01T10:00:00Z", "a", self.transcript],
                     ["-h", "a", self.transcript]):
            code, _, err = self.run_main(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("condense.py [--since TIME]", err)
            self.assertEqual(os.listdir(self.tmp), [os.path.basename(self.transcript)])
        self.assertEqual(self.run_main(self.out, "--since", "2026-10-01T10:00:00Z",
                                       self.transcript)[0], 2)
        self.assertFalse(os.path.exists(self.out))

    def test_a_z_time_where_python_reads_none(self):
        class Before311(datetime):
            @classmethod
            def fromisoformat(cls, s):
                if s[-1:] in ("Z", "z"):
                    raise ValueError("no Z before Python 3.11")
                return datetime.fromisoformat(s)

        with mock.patch.object(condense, "datetime", Before311):
            code, out, err = self.run_main("--since", "2026-10-01T06:00:12-04:00", self.out,
                                           self.transcript)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("STUDENT ANSWER\nWhich layout?", self.shard())
        self.assertEqual(condense.moment("2026-10-01T10:00:00.000z"),
                         condense.moment("2026-10-01T10:00:00+00:00"))

    @unittest.skipUnless(shutil.which("python3.10"), "no python3.10 here")
    def test_a_window_on_python_3_10(self):
        r = subprocess.run(["python3.10", "-I", CONDENSE, "--since", "2026-10-01T10:00:12+00:00",
                            self.out, self.transcript], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("STUDENT ANSWER", self.shard())

    def test_an_unreadable_timestamp(self):
        self.run_main(self.out, self.transcript)
        odd = os.path.join(self.tmp, "0123abcd.jsonl")
        with open(odd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": "around ten",
                                "origin": {"kind": "human"},
                                "message": {"content": "ODDSTAMP"}}) + "\n")
        code, out, err = self.run_main("--since", "2026-10-01T00:00:00Z", self.out, odd)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("1 timestamps", err)
        self.assertNotIn("ODDSTAMP", err)
        self.assertIn(TYPED, self.shard())
        with open(odd, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": at(5), "origin": {"kind": "human"},
                                "message": {"content": "GOODSTAMP"}}) + "\n")
        code, out, err = self.run_main("--since", "2026-10-01T00:00:00Z", self.out, odd)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"^0123abcd\.md \d+K\n$")
        self.assertIn("GOODSTAMP", self.shard())
        self.assertNotIn("ODDSTAMP", self.shard())

    def test_a_time_out_of_utc_range(self):
        with open(self.transcript, "w", encoding="utf-8") as f:
            for stamp in ("0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-01:00"):
                f.write(json.dumps({"type": "user", "timestamp": stamp, "origin": {"kind": "human"},
                                    "message": {"content": "EDGE " + stamp}}) + "\n")
        code, _, err = self.run_main(self.out, self.transcript)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("### [0001-01-01T00:00:00] STUDENT\nEDGE", self.shard())
        code, _, err = self.run_main("--until", "2026-10-01T10:00:00Z", self.out, self.transcript)
        self.assertEqual(code, 1)
        self.assertIn("2 timestamps", err)

    def test_times_in_utc_earliest_to_latest(self):
        with open(self.transcript, "w", encoding="utf-8") as f:
            for stamp, words in (("2026-10-01T08:00:00-04:00", "SECOND"),
                                 ("2026-10-01T11:30:00.250Z", "THIRD"),
                                 ("2026-10-01T10:00:00Z", "FIRST")):
                f.write(json.dumps({"type": "user", "timestamp": stamp,
                                    "origin": {"kind": "human"},
                                    "message": {"content": words}}) + "\n")
        self.run_main(self.out, self.transcript)
        shard = self.shard()
        self.assertIn("- From 2026-10-01T10:00:00 to 2026-10-01T12:00:00 (UTC)", shard)
        self.assertIn("### [2026-10-01T12:00:00] STUDENT\nSECOND", shard)

    def test_the_wrapper_list(self):
        self.assertEqual(set(condense.INJECTED), set(WRAPPERS))
        self.assertEqual(set(condense.OUTPUT), set(OUTPUTS))
        self.assertEqual(set(condense.NEVER_TYPED), set(NEVER_TYPED))

    def test_prints_no_text(self):
        code, out, _ = self.run_main(self.out, self.transcript)
        self.assertEqual(code, 0)
        self.assertNotIn("cheat sheet", out)

    def test_private_modes_and_planted_links(self):
        os.makedirs(self.out, mode=0o755)
        os.chmod(self.out, 0o755)
        tree = os.path.join(self.tmp, "tree")
        os.makedirs(tree)
        target = os.path.join(self.tmp, "target.txt")
        kept = os.path.join(tree, "kept.md")
        with open(kept, "w") as f:
            f.write("KEPT")
        later = os.path.join(self.tmp, "fedcba98.jsonl")
        shutil.copy(self.transcript, later)
        os.symlink(target, os.path.join(self.out, "0123abcd.md"))
        os.link(kept, os.path.join(self.out, "fedcba98.md"))
        code, out, err = self.run_main(self.out, self.transcript, later)
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(target))
        with open(kept) as f:
            self.assertEqual(f.read(), "KEPT")
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)
        for name in ("0123abcd.md", "fedcba98.md"):
            path = os.path.join(self.out, name)
            self.assertFalse(os.path.islink(path))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(sorted(os.listdir(self.out)), ["0123abcd.md", "fedcba98.md"])

    def test_an_unwritable_shard_and_an_unusable_out_dir(self):
        os.makedirs(os.path.join(self.out, "0123abcd.md"))
        later = os.path.join(self.tmp, "fedcba98.jsonl")
        shutil.copy(self.transcript, later)
        code, out, err = self.run_main(self.out, self.transcript, later)
        self.assertEqual(code, 1)
        self.assertIn("0123abcd.md", err)
        self.assertNotIn("cheat sheet", err)
        self.assertIn("fedcba98.md", out)
        self.assertEqual(sorted(os.listdir(self.out)), ["0123abcd.md", "fedcba98.md"])
        afile = os.path.join(self.tmp, "afile")
        with open(afile, "w") as f:
            f.write("x")
        self.assertEqual(self.run_main(afile, self.transcript)[0], 2)

    def test_refuses_a_work_tree(self):
        repo = os.path.join(self.tmp, "hub")
        os.makedirs(os.path.join(repo, ".git"))
        code, _, err = self.run_main(os.path.join(repo, "retro", "shards"), self.transcript)
        self.assertEqual(code, 2)
        self.assertIn("git work tree", err)
        self.assertFalse(os.path.exists(os.path.join(repo, "retro")))
        lane = os.path.join(self.tmp, "lane")
        os.makedirs(lane)
        with open(os.path.join(lane, ".git"), "w") as f:
            f.write("gitdir: /elsewhere\n")
        self.assertEqual(self.run_main(os.path.join(lane, "s"), self.transcript)[0], 2)
        inside = os.path.join(repo, "notes")
        os.makedirs(inside)
        link = os.path.join(self.tmp, "looks-private")
        os.symlink(inside, link)
        self.assertEqual(self.run_main(os.path.join(link, "s"), self.transcript)[0], 2)
        self.assertFalse(os.path.exists(os.path.join(inside, "s")))

    def test_refuses_colliding_names(self):
        twin = os.path.join(self.tmp, "0123abcd-eeee.jsonl")
        shutil.copy(self.transcript, twin)
        code, _, err = self.run_main(self.out, self.transcript, twin)
        self.assertEqual(code, 2)
        self.assertIn("0123abcd.md", err)
        self.assertFalse(os.path.exists(self.out))

    def test_a_rerun_replaces_the_shard(self):
        self.run_main(self.out, self.transcript)
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-10-02T09:00:00Z",
                                "message": {"content": "LATERTURN"}}) + "\n")
        self.run_main(self.out, self.transcript)
        self.assertIn("LATERTURN", self.shard())

    def test_unreadable_and_usage(self):
        code, _, err = self.run_main(self.out, os.path.join(self.tmp, "missing.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("missing.jsonl", err)
        self.assertEqual(self.run_main(self.out)[0], 2)
        self.assertEqual(self.run_main("--help", self.transcript)[0], 2)

    def test_runs_isolated(self):
        r = subprocess.run([sys.executable, "-I", CONDENSE, self.out, self.transcript],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
