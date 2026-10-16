#!/usr/bin/env python3
"""Budget planner for the Gemma 4 Developer Agent Competition.

WHY THIS EXISTS
---------------
The competition gives ONE global budget (12 h) for ALL tasks including sandbox
setup.  `eval_config.yaml` additionally allows a *per-task* timeout.  Those two
numbers are independent knobs, and it is easy to set them inconsistently:

    N tasks x per-task timeout  >>  global budget

If that happens the agent burns the global budget on the first slice of tasks
and the rest are never attempted (score 0).  A per-task timeout is only a
runaway GUARD -- it does not protect the global budget.  This script makes the
arithmetic explicit and prints a VERDICT for the values currently committed in
`eval_config.yaml`.

Every number below is an ASSUMPTION with a named flag.  None of them are known
from official documentation; change them when real numbers are measured inside
the Kaggle container.

Usage
-----
    python eval/budget_planner.py
    python eval/budget_planner.py --tasks 129 --reserve 0.20 --call 12 --test 45
    python eval/budget_planner.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

GLOBAL_BUDGET_S = 12 * 3600          # official: 12 hours for ALL tasks

# Defaults are estimates, NOT measurements. Documented so they can be replaced.
DEF_TASKS = 129          # size of the public dev set (FastAPI/Rich/Requests/HTTPX)
DEF_RESERVE = 0.20       # fraction of the global budget eaten by sandbox setup
DEF_CALL_S = 12.0        # wall seconds per LLM tool call (31B Q4 on one L4)
DEF_TEST_S = 45.0        # wall seconds per targeted pytest run
DEF_TEST_RUNS = 2        # 1x reproduce (RED) + 1x verify (GREEN)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "eval_config.yaml")

# Tool calls each skill declares it is allowed to spend (kept in sync with the
# `budget:` line of every SKILL.md). If the sum does not fit inside one task's
# allowance, the 8-phase loop CANNOT complete and every skill is lying.
SKILL_CALL_BUDGET = {
    "repo_navigate": 4,     # graph calls before a hypothesis (was 6: did not fit)
    "reproduce": 2,         # 1 run_command (+1 optional verify)
    "patch": 2,             # edit_file + submit_patch
    "verify": 2,            # run_command pytest + get_status
    "get_status_baseline": 1,
    "read_file": 2,         # read the target file / the test file
}


def read_eval_config(path: str) -> dict:
    """Read the committed eval_config.yaml without a YAML dependency.

    Only the flat `key: value` pairs under `evaluation:` are needed; inline
    comments are stripped (a real bug caught earlier: comments leaked into
    values).
    """
    out: dict = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
            if not m:
                continue
            val = re.split(r"\s+#", m.group(2), maxsplit=1)[0].strip()
            try:
                out[m.group(1)] = int(val)
            except ValueError:
                out[m.group(1)] = val
    return out


def plan(tasks: int, reserve: float, call_s: float, test_s: float,
         test_runs: int, per_task_cap: int) -> dict:
    usable = GLOBAL_BUDGET_S * (1.0 - reserve)
    per_task = usable / tasks if tasks else 0.0

    fixed = test_runs * test_s
    calls_that_fit = max(0.0, (per_task - fixed) / call_s) if call_s else 0.0

    # How many tasks may hit the per-task CAP before the global budget is gone?
    # (conservative: those tasks consume the full cap, everything else consumes
    #  the nominal per-task allowance)
    nominal = fixed + 12 * call_s          # a "well behaved" task: <=12 calls
    if per_task_cap > nominal and tasks:
        slack = usable - tasks * nominal
        tasks_at_cap = int(slack / (per_task_cap - nominal)) if slack > 0 else 0
    else:
        tasks_at_cap = tasks              # cap is not the binding risk

    declared_calls = sum(SKILL_CALL_BUDGET.values())
    return {
        "declared_skill_calls": declared_calls,
        "skill_budget_fits": declared_calls <= calls_that_fit,
        "global_budget_s": GLOBAL_BUDGET_S,
        "reserve_frac": reserve,
        "usable_s": round(usable, 1),
        "tasks": tasks,
        "per_task_allowance_s": round(per_task, 1),
        "per_task_cap_s": per_task_cap,
        "cap_sum_s": per_task_cap * tasks,
        "cap_sum_exceeds_budget": per_task_cap * tasks > usable,
        "fixed_test_cost_s": round(fixed, 1),
        "llm_calls_that_fit": round(calls_that_fit, 1),
        "tasks_allowed_to_hit_cap": max(0, tasks_at_cap),
    }


def verdict(p: dict) -> tuple[bool, list[str]]:
    ok = True
    msgs: list[str] = []

    if p["cap_sum_exceeds_budget"]:
        msgs.append(
            f"WARN  N x per-task cap = {p['cap_sum_s']/3600:.1f} h exceeds the "
            f"usable {p['usable_s']/3600:.1f} h. The per-task cap is only a "
            f"runaway guard; it does NOT protect the global budget.")

    if p["llm_calls_that_fit"] < 8:
        ok = False
        msgs.append(
            f"FAIL  only {p['llm_calls_that_fit']:.1f} LLM calls fit per task "
            f"({p['fixed_test_cost_s']:.0f}s of that is test runs). That is too "
            f"few to run the 8-phase loop -- raise --reserve realism, cut test "
            f"time (targeted -k, not whole suite), or accept fewer tasks attempted.")

    if not p["skill_budget_fits"]:
        ok = False
        msgs.append(
            f"FAIL  the skills together declare {p['declared_skill_calls']} tool "
            f"calls per task but only {p['llm_calls_that_fit']:.1f} fit. The "
            f"8-phase loop cannot complete: cut skill budgets, cut test runs, "
            f"or make each call cheaper (smaller context).")

    if p["tasks_allowed_to_hit_cap"] < p["tasks"] * 0.10:
        msgs.append(
            f"WARN  only {p['tasks_allowed_to_hit_cap']} of {p['tasks']} tasks "
            f"may hit the per-task cap before the global budget dies. Stalling "
            f"is expensive: submit the best diff early rather than iterate to "
            f"perfection.")

    if not msgs:
        msgs.append("OK    budget arithmetic is consistent.")
    return ok, msgs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", type=int, default=DEF_TASKS,
                    help=f"number of evaluation tasks (default {DEF_TASKS})")
    ap.add_argument("--reserve", type=float, default=DEF_RESERVE,
                    help=f"fraction of budget lost to sandbox setup (default {DEF_RESERVE})")
    ap.add_argument("--call", type=float, default=DEF_CALL_S,
                    help=f"seconds per LLM tool call (default {DEF_CALL_S})")
    ap.add_argument("--test", type=float, default=DEF_TEST_S,
                    help=f"seconds per targeted pytest run (default {DEF_TEST_S})")
    ap.add_argument("--test-runs", type=int, default=DEF_TEST_RUNS,
                    help=f"pytest runs per task (default {DEF_TEST_RUNS})")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    cfg = read_eval_config(CONFIG)
    cap = int(cfg.get("timeout_seconds", 0) or 0)
    p = plan(args.tasks, args.reserve, args.call, args.test,
             args.test_runs, cap)
    ok, msgs = verdict(p)
    p["eval_config"] = cfg
    p["verdict_ok"] = ok
    p["messages"] = msgs

    if args.json:
        print(json.dumps(p, indent=2))
        return 0 if ok else 1

    print("=" * 68)
    print("GemmaPilot budget plan  (all inputs are ASSUMPTIONS, see --help)")
    print("=" * 68)
    print(f"  global budget           {p['global_budget_s']/3600:6.1f} h")
    print(f"  sandbox reserve         {p['reserve_frac']*100:5.0f} %")
    print(f"  usable for solving      {p['usable_s']/3600:6.1f} h")
    print(f"  tasks                   {p['tasks']:6d}")
    print("-" * 68)
    print(f"  per-task allowance      {p['per_task_allowance_s']:6.0f} s "
          f"({p['per_task_allowance_s']/60:.1f} min)   <-- the real ceiling")
    print(f"  per-task cap in config  {p['per_task_cap_s']:6d} s "
          f"({p['per_task_cap_s']/60:.1f} min)   <-- runaway guard only")
    print(f"  N x cap                 {p['cap_sum_s']/3600:6.1f} h")
    print("-" * 68)
    print(f"  test runs               {args.test_runs} x {args.test:.0f}s = "
          f"{p['fixed_test_cost_s']:.0f} s fixed per task")
    print(f"  LLM calls that fit      {p['llm_calls_that_fit']:6.1f} calls/task")
    print(f"  calls declared by skills{p['declared_skill_calls']:6d} "
          f"({'fits' if p['skill_budget_fits'] else 'DOES NOT FIT'})")
    print(f"  tasks allowed to hit cap{p['tasks_allowed_to_hit_cap']:6d} of {p['tasks']}")
    print("=" * 68)
    for m in msgs:
        print(" ", m)
    print("=" * 68)
    print("  Design consequence: the loop must stay economical -- roughly <=12 tool")
    print("  calls and <=2 targeted pytest runs per task. Whole-suite runs and")
    print("  open-ended exploration do not fit; aim the skill budgets at this number.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
