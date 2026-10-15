name: patch
description: >
  Apply the minimal correct edit and stage it. Use after REASON. Prefer surgical
  edit_file; use write_file only for genuinely new modules.
steps:
  - call: edit_file
    args:
      filepath: "<target_file>"
      old_string: "<exact existing lines>"
      new_string: "<corrected lines>"
      allow_multiple: false
    note: old_string must match exactly (whitespace + indentation). One hunkset per call.
  - call: write_file
    args:
      filepath: "<new_module>.py"
      content: "<new helper code>"
    note: Only for new files; never traverse outside /workspace.
  - call: submit_patch
    args: {}
    note: Captures `git diff HEAD` of currently staged/untracked intents. Call ONLY when target test is GREEN.
forbidden: "../", symlinks, editing unrelated files, multiple unrelated changes in one diff.
