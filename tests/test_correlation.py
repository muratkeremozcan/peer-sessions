"""Request correlation: stale, duplicate and misaddressed replies."""

import json
import os
import subprocess
import sys
import unittest

from helpers import INBOX, SCRIPTS, FleetCase

sys.path.insert(0, SCRIPTS)
import peer_correlation as correlation  # noqa: E402


class CorrelationLines(unittest.TestCase):
    def test_footer_round_trips_through_a_reply(self):
        reply = correlation.reply_line("r2", "orbits", 3) + "\nDone: PR 12"
        self.assertEqual(correlation.classify(reply, "r2", "orbits", "3"), "match")

    def test_echoed_brief_never_matches_itself(self):
        # A terminal read shows the brief, including its own instructions.
        echoed = "please review\n" + correlation.footer("r2", "orbits", "3")
        self.assertEqual(correlation.classify(echoed, "r2", "orbits", "3"), "uncorrelated")

    def test_verdicts(self):
        cases = {
            "no line at all": "uncorrelated",
            "peer-reply: id=r1 target=orbits generation=3": "other-request",
            "peer-reply: id=r2 target=sun generation=3": "wrong-target",
            "peer-reply: id=r2 target=orbits generation=2": "wrong-generation",
            "  peer-reply: id=r2 target=orbits generation=3  ": "match",
            "text before peer-reply: id=r2 target=orbits generation=3": "uncorrelated",
            "peer-reply: id=old target=wrong generation=1 id=r2 target=orbits generation=3":
                "malformed",
            "peer-reply: id=r2 target=orbits generation=3 extra": "malformed",
            "peer-reply: id=r2 target=orbits colour=red": "malformed",
        }
        for text, verdict in cases.items():
            with self.subTest(text=text):
                self.assertEqual(correlation.classify(text, "r2", "orbits", "3"), verdict)

    def test_target_and_generation_are_optional(self):
        self.assertEqual(correlation.classify("peer-reply: id=r2", "r2"), "match")

    def test_ids_with_whitespace_are_refused(self):
        for value in ("r 2", "r2\n", "\tr2", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                correlation.request_line(value)

    def test_cli_prints_the_footer(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "peer_correlation.py"),
             "--id", "r2", "--target", "orbits"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines()[:2],
            ["peer-request: id=r2 target=orbits",
             "Make the first line of your reply exactly: peer-reply: id=r2 target=orbits"],
        )


