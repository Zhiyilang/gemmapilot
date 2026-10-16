name: verify
description: >
  Run the target test suite and enforce budget discipline. The closing phase of
  every loop. Loop back to repo_navigate if RED.
steps:
  - call: run_command
    args:
      command: "cd /workspace && python skills/verify/scripts/summarize_pytest.py --target <target_test> --timeout 600"
    note: >
      Prefer this script over a raw pytest call. Raw output on a real repo runs to
      hundreds of lines and eats context twice (read + reason). The script returns
      RESULT (PASSED / FAILED / NO_TESTS_COLLECTED), the counts, one line per
      failing test with its reason, and a short error excerpt — capped at ~25 lines.
  - call: get_status
    args: {}
    note: Read budget consumption. If < 15% remaining, stop exploring and submit best diff.
decision:
  - if RESULT: PASSED: call submit_patch.
  - if RESULT: FAILED: return to repo_navigate with the failing test name and reason as context.
  - if RESULT: NO_TESTS_COLLECTED: the path or -k expression is wrong, NOT necessarily the fix.
    Re-scope the test target first (check collected item names) before editing source again.
  - if budget low: submit current best diff even if uncertain.
