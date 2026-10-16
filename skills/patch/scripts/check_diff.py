#!/usr/bin/env python3
"""
check_diff.py — gate the patch BEFORE submit_patch.

WHY THIS EXISTS
Scoring is PASS/FAIL on the repository's validation tests. An oversized or
stray-file diff is the silent killer: it can break unrelated tests, and it makes
the patch harder for a reviewer to accept. This script turns "is my diff sane?"
into a cheap, objective check instead of a vibe.

WHAT IT REPORTS
  - per-file added/removed line counts and the total
  - files touched outside the ones you declared (--expect)
  - obvious red flags: new files added, test files modified, huge diffs
  - a single verdict: OK / REVIEW

USAGE (in the sandbox, right before submit_patch)
  python skills/patch/scripts/check_diff.py
  python skills/patch/scripts/check_diff.py --expect fastapi/routing.py --expect fastapi/_compat/shared.py
  python skills/patch/scripts/check_diff.py --log /tmp/mydiff.patch   # parse saved diff

Exit code is always 0 — this reports, the agent decides. Stdlib only.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys

DEFAULT_MAX_FILES = 3
DEFAULT_MAX_LINES = 60

FILE_RE = re.compile(r"^\+\+\+\s+b?/(.+)$", re.M)
HUNK_RE = re.compile(r"^@@", re.M)
NEWFILE_RE = re.compile(r"^new file mode", re.M)
TEST_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$")


def get_diff(root: str) -> str:
    try:
        p = subprocess.run(["git", "-C", root, "diff", "HEAD"],
                           capture_output=True, timeout=120)
        return ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")
    except FileNotFoundError:
        return "[check_diff] git not available"
    except subprocess.TimeoutExpired:
        return "[check_diff] git diff timed out"


def parse(diff: str, root: str = "/workspace") -> dict:
    if not diff.strip():
        return {"verdict": "EMPTY", "files": [], "notes":
                ["diff is empty — nothing will be submitted"]}

    files, notes = [], []
    # split per file on 'diff --git' boundaries
    chunks = re.split(r"^diff --git ", diff, flags=re.M)[1:] or ([diff] if "--- " in diff else [])
    if not chunks:
        chunks = [diff]

    for ch in chunks:
        m = FILE_RE.search(ch)
        path = m.group(1) if m else "(unknown)"
        add = sum(1 for l in ch.splitlines()
                  if l.startswith("+") and not l.startswith("+++"))
        dele = sum(1 for l in ch.splitlines()
                   if l.startswith("-") and not l.startswith("---"))
        files.append({"file": path, "added": add, "removed": dele,
                      "new_file": bool(NEWFILE_RE.search(ch)),
                      "is_test": bool(TEST_RE.search(path))})

    total = sum(f["added"] + f["removed"] for f in files)
    return {"files": files, "total_changed_lines": total,
            "n_files": len(files), "notes": notes}


def render(info: dict, expect: list[str], max_files: int, max_lines: int,
           as_json: bool) -> str:
    if info.get("verdict") == "EMPTY":
        return ("RESULT: EMPTY\nNOTE: no changes detected — submit_patch would "
                "send nothing." if not as_json else json.dumps(info, indent=2))

    flags = []
    if info["n_files"] > max_files:
        flags.append(f"touches {info['n_files']} files (> {max_files}) — is the "
                     f"change still minimal?")
    if info["total_changed_lines"] > max_lines:
        flags.append(f"{info['total_changed_lines']} changed lines (> {max_lines}) "
                     f"— consider splitting or narrowing the edit")
    for f in info["files"]:
        if f["new_file"]:
            flags.append(f"{f['file']} is a NEW file — make sure it is part of "
                         f"the fix, not a stray artifact")
        if f["is_test"]:
            flags.append(f"{f['file']} is a TEST file — modifying tests can look "
                         f"like gaming the metric")
    if expect:
        extra = [f["file"] for f in info["files"]
                 if not any(e in f["file"] or f["file"] in e for e in expect)]
        if extra:
            flags.append("touched files outside the expected set: "
                         + ", ".join(extra))

    verdict = "REVIEW" if flags else "OK"
    info["verdict"] = verdict
    info["flags"] = flags
    if as_json:
        return json.dumps(info, ensure_ascii=False, indent=2)

    out = [f"RESULT: {verdict}",
           f"FILES: {info['n_files']}  LINES: {info['total_changed_lines']}"]
    for f in info["files"]:
        out.append(f"  {f['file']}: +{f['added']} -{f['removed']}"
                   + (" [new]" if f["new_file"] else "")
                   + (" [test]" if f["is_test"] else ""))
    for fl in flags:
        out.append(f"FLAG: {fl}")
    out.append("NEXT: " + ("re-scope the edit before submit_patch."
                           if verdict == "REVIEW" else "safe to submit_patch."))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("WORKSPACE", "/workspace"))
    ap.add_argument("--log", help="parse this saved diff instead of running git")
    ap.add_argument("--expect", action="append", default=[],
                    help="file you intend to touch (repeatable)")
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    ap.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    diff = open(a.log, "r", encoding="utf-8", errors="replace").read() if a.log \
        else get_diff(a.root)
    info = parse(diff, a.root)
    print(render(info, a.expect, a.max_files, a.max_lines, a.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
