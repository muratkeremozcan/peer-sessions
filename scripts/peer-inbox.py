#!/usr/bin/env python3
"""Extract verified peer-origin messages from a Claude session transcript.

With --request-id, only a reply carrying the matching line-leading
`peer-reply:` line (see peer_correlation.py) counts. The latest message from the right sender is
not enough: an older reply to an earlier request would otherwise be read as the
answer to this one. Rejected messages are counted by reason, never dropped
silently.
"""

import argparse
import datetime
import json
import sys
import time

from peer_correlation import classify
from peer_registry import find_record, find_transcript


def peer_messages(path, sender=None, msg_id=None):
    messages = []
    try:
        handle = open(path)
    except OSError as error:
        raise RuntimeError(f"cannot read transcript {path}: {error}") from error
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            origin = event.get("origin") or {}
            if event.get("type") != "user" or origin.get("kind") != "peer":
                continue
            if not isinstance(origin.get("verifiedPeerPid"), int):
                continue
            if sender is not None and sender not in (
                origin.get("name"),
                origin.get("from"),
            ):
                continue
            if msg_id is not None and origin.get("msg_id") != msg_id:
                continue
            body = origin.get("body")
            if not isinstance(body, str):
                continue
            messages.append(
                {
                    "name": origin.get("name"),
                    "from": origin.get("from"),
                    "verifiedPeerPid": origin.get("verifiedPeerPid"),
                    "msgId": origin.get("msg_id"),
                    "timestamp": event.get("timestamp"),
                    "body": body,
                }
            )
    return messages


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def correlate(messages, request_id, target=None, generation=None, since=None):
    """Split messages into matches and rejections for one request."""
    matches = []
    rejected = {}
    for message in messages:
        if since is not None:
            stamp = parse_time(message.get("timestamp"))
            if stamp is None or stamp < since:
                rejected["before-since"] = rejected.get("before-since", 0) + 1
                continue
        if request_id is None:
            matches.append(message)
            continue
        verdict = classify(message["body"], request_id, target, generation)
        if verdict == "match":
            matches.append(message)
        else:
            rejected[verdict] = rejected.get(verdict, 0) + 1
    return matches, rejected


def classify_text(args):
    """Check text from another channel (e.g. `herdr agent read`) for one request."""
    text = sys.stdin.read()
    verdict = classify(text, args.request_id, args.target, args.generation)
    payload = {
        "requestId": args.request_id,
        "target": args.target,
        "generation": args.generation,
        "outcome": verdict,
        "evidence": "reply-correlated" if verdict == "match" else "missing",
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(verdict)
    return 0 if verdict == "match" else 1


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pid", type=int, help="registry PID of the receiving session")
    target.add_argument("--session-id", help="receiving session ID")
    target.add_argument(
        "--stdin",
        action="store_true",
        help="classify text on stdin for --request-id instead of reading a transcript",
    )
    parser.add_argument("--from", dest="sender", help="exact peer name or uds: address")
    parser.add_argument("--msg-id", help="exact inbound peer message ID")
    parser.add_argument(
        "--request-id",
        help="accept only replies with a line-leading peer-reply line for this id",
    )
    parser.add_argument("--target", help="with --request-id: the peer-reply target")
    parser.add_argument(
        "--generation", help="with --request-id: the peer-reply generation"
    )
    parser.add_argument(
        "--since",
        metavar="ISO8601",
        help="reject messages stamped before this time (e.g. when the request was sent)",
    )
    parser.add_argument(
        "--all", action="store_true", help="print all matches, not only latest"
    )
    parser.add_argument("--body-only", action="store_true", help="print only message bodies")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDS")
    args = parser.parse_args()
    if (args.target or args.generation) and not args.request_id:
        parser.error("--target and --generation need --request-id")
    since = None
    if args.since is not None:
        since = parse_time(args.since)
        if since is None:
            parser.error(f"--since is not an ISO 8601 time: {args.since!r}")
    if args.stdin:
        if not args.request_id:
            parser.error("--stdin needs --request-id")
        return classify_text(args)

    session_id = args.session_id
    if args.pid is not None:
        record = find_record(pid=args.pid)
        if record is None:
            parser.error(f"no registry record for pid {args.pid}; use --session-id after exit")
        session_id = record.get("sessionId")
    if not session_id:
        parser.error("target registry record has no sessionId")

    deadline = time.monotonic() + max(args.wait, 0)
    transcript = None
    matches = []
    rejected = {}
    while True:
        transcript = find_transcript(session_id)
        if transcript:
            candidates = peer_messages(transcript, args.sender, args.msg_id)
            matches, rejected = correlate(
                candidates, args.request_id, args.target, args.generation, since
            )
        if matches or time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    correlation = None
    if args.request_id is not None or since is not None:
        correlation = {
            "requestId": args.request_id,
            "target": args.target,
            "generation": args.generation,
            "since": args.since,
            "matched": len(matches),
            "duplicates": max(len(matches) - 1, 0),
            "rejected": rejected,
            "evidence": "reply-correlated" if matches else "missing",
        }

    if not matches:
        if args.json and correlation is not None:
            print(
                json.dumps(
                    {
                        "sessionId": session_id,
                        "transcript": transcript,
                        "messages": [],
                        "correlation": correlation,
                    },
                    indent=2,
                )
            )
        if rejected:
            detail = ", ".join(f"{count} {reason}" for reason, count in sorted(rejected.items()))
            print(f"No verified peer messages matched (rejected: {detail}).", file=sys.stderr)
        else:
            print("No verified peer messages matched.", file=sys.stderr)
        return 1
    selected = matches if args.all else matches[-1:]

    if args.json:
        payload = {"sessionId": session_id, "transcript": transcript, "messages": selected}
        if correlation is not None:
            payload["correlation"] = correlation
        print(json.dumps(payload, indent=2))
        return 0

    for index, message in enumerate(selected):
        if index:
            print()
        if not args.body_only:
            print(
                f"from {message['name'] or message['from']} "
                f"pid {message['verifiedPeerPid']} msg_id {message['msgId']} "
                f"at {message['timestamp']}"
            )
        print(message["body"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
