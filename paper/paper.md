# Verified Trajectory Synthesis: Mining Real-World Pull Requests to Parameter-Efficiently Post-Train a 31B Open Model into an Offline SWE Agent

**Track:** Gemma 4 Developer Agent Competition — Paper Submission Award
**Status:** DRAFT — Sections 1–4, 6, 7 are complete. Section 5 (Results) is a
placeholder table; every `{{...}}` must be replaced from `finetune/` logs before
submission. Deadline **November 12, 2026, 23:59 UTC**.
**Code:** <https://github.com/Zhiyilang/gemmapilot> (Apache-2.0)

---

## Abstract

Autonomous software-engineering (SWE) agents are almost exclusively evaluated
behind proprietary cloud APIs. We study whether a 4-bit quantized open model
(`gemma-4-31b-it-qat-w4a16-ct`) can be post-trained, with a single
consumer-class accelerator and **no internet access**, into a competent
repository-navigating bug-fixing agent under a hard global time budget. We make
three claims, each backed by machinery that runs today in the accompanying
repository. **(1)** The binding constraint is not the fine-tuning method but the
*verifiability of the supervision signal*: converting gold patches into
`edit_file` actions silently produces operations whose `old_string` does not
occur in the target file, teaching the model to emit edits that fail at
execution time. We therefore certify every training example with a **dual-path
verification gate** — synthesize the trajectory with one code path,
independently apply the raw gold diff with another, and admit the example only
if both results are byte-identical — fetching true source at the PR's
`base_sha`. On a corpus of **59 real merged bug-fix PRs** mined from the target
repositories the gate certifies **59/59**, i.e. the corpus is provably clean
rather than hopefully clean; ablation A2 tests whether this matters.
**(2)** Verbosity is a first-class failure mode under a global budget, so we
derive the per-task allowance arithmetically (129 tasks / 12 h / 20 % sandbox
reserve → **268 s and ~14 tool calls per task**) and filter training
trajectories against it; **1 of 59** mined trajectories exceeded the call
budget and was removed. **(3)** A fixed 8-stage, graph-first scaffold is what
the adapter specialises, rather than learning tool use from scratch.
Verified-data training improves pass@1 from `{{BASELINE}}` to `{{FINAL}}`, and
the gate is worth `{{DELTA}}` points — `{{GATE_VS_TUNING}}` the benefit
attributable to hyper-parameter tuning. We report negative results as-is,
including the falsification condition under which contribution (1) collapses.

---

## 1. Introduction

Frontier SWE agents (Devin, SWE-agent, OpenHands and successors) pair large
proprietary models with long-horizon tool loops. The Gemma 4 Developer Agent
Competition asks the inverse question: *how far can a single open, quantized
31B model go, offline, on consumer accelerators, inside a 12-hour wall-clock
budget for the whole evaluation set?* That constraint set changes the problem.
Latency, tool-call count, and patch minimality are not quality metrics bolted
on afterwards — they are the scoreboard.

Three observations shaped this work.

**Supervision must be executable, not merely plausible.** The natural way to
build SWE training data is to mine merged bug-fix pull requests and replay the
gold patch. But a replay is only useful if every derived action actually
executes against the code the model will see. A diff hunk whose context has
drifted, or whose `old_string` never occurs in the base revision, produces a
training example that teaches the model to emit edits that fail at execution
time — and it fails *silently*, because the loss goes down regardless. We treat
this as a data-integrity problem and solve it with a gate, not with hope.

**Budget is arithmetic, not a hyper-parameter.** A per-task timeout is a
guardrail against runaway tasks; it does nothing for a *global* budget. If 129
tasks share 12 hours, then 129 × 1200 s = 43 h of nominal capacity is 4.5× the
budget, and four stalled tasks starve the remaining 125. We compute the
per-task allowance from the global budget and align every downstream artifact
— skill call budgets, per-task caps, and the training corpus itself — to that
single number.

**Scaffold first, adapter second.** With a small corpus and a fixed tool
vocabulary, the most valuable thing an adapter can learn is not *what tools
exist* but *how this particular 8-stage repair loop uses them*. We therefore
train on trajectories that instantiate one fixed policy shape, and let the
LoRA specialise rather than discover.

**Contributions.**

1. **Verified trajectory synthesis** — a mining pipeline plus a dual-path
   correctness gate that certifies each training example against the true
   source at the PR's base revision (Section 3.1–3.2).
2. **Budget-aware data curation** — a planner that derives per-task allowances
   from the global budget and filters the corpus against them (Section 3.4).
3. **A minimal-diff action serialization** that expresses supervision in
   exactly the vocabulary of the 9-tool harness (Section 3.3).
4. **A reproducible, fully offline experimental setup** with seven ablations,
   including the falsification test for contribution 1 (Section 4).

## 2. Related Work

**SWE agents and benchmarks.** SWE-bench established the task form we target:
given an issue and a repository, produce a patch that turns failing tests green.
Agent scaffolds (ReAct-style loops, graph-augmented navigation, and
retrieve-and-repair variants) supply the tool layer; our scaffold is
deliberately close to the harness the competition fixes, because deviating
from the tool vocabulary costs distribution shift for no benchmark benefit.

**Post-training for tool use.** Training models to emit structured tool calls
is typically done with supervised trajectories (SFT over rollouts) followed by
rejection sampling or RL. We are firmly in the SFT regime, and our
contribution is orthogonal to the optimiser: we show that *example admission*
— deciding which trajectories enter the corpus at all — is a lever at least as
large as rank and learning-rate tuning, because a silently non-executable
example is worse than no example.

**Data quality for code.** Work on neural code repair has long noted that
patch-context drift breaks replay-based datasets; the standard mitigation is
fuzzy matching or manual filtering. Our gate replaces both with a
*proof*: two independent derivations must agree byte-for-byte, or the example
is dropped. This is cheap (a diff apply and a string compare) and catches the
failure mode exactly.

**Budgeted evaluation.** Time- and cost-bounded agent evaluation has been
studied as a fairness concern; we treat it as a *training-time* constraint and
push it into data curation, which to our knowledge is new.

## 3. Method

### 3.0 Overview

```
mine real bug-fix PRs ──► tasks.jsonl ──► dual-path gate ──► certified tasks
                                                              │
                              budget planner ◄── global budget │
                                                              ▼
                              diff→edit_file serialization ──► trajectories
                                                              │
                              over-budget filter ──────────────┤
                                                              ▼
                                                         train.jsonl ──► QLoRA
```

### 3.1 Mining (`finetune/fetch_real_tasks.py`)

The public development set for this competition is drawn from four Python
repositories — **FastAPI, Rich, Requests, HTTPX** — so we mine from exactly
those, using the GitHub REST API. A pull request is admitted as a task when:

1. the title reads as a bug fix and the PR is **merged**;
2. it is not docs/chore/ci/refactor noise;
3. it changes at least one **non-test** `.py` file **and** touches a test file
   (a repair with no observable test consequence is not trainable);