class InboxCorrelation(FleetCase):
    session_id = "relay-session"

    def setUp(self):
        super().setUp()
        transcript_dir = os.path.join(self.projects, "-tmp-relay")
        os.makedirs(transcript_dir)
        events = [
            self.event("orbits", "peer-reply: id=r1 target=orbits generation=3\nold answer",
                       "2026-10-31T10:00:00Z", 101),
            self.event("orbits", "no correlation line", "2026-10-31T10:05:00Z", 102),
            self.event("orbits", "peer-reply: id=r2 target=orbits generation=2\nlate gen",
                       "2026-10-31T10:06:00Z", 103),
            self.event("sun", "peer-reply: id=r2 target=sun generation=3\nwrong peer",
                       "2026-10-31T10:07:00Z", 104),
            self.event("orbits", "peer-reply: id=r2 target=sun generation=3\nmislabeled",
                       "2026-10-31T10:07:30Z", 107),
            self.event("someone-else",
                       "peer-reply: id=r2 target=orbits generation=3\nquoted orbits",
                       "2026-10-31T10:07:45Z", 108),
            self.event("orbits", "peer-reply: id=r2 target=orbits generation=3\nfirst",
                       "2026-10-31T10:08:00Z", 105),
            self.event("orbits", "peer-reply: id=r2 target=orbits generation=3\nrepeat",
                       "2026-10-31T10:09:00Z", 106),
            {"type": "user", "origin": {"kind": "peer", "name": "orbits",
                                        "body": "peer-reply: id=r2", "msg_id": "unverified"}},
        ]
        with open(os.path.join(transcript_dir, f"{self.session_id}.jsonl"), "w") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    def event(self, name, body, timestamp, msg):
        return {
            "type": "user",
            "timestamp": timestamp,
            "origin": {"kind": "peer", "name": name, "verifiedPeerPid": 4242,
                       "msg_id": f"m{msg}", "body": body},
        }

    def inbox(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, INBOX, *args],
            env=self.env(herdr_env=False),
            capture_output=True, text=True, input=stdin,
        )

    def test_latest_from_sender_alone_would_pick_any_reply(self):
        # Original behavior, unchanged without --request-id.
        result = self.inbox("--session-id", self.session_id, "--from", "orbits", "--json")
        self.assertEqual(json.loads(result.stdout)["messages"][0]["msgId"], "m106")

    def test_old_and_uncorrelated_replies_cannot_answer_a_new_request(self):
        result = self.inbox("--session-id", self.session_id, "--request-id", "r3", "--json")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["correlation"]["evidence"], "missing")
        self.assertEqual(
            payload["correlation"]["rejected"], {"other-request": 7, "uncorrelated": 1}
        )
        self.assertIn("rejected:", result.stderr)

    def test_only_the_right_target_and_generation_match(self):
        result = self.inbox(
            "--session-id", self.session_id, "--from", "orbits", "--request-id", "r2",
            "--target", "orbits", "--generation", "3", "--all", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual([m["msgId"] for m in payload["messages"]], ["m105", "m106"])
        self.assertEqual(payload["correlation"]["duplicates"], 1)
        self.assertEqual(
            payload["correlation"]["rejected"],
            {"other-request": 1, "uncorrelated": 1, "wrong-generation": 1, "wrong-target": 1},
        )
        self.assertEqual(payload["correlation"]["evidence"], "reply-correlated")

    def test_target_must_be_the_verified_sender(self):
        result = self.inbox(
            "--session-id", self.session_id, "--request-id", "r2", "--target", "orbits",
            "--generation", "3", "--all", "--json",
        )
        payload = json.loads(result.stdout)
        # sun's own reply and someone-else quoting orbits both fail the sender check.
        self.assertEqual(payload["correlation"]["rejected"]["sender-mismatch"], 2)
        self.assertEqual(payload["correlation"]["rejected"]["wrong-target"], 1)
        self.assertEqual([m["msgId"] for m in payload["messages"]], ["m105", "m106"])

    def test_since_drops_replies_older_than_the_request(self):
        result = self.inbox(
            "--session-id", self.session_id, "--request-id", "r2",
            "--since", "2026-10-31T10:08:30Z", "--json",
        )
        payload = json.loads(result.stdout)
        self.assertEqual([m["msgId"] for m in payload["messages"]], ["m106"])
        self.assertEqual(payload["correlation"]["rejected"]["before-since"], 7)

    def test_unverified_peer_events_never_count(self):
        result = self.inbox("--session-id", self.session_id, "--msg-id", "unverified")
        self.assertEqual(result.returncode, 1)

    def test_stdin_classifies_a_terminal_read(self):
        brief_echo = correlation.footer("r9", "rev", "1")
        result = self.inbox("--stdin", "--request-id", "r9", "--json", stdin=brief_echo)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["outcome"], "uncorrelated")
        answered = brief_echo + "\n" + correlation.reply_line("r9", "rev", "1") + "\nok"
        result = self.inbox("--stdin", "--request-id", "r9", "--target", "rev",
                            "--generation", "1", "--json", stdin=answered)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["outcome"], "match")
        # Raw text proves no sender or time: weaker evidence than a transcript.
        self.assertEqual(json.loads(result.stdout)["evidence"], "text-correlated")

    def test_stdin_refuses_filters_it_cannot_check(self):
        for flag, value in (("--since", "2099-01-01T00:00:00Z"), ("--from", "rev"),
                            ("--msg-id", "m1")):
            with self.subTest(flag=flag):
                result = self.inbox("--stdin", "--request-id", "r", flag, value,
                                    stdin="peer-reply: id=r")
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"--stdin cannot check {flag}", result.stderr)

    def test_argument_errors(self):
        for args, message in (
            (["--session-id", "x", "--target", "orbits"], "need --request-id"),
            (["--stdin"], "--stdin needs --request-id"),
            (["--session-id", "x", "--since", "yesterday"], "not an ISO 8601 time"),
        ):
            with self.subTest(args=args):
                result = self.inbox(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
