#!/usr/bin/env python3
"""
build_trajectories.py — turn (issue, gold patch) pairs into LoRA training data.

WHY THIS EXISTS
The competition is "post-train Gemma 4 into a SWE agent". Prompts alone won't win;
the LoRA needs supervised trajectories that teach:
  - exact tool-call serialization for the 9 harness tools,
  - graph-first localization (search before edit),
  - minimal-diff patching via edit_file(old_string, new_string),
  - test-then-submit discipline.

WHAT IT DOES
Parses a unified diff (gold patch) into `edit_file(old_string, new_string)` operations
and emits a multi-turn (system, user, assistant) trajectory in the messages format
expected by finetune/gemma4_qlora_recipe.py.

USAGE
  python finetune/build_trajectories.py --demo --verify
      Runs a built-in sample bug, writes demo_train.jsonl, and VERIFIES that the
      extracted edit_file operations actually transform the buggy file into the
      fixed file (this is the correctness check that matters).

  python finetune/build_trajectories.py --tasks tasks.jsonl --out train.jsonl
      tasks.jsonl: one JSON object per line with keys
        id, repo, issue (text), gold_patch (unified diff), [tests]

CUSTOMIZATION
  `fmt_call()` defines how an assistant action is serialized. The exact serialization
  the harness uses is NOT verifiable offline (see README "Known unknowns"); if the
  dataset's HARNESS_README shows a different one, change this single function.

Stdlib only — runs anywhere, no GPU, no network.
"""
from __future__ import annotations
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- unified diff
def parse_unified_diff(diff: str):
    """Parse a unified diff into [{file, hunks:[{old,new}]}]."""
    files, cur, lines, i = [], None, diff.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git"):
            cur = None
            i += 1
            continue
        if line.startswith("--- "):
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                newp = lines[i + 1][4:].strip()
                newp = newp[2:] if newp.startswith("b/") else newp
                cur = {"file": newp, "hunks": []}
                files.append(cur)
                i += 2
                continue
            i += 1
            continue
        if line.startswith("@@"):
            old, new = [], []
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@", "diff --git", "--- ")):
                b = lines[i]
                if b.startswith("-"):
                    old.append(b[1:])
                elif b.startswith("+"):
                    new.append(b[1:])
                else:
                    ctx = b[1:] if b.startswith(" ") else ""
                    old.append(ctx)
                    new.append(ctx)
                i += 1
            if cur is not None and (old or new):
                cur["hunks"].append({"old": "\n".join(old), "new": "\n".join(new)})
            continue
        i += 1
    return files


# ------------------------------------------------------------ action encoding
def fmt_call(name: str, args: dict) -> str:
    """Serialize one assistant action. Single point of customization."""
    if not args:
        return json.dumps({"tool": name}, ensure_ascii=False)
    return json.dumps({"tool": name, "args": args}, ensure_ascii=False)


# ------------------------------------------------------------ trajectory build
def _keywords(text: str, limit: int = 6) -> str:
    """Crude but effective query: identifiers that look like symbols."""
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text)
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= limit:
            break
    return " ".join(out) or "defect"


def synthesize(task: dict, system_prompt: str) -> dict:
    """Build one (system, user, assistant-multiturn) training example."""
    files = parse_unified_diff(task["gold_patch"])
    if not files:
        raise ValueError(f"no hunks parsed for task {task.get('id')}")

    first = files[0]
    sym = _keywords(first["hunks"][0]["old"]) if first["hunks"] else "defect"
    target_test = task.get("tests") or f"tests/test_{os.path.basename(first['file']).replace('.py','')}.py"

    user = (
        f"Repository: {task.get('repo','unknown')}\n"
        f"Issue:\n{task['issue'].strip()}\n\n"
        f"Fix the bug. Verify with: {target_test}\n"
        f"Tools: run_command, read_file, edit_file, write_file, submit_patch, "
        f"get_status, get_code_neighbors, search_similar_code, get_code_subgraph"
    )

    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},

        # PERCEIVE
        {"role": "assistant", "content": fmt_call("get_status", {})},
        # SEARCH — graph first, never patch blind
        {"role": "assistant", "content": fmt_call("search_similar_code",
                                                  {"query": sym, "k": 10})},
        {"role": "assistant", "content": fmt_call("get_code_neighbors",
                                                  {"node": sym, "max_neighbors": 20})},
        {"role": "assistant", "content": fmt_call("read_file",
                                                  {"filepath": first["file"]})},
        # SELECT + REASON + EXPLAIN (single short turn)
        {"role": "assistant", "content":
            f"HYPOTHESIS: {first['file']} — the defect is in '{sym}'. "
            f"I will apply the minimal fix that preserves existing behaviour."},
    ]

    # ACT — one edit_file per hunk (minimal, surgical)
    for f in files:
        for h in f["hunks"]:
            msgs.append({"role": "assistant", "content": fmt_call("edit_file", {
                "filepath": f["file"],
                "old_string": h["old"],
                "new_string": h["new"],
            })})

    # RECEIPT
    msgs.append({"role": "assistant", "content": fmt_call("run_command", {
        "command": f"python -m pytest {target_test} -q"})})
    msgs.append({"role": "assistant", "content": fmt_call("submit_patch", {})})
    return {"messages": msgs}


