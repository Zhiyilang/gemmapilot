name: reproduce
description: >
  Write a minimal reproduction that triggers the reported failure, so you can
  prove a fix actually addresses the bug. Run AFTER forming a hypothesis, BEFORE
  editing, when feasible; at minimum run it right after the first edit.
steps:
  - call: write_file
    args:
      filepath: "/workspace/repro_test.py"
      content: |
        # Minimal repro for <issue_id>
        import pytest
        from <module> import <symbol>

        def test_repro():
            with pytest.raises(<ExpectedError>):
                <symbol>(<failing_inputs>)
    note: Keep it tiny and deterministic. Target the exact failing behaviour.
  - call: run_command
    args: { command: "cd /workspace && python -m pytest repro_test.py -q" }
    note: Confirm RED (failure present) before patching.
success: Test FAILS (proves the bug exists). After the fix it must PASS.
budget: 1 write_file + 1 run_command. Delete repro_test.py before submit_patch if it is not part of the fix.
