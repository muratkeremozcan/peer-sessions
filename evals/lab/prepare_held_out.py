#!/usr/bin/env python3
"""Build the private held-out evaluation view outside the repository.

The held-out source never lives in this repository. It sits in a mode-0700
state directory that the tested agent cannot read (see `lab.py`, whose
`claude` wrapper denies it under Seatbelt):

    $XDG_STATE_HOME/peer-sessions-eval/   (default ~/.local/state/...)
      held-out/partition.json   partitionPlan, heldOutProbes, heldOutCoverageExclusions
      held-out/plan.json        the held-out steps and oracles
      held-out/probes/          the held-out probes
      views/held-out-*/         views this script builds

The view joins the public development inputs with the held-out source, binds
P-023's exact address signature, and passes `tea-evaluate digest` and `check`.
Use the printed directory as --evaluation for the held-out preflight and run,
with --partition held-out --from-working-tree, and score its invocation by ID
in the same directory. Keep the view with its evidence until review.

`--digest` prints the frozen held-out digest of the current source without
keeping a view.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import build_corpus as bc

SOURCE = Path(bc.EVAL)
TEA = SOURCE.parent / "node_modules" / ".bin" / "tea-evaluate"
PUBLIC = ("requirements.md", "contract.json", "policy", "mutations", "probes")
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "peer-sessions-eval"
HELD = STATE / "held-out"
VIEWS = STATE / "views"


def private_dir(path):
    info = path.lstat()
    if not path.is_dir() or path.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError(f"{path} must be a mode-0700 directory you own")
    return path


def held_file(name):
    """A held-out path inside HELD with no symlink, so the sandbox deny list covers it."""
    path = private_dir(HELD) / name
    if path.is_symlink() or not path.resolve().is_relative_to(HELD.resolve()):
        raise ValueError(f"{path} must resolve inside {HELD} with no symlink")
    return path


def source_digest():
    """sha256 over every held-out source file, by relative path."""
    digest = hashlib.sha256()
    for path in sorted(private_dir(HELD).rglob("*")):
        if path.is_file() or path.is_symlink():
            held_file(path.relative_to(HELD))
            digest.update(f"{path.relative_to(HELD).as_posix()}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return "sha256:" + digest.hexdigest()


def prepare():
    private_dir(STATE)
    partition = json.loads(held_file("partition.json").read_text())
    manifest = json.loads((SOURCE / "evaluation.json").read_text())
    if set(partition) & set(manifest):
        raise ValueError("the public evaluation.json must not declare the held-out partition")
    held_plan = json.loads(held_file("plan.json").read_text())
    step = next(item for item in held_plan["interactionPlan"] if item["stepId"] == "held-brief-address")
    prompt = step["inputBinding"]["stdin"]["prompt"]["literal"]
    address, = re.findall(bc.REPLY_SOCKET, prompt)

    VIEWS.mkdir(mode=0o700, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="held-out-", dir=private_dir(VIEWS)))
    try:
        for name in PUBLIC:
            source = SOURCE / name
            if source.is_dir():
                shutil.copytree(source, folder / name)
            else:
                shutil.copy2(source, folder / name)
        # launch.root must stay relative, so climb from the view to the public export.
        manifest["launch"]["root"] = os.path.relpath((SOURCE / manifest["launch"]["root"]).resolve(), folder)
        manifest.update(partition)
        (folder / "evaluation.json").write_text(json.dumps(manifest, indent=2) + "\n")
        plan_path = folder / partition["partitionPlan"]["heldOutPlan"]
        plan_path.parent.mkdir(parents=True)
        shutil.copy2(held_file("plan.json"), plan_path)
        for probe in sorted(held_file("probes").glob("*.probe.json")):
            probe = held_file(probe.relative_to(HELD))
            if (folder / "probes" / probe.name).exists():
                raise ValueError(f"held-out probe {probe.name} collides with a development probe")
            shutil.copy2(probe, folder / "probes" / probe.name)
        # Keep the sealed literal in the held-out view. TeA rejects a signature
        # clause that compares the input prompt directly with stdout.
        probe_file = folder / "probes" / "P-023.probe.json"
        probe = json.loads(probe_file.read_text())
        probe["defectSignature"]["condition"]["predicate"] = bc.fill(
            bc.missing_reply_footer(address), "/interactions/observed/stdout",
        )
        # The manifestation witness comes from the same function, so the two
        # cannot drift apart (held-out preflight 20261125T011503703Z-216b2505
        # failed seeded-faults-scoped on a witness left on the old form).
        witness = probe["defects"][0]["manifestationWitness"]
        witness_addresses = set(re.findall(
            r"uds:/tmp/cc-socks/[0-9]+\.sock", json.dumps(witness["inputs"]),
        ))
        if len(witness_addresses) != 1:
            raise ValueError("P-023's manifestation witness must name exactly one reply address")
        witness["relation"] = bc.fill(
            bc.missing_reply_footer(witness_addresses.pop()),
            f"/interactions/{witness['legId']}/stdout",
        )
        probe_file.write_text(json.dumps(probe, indent=2) + "\n")
        for verb in ("digest", "check"):
            subprocess.run([TEA, verb, "--evaluation", folder], stdout=subprocess.DEVNULL, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError):
        shutil.rmtree(folder)
        raise
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digest", action="store_true", help="print the held-out source digest and exit")
    args = parser.parse_args()
    if args.digest:
        print(source_digest())
    else:
        print(prepare())


if __name__ == "__main__":
    main()
