name: repo_navigate
description: >
  Localize the root cause of a bug using the codebase graph tools. Use BEFORE
  any edit. Invoke from the root agent when you need to map call/dependency
  structure around a failing symbol.
steps:
  - call: get_code_neighbors
    args: { node: "<failing_symbol>", edge_type: null, max_neighbors: 50 }
    note: Walk inbound/outbound edges to see who calls the symbol and what it calls.
  - call: search_similar_code
    args: { query: "<bug_keyword_or_snippet>", k: 10 }
    note: Find analogous implementations that may reveal the intended pattern.
  - call: get_code_subgraph
    args: { nodes: ["<symbol_a>", "<symbol_b>"] }
    note: Pull the induced subgraph to reason about data flow between candidates.
  - call: read_file
    args: { filepath: "<candidate_file>", start_line: null, end_line: null }
    note: Confirm the offending lines by reading actual source.
output: A ranked list of (file, symbol, reason) root-cause candidates.
budget: Use at most 6 graph/tool calls before forming a hypothesis.
