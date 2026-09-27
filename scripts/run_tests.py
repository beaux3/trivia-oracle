#!/usr/bin/env python3
"""Run the full test suite (or a subset) in one shot with a consolidated report.

Each test directory needs its own Docker image and mounts (see AGENTS.md /
README "Running tests"), so historically that meant three separate `docker
run ... unittest discover ...` invocations with verbose per-test output to
read through. This script runs all of them, collapses passing runs to one
line each, and only prints full tracebacks for what actually failed — along
with a ready-to-paste command to rerun just those tests.

Usage:
    python3 scripts/run_tests.py                      # everything
    python3 scripts/run_tests.py backend               # one group
    python3 scripts/run_tests.py bot integration        # a few groups
    python3 scripts/run_tests.py tests.backend.test_votes.VotesTest.test_foo
                                                          # one specific test
    python3 scripts/run_tests.py --no-build             # skip `docker build`
    python3 scripts/run_tests.py --with-data backend    # mount ./data too
                                                          # (checks every answerline)

Exit code is 0 iff every test passed.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

BOT_IMAGE = "trivia-oracle-bot"
BACKEND_IMAGE = "trivia-oracle-backend"

# name -> (image, [test dirs], extra host:container mounts beyond tests/)
GROUPS = {
    "bot": (BOT_IMAGE, ["tests/bot", "tests/game"], []),
    "backend": (BACKEND_IMAGE, ["tests/backend"], []),
    "integration": (
        BACKEND_IMAGE,
        ["tests/contract", "tests/integration"],
        [("trivia_oracle_bot", "trivia_oracle_bot")],
    ),
}

# tests/<subdir> -> owning group, so a dotted test id can be routed to the
# right image+mounts without the caller having to know the grouping.
DIR_TO_GROUP = {
    "bot": "bot",
    "game": "bot",
    "backend": "backend",
    "contract": "integration",
    "integration": "integration",
}

SEP = "-" * 70

FAILURE_BLOCK_RE = re.compile(
    r"^={10,}\n(?P<kind>FAIL|ERROR): \S+ \((?P<id>[^)]+)\)\n-{10,}\n"
    r"(?P<trace>.*?)(?=\n={10,}\n|\n-{10,}\nRan \d+ test)",
    re.M | re.S,
)
SUMMARY_RE = re.compile(r"^Ran (\d+) tests? in [\d.]+s$", re.M)
RESULT_RE = re.compile(r"^(OK|FAILED)(?:\s*\(([^)]*)\))?\s*$", re.M)


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, **kw)


def build_images(images, quiet_ok=True):
    for image, dockerfile in images:
        print(f"[build] {image} ...", end=" ", flush=True)
        proc = sh(["docker", "build", "-q", "-f", dockerfile, "-t", image, "."])
        if proc.returncode != 0:
            print("FAILED")
            print(proc.stdout)
            print(proc.stderr)
            sys.exit(1)
        print("ok")


def run_discover(image, test_dir, extra_mounts, with_data):
    mounts = ["-v", f"{REPO_ROOT / 'tests'}:/app/tests:ro"]
    for host_rel, container_rel in extra_mounts:
        mounts += ["-v", f"{REPO_ROOT / host_rel}:/app/{container_rel}:ro"]
    if with_data:
        mounts += ["-v", f"{REPO_ROOT / 'data'}:/app/data:ro"]
    cmd = ["docker", "run", "--rm", *mounts, image,
           "python", "-m", "unittest", "discover", "-s", test_dir, "-t", "."]
    proc = sh(cmd)
    return proc.stdout + proc.stderr


def run_single(image, extra_mounts, with_data, test_id):
    mounts = ["-v", f"{REPO_ROOT / 'tests'}:/app/tests:ro"]
    for host_rel, container_rel in extra_mounts:
        mounts += ["-v", f"{REPO_ROOT / host_rel}:/app/{container_rel}:ro"]
    if with_data:
        mounts += ["-v", f"{REPO_ROOT / 'data'}:/app/data:ro"]
    cmd = ["docker", "run", "--rm", *mounts, image,
           "python", "-m", "unittest", "-v", test_id]
    proc = sh(cmd)
    return proc.stdout + proc.stderr


def parse(output):
    """Return (ran, status_word, counts_dict, [(kind, id, trace), ...])."""
    ran_match = SUMMARY_RE.search(output)
    ran = int(ran_match.group(1)) if ran_match else 0
    result_match = RESULT_RE.search(output)
    status = result_match.group(1) if result_match else "UNKNOWN"
    counts = {}
    if result_match and result_match.group(2):
        for part in result_match.group(2).split(", "):
            k, v = part.split("=")
            counts[k] = int(v)
    failures = [
        (m.group("kind"), m.group("id"), m.group("trace").strip())
        for m in FAILURE_BLOCK_RE.finditer(output)
    ]
    return ran, status, counts, failures


def route_test_id(test_id):
    parts = test_id.split(".")
    if len(parts) < 2 or parts[0] != "tests" or parts[1] not in DIR_TO_GROUP:
        return None
    group_name = DIR_TO_GROUP[parts[1]]
    return group_name, GROUPS[group_name]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("targets", nargs="*",
                         help="group names (bot, backend, integration) and/or dotted test ids "
                              "(e.g. tests.backend.test_votes.VotesTest.test_foo). Default: all groups.")
    parser.add_argument("--no-build", action="store_true", help="skip `docker build` (reuse existing images)")
    parser.add_argument("--with-data", action="store_true",
                         help="also mount ./data into the backend group (checks every answerline in the db)")
    args = parser.parse_args()

    group_targets = [t for t in args.targets if t in GROUPS]
    test_id_targets = [t for t in args.targets if t not in GROUPS]

    single_runs = []  # (label, image, extra_mounts, test_id)
    for tid in test_id_targets:
        routed = route_test_id(tid)
        if routed is None:
            print(f"error: can't route {tid!r} to a test group "
                  f"(expected tests.<bot|game|backend|contract|integration>....)")
            sys.exit(2)
        group_name, (image, _dirs, extra_mounts) = routed
        single_runs.append((tid, image, extra_mounts, tid))

    if not group_targets and not single_runs:
        group_targets = list(GROUPS.keys())

    needed_images = {}
    for name in group_targets:
        image, _dirs, _mounts = GROUPS[name]
        dockerfile = "trivia_oracle_bot/Dockerfile" if image == BOT_IMAGE else "trivia_oracle_backend/Dockerfile"
        needed_images[image] = dockerfile
    for _label, image, _mounts, _tid in single_runs:
        dockerfile = "trivia_oracle_bot/Dockerfile" if image == BOT_IMAGE else "trivia_oracle_backend/Dockerfile"
        needed_images[image] = dockerfile

    if not args.no_build:
        build_images(sorted(needed_images.items()))
    print()

    rows = []          # (label, ran, status, counts)
    all_failures = []  # (kind, id, trace)
    start = time.time()

    for name in group_targets:
        image, dirs, extra_mounts = GROUPS[name]
        for test_dir in dirs:
            label = f"{name:<12} {test_dir}"
            print(f"{label} ...", end=" ", flush=True)
            output = run_discover(image, test_dir, extra_mounts, args.with_data and name == "backend")
            ran, status, counts, failures = parse(output)
            rows.append((label, ran, status, counts))
            all_failures.extend(failures)
            extra = f" ({', '.join(f'{k}={v}' for k, v in counts.items())})" if counts else ""
            print(f"{status}{extra}  [{ran} tests]")

    for label, image, extra_mounts, tid in single_runs:
        print(f"{label} ...", end=" ", flush=True)
        output = run_single(image, extra_mounts, args.with_data, tid)
        ran, status, counts, failures = parse(output)
        rows.append((label, ran, status, counts))
        all_failures.extend(failures)
        extra = f" ({', '.join(f'{k}={v}' for k, v in counts.items())})" if counts else ""
        print(f"{status}{extra}  [{ran} tests]")

    elapsed = time.time() - start

    if all_failures:
        print()
        print(SEP)
        for kind, test_id, trace in all_failures:
            print(f"{kind}: {test_id}")
            print(trace)
            print(SEP)

        print()
        print(f"{len(all_failures)} failing test(s):")
        for _kind, test_id, _trace in all_failures:
            print(f"  {test_id}")
        print()
        print("Rerun just the failing test(s):")
        ids = " ".join(t for _k, t, _tr in all_failures)
        print(f"  python3 scripts/run_tests.py --no-build {ids}")

    total_ran = sum(r[1] for r in rows)
    total_failures = sum(r[3].get("failures", 0) for r in rows)
    total_errors = sum(r[3].get("errors", 0) for r in rows)
    total_skipped = sum(r[3].get("skipped", 0) for r in rows)
    ok = total_failures == 0 and total_errors == 0 and all(r[2] != "UNKNOWN" for r in rows)

    print()
    skip_part = f", {total_skipped} skipped" if total_skipped else ""
    print(f"TOTAL: {total_ran} tests, {total_failures} failed, {total_errors} errors{skip_part} "
          f"in {elapsed:.1f}s — {'PASSED' if ok else 'FAILED'}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
