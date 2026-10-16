#!/usr/bin/env python3
"""
summarize_pytest.py — run pytest and return a COMPACT report.

WHY THIS IS A SKILL SCRIPT AND NOT JUST `run_command`
The harness gives the agent 12 hours for ALL tasks and a limited number of tool
calls. A raw `pytest` on a real repository prints hundreds of lines (warnings
summary, full tracebacks, deprecation spam). Feeding that back into the model
burns context twice: once to read it, once to reason about it. This script
collapses the output to the handful of facts that actually change the next
action:

    did it pass? | which tests failed and why (one line each) | first real error

It also distinguishes "no tests were collected" from "tests failed" — a
distinction the agent routinely gets wrong (usually a wrong path or a bad
`-k` expression), and one that sends it down a completely different branch.

USAGE (inside the competition sandbox, via run_command)
    python skills/verify/scripts/summarize_pytest.py --target tests/test_routing.py
    python skills/verify/scripts/summarize_pytest.py --target "tests/ -k sse" --timeout 300
    python skills/verify/scripts/summarize_pytest.py --log /tmp/out.txt    # parse a saved log

Stdlib only. Never raises on weird output — always prints something useful.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys

MAX_LINES_DEFAULT = 25

SUMMARY_RE = re.compile(
    r"(\d+)\s+passed|(\d+)\s+failed|(\d+)\s+error|"
    r"(?:={3,}\s*)?([\w\W]*?)", re.I)
COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|skipped|deselected|warnings?)")
FAILED_RE = re.compile(r"^FAILED\s+(\S+)\s*(?:-\s*(.*))?$", re.M)
ERROR_TEST_RE = re.compile(r"^ERROR\s+(\S+)\s*(?:-\s*(.*))?$", re.M)
NO_TESTS_RE = re.compile(r"(no tests ran|collected 0 items|no test files found)", re.I)
TRACEBACK_LINE = re.compile(r"^(E\s+|\s*assert|\s*AssertionError|\s*\w*Error:)", re.M)


def run(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           cwd=os.environ.get("WORKSPACE", os.getcwd()))
    except subprocess.TimeoutExpired as e:
        out = (e.output or b"") + (e.stderr or b"")
        return 124, out.decode("utf-8", "replace") + f"\n[TIMEOUT after {timeout}s]"
    except FileNotFoundError:
        return 127, f"[pytest not runnable: {cmd[0]} not found]"
    return p.returncode, ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")


def parse(log: str) -> dict:
    counts = {k: int(v) for v, k in COUNT_RE.findall(log)}
    failed = [(m.group(1), (m.group(2) or "").strip()) for m in FAILED_RE.finditer(log)]
    errors = [(m.group(1), (m.group(2) or "").strip()) for m in ERROR_TEST_RE.finditer(log)]
    no_tests = bool(NO_TESTS_RE.search(log))

    excerpt = []
    for ln in log.splitlines():
        s = ln.rstrip()
        if TRACEBACK_LINE.match(s) and s.strip():
            excerpt.append(s.strip())
        if len(excerpt) >= 6:
            break

    if counts.get("failed") or counts.get("error"):
        verdict = "FAILED"
    elif no_tests and not counts.get("passed"):
        verdict = "NO_TESTS_COLLECTED"
    elif counts.get("passed"):
        verdict = "PASSED"
    else:
        verdict = "UNKNOWN"

    return {"verdict": verdict, "counts": counts, "failed": failed,
            "errors": errors, "excerpt": excerpt}


def render(info: dict, rc: int, max_lines: int, as_json: bool) -> str:
    if as_json:
        info["returncode"] = rc
        return json.dumps(info, ensure_ascii=False, indent=2)

    out = [f"RESULT: {info['verdict']} (exit {rc})"]
    c = info["counts"]
    if c:
        out.append("COUNTS: " + ", ".join(f"{v} {k}" for k, v in c.items()))
    if info["verdict"] == "NO_TESTS_COLLECTED":
        out.append("NOTE: pytest collected nothing — check the path / -k expression "
                   "before assuming the fix is wrong.")
    for name, why in (info["failed"] + info["errors"])[:8]:
        out.append(f"  - {name}" + (f" :: {why[:160]}" if why else ""))
    if info["excerpt"]:
        out.append("ERROR EXCERPT:")
        out.extend("  " + e[:200] for e in info["excerpt"])
    if info["verdict"] == "PASSED":
        out.append("NEXT: run submit_patch.")
    elif info["verdict"] in ("FAILED", "NO_TESTS_COLLECTED"):
        out.append("NEXT: fix or re-scope the test; do NOT submit a patch "
                   "while verification is red.")
    return "\n".join(out[:max_lines])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="", help="test path / -k expression")
    ap.add_argument("--cmd", default="python -m pytest")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-lines", type=int, default=MAX_LINES_DEFAULT)
    ap.add_argument("--log", help="parse this file instead of running pytest")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.log:
        with open(a.log, "r", encoding="utf-8", errors="replace") as f:
            log = f.read()
        rc = -1
    else:
        cmd = a.cmd.split() + ["-q"] + (a.target.split() if a.target else [])
        rc, log = run(cmd, a.timeout)

    info = parse(log)
    print(render(info, rc, a.max_lines, a.json))
    # exit 0: this is a reporting tool; the caller decides from RESULT.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
