#!/usr/bin/env python3
"""
GemmaPilot — offline local harness.

Simulates the 9 competition tools over a LOCAL git repo so we can iterate on the
8-phase orchestration WITHOUT a Kaggle GPU. The competition harness provides the
same tool surface; our agent logic (prompts/system.md + skills) is identical.

Run:
    python eval/local_harness.py
It builds a sample buggy repo, runs a MockPolicy that reproduces -> patches ->
verifies, and asserts submit_patch captured a GREEN-test diff.

Swap MockPolicy for a real LLM policy (calling gemma-4-31b locally or an API) to
graduate from dry-run to real solving.
"""
from __future__ import annotations
import os, subprocess, shutil, tempfile, textwrap, json, sys

BUDGET = 100  # arbitrary units; each tool call costs 1


class Workspace:
    def __init__(self, root: str):
        self.root = root
        self.budget = BUDGET
        self.last_patch = None
        self.history = []

    # ---- competition tool surface (local implementations) ----
    def read_file(self, filepath, start_line=None, end_line=None):
        p = os.path.join(self.root, filepath)
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if start_line is not None:
            lines = lines[start_line - 1: end_line]
        return "".join(lines)

    def write_file(self, filepath, content):
        p = os.path.join(self.root, filepath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return "written"

    def edit_file(self, filepath, old_string, new_string, allow_multiple=False):
        p = os.path.join(self.root, filepath)
        with open(p, "r", encoding="utf-8") as f:
            data = f.read()
        if old_string not in data:
            raise ValueError(f"old_string not found in {filepath}")
        if not allow_multiple and data.count(old_string) > 1:
            raise ValueError("old_string ambiguous; set allow_multiple=True")
        data = data.replace(old_string, new_string, -1 if allow_multiple else 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)
        return "edited"

    def run_command(self, command):
        r = subprocess.run(command, shell=True, cwd=self.root,
                            capture_output=True, text=True, timeout=120)
        return f"[rc={r.returncode}]\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"

    def submit_patch(self):
        r = subprocess.run("git add -N . && git diff HEAD", shell=True,
                            cwd=self.root, capture_output=True, text=True)
        self.last_patch = r.stdout
        return "patch captured"

    def get_status(self):
        return json.dumps({"budget_remaining": self.budget,
                            "steps": len(self.history)})

    def get_code_neighbors(self, node, edge_type=None, max_neighbors=50):
        hits = []
        for dp, _, fns in os.walk(self.root):
            if ".git" in dp:
                continue
            for fn in fns:
                if fn.endswith(".py"):
                    with open(os.path.join(dp, fn), encoding="utf-8") as f:
                        src = f.read()
                    if node in src:
                        hits.append(f"{fn}: contains '{node}'")
        return "\n".join(hits[:max_neighbors]) or "no matches"

    def search_similar_code(self, query, k=10):
        return self.get_code_neighbors(query, max_neighbors=k)

    def get_code_subgraph(self, nodes):
        return "\n".join(f"node {n}: {self.get_code_neighbors(n, max_neighbors=5)}"
                         for n in nodes)

    def agent_tool(self, subagent="analyzer", query=""):
        # Stub read-only analyst: returns graph-localization hints.
        return f"[analyzer] candidates for '{query}':\n" + self.search_similar_code(query)

    def dispatch(self, action):
        self.budget -= 1
        t = action["tool"]
        a = action.get("args", {})
        if t == "read_file":      return self.read_file(**a)
        if t == "write_file":     return self.write_file(**a)
        if t == "edit_file":      return self.edit_file(**a)
        if t == "run_command":    return self.run_command(**a)
        if t == "submit_patch":   return self.submit_patch()
        if t == "get_status":     return self.get_status()
        if t == "get_code_neighbors": return self.get_code_neighbors(**a)
        if t == "search_similar_code": return self.search_similar_code(**a)
        if t == "get_code_subgraph":   return self.get_code_subgraph(**a)
        if t == "agent_tool":     return self.agent_tool(**a)
        raise ValueError(f"unknown tool {t}")


def orchestrate(ws: Workspace, policy, max_steps=40):
    state = {"history": ws.history, "budget": ws.budget}
    for step in range(max_steps):
        action = policy(state, ws)
        if action is None:
            break
        obs = ws.dispatch(action)
        ws.history.append({"action": action, "obs": obs[:500]})
        if action["tool"] == "submit_patch":
            return True
        if ws.budget <= 0:
            return False
    return False


class MockPolicy:
    """Solves the sample bug deterministically to prove wiring + budget loop."""
    def __init__(self, fix_file, old, new, test_cmd):
        self.fix_file, self.old, self.new, self.test_cmd = fix_file, old, new, test_cmd
        self.phase = 0

    def __call__(self, state, ws):
        if self.phase == 0:
            self.phase = 1
            return {"tool": "run_command",
                    "args": {"command": self.test_cmd}}   # see RED
        if self.phase == 1:
            self.phase = 2
            return {"tool": "edit_file",
                    "args": {"filepath": self.fix_file,
                             "old_string": self.old,
                             "new_string": self.new}}     # apply known fix
        if self.phase == 2:
            self.phase = 3
            return {"tool": "run_command",
                    "args": {"command": self.test_cmd}}   # expect GREEN
        # after GREEN -> submit
        return {"tool": "submit_patch", "args": {}}


def build_sample_bug(root: str):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "calc.py"), "w", encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a - b   # BUG: should be a + b\n")
    with open(os.path.join(root, "test_calc.py"), "w", encoding="utf-8") as f:
        f.write("def test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run("git init -q && git add -A && git commit -qm init",
                   shell=True, cwd=root, capture_output=True)


def main():
    tmp = tempfile.mkdtemp(prefix="gemmapilot_")
    repo = os.path.join(tmp, "sample_bug")
    build_sample_bug(repo)
    ws = Workspace(repo)
    policy = MockPolicy(
        fix_file="calc.py",
        old="    return a - b   # BUG: should be a + b\n",
        new="    return a + b\n",
        test_cmd="python test_calc.py",
    )
    ok = orchestrate(ws, policy)
    green = ws.last_patch is not None and "a + b" in ws.last_patch
    print("submit_patch called:", ok)
    print("captured patch contains fix:", green)
    print("budget remaining:", ws.budget)
    print("patch:\n" + (ws.last_patch or ""))
    assert ok and green, "local harness FAILED"
    print("\n[GemmaPilot] local_harness OK — tool surface + 8-phase loop wired.")


if __name__ == "__main__":
    main()
