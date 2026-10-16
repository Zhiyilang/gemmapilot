# -*- coding: utf-8 -*-
"""Paper submission gate: refuses to let a placeholder-laden draft be submitted.

Run: python paper/check_paper.py [paper.md] [--allow-placeholders]

Checks (offline, stdlib only):
  1. no ``{{...}}`` placeholders remain (results must be filled in) —
     skipped with ``--allow-placeholders`` (used by CI, where the draft is
     expected to carry placeholders until the training run lands),
  2. all required sections are present,
  3. every in-text citation ``[n]`` resolves to a reference entry, and no
     reference is orphaned,
  4. the draft is substantial enough to be a paper (word-count floor).

Exit code 1 on any failure -- run WITHOUT --allow-placeholders before
converting to PDF for the paper track; wire the flagged form into CI so the
structure cannot rot while results are pending.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PAPER = os.path.join(HERE, "paper.md")

REQUIRED_SECTIONS = [
    "Abstract", "Introduction", "Related Work", "Method",
    "Experimental Setup", "Results", "Discussion", "Reproducibility",
    "References",
]

MIN_WORDS = 1000


def check_paper(path=DEFAULT_PAPER, allow_placeholders=False):
    problems = []
    if not os.path.exists(path):
        return ["paper file missing: %s" % path]

    text = open(path, encoding="utf-8").read()

    # 1. placeholders -------------------------------------------------------
    # "{{...}}" inside the reproducibility checklist is meta-text (it names the
    # pattern to replace), not an unfilled value.
    placeholders = [p for p in re.findall(r"\{\{[^}]*\}\}", text) if p != "{{...}}"]
    if placeholders and not allow_placeholders:
        problems.append("%d unfilled placeholder(s): %s"
                        % (len(placeholders), ", ".join(sorted(set(placeholders))[:8])))

    # 2. sections -----------------------------------------------------------
    def _bare(h):
        return re.sub(r"^\d+(\.\d+)*\.?\s*", "", h).strip().lower()

    headings = [_bare(h) for h in re.findall(r"^##+\s+(.+?)\s*$", text, re.MULTILINE)]
    for sec in REQUIRED_SECTIONS:
        if not any(h.startswith(sec.lower()) for h in headings):
            problems.append("missing section: %s" % sec)

    # 3. citations ----------------------------------------------------------
    body, _, refs = text.partition("## References")
    cited = set()
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", body):
        for n in m.group(1).split(","):
            cited.add(int(n.strip()))
    listed = set(int(m.group(1)) for m in
                 re.finditer(r"^\[(\d+)\]", refs, re.MULTILINE))
    for n in sorted(cited - listed):
        problems.append("citation [%d] has no reference entry" % n)
    for n in sorted(listed - cited):
        problems.append("reference [%d] is never cited in the text" % n)

    # 4. substance ----------------------------------------------------------
    words = len(re.findall(r"\b[\w'-]+\b", re.sub(r"\{\{[^}]*\}\}", "", text)))
    if words < MIN_WORDS:
        problems.append("only %d words (floor %d)" % (words, MIN_WORDS))

    return problems


def main(argv=None):
    argv = list(argv or [])
    allow = "--allow-placeholders" in argv
    rest = [a for a in argv if not a.startswith("--")]
    path = rest[0] if rest else DEFAULT_PAPER
    problems = check_paper(path, allow_placeholders=allow)
    for p in problems:
        print("PROBLEM  " + p)
    if problems:
        print("RESULT: FAILED (%d problem(s))" % len(problems))
        return 1
    print("RESULT: OK%s" % (" (placeholders allowed)" if allow else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
