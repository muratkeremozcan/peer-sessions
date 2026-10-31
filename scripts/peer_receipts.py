#!/usr/bin/env python3
"""Launch receipts: an incremental record of what one spawn allocated.

A receipt is written after every allocation, not once at the end, so a launch
that dies halfway still leaves an inventory of the panes, workspaces, windows
and directories it created. The transport echoes caller-supplied correlation
fields verbatim and never assigns them meaning. See
docs/coordination-contract-v1.md.
"""

import datetime
import json
import os
import tempfile
import uuid


SCHEMA = "peer-sessions/launch-receipt"
SCHEMA_VERSION = 1
CONTRACT = {
    "name": "peer-sessions-transport",
    "version": "1",
    # No consumer has agreed this contract yet. Flip to "agreed" only when a
    # consumer records the same version and file digest.
    "status": "pending",
}

# Session states, in launch order. A session moves forward only.
SESSION_STATES = (
    "pending",  # validated, nothing started yet
    "start_requested",  # launch command issued to the backend
    "started",  # backend confirmed the agent process came up
    "ready",  # addressable through this backend's readiness signal
    "not_ready",  # started, but not addressable before the timeout
    "blocked",  # startup stopped at an approval or question UI
    "denied",  # the backend refused the operation
    "unknown",  # the backend's outcome could not be determined
    "failed",  # the backend rejected the launch outright
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class LaunchReceipt:
    def __init__(self, backend, runtime, placement, correlation=None, path=None):
        self.path = path
        self.data = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "contract": dict(CONTRACT),
            "launch_id": uuid.uuid4().hex,
            "created_at": now(),
            "updated_at": now(),
            "backend": backend,
            "runtime": runtime,
            "placement": placement,
            "correlation": dict(correlation or {}),
            "status": "launching",
            "resources": [],
            "sessions": [],
            "failure": None,
        }
        self.flush()

    # -- recording ---------------------------------------------------------

    def add_session(self, name, cwd, directory_created):
        self.data["sessions"].append(
            {
                "name": name,
                "runtime": self.data["runtime"],
                "cwd": cwd,
                "directory_created": directory_created,
                "state": "pending",
                "identity": {},
            }
        )
        self.flush()

    def session(self, name):
        for entry in self.data["sessions"]:
            if entry["name"] == name:
                return entry
        raise KeyError(name)

    def update_session(self, name, state=None, **identity):
        entry = self.session(name)
        if state is not None:
            if state not in SESSION_STATES:
                raise ValueError(f"unknown session state {state!r}")
            entry["state"] = state
        entry["identity"].update(
            {key: value for key, value in identity.items() if value is not None}
        )
        self.flush()

    def add_resource(self, kind, resource_id, operation, session=None, **extra):
        """Record a resource this launch created, the moment it exists."""
        resource = {
            "kind": kind,
            "id": resource_id,
            "operation": operation,
            "owned": True,
            "session": session,
            "created_at": now(),
        }
        resource.update({key: value for key, value in extra.items() if value is not None})
        self.data["resources"].append(resource)
        self.flush()
        return resource

    def owned(self, kind):
        return [r for r in self.data["resources"] if r["kind"] == kind and r["owned"]]

    def fail(self, operation, error, session=None):
        self.data["failure"] = {
            "operation": operation,
            "session": session,
            "backend": getattr(error, "backend", None),
            "command": getattr(error, "command", None),
            "code": getattr(error, "code", None),
            "outcome": getattr(error, "outcome", "failed"),
            "exit_code": getattr(error, "exit_code", None),
            "message": getattr(error, "message", str(error)),
            "at": now(),
        }
        self.data["status"] = "partial" if self.data["resources"] else "failed"
        self.flush()

    def finish(self, status):
        self.data["status"] = status
        self.flush()

    # -- output ------------------------------------------------------------

    def to_json(self):
        return json.dumps(self.data, indent=2)

    def flush(self):
        self.data["updated_at"] = now()
        if not self.path:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=directory, prefix=".receipt-", suffix=".json")
        try:
            with os.fdopen(handle, "w") as stream:
                stream.write(self.to_json() + "\n")
            os.replace(temp, self.path)
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise
