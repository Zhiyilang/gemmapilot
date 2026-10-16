#!/usr/bin/env python3
"""
fetch_real_tasks.py — mine REAL bug-fix PRs from the competition dev-set repos
and emit tasks.jsonl for finetune/build_trajectories.py.

WHY THIS EXISTS
LoRA quality is the core scoring axis of this competition, and LoRA quality is
bounded by trajectory quality. Synthetic toy bugs (the `calc.py` demo) teach the
model nothing about real defect shapes. The public development set has been
confirmed to be built from FastAPI / Rich / Requests / HTTPX, so the highest-value
offline work is to harvest genuine merged bug-fix PRs from exactly those repos.

WHAT IT DOES
  1. lists recently merged PRs (GitHub REST v3)
  2. keeps PRs whose title looks like a bug fix
  3. splits the changed files into  gold_patch (non-test .py)  and  tests
  4. rebuilds a proper unified diff (GitHub's per-file `patch` omits the
     `--- a/x` / `+++ b/x` headers, which our parser requires)
  5. writes one JSON object per line: {id, repo, issue, gold_patch, tests, ...}

AUTH
  Unauthenticated GitHub API is 60 req/hour — useless. Pass a token:
      $env:GH_TOKEN = "ghp_..."
      python finetune/fetch_real_tasks.py --limit 40
  The token is NEVER written into any output file and is never hardcoded here
  (this repository is public).

USAGE
  python finetune/fetch_real_tasks.py --limit 40 --out tasks.jsonl
  python finetune/fetch_real_tasks.py --repos encode/httpx --limit 10 --dry-run

Stdlib only.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.error, urllib.request

API = "https://api.github.com"
DEFAULT_REPOS = [
    "fastapi/fastapi",
    "Textualize/rich",
    "psf/requests",
    "encode/httpx",
]

# A PR title that looks like a real defect fix (not docs / chore / feature).
FIX_RE = re.compile(
    r"(?i)\b(fix|fixes|fixed|bug|bugfix|regression|patch|correct|repair|hotfix)\b"
)
# Noise we never want in a bug-fix training set.
NOISE_RE = re.compile(
    r"(?i)\b(docs?|docstring|typo|chore|bump|release|ci|lint|format|refactor|"
    r"deprecat|rename|upgrade|dependenc|readme|translations?|sponsor)\b"
)

TEST_PATH_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
MAX_ISSUE_CHARS = 3500
MAX_GOLD_LINES = 220          # skip sprawling PRs: they teach noise, not repair
MAX_FILES = 6


def gh(path: str, token: str | None):
    """GET an API path, return parsed JSON. Raises on non-200."""
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "gemmapilot-task-miner/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def is_test(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path))


def merge_file_patches(files: list[dict]) -> str:
    """Rebuild a unified diff WITH the ---/+++ headers our parser needs."""
    out = []
    for f in files:
        p = f.get("filename", "")
        patch = f.get("patch")
        if not patch:
            continue
        header = f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n"
        out.append(header + patch.rstrip("\n") + "\n")
    return "".join(out)


# PR-template sections that carry zero defect signal but would otherwise be
# memorised by the LoRA as "what an issue looks like".
JUNK_HEADINGS = re.compile(
    r"(?im)^#{1,4}\s*(ai\s+disclaimer|disclaimer|checklist|pull\s+request\s+"
    r"checklist|contributing|how\s+to\s+review|reviewers?|notes?\s+for\s+"
    r"reviewers?)\s*$")


def clean_body(body: str | None, title: str = "") -> str:
    """Strip HTML comments, image noise, template boilerplate and title echo."""
    if not body:
        return ""
    t = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\r\n", "\n", t)

    # drop a junk section: its heading through the next heading of same-or-higher level
    lines, out, skipping = t.split("\n"), [], False
    for ln in lines:
        h = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if h:
            skipping = bool(JUNK_HEADINGS.match(ln))
            if skipping:
                continue
        if not skipping:
            out.append(ln)
    t = "\n".join(out)

    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    # many PRs repeat the title as the first body line
    if title and t.lower().startswith(title.strip().lower()):
        t = t[len(title.strip()):].lstrip(" \n:-")
    return t.strip()[:MAX_ISSUE_CHARS]


def looks_like_fix(title: str) -> bool:
    return bool(FIX_RE.search(title)) and not NOISE_RE.search(title)


def mine_repo(slug: str, token: str | None, limit: int, pages: int,
              dry: bool, seen: set) -> tuple[list[dict], int, int]:
    owner, repo = slug.split("/")
    tasks, scanned, api_calls = [], 0, 0
    for page in range(1, pages + 1):
        if len(tasks) >= limit:
            break
        try:
            pulls = gh(f"/repos/{owner}/{repo}/pulls?state=closed&sort=updated"
                       f"&direction=desc&per_page=100&page={page}", token)
        except urllib.error.HTTPError as e:
            print(f"  [{slug}] PR list page {page} failed: {e}", file=sys.stderr)
            break
        api_calls += 1
        if not pulls:
            break
        for pr in pulls:
            if len(tasks) >= limit:
                break
            scanned += 1
            num, title = pr["number"], pr["title"] or ""
            if not pr.get("merged_at"):
                continue
            if not looks_like_fix(title):
                continue
            if f"{slug}#{num}" in seen:
                continue
            try:
                files = gh(f"/repos/{owner}/{repo}/pulls/{num}/files?per_page=100", token)
            except urllib.error.HTTPError as e:
                print(f"  [{slug}#{num}] files failed: {e}", file=sys.stderr)
                continue
            api_calls += 1
            gold = [f for f in files
                    if f.get("filename", "").endswith(".py")
                    and not is_test(f["filename"])
                    and f.get("patch")]
            tests = [f["filename"] for f in files if is_test(f.get("filename", ""))]
            if not gold or not tests:
                continue
            if len(gold) > MAX_FILES:
                continue
            diff = merge_file_patches(gold)
            if diff.count("\n") > MAX_GOLD_LINES:
                continue
            # A patch with no real change (pure context/whitespace) is not a lesson.
            changed = [l for l in diff.splitlines()
                       if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
            if not changed:
                continue
            seen.add(f"{slug}#{num}")
            tasks.append({
                "id": f"{owner}__{repo}__{num}",
                "repo": slug,
                "issue": (title.strip() + "\n\n"
                          + clean_body(pr.get("body"), title)).strip(),
                "gold_patch": diff,
                "tests": " ".join(tests[:3]),
                "url": pr.get("html_url", ""),
                "base_sha": (pr.get("base") or {}).get("sha", ""),
                "n_gold_files": len(gold),
                "n_changed_lines": len(changed),
            })
            if dry:
                print(f"  [dry-run] {slug}#{num} — {title[:70]} "
                      f"({len(gold)} gold files, {len(changed)} changed lines)")
        time.sleep(0.15)   # be polite; keeps us far from secondary rate limits
    return tasks, scanned, api_calls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="*", default=DEFAULT_REPOS)
    ap.add_argument("--limit", type=int, default=40, help="tasks PER REPO")
    ap.add_argument("--pages", type=int, default=3, help="PR list pages per repo")
    ap.add_argument("--out", default="tasks.jsonl")
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN")
                    or os.environ.get("GITHUB_TOKEN"),
                    help="defaults to $GH_TOKEN / $GITHUB_TOKEN")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.token and not a.dry_run:
        print("NOTE: no token -> 60 req/hour unauthenticated. "
              "Set $GH_TOKEN for 5000/hour.", file=sys.stderr)

    all_tasks, seen = [], set()
    for slug in a.repos:
        print(f"mining {slug} ...")
        t, scanned, calls = mine_repo(slug, a.token, a.limit, a.pages, a.dry_run, seen)
        print(f"  scanned {scanned} merged PRs, {calls} API calls, kept {len(t)}")
        all_tasks.extend(t)

    if a.dry_run:
        print(f"[dry-run] would write {len(all_tasks)} tasks; nothing written")
        return 0
    if not all_tasks:
        print("no tasks mined — check token / rate limit", file=sys.stderr)
        return 1

    with open(a.out, "w", encoding="utf-8") as f:
        for t in all_tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    tot_lines = sum(t["n_changed_lines"] for t in all_tasks)
    print(f"wrote {len(all_tasks)} tasks -> {a.out} "
          f"({tot_lines} changed lines of real bug-fix signal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
