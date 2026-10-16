# Paper Track — outline & draft scaffolding

**Track:** Gemma 4 Developer Agent Competition — *Paper Submission Award* ($35,000 pool)
**Topic fit (official list):** *"Tuning & Optimization: Parameter-efficient fine-tuning
and Reinforcement Learning (RL) approaches tailored to improve SWE agent capabilities."*
**Deadline:** **November 12, 2026, 23:59 UTC** — three weeks BEFORE the main
submission deadline (Dec 2). Sign up separately at
<https://www.kaggle.com/competitions/gemma-4-developer-agent-paper>.

> STATUS: draft scaffolding, written before the LoRA run. Every number is a
> `{{PLACEHOLDER}}` to be filled from `finetune/` logs. **Do not submit with
> placeholders.** The contribution statements below describe machinery that
> already exists and runs in this repository — no invented results.

---

## Working title

> **Verified Trajectory Synthesis: Mining Real-World Pull Requests to
> Parameter-Efficiently Post-Train a 31B Open Model into an Offline SWE Agent**

## Abstract (draft — fill after the run)

Autonomous software-engineering agents are almost exclusively evaluated behind
proprietary cloud APIs. We study whether a 4-bit quantized open model
(`gemma-4-31b-it-qat-w4a16-ct`) can be post-trained, with a single consumer-class
accelerator and **no internet access**, into a competent repository-navigating
bug-fixing agent. Our central finding is that **the binding constraint is not the
fine-tuning method but the verifiability of the supervision signal**: naively
converting gold patches into `edit_file` actions produces a large fraction of
operations whose `old_string` does not occur in the target file, silently
teaching the model to emit edits that fail at execution time. We introduce a
**dual-path verification gate** — synthesize the trajectory with one code path,
independently apply the raw gold diff with another, and admit a training example
only if both produce byte-identical results — and show it removes
`{{N_REJECTED}}` poisoned examples from a corpus of `{{N_MINED}}` real
bug-fix pull requests mined from the target repositories (FastAPI, Rich,
Requests, HTTPX). On top of verified data we train a `{{RANK}}`-rank QLoRA
adapter and drive it with a graph-first scaffold. Verified-data training
improves `{{METRIC}}` from `{{BASELINE}}` to `{{FINAL}}` (pass@1), and the
gate itself is worth `{{DELTA}}` points — more than doubling the benefit
attributable to hyper-parameter tuning.

## Contributions (all three are implemented in this repo today)

1. **Verified trajectory synthesis.** A mining pipeline
   (`finetune/fetch_real_tasks.py`) that turns real merged bug-fix PRs into
   training tasks, plus a correctness gate (`finetune/verify_trajectories.py`)
   that fetches the true source at the PR's `base_sha` and accepts an example
   only when two independent derivation paths agree. Measured: **59/59 mined
   tasks pass**, i.e. the gate is not vacuous — it is what makes the corpus
   trustworthy.
2. **Graph-first action scaffold.** A fixed 8-stage policy shape
   (`get_status → search_similar_code → get_code_neighbors → read_file →
   hypothesis → edit_file* → run_command(pytest) → submit_patch`) encoded in
   `prompts/system.md` and four ADK skills. The scaffold is what the LoRA is
   trained to *specialise*, rather than learning tool use from scratch.
3. **Minimal-diff action serialization.** Gold unified diffs are decomposed into
   one `edit_file(old_string, new_string)` per hunk, so supervision is expressed
   in exactly the vocabulary of the 9-tool harness. This removes the
   distribution shift between "predict a diff" and "call a tool".
4. **Budget-aware training-data curation.** A shared global time budget makes
   *verbosity* a first-class failure mode: a trajectory that spends 20 tool
   calls teaches behaviour that loses points even when the patch is correct.
   `eval/budget_planner.py` derives the per-task allowance from the global
   budget (129 tasks / 12 h / 20 % sandbox reserve → ~268 s and ~14 calls per
   task), and `build_trajectories.py` drops any trajectory that exceeds it.
   Measured: **1 of 59** mined trajectories was over budget (18 calls) and was
   removed, leaving 58 with max 12 calls. The same arithmetic drives the
   per-task limits in `eval_config.yaml`: lowering the cap from 1200 s to 360 s
   raised the number of tasks allowed to stall (hit the cap) before the global
   budget is exhausted from **4 to 34 of 129**.

## Planned experiments (fill from logs)

| ID | Ablation | Isolates |
|----|----------|----------|
| A1 | base model + scaffold, **no adapter** | scaffold contribution |
| A2 | scaffold + LoRA trained on **unverified** trajectories | value of the gate |
| A3 | scaffold + LoRA trained on **verified** trajectories | full method |
| A4 | A3 with adapter on root agent only vs. root + analyzer sub-agent | adapter placement |
| A5 | rank `{{16}}` vs `{{32}}` vs `{{64}}` | capacity/budget trade-off |
| A6 | A3 with vs. without the **over-budget trajectory filter** (contribution 4) | does curation for brevity actually save wall clock |
| A7 | A3 with per-task cap 360 s vs. 1200 s | cap vs. global-budget interaction |

Metrics: pass@1 (patched repo passes validation tests), **edit-apply rate**
(fraction of emitted `edit_file` calls whose `old_string` matches — the metric
that directly measures what the gate fixes), tool-call validity rate, and mean
budget consumption against the 12 h global limit.

## Honest limitations (state these, do not hide them)

- Trajectories are **gold-patch replays**, not on-policy rollouts: they teach
  the *shape* of a correct repair, not recovery from failure. RL / rejection
  sampling is the natural next step and is out of scope for this submission.
- The corpus is mined from the four repositories confirmed in the public
  development set; generalisation to the hidden test repositories is unverified.
- All results are single-run unless stated; seeds and variance to be reported.

## Reproducibility checklist

- [ ] `tasks.jsonl` + `train.jsonl` regenerated and hashed
- [ ] base commit SHAs recorded per task (already stored as `base_sha`)
- [ ] QLoRA hyper-parameters dumped from `finetune/gemma4_qlora_recipe.py`
- [ ] adapter placed at `adapters/main_lora/`
- [ ] every `{{PLACEHOLDER}}` replaced by a measured number
- [ ] PDF + source submitted to the **paper track** before Nov 12, 23:59 UTC

## Falsification note

If A2 ≥ A3 (unverified data trains as well as verified data), the gate is not
doing useful work and Contribution 1 collapses to an engineering convenience.
That result is still worth publishing, and we will report it as-is.
