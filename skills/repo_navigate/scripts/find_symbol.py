#!/usr/bin/env python3
"""
find_symbol.py — AST-based symbol locator.

Custom Python tooling CANNOT be registered as a host tool (the harness uses a closed
ToolRegistry and disallows importlib). The sanctioned pattern is: ship logic as a SKILL
SCRIPT and invoke it from the sandbox via run_command, e.g.

    run_command("python3 skills/repo_navigate/scripts/find_symbol.py <symbol>")

Prints file:line for every definition and every reference of <symbol> under /workspace.
Stdlib only — the sandbox is air-gapped, so no third-party imports are permitted.
"""
from __future__ import annotations
import ast, os, sys

ROOT = "/workspace"
SKIP = {".git", "__pycache__", ".venv", "node_modules", "site-packages"}


def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        for fn in fns:
            if fn.endswith(".py"):
                yield os.path.join(dp, fn)


def main():
    if len(sys.argv) < 2:
        print("usage: find_symbol.py <symbol>")
        return 2
    target = sys.argv[1]
    hits = []
    for path in walk(ROOT):
        try:
            src = open(path, "r", encoding="utf-8").read()
            tree = ast.parse(src)
        except Exception:
            continue
        rel = os.path.relpath(path, ROOT)
        for node in ast.walk(tree):
            # definitions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.name == target:
                hits.append((rel, node.lineno, "def " + target))
            # attribute / name references
            elif isinstance(node, ast.Name) and node.id == target:
                hits.append((rel, node.lineno, "ref " + target))
            elif isinstance(node, ast.Attribute) and node.attr == target:
                hits.append((rel, node.lineno, "attr ." + target))
    if not hits:
        print(f"no matches for '{target}'")
        return 1
    seen = set()
    for rel, line, kind in sorted(hits):
        key = (rel, line, kind)
        if key in seen:
            continue
        seen.add(key)
        print(f"{rel}:{line}: {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
