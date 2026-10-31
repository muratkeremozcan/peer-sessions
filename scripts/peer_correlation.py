#!/usr/bin/env python3
"""Carry a request identity through a brief and match it in the reply.

The issuer (a coordinator, or you) owns the request ID, target and generation.
This module only formats them into a request line and a reply line, and checks
a reply for that exact reply line. It never invents IDs or decides whether the work is complete: a
correlated reply proves the peer answered *this* request, nothing more.

The brief carries a request line; the reply must open with the matching reply
line, on a line of its own:

    peer-request: id=<id> target=<name> generation=<generation>
    peer-reply: id=<id> target=<name> generation=<generation>

Only `peer-reply:` lines that start a line count as a reply. The footer states
the reply line mid-sentence, so a terminal that echoes the brief back (such as
`herdr agent read`) never matches its own instructions. `target` and
`generation` are optional. Values may not contain whitespace.

Print the footer to paste at the end of a brief:

    python3 peer_correlation.py --id run7-ws2-r1 --target orbits --generation 3
"""

import argparse
import re
import sys


REQUEST = "peer-request:"
REPLY = "peer-reply:"
LINE = re.compile(r"^[ \t]*peer-reply:[ \t]*(?P<fields>[^\n]*?)[ \t]*$", re.MULTILINE)
VALUE = re.compile(r"^\S+$")
FIELDS = ("id", "target", "generation")


def _check(name, value):
    if value is None:
        return None
    value = str(value)
    if not VALUE.match(value):
        raise ValueError(f"{name} must be non-empty with no whitespace: {value!r}")
    return value


def _fields(request_id, target=None, generation=None):
    parts = [f"id={_check('id', request_id)}"]
    if target is not None:
        parts.append(f"target={_check('target', target)}")
    if generation is not None:
        parts.append(f"generation={_check('generation', generation)}")
    return " ".join(parts)


def request_line(request_id, target=None, generation=None):
    return f"{REQUEST} {_fields(request_id, target, generation)}"


def reply_line(request_id, target=None, generation=None):
    return f"{REPLY} {_fields(request_id, target, generation)}"


def footer(request_id, target=None, generation=None):
    return (
        f"{request_line(request_id, target, generation)}\n"
        "Make the first line of your reply exactly: "
        f"{reply_line(request_id, target, generation)}\n"
        "A reply without that line cannot be matched to this request."
    )


def parse_line(fields_text):
    """One envelope, or None if it is malformed.

    Malformed: a token without `=`, an unknown key, an empty value, a repeated
    key, or no id. A damaged or concatenated envelope must not satisfy an
    identity its opening fields do not carry.
    """
    fields = {}
    for token in fields_text.split():
        key, sep, value = token.partition("=")
        if not sep or key not in FIELDS or not value or key in fields:
            return None
        fields[key] = value
    return fields if "id" in fields else None


def parse(text):
    """Return (envelopes, malformed count) for the line-leading peer-reply lines."""
    found = []
    malformed = 0
    for match in LINE.finditer(text or ""):
        fields = parse_line(match.group("fields"))
        if fields is None:
            malformed += 1
        else:
            found.append(fields)
    return found, malformed


def classify(text, request_id, target=None, generation=None):
    """Say how `text` relates to one request.

    match             carries this id, and the target/generation asked for
    uncorrelated      carries no peer-reply line at all
    malformed         carries only peer-reply lines that do not parse cleanly
    other-request     carries only lines for different request ids
    wrong-target      right id, different target
    wrong-generation  right id and target, different generation
    """
    lines, malformed = parse(text)
    if not lines:
        return "malformed" if malformed else "uncorrelated"
    same_id = [fields for fields in lines if fields["id"] == request_id]
    if not same_id:
        return "other-request"
    if target is not None:
        same_id_target = [f for f in same_id if f.get("target") == target]
        if not same_id_target:
            return "wrong-target"
        same_id = same_id_target
    if generation is not None:
        if not any(f.get("generation") == str(generation) for f in same_id):
            return "wrong-generation"
    return "match"


def main():
    parser = argparse.ArgumentParser(description="Print a peer-request footer for a brief.")
    parser.add_argument("--id", required=True, dest="request_id")
    parser.add_argument("--target")
    parser.add_argument("--generation")
    args = parser.parse_args()
    try:
        print(footer(args.request_id, args.target, args.generation))
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
