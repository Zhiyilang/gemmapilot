#!/usr/bin/env python3
"""
validate_zip.py — offline structural validator for the Kaggle submission.

The harness compiles submissions with a closed ToolRegistry and a sandboxed YAML
compiler. A single wrong key or an undeclared tool name makes the whole submission
fail to compile. This script catches those mistakes LOCALLY, before spending a
Kaggle submission slot.

Checks
  1. agent.yaml exists at the archive root.
  2. Base model is one of the 4 allowed Gemma 4 variants.
  3. Root agent and every sub-agent use the SAME model.
  4. Only the 9 harness tools (or agent_tool) are declared.
     run_skill_script / load_skill_resource are FORBIDDEN as tools (compile failure).
  5. Every !include target resolves to a real file.
  6. Every listed skill dir contains SKILL.md with `name:` frontmatter.
  7. adapters/<name>/ has adapter_config.json + adapter_model.safetensors (if present).
  8. No path traversal (../) or symlinks in the archive.
  9. Packs the result to submission.zip.

Run:  python eval/validate_zip.py [--root <dir>] [--zip <out>]
"""
from __future__ import annotations
import os, re, sys, zipfile, argparse

ALLOWED_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}
HARNESS_TOOLS = {
    "run_command", "submit_patch", "get_status", "read_file", "edit_file",
    "write_file", "get_code_neighbors", "search_similar_code", "get_code_subgraph",
}
FORBIDDEN_TOOLS = {"run_skill_script", "load_skill_resource"}


class Report:
    def __init__(self):
        self.errors, self.warnings, self.ok = [], [], 0

    def err(self, m):
        self.errors.append(m)

    def warn(self, m):
        self.warnings.append(m)

    def good(self, m):
        self.ok += 1


def _strip_comment(val):
    """Drop an inline `# ...` comment from an unquoted scalar."""
    if val.startswith(("'", '"')):
        return val
    return re.split(r"\s+#", val, maxsplit=1)[0].strip()


