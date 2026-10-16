# Navigation playbook — domain knowledge for the repo_navigate skill

## Known evaluation repositories (public dev set, 129 tasks)
FastAPI, Rich, Requests, HTTPX (hidden set adds ~120 private-repo tasks).
These are mature, well-tested Python libraries. Practical implications:

- **Tests are the spec.** Before theorizing, find and run the failing test:
  `run_command("python -m pytest <path> -x -q")`. The traceback usually names the file.
- **Bugs are usually local.** A single function/class is wrong, not an architecture
  problem. Resist large refactors; the scorer only checks the validation tests.
- **Public API stability matters.** FastAPI/Requests/HTTPX have broad public surfaces;
  prefer fixing internals without changing exported signatures.

## Localization order (cheapest -> most expensive)
1. `search_similar_code("<error text or symbol>")` — fastest way to find the right area.
2. `get_code_neighbors("<symbol>")` — who calls it, what it calls.
3. `read_file(<file>, start, end)` — confirm the actual lines.
4. `get_code_subgraph([...])` — only when data flow across modules is unclear.
5. `run_command("python3 skills/repo_navigate/scripts/find_symbol.py <symbol>")`
   — AST sweep when the graph tools miss dynamically-referenced symbols.

## Failure signatures worth recognizing
- `TypeError: ... got an unexpected keyword` -> a call site drifted from the signature.
- `AttributeError` on a common object -> a dataclass/model field was renamed or dropped.
- Assertion on repr/formatting (Rich) -> output formatting changed, not logic.
- Status-code / header assertions (FastAPI/HTTPX/Requests) -> routing or serialization.
