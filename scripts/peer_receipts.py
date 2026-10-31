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


class ReceiptError(RuntimeError):
    """The receipt file could not be written.

    Shaped like spawn-fleet's BackendError so a launch reports it the same
    way. The in-memory receipt stays complete and is still printable.
    """

    backend = "receipt"
    outcome = "failed"
    exit_code = None

    def __init__(self, path, error):
        self.command = ["write", path]
        self.code = type(error).__name__
        self.message = f"cannot write receipt {path}: {error}"
        self.session = None
        super().__init__(self.message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class LaunchReceipt:
    def __init__(self, backend, runtime, placement, correlation=None, path=None):
        self.path = path
        self.persist_failed = False
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

    def add_session(self, name, cwd, directory_created, flush=True):
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
        if flush:
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

    def add_resource(self, kind, resource_id, operation, session=None, flush=True, **extra):
        """Record a resource this launch created, the moment it exists.

        flush=False stages it in memory so several ids from one backend answer
        are all recorded before the next (fallible) write.
        """
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
        if flush:
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
        """Rewrite the receipt file atomically.

        The first write failure raises ReceiptError once; later flushes only
        update memory, so the caller can still finish and print the inventory.
        The receipt's parent directory must already exist: writing a receipt
        never creates directories that would escape the inventory.
        """
        self.data["updated_at"] = now()
        if not self.path or self.persist_failed:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        temp = None
        try:
            handle, temp = tempfile.mkstemp(dir=directory, prefix=".receipt-", suffix=".json")
            with os.fdopen(handle, "w") as stream:
                stream.write(self.to_json() + "\n")
            os.replace(temp, self.path)
        except OSError as error:
            self.persist_failed = True
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass  # reporting the write failure matters more
            failure = ReceiptError(self.path, error)
            self.data["persistence_error"] = failure.message
            raise failure from error