4. the total diff is at most 220 lines (replayable, reviewable, and within a
   task's tool-call budget).

For each surviving PR we record the issue text (HTML comments, images and PR
template boilerplate — "AI Disclaimer" blocks, checklists, repeated titles —
stripped), the `base_sha`, the changed file list, and the **gold unified diff**
with `--- a/ +++ b/` headers rebuilt, because GitHub's per-file patch payload
does not include them.

**Measured corpus:** 59 tasks, 1,193 changed lines — FastAPI 13, Rich 25,
Requests 9, HTTPX 12. The official development set contains 129 tasks; mining
recovers 59 under the strictness above, which we prefer to a larger, noisier
corpus because every example must survive the gate anyway.

### 3.2 The dual-path verification gate (`finetune/verify_trajectories.py`)

The gate answers one question per task: *do the `edit_file` actions we
synthesized actually reproduce the gold patch when applied to the real base
source?* It refuses to trust the synthesizer with its own answer.

- **Path A (synthesis):** decompose the gold diff into hunks; each hunk becomes
  one `edit_file(old_string, new_string)`; apply them in order to the base file.
- **Path B (independent replay):** apply the raw gold unified diff to the same
  base file with a separate, minimal patch applier.

Both paths start from the **true file contents at `base_sha`**, fetched through
the GitHub contents API (the sandbox blocks `raw.githubusercontent.com`, so we
use `/repos/{r}/contents/{path}?ref={sha}` with base64 decoding, falling back
to `/git/blobs/{sha}` for large files). A task is admitted only if the two
results are **byte-identical**; any mismatch — an `old_string` that does not
occur, a hunk boundary that drifts, a whitespace disagreement — drops the task
and is logged.

**Measured:** 59/59 tasks pass. We state this plainly rather than dressing it
up: on this corpus the gate found **0** rejects, which *certifies* the corpus
rather than demonstrating a large rescue rate. The question "does certification
matter?" is empirical and is answered by ablation A2 (Section 4), in which the
same 59 tasks are trained *without* the gate — i.e. with a naive converter that
admits context-drifted `old_string`s. If A2 ≥ A3, contribution 1 collapses to
engineering hygiene and we will say so (Section 6).

### 3.3 Minimal-diff action serialization

Each hunk becomes exactly one `edit_file` call with the hunk's removed lines
as `old_string` and its added lines as `new_string`. We deliberately do **not**
let the model predict diffs, file paths from scratch, or multi-file plans: the
harness exposes nine tools, and supervision expressed in that vocabulary
removes the predict-a-diff / call-a-tool distribution shift. Pure renames and
pure deletions are expressed as degenerate `edit_file` calls rather than
special-cased, so the action space stays at one tool.

### 3.4 Budget-aware curation (`eval/budget_planner.py`)

The competition gives **12 hours globally** for the whole evaluation set
(sandbox setup included). The planner turns that into per-task allowances:

```
43200 s × (1 − 20 % sandbox/setup reserve) = 34560 s usable
34560 s ÷ 129 tasks                        = 268 s per task
268 s − 2 targeted pytest runs (≈90 s)     = 180 s for model+tools
180 s ÷ 12 s per tool call                 ≈ 14 tool calls per task
```

Every input is a **flag**, not a constant: task count, sandbox reserve,
per-call latency, and per-test latency are assumptions to be re-measured inside
the container and re-derived in one command. The planner also **adjudicates**:
it fails the build if the skills' declared call budgets do not fit inside the
per-task allowance, or if the allowance is too small to close the 8-stage loop.
On first run it failed — the four skills declared 15 calls against 14.8 that
fit — and `repo_navigate` was tightened from 6 to 4 calls, bringing the total
to 13.

The same arithmetic is then applied **to the training corpus**
(`build_trajectories.py --max-calls 14`): a trajectory that spends 18 calls
teaches behaviour that loses points even when its patch is correct, so it is
dropped. Measured: **1 of 59** trajectories was over budget (18 calls) and
removed, leaving 58 with a maximum of 12 calls. Finally the per-task caps in
`eval_config.yaml` were set consistently with the global budget
(`timeout_seconds` 1200 → 360, `max_tool_calls` 60 → 24): the number of tasks
allowed to hit the cap before the global budget dies rose from **4 to 34 of
129**. The planner runs as a CI gate so configuration cannot silently drift
away from the arithmetic again.

### 3.5 Scaffold and QLoRA setup

The scaffold is a fixed 8-stage loop:
`get_status → search_similar_code → get_code_neighbors → read_file →
HYPOTHESIS → edit_file* → run_command(pytest, targeted) → submit_patch`,
encoded in `prompts/system.md` and four ADK skills, each with an executable
script (AST symbol location, minimal-repro generation, diff gate, pytest-output
summariser). The adapter is a QLoRA on `gemma-4-31b-it-qat-w4a16-ct`, rank
`{{RANK}}`, trained with prompt masking (loss on assistant tokens only) and a
fixed seed; `--holdout` reserves the tail of the corpus for the ablations.
Full recipe: `finetune/gemma4_qlora_recipe.py`, which refuses to start unless
an offline pre-flight of the dataset passes (schema, missing turns, and
sequence-length headroom — the longest certified trajectory is 3,999 tokens, so
`max_len` is 8,192, not 4,096, which would truncate the closing `submit_patch`).

## 4. Experimental Setup

**Model.** `gemma-4-31b-it-qat-w4a16-ct` (mandatory base for all agents and
sub-agents). No frontier APIs; all inference offline.

**Hardware.** Kaggle L4×4 sessions (no network at runtime; the base model must
be referenced from mounted input, a mistake that costs a whole session).

**Data.** 59 certified tasks (Section 3.1–3.2), 58 after the budget filter
(Section 3.4). Statistics: ~105k tokens total, 529 assistant turns of which 471
are tool calls, longest trajectory ≈14k characters (pre-flight estimate 3,999
tokens), 7–12 tool calls per trajectory.

**Baselines.**

| ID | Configuration |
|----|---------------|
| B0 | base model + scaffold, no adapter |
| A2 | scaffold + LoRA on **unverified** trajectories (naive converter, gate off) |
| A3 | scaffold + LoRA on **verified** trajectories (full method) |
| A4 | A3 with adapter on root agent only vs. root + analyzer sub-agent |
| A5 | A3 at rank 16 / 32 / 64 |
| A6 | A3 with vs. without the over-budget filter |
| A7 | A3 with per-task cap 360 s vs. 1200 s |

**Metrics.** pass@1 (validation tests green), **edit-apply rate** (fraction of
emitted `edit_file` calls whose `old_string` occurs — the metric the gate
directly targets), tool-call validity rate, trajectory length in calls, and
wall-clock consumption against the 12 h global budget.

**Protocol.** Single seed unless stated; the same certified corpus is used for
every adapter arm so that A2 vs A3 isolates *only* the gate. Per-task budget
follows the planner: ~268 s, ~14 calls.

## 5. Results *(placeholder — fill from logs; do not submit as-is)*

| Arm | pass@1 | edit-apply | calls/task | wall-clock |
|-----|--------|-----------|-----------|-----------|
| B0 no adapter | `{{B0_PASS1}}` | `{{B0_APPLY}}` | `{{B0_CALLS}}` | `{{B0_TIME}}` |
| A2 unverified data | `{{A2_PASS1}}` | `{{A2_APPLY}}` | `{{A2_CALLS}}` | `{{A2_TIME}}` |
| A3 verified data | `{{A3_PASS1}}` | `{{A3_APPLY}}` | `{{A3_CALLS}}` | `{{A3_TIME}}` |
| A4 placement | `{{A4_PASS1}}` | — | — | — |
| A5 rank | `{{A5_PASS1}}` | — | — | — |
| A6 budget filter | `{{A6_PASS1}}` | — | `{{A6_CALLS}}` | `{{A6_TIME}}` |
| A7 cap | `{{A7_PASS1}}` | — | — | `{{A7_TIME}}` |

**The comparison that carries the paper is A2 vs A3**, on identical tasks,
differing only in whether the gate admitted the examples.

## 6. Discussion, Limitations, and Falsification

**What we do not claim.** Trajectories are *gold-patch replays*, not on-policy
rollouts: they teach the shape of a correct repair, not recovery from a failed
attempt. Rejection sampling or RL over the certified data is the natural next
step and is out of scope. The corpus is mined from the four repositories named
in the public development set; generalisation to the hidden repositories is
unverified. All results are single-run; we report seeds and variance.

**Falsification.** If A2 ≥ A3 — unverified data trains as well as verified
data — then the gate is not doing useful work and contribution 1 reduces to
engineering convenience. That is a real possibility and we will report it
as-is rather than re-framing it. Conversely, if A3 beats A2 by less than the
rank sweep (A5) moves pass@1, we will say that tuning matters more than data
certification. The budget claims (contributions 2 and 4) are falsified by A6:
if filtering over-budget trajectories does not reduce wall-clock or calls per
task, brevity curation is decoration.

## 7. Reproducibility

- [ ] `tasks.jsonl` and `train.jsonl` regenerated and hashed
- [ ] base commit SHAs recorded per task (already stored as `base_sha`)
- [ ] QLoRA hyper-parameters dumped from `finetune/gemma4_qlora_recipe.py`
- [ ] adapter placed at `adapters/main_lora/`
- [ ] every `{{...}}` replaced by a measured number
- [ ] converted to PDF and submitted to the paper track before Nov 12, 23:59 UTC

Repository: <https://github.com/Zhiyilang/gemmapilot>. Mining, gating, budget
planning, and the submission-structure validator all run offline with the
standard library only; CI (Python 3.10/3.11/3.12) runs the gate, the planner,
and the structural validator on every push.