def scalar_keys(text):
    """Minimal top-level `key: value` extraction (tolerant of inline !include)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m and not line.startswith((" ", "\t", "#", "-")):
            out[m.group(1)] = _strip_comment(m.group(2))
    return out


def list_items(text, key):
    """Collect `- item` entries under a top-level `key:` block."""
    items, active = [], False
    for line in text.splitlines():
        if re.match(rf"^{key}\s*:", line):
            active = True
            inline = re.match(rf"^{key}\s*:\s*\[(.*)\]", line)
            if inline:
                return [x.strip() for x in inline.group(1).split(",") if x.strip()]
            continue
        if active:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", line):
                break
            m = re.match(r"^\s*-\s+(.*)$", line)
            if m:
                items.append(m.group(1).strip())
    return items


def collect_tools(text):
    tools, active = [], False
    for line in text.splitlines():
        if re.match(r"^tools\s*:", line):
            active = True
            continue
        if active:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", line):
                break
            m = re.match(r"^\s*-\s+([A-Za-z_][A-Za-z0-9_]*)", line)
            if m:
                tools.append(m.group(1))
    return tools


def resolve_includes(text, base_dir, rep):
    for name, val in scalar_keys(text).items():
        if val.startswith("!include"):
            target = val.split("!include", 1)[1].strip()
            p = os.path.normpath(os.path.join(base_dir, target))
            if os.path.isfile(p):
                rep.good(f"include ok: {target}")
            else:
                rep.err(f"MISSING !include target: {target} (resolved {p})")
    # nested agent_tool config_path
    for m in re.finditer(r"config_path\s*:\s*(\S+)", text):
        p = os.path.normpath(os.path.join(base_dir, m.group(1)))
        if not os.path.isfile(p):
            rep.err(f"MISSING agent_tool config_path: {m.group(1)}")


def validate(root, out_zip):
    rep = Report()
    agent = os.path.join(root, "agent.yaml")
    if not os.path.isfile(agent):
        rep.err("agent.yaml missing at root")
        return rep
    rep.good("agent.yaml present at root")
    atext = open(agent, "r", encoding="utf-8").read()
    akeys = scalar_keys(atext)
    model = akeys.get("model", "").strip()

    if model not in ALLOWED_MODELS:
        rep.err(f"model '{model}' not in allowed set: {sorted(ALLOWED_MODELS)}")
    else:
        rep.good(f"base model ok: {model}")

    # sub-agents must match the base model
    subdir = os.path.join(root, "sub_agents")
    if os.path.isdir(subdir):
        for fn in sorted(os.listdir(subdir)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            stext = open(os.path.join(subdir, fn), "r", encoding="utf-8").read()
            smodel = scalar_keys(stext).get("model", "").strip()
            if smodel != model:
                rep.err(f"sub_agent {fn} model '{smodel}' != root '{model}'")
            else:
                rep.good(f"sub_agent {fn} model matches")
            for t in collect_tools(stext):
                if t in FORBIDDEN_TOOLS:
                    rep.err(f"sub_agent {fn} declares forbidden tool '{t}'")
                elif t not in HARNESS_TOOLS and t != "agent_tool":
                    rep.err(f"sub_agent {fn} declares unknown tool '{t}'")
            resolve_includes(stext, root, rep)

    # tools on root
    for t in collect_tools(atext):
        if t in FORBIDDEN_TOOLS:
            rep.err(f"agent.yaml declares forbidden tool '{t}' (not in closed ToolRegistry)")
        elif t not in HARNESS_TOOLS and t != "agent_tool":
            rep.err(f"agent.yaml declares unknown tool '{t}'")
    if not collect_tools(atext):
        rep.warn("agent.yaml declares no tools")

    resolve_includes(atext, root, rep)

    # skills
    for s in list_items(atext, "skills"):
        sdir = os.path.normpath(os.path.join(root, s))
        sk = os.path.join(sdir, "SKILL.md")
        if not os.path.isfile(sk):
            rep.err(f"skill '{s}' missing SKILL.md")
            continue
        head = open(sk, "r", encoding="utf-8").read()[:400]
        if not re.search(r"^name\s*:", head, re.M):
            rep.err(f"skill '{s}' SKILL.md lacks 'name:' frontmatter")
        else:
            rep.good(f"skill ok: {s}")

    # adapters (optional)
    adir = os.path.join(root, "adapters")
    if os.path.isdir(adir):
        for name in sorted(os.listdir(adir)):
            d = os.path.join(adir, name)
            if not os.path.isdir(d):
                continue
            missing = [n for n in ("adapter_config.json", "adapter_model.safetensors")
                       if not os.path.isfile(os.path.join(d, n))]
            if missing:
                rep.err(f"adapter '{name}' missing {', '.join(missing)}")
            else:
                rep.good(f"adapter dir ok: {name}")
    else:
        rep.warn("adapters/ absent (optional — base model only)")

    # pack + traversal check
    if out_zip:
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, dns, fns in os.walk(root):
                dns[:] = [d for d in dns if d not in {".git", "__pycache__"}]
                for fn in fns:
                    full = os.path.join(dp, fn)
                    rel = os.path.relpath(full, root).replace("\\", "/")
                    if rel.startswith("..") or os.path.islink(full):
                        rep.err(f"illegal entry: {rel}")
                        continue
                    z.write(full, rel)
        rep.good(f"packed -> {out_zip}")
        with zipfile.ZipFile(out_zip) as z:
            names = z.namelist()
            if "agent.yaml" not in names:
                rep.err("packed zip lacks agent.yaml at root")
            else:
                rep.good("zip contains agent.yaml at root")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--zip", default=None)
    a = ap.parse_args()
    rep = validate(a.root, a.zip)
    print(f"checks passed : {rep.ok}")
    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"ERROR {e}")
    if rep.errors:
        print("\n[GemmaPilot] validate_zip FAILED")
        return 1
    print("\n[GemmaPilot] validate_zip OK — submission structure compliant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
