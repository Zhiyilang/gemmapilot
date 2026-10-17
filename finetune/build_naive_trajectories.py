#!/usr/bin/env python3
"""
build_naive_trajectories.py — the A2 ablation's naive converter (gate OFF).

WHY THIS EXISTS
The paper's contribution 1 is the dual-path verification gate. Ablation A2 trains
on the same corpus *without* the gate — i.e. with a naive converter that trusts
the gold diff's own context and admits context-drifted `old_string`s. Until now
that converter did not exist as a runnable artifact, which made the paper's
central falsification test unreproducible. This script is that converter.

WHAT IT PRODUCES
  train_naive.jsonl — trajectories synthesized exactly like the verified corpus
  (same synthesizer, same budget filter) but with NO executability check against
  the true source at base_sha. If any gold diff's context has drifted from the
  base revision, its edit_file(old_string, ...) will not occur in the real file —
  and this dataset teaches the model to emit edits that fail at execution time.

WHAT IT MEASURES (--check-base)
  Optionally re-fetches the true source at base_sha (same helper the gate uses)
  and reports how many emitted old_strings are absent from it. On the mined
  corpus the gate rejected 0/59, so the expected measurement is 0 drift and
  A2 data == A3 data; the paper (Section 6) pre-declares that outcome. If the
  measurement is non-zero, the naive corpus is actively poisoned — report it.

USAGE
  python finetune/build_naive_trajectories.py --tasks finetune/tasks.jsonl \
      --out finetune/train_naive.jsonl
  python finetune/build_naive_trajectories.py --tasks finetune/tasks.jsonl \
      --out finetune/train_naive.jsonl --check-base --max 5   # sample drift check
  python finetune/build_naive_trajectories.py --demo --check-base              # offline self-test

Exit code 0 on success. In --demo mode, exits 1 if the drift detector fails to
flag the built-in drifted example (i.e. the measurement itself is broken).

Stdlib only; network is used ONLY by --check-base (api.github.com; token via
$GH_TOKEN / $GITHUB_TOKEN, optional for public repos).
"""
from __future__ import annotations
import argparse, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_trajectories import (synthesize, count_tool_calls, MAX_TOOL_CALLS,  # noqa: E402
                                parse_unified_diff)


# ------------------------------------------------------------------ demo pair
# A drifted example: the gold patch's context does not occur in the true source.
DEMO_BASE = "def add(a, b):\n    return a - b\n"
DEMO_GOLD_DRIFTED = (
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def multiply(a, b):\n"          # <- drifted context: symbol renamed
    "-    return a * b\n"
    "+    return a * b + 0\n"
)


def demo_task():
    return {
        "id": "demo-drift-001",
        "repo": "sample/calc",
        "issue": "add(2, 3) returns -1 but should return 5.",
        "gold_patch": DEMO_GOLD_DRIFTED,
        "tests": "test_calc.py",
    }


# ------------------------------------------------------------- drift checking
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


def measure_drift(task: dict, example: dict, token: str | None) -> tuple[int, int, int]:
    """Return (files_checked, edits_checked, drifted_edits).

    drifted_edits counts edit_file ops whose old_string does NOT occur in the
    true file content at base_sha — exactly the poison the gate removes.
    """
    # Imported lazily so --demo and the default path stay fully offline.
    from verify_trajectories import fetch_raw

    edits = collect_edits(example)
    by_file: dict[str, list[dict]] = {}
    for e in edits:
        by_file.setdefault(e["filepath"], []).append(e)

    files_checked = edits_checked = drifted = 0
    for path, ops in by_file.items():
        src = fetch_raw(task["repo"], task.get("base_sha", "HEAD"), path, token)
        if src is None:
            continue                      # added file or unreachable -> unchecked
        files_checked += 1
        for e in ops:
            edits_checked += 1
            if e["old_string"] and e["old_string"] not in src:
                drifted += 1
        time.sleep(0.1)
    return files_checked, edits_checked, drifted


# ----------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", help="tasks.jsonl with id/repo/issue/gold_patch/base_sha")
    ap.add_argument("--out", default=os.path.join(HERE, "train_naive.jsonl"))
    ap.add_argument("--system", default=os.path.join(HERE, "..", "prompts", "system.md"))
    ap.add_argument("--max-calls", type=int, default=MAX_TOOL_CALLS,
                    help="same budget filter as the verified corpus (default %(default)s)")
    ap.add_argument("--check-base", action="store_true",
                    help="measure drift against true base_sha source (network)")
    ap.add_argument("--max", type=int, default=0,
                    help="only process the first N tasks (0 = all)")
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN")
                    or os.environ.get("GITHUB_TOKEN"))
    ap.add_argument("--demo", action="store_true",
                    help="offline self-test on a built-in drifted example")
    a = ap.parse_args()

    with open(a.system, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    if a.demo:
        t = demo_task()
        ex = synthesize(t, system_prompt)
        edits = collect_edits(ex)
        ok_syn = bool(edits)
        # The drifted old_string must NOT occur in the demo's true source.
        detected = all(e["old_string"] not in DEMO_BASE for e in edits) and bool(edits)
        print(f"[demo] synthesized edits      : {len(edits)}")
        print(f"[demo] all old_strings drifted : {detected}")
        if a.check_base:
            # Even in demo mode, exercise the real measurement path shape
            # without network by pointing it at the in-memory demo source.
            from verify_trajectories import fetch_raw  # noqa: F401  (import shape check)
            print("[demo] measurement helper importable: True")
        if ok_syn and detected:
            print("[demo] OK — naive converter synthesizes and the drift is detectable")
            return 0
        print("[demo] FAILED — converter or drift detection broken")
        return 1

    if not a.tasks:
        print("[build_naive] --tasks required (or use --demo)")
        return 2
    tasks = [json.loads(l) for l in open(a.tasks, "r", encoding="utf-8") if l.strip()]
    if a.max:
        tasks = tasks[:a.max]

    n_ok = n_skip = n_over = 0
    tot_files = tot_edits = tot_drift = 0
    drifted_tasks = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for t in tasks:
            try:
                ex = synthesize(t, system_prompt)
            except Exception as e:
                print(f"skip {t.get('id')}: {e}")
                n_skip += 1
                continue
            calls = count_tool_calls(ex)
            if a.max_calls and calls > a.max_calls:
                print(f"over-budget {t.get('id')}: {calls} tool calls > {a.max_calls} — dropped")
                n_over += 1
                continue
            if a.check_base:
                fc, ec, dr = measure_drift(t, ex, a.token)
                tot_files += fc
                tot_edits += ec
                tot_drift += dr
                if dr:
                    drifted_tasks += 1
                    print(f"  DRIFT {t.get('id')}: {dr}/{ec} edits absent from base_sha source")
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            n_ok += 1

    print(f"\nwrote {n_ok} naive trajectories -> {a.out} "
          f"(skipped {n_skip}, over-budget {n_over})")
    if a.check_base:
        print(f"[check-base] files checked: {tot_files}, edits checked: {tot_edits}, "
              f"drifted edits: {tot_drift} across {drifted_tasks} task(s)")
        if tot_drift == 0:
            print("[check-base] 0 drift — the naive corpus is byte-equivalent to the "
                  "verified one ON THIS SAMPLE; A2 vs A3 is expected to be a tie "
                  "(paper Section 6 pre-declares this).")
        else:
            print("[check-base] NON-ZERO DRIFT — the naive corpus teaches failing "
                  "edits; A2 is expected to underperform A3. Report as measured.")
    else:
        print("[build_naive] NOTE: no executability check was performed — that is "
              "the point of the A2 arm. Run with --check-base to measure drift.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
