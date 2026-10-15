name: verify
description: >
  Run the target test suite and enforce budget discipline. The closing phase of
  every loop. Loop back to repo_navigate if RED.
steps:
  - call: run_command
    args: { command: "cd /workspace && python -m pytest <target_test> -q" }
    note: GREEN here is the ONLY success criterion before submit_patch.
  - call: get_status
    args: {}
    note: Read budget consumption. If < 15% remaining, stop exploring and submit best diff.
decision:
  - if GREEN and target test passes: call submit_patch.
  - if RED: return to repo_navigate with the new error message as context.
  - if budget low: submit current best diff even if uncertain.