# ------------------------------------------------------------ built-in demo
DEMO_BUGGY = "def add(a, b):\n    return a - b\n"
DEMO_FIXED = "def add(a, b):\n    return a + b\n"
DEMO_GOLD = (
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
)


def demo_task():
    return {
        "id": "demo-001",
        "repo": "sample/calc",
        "issue": "add(2, 3) returns -1 but should return 5.",
        "gold_patch": DEMO_GOLD,
        "tests": "test_calc.py",
    }


def verify_edits(example) -> bool:
    """Apply the synthesized edit_file ops to DEMO_BUGGY; must yield DEMO_FIXED."""
    src = DEMO_BUGGY
    applied = 0
    for m in example["messages"]:
        if m["role"] != "assistant":
            continue
        try:
            obj = json.loads(m["content"])
        except Exception:
            continue
        if obj.get("tool") == "edit_file":
            old, new = obj["args"]["old_string"], obj["args"]["new_string"]
            if old not in src:
                return False
            src = src.replace(old, new, 1)
            applied += 1
    return applied >= 1 and src == DEMO_FIXED


def count_tool_calls(example: dict) -> int:
    """Number of tool calls a trajectory teaches the model to make.

    The global 12 h budget allows roughly 14 calls per task (see
    eval/budget_planner.py). A trajectory with 20 edit_file calls is a
    demonstration of how to blow that budget, so we drop it.
    """
    n = 0
    for m in example.get("messages", []):
        if m.get("role") != "assistant":
            continue
        try:
            d = json.loads(m["content"])
        except Exception:
            continue
        if isinstance(d, dict) and "tool" in d:
            n += 1
    return n


# Kept in sync with eval/budget_planner.py SKILL_CALL_BUDGET (13 declared calls)
# plus one call of headroom.
MAX_TOOL_CALLS = 14


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", help="tasks.jsonl with id/repo/issue/gold_patch")
    ap.add_argument("--out", default="train.jsonl")
    ap.add_argument("--system", default=os.path.join(HERE, "..", "prompts", "system.md"))
    ap.add_argument("--demo", action="store_true", help="use the built-in sample bug")
    ap.add_argument("--verify", action="store_true", help="verify edits actually fix the demo")
    ap.add_argument("--max-calls", type=int, default=MAX_TOOL_CALLS,
                    help=f"drop trajectories that teach more tool calls than the "
                         f"budget allows (default {MAX_TOOL_CALLS}; see "
                         f"eval/budget_planner.py). 0 disables the filter.")
    a = ap.parse_args()

    with open(a.system, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    if a.demo or not a.tasks:
        if not a.tasks:
            print("[build_trajectories] no --tasks given; running built-in demo")
        tasks = [demo_task()]
    else:
        tasks = [json.loads(l) for l in open(a.tasks, "r", encoding="utf-8") if l.strip()]

    n_ok = n_skip = n_over = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for t in tasks:
            try:
                ex = synthesize(t, system_prompt)
            except Exception as e:
                print(f"skip {t.get('id')}: {e}")
                n_skip += 1
                continue
            # Budget gate: a trajectory that spends more tool calls than the
            # global 12 h budget allows is teaching behaviour that loses points.
            # Fine-tuning on it would push the agent toward overspending.
            if a.max_calls and count_tool_calls(ex) > a.max_calls:
                print(f"over-budget {t.get('id')}: {count_tool_calls(ex)} "
                      f"tool calls > {a.max_calls} — dropped")
                n_over += 1
                continue
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            n_ok += 1
    print(f"wrote {n_ok} trajectories -> {a.out} "
          f"(skipped {n_skip}, over-budget {n_over})")

    if a.verify:
        ex = synthesize(demo_task(), system_prompt)
        ok = verify_edits(ex)
        print("verify: synthesized edits transform buggy -> fixed:", ok)
        if not ok:
            print("[build_trajectories] VERIFY FAILED")
            return 1
        print("[build_trajectories] VERIFY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
