"""hooks/haiku.py (the Haiku call the Stop hooks share) and hooks/wants_input.py (the tab glyph's
"does this reply want Hayden?"). urlopen is mocked: nothing here reaches the network, and HOME
points at an empty dir so the real credentials file is never read (stdlib only)."""
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wants_input = load("wants_input")   # imports haiku from HOOKS; share that module
haiku = sys.modules["haiku"]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reply(text, stop_reason="end_turn"):
    return Response(json.dumps({"content": [{"type": "text", "text": text}],
                                "stop_reason": stop_reason}).encode())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.cfg = os.path.join(self.tmp.name, "cfg")
        os.makedirs(os.path.join(self.cfg, "projects", "slug"))
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"HOME": self.home}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.transcript = os.path.join(self.cfg, "projects", "slug", "sid.jsonl")

    def token(self, value="sk-ant-oat01-test", where=None):
        with open(os.path.join(where or self.cfg, ".credentials.json"), "w") as f:
            json.dump({"claudeAiOauth": {"accessToken": value}}, f)

    def urlopen(self, *results):
        """Patch urlopen to return or raise each result in turn; the requests land in calls."""
        self.calls = []
        results = list(results)

        def fake(req, timeout=None):
            self.calls.append((req, timeout))
            r = results.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r
        p = mock.patch.object(haiku.urllib.request, "urlopen", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)


class Haiku(Base):
    def test_the_config_dir_comes_from_the_transcripts_path(self):
        self.assertEqual(haiku.config_dir(self.transcript), self.cfg)
        self.assertEqual(haiku.config_dir("/elsewhere/x.jsonl"),
                         os.path.join(self.home, ".claude"))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/c"}):
            self.assertEqual(haiku.config_dir(None), "/c")

    def test_the_token_comes_from_the_config_dir_then_home(self):
        self.assertEqual(haiku.oauth_token(self.cfg), "")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.token("home-token", os.path.join(self.home, ".claude"))
        self.assertEqual(haiku.oauth_token(self.cfg), "home-token")
        self.token("cfg-token")
        self.assertEqual(haiku.oauth_token(self.cfg), "cfg-token")
        with open(os.path.join(self.cfg, ".credentials.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(haiku.oauth_token(self.cfg), "home-token")

    def test_a_call_sends_the_token_and_the_fields(self):
        self.token()
        self.urlopen(reply("hello"))
        self.assertEqual(haiku.ask("sys", "usr", model="m", max_tokens=9, timeout=3,
                                   cfg=self.cfg, temperature=0), "hello")
        ((req, timeout),) = self.calls
        self.assertEqual(timeout, 3)
        self.assertEqual(req.full_url, haiku.API_URL)
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-ant-oat01-test")
        self.assertEqual(req.get_header("Anthropic-beta"), "oauth-2025-04-20")
        self.assertEqual(json.loads(req.data), {
            "model": "m", "max_tokens": 9, "system": "sys", "temperature": 0,
            "messages": [{"role": "user", "content": "usr"}]})

    def test_every_failure_is_a_haiku_error_with_a_reason(self):
        self.token()
        cases = [
            (urllib.error.HTTPError(haiku.API_URL, 429, "", {}, io.BytesIO(b"")), "http-429"),
            (urllib.error.URLError(socket.timeout("timed out")), "timeout"),
            (socket.timeout("timed out"), "timeout"),
            (urllib.error.URLError(ConnectionRefusedError()), "network"),
            (ConnectionResetError(), "network"),
            (Response(b"{not json"), "bad-response"),
            (Response(b'{"content": "x"}'), "bad-response"),
            (reply("", stop_reason="refusal"), "refusal"),
        ]
        for result, reason in cases:
            with self.subTest(reason=reason, result=type(result).__name__):
                self.urlopen(result)
                with self.assertRaises(haiku.HaikuError) as e:
                    haiku.ask("s", "u", model="m", max_tokens=1, timeout=1, cfg=self.cfg)
                self.assertEqual(e.exception.reason, reason)

    def test_no_token_means_no_request(self):
        self.urlopen()
        with self.assertRaises(haiku.HaikuError) as e:
            haiku.ask("s", "u", model="m", max_tokens=1, timeout=1, cfg=self.cfg)
        self.assertEqual(e.exception.reason, "no-token")
        self.assertEqual(self.calls, [])


class WantsInput(Base):
    def event(self, message):
        return {"session_id": "sid", "transcript_path": self.transcript,
                "last_assistant_message": message}

    def test_the_answer_is_read_from_its_first_word(self):
        self.token()
        for text, want in (("YES", ("yes", "-")), ("no.", ("no", "-")),
                           ("Yes\n\nThe message asks", ("yes", "-")), ("**NO**", ("no", "-")),
                           ("Maybe", ("error", "bad-answer")), ("", ("error", "bad-answer"))):
            with self.subTest(text=text):
                self.urlopen(reply(text))
                self.assertEqual(wants_input.classify(self.event("Shall I push?")), want)

    def test_the_request_is_the_replay_tested_one(self):
        # PLAN.md "Next: two workflow fixes": v4 of the replay ran on Haiku 4.5 at temperature
        # 0 with the reply's last 2,000 characters; Haiku 5.5 answers 429 to this token.
        self.token()
        self.urlopen(reply("NO"))
        wants_input.classify(self.event("x" * 2500 + "Add this line to settings.json."))
        body = json.loads(self.calls[0][0].data)
        self.assertEqual((body["model"], body["temperature"], body["max_tokens"]),
                         ("claude-haiku-4-5", 0, 16))
        self.assertNotIn("thinking", body)
        self.assertEqual(body["system"], wants_input.SYSTEM)
        content = body["messages"][0]["content"]
        self.assertTrue(content.startswith("<message>\n" + chr(0x2026)), content[:20])
        self.assertTrue(content.endswith("Add this line to settings.json.\n</message>"))
        self.assertEqual(len(content), len("<message>\n\n</message>") + 1 + 2000)

    def test_an_empty_reply_is_no_without_a_call(self):
        self.urlopen()
        for message in ("", "   \n", None, 7):
            self.assertEqual(wants_input.classify(self.event(message)), ("no", "-"))
        self.assertEqual(wants_input.classify(None), ("no", "-"))
        self.assertEqual(self.calls, [])

    def test_a_failed_call_is_an_error_with_its_reason(self):
        self.assertEqual(wants_input.classify(self.event("Shall I push?")),
                         ("error", "no-token"))

    def test_the_script_prints_one_line_of_three_fields(self):
        # No token under this HOME, so the call fails fast with no request.
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        p = subprocess.run([sys.executable, "-I", os.path.join(HOOKS, "wants_input.py")],
                           input=json.dumps(self.event("Shall I push?")), capture_output=True,
                           text=True, timeout=20, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        verdict, reason, ms = p.stdout.split()
        self.assertEqual((verdict, reason), ("error", "no-token"))
        self.assertTrue(ms.isdigit())
        p = subprocess.run([sys.executable, "-I", os.path.join(HOOKS, "wants_input.py")],
                           input="{garbage", capture_output=True, text=True, timeout=20, env=env)
        self.assertEqual(p.stdout.split()[:2], ["no", "-"])


if __name__ == "__main__":
    unittest.main()
