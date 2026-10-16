#!/usr/bin/env python3
"""
verify_trajectories.py — prove that synthesized edit_file ops apply to REAL files.

WHY THIS EXISTS (this is the gate that matters)
build_trajectories.py can happily emit a trajectory whose edit_file(old_string, ...)
does not exist in the actual repository source. If that happens, every trajectory
teaches the model to emit an edit that FAILS — silently poisoning the LoRA and
wasting the whole fine-tuning budget on Kaggle.

This verifier closes that hole with real GitHub content:
  1. fetch the buggy source of every patched file at the PR's base_sha
  2. apply the synthesized edit_file ops, in order            -> `got`
  3. apply the gold unified diff independently (from the raw patch) -> `want`
  4. assert got == want

Both sides are derived by different code paths, so agreement is real evidence that
the diff -> edit_file conversion is lossless.

USAGE
  python finetune/verify_trajectories.py --tasks finetune/tasks.jsonl --max 15
  python finetune/verify_trajectories.py --tasks finetune/tasks.jsonl --max 15 -v

Exit code 0 only if every checked task passes. Token via $GH_TOKEN (optional;
raw.githubusercontent.com works unauthenticated for public repos).

Stdlib only.
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_trajectories import parse_unified_diff, synthesize, fmt_call  # noqa: E402

API = "https://api.github.com"

# NOTE: raw.githubusercontent.com is unreachable from this sandbox (TLS is
# severed mid-handshake: SSL UNEXPECTED_EOF_WHILE_READING). Everything therefore
# goes through api.github.com, which is verified reachable.


def _api(path: str, token: str | None, raw: bool = False):
    req = urllib.request.Request(
        path if path.startswith("http") else f"{API}{path}",
        headers={
            "Accept": "application/vnd.github.raw" if raw
                      else "application/vnd.github+json",
            "User-Agent": "gemmapilot-verify/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def fetch_raw(repo: str, sha: str, path: str, token: str | None,
              tries: int = 3) -> str | None:
    """Fetch a file's content at a given commit, via the contents/blobs API."""
    for k in range(tries):
        try:
            meta = json.loads(_api(f"/repos/{repo}/contents/{path}?ref={sha}", token))
            if isinstance(meta, list):          # path is a directory
                return None
            if meta.get("encoding") == "base64" and meta.get("content"):
                import base64
                return base64.b64decode(
                    "".join(meta["content"].split())).decode("utf-8", "replace")
            # >1 MB: content omitted, fall back to the blob API
            if meta.get("sha"):
                blob = json.loads(_api(f"/repos/{repo}/git/blobs/{meta['sha']}", token))
                if blob.get("encoding") == "base64":
                    import base64
                    return base64.b64decode(
                        "".join(blob["content"].split())).decode("utf-8", "replace")
            return None
        except urllib.error.HTTPError as e:
            if e.code == 404:       # file was ADDED by the PR -> nothing to patch
                return None
            if e.code in (403, 429):
                time.sleep(2 + 2 * k)
                continue
            return None
        except Exception:
            time.sleep(1 + k)
    return None


def apply_hunks(src: str, hunks: list[dict]) -> str | None:
    """Independent patch applier: exact old-block -> new-block, in order."""
    for h in hunks:
        old, new = h["old"], h["new"]
        if old and old not in src:
            return None
        if not old:                       # pure insertion at top of hunk
            src = new + src
        else:
            src = src.replace(old, new, 1)
    return src


def collect_edits(example: dict) -> list[dict]:
    ops = []
    for m in example["messages"]:
        if m.get("role") != "assistant":
            continue
        try:
            obj = json.loads(m["content"])
        except Exception:
            continue
        if obj.get("tool") == "edit_file":
            ops.append(obj["args"])
    return ops


def verify_task(task: dict, system_prompt: str, token: str | None,
                verbose: bool) -> tuple[bool, str]:
    files = parse_unified_diff(task["gold_patch"])
    if not files:
        return False, "gold_patch parsed to zero files"

    example = synthesize(task, system_prompt)
    edits = collect_edits(example)
    if not edits:
        return False, "trajectory contains no edit_file op"

    edits_by_file: dict[str, list[dict]] = {}
    for e in edits:
        edits_by_file.setdefault(e["filepath"], []).append(e)

    checked = 0
    for f in files:
        path, hunks = f["file"], f["hunks"]
        if path not in edits_by_file:
            return False, f"{path}: no edit op emitted"
        base = fetch_raw(task["repo"], task.get("base_sha", "HEAD"), path, token)
        if base is None:
            continue                       # added file, or unreachable -> skip
        want = apply_hunks(base, hunks)
        if want is None:
            return False, f"{path}: gold diff does not apply to base_sha source"
        got = base
        for e in edits_by_file[path]:
            if e["old_string"] not in got:
                return False, f"{path}: synthesized old_string NOT FOUND in real source"
            got = got.replace(e["old_string"], e["new_string"], 1)
        if got != want:
            return False, f"{path}: edit result != gold diff result"
        checked += 1
        if verbose:
            print(f"    OK {path} ({len(hunks)} hunk(s))")
        time.sleep(0.1)

    if checked == 0:
        return False, "no file could be fetched (all added or unreachable)"
    return True, f"{checked} file(s) verified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--system", default=os.path.join(HERE, "..", "prompts", "system.md"))
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN")
                    or os.environ.get("GITHUB_TOKEN"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    with open(a.system, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    tasks = [json.loads(l) for l in open(a.tasks, "r", encoding="utf-8") if l.strip()]
    tasks = tasks[:a.max]

    ok = fail = 0
    for t in tasks:
        good, why = verify_task(t, system_prompt, a.token, a.verbose)
        tag = "PASS" if good else "FAIL"
        print(f"[{tag}] {t['id']}: {why}")
        ok += good
        fail += not good

    print(f"\n{ok} passed, {fail} failed (of {len(tasks)})")
    if fail:
        print("[verify_trajectories] NOT ALL TRAJECTORIES APPLY TO REAL SOURCE")
        return 1
    print("[verify_trajectories] ALL CHECKED TRAJECTORIES APPLY TO REAL SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
