#!/usr/bin/env python3
"""Screen a development step once under its controlled mutation or clean.

This is an authoring aid. Native eval-quality preflight qualifies probes.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import build_corpus as bc
import lab

ROOT = Path(bc.ROOT) / "evals" / "root"
RUNNER = ROOT.parent / "node_modules" / ".bin" / "tea-skill-runner"
EVALUATOR = Path(__file__).with_name("prescreen-evaluator.cjs")
OUT = Path(bc.ROOT) / "_bmad-output/test-artifacts/evaluate/peer-sessions/logs/prescreen"


def evaluate(step, check, stdout):
    result = subprocess.run(
        ["node", str(EVALUATOR)],
        input=json.dumps({"step": step, "check": check, "stdout": stdout}),
        text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


def screen(spec, clean, run, lab_path):
    step = spec["step"]
    with tempfile.TemporaryDirectory(prefix=f"ps-screen-{step}-") as work:
        target = Path(work) / "root"
        shutil.copytree(ROOT, target, symlinks=True)
        if not clean:
            skill = target / "peer-sessions" / "SKILL.md"
            text = skill.read_text()
            if text.count(spec["find"]) != 1:
                raise ValueError(f"{step} mutation requires exactly one match")
            skill.write_text(text.replace(spec["find"], spec["replace"]))
        argv = [str(RUNNER)]
        for option, value in bc.options(step).items():
            argv.extend([f"--{option}", value])
        env = {"PATH": lab_path, "HOME": os.environ["HOME"], "USER": os.environ.get("USER", "")}
        result = subprocess.run(
            argv, input=bc.prompt(spec), cwd=target, env=env,
            capture_output=True, text=True, timeout=600,
        )
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "clean" if clean else "mutated"
    (OUT / f"{step}.{tag}.{run}.txt").write_text(
        f"exit {result.returncode}\n--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}\n"
    )
    check = bc.fill(spec["clean"] if clean else spec["manifest"], f"/interactions/{step}/stdout")
    return step, tag, result.returncode, evaluate(step, check, result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("steps", nargs="*", metavar="STEP")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat requires a positive integer")
    by_step = {spec["step"]: spec for spec in bc.STEPS}
    if unknown := set(args.steps) - by_step.keys():
        parser.error(f"unknown development steps: {', '.join(sorted(unknown))}")
    if not (ROOT / "target-revision.json").is_file() or (ROOT / "peer-sessions" / ".git").exists():
        parser.error("export a committed skill with lab.py sync-root before prescreening")
    steps = args.steps or list(by_step)
    if not args.clean:
        # A step with no seed signature (teardown-split) has nothing to manifest.
        unseeded = [step for step in steps if "manifest" not in by_step[step]]
        if args.steps and unseeded:
            parser.error(f"no seeded mutation to screen: {', '.join(unseeded)}")
        steps = [step for step in steps if step not in unseeded]
    jobs = [(by_step[step], run) for run in range(args.repeat) for step in steps]
    owned_lab = lab.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            for step, tag, code, verdict in pool.map(
                lambda job: screen(job[0], args.clean, job[1], lab.run_path(owned_lab)), jobs,
            ):
                label = "passes" if args.clean else "manifests"
                print(f"{step:22} {tag:8} exit={code} {label}={verdict}", flush=True)
    finally:
        lab.stop(owned_lab)


if __name__ == "__main__":
    main()
