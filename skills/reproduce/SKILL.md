name: reproduce
description: >
  Write a minimal reproduction that triggers the reported failure, so you can
  prove a fix actually addresses the bug. Run AFTER forming a hypothesis, BEFORE
  editing, when feasible; at minimum run it right after the first edit.
steps:
  - call: run_command
    args:
      command: "cd /workspace && python skills/reproduce/scripts/make_repro.py --out repro_test.py --module <module> --expr '<failing_expression>' --expect '<correct_value>' --run"
    note: >
      Generates a minimal repro and immediately reports RED / GREEN / ERROR.
      Prefer it over hand-writing a test: it refuses syntactically invalid
      expressions (exit 1) and can execute without pytest installed.
      For exceptions instead of wrong values, hand-write the test and use
      pytest.raises — this script only asserts equality.
  - call: run_command
    args:
      command: "cd /workspace && python skills/verify/scripts/summarize_pytest.py --target repro_test.py"
    note: Confirm RED (failure present) BEFORE patching.
success: >
  RED before patching proves the bug exists; GREEN after patching proves the fix
  works. GREEN *before* patching means your expression is wrong or the issue is
  misread — do NOT patch. ERROR means the repro could not run (path/import), which
  is NOT evidence about the bug.
budget: 1 run_command (+1 optional verify). Delete repro_test.py before submit_patch if it is not part of the fix.
