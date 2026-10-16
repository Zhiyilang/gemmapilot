#!/usr/bin/env python3
"""
GemmaPilot — LoRA fine-tuning recipe for the Gemma 4 Developer Agent Competition.

Target base model (mandated by the competition):
    gemma-4-31b-it-qat-w4a16-ct   (Gemma 4 31B Instruct, QAT W4A16)

Runs INSIDE a Kaggle notebook on the competition's L4x4 accelerators (4x L4,
~96 GB) and writes a PEFT/LoRA adapter in the exact layout the harness expects:

    adapters/main_lora/
        adapter_config.json
        adapter_model.safetensors

Then reference it from agent.yaml as `adapter: main_lora`.

Dataset format (produced by finetune/build_trajectories.py):
    {"messages": [{"role": "system"|"user"|"assistant", "content": "..."}, ...]}

TWO THINGS BEFORE YOU BURN GPU QUOTA
  1. `--dry-run` validates the dataset with NO torch/GPU at all. Run it locally
     first. It catches the failure modes that silently waste a whole L4x4 run:
     malformed messages, empty system prompt, sequences that blow past --max_len,
     assistant turns that carry no loss signal.
  2. L4 sessions have NO INTERNET, so the base model must come from a Kaggle
     dataset/input attached to the notebook. Pass --model_id with that path.

Stdlib only for --dry-run; torch/transformers/peft are imported lazily.
"""
from __future__ import annotations
import argparse, json, os, sys

# --------------------------------------------------------------------- data
def load_dataset(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def dry_run(rows, args) -> int:
    """Validate the dataset offline. Returns exit code."""
    problems, warns = [], []
    if not rows:
        print("[dry-run] FATAL: dataset is empty")
        return 2

    n_tok_est = 0
    max_chars = 0
    for i, r in enumerate(rows):
        msgs = r.get("messages")
        if not isinstance(msgs, list) or not msgs:
            problems.append(f"row {i}: missing/empty 'messages'")
            continue
        roles = [m.get("role") for m in msgs]
        if roles[0] != "system":
            problems.append(f"row {i}: first message is '{roles[0]}', expected 'system'")
        if not (msgs[0].get("content") or "").strip():
            problems.append(f"row {i}: empty system prompt")
        if "user" not in roles:
            problems.append(f"row {i}: no user turn")
        n_assist = sum(1 for x in roles if x == "assistant")
        if n_assist == 0:
            problems.append(f"row {i}: no assistant turn -> contributes zero loss")
        for m in msgs:
            if not isinstance(m.get("content"), str):
                problems.append(f"row {i}: non-string content in role {m.get('role')}")
                break
        chars = sum(len(m.get("content", "")) for m in msgs)
        max_chars = max(max_chars, chars)
        # crude but useful: ~4 chars/token for English+code
        est = chars // 4
        n_tok_est += est
        if est > args.max_len:
            warns.append(f"row {i}: ~{est} tokens > --max_len {args.max_len} "
                         f"(will be truncated; assistant tail may be cut -> "
                         f"teaches a truncated action)")

    print(f"[dry-run] rows              : {len(rows)}")
    print(f"[dry-run] est. total tokens : ~{n_tok_est}")
    print(f"[dry-run] longest sequence  : {max_chars} chars (~{max_chars//4} tokens)")
    print(f"[dry-run] --max_len         : {args.max_len}")
    n_tool = sum(1 for r in rows for m in r.get("messages", [])
                 if m.get("role") == "assistant" and m.get("content", "").startswith('{"tool"'))
    print(f"[dry-run] assistant turns   : "
          f"{sum(1 for r in rows for m in r.get('messages',[]) if m.get('role')=='assistant')} "
          f"({n_tool} look like tool calls)")

    for w in warns[:10]:
        print(f"[dry-run] WARN  {w}")
    if len(warns) > 10:
        print(f"[dry-run] ... and {len(warns)-10} more warnings")
    for p in problems[:10]:
        print(f"[dry-run] ERROR {p}")
    if len(problems) > 10:
        print(f"[dry-run] ... and {len(problems)-10} more errors")

    if problems:
        print("\n[dry-run] FAILED — fix the dataset before spending GPU quota")
        return 1
    print("\n[dry-run] OK — dataset looks trainable")
    return 0


# ------------------------------------------------------- assistant-only loss
def mask_prompt_tokens(tok, text: str, msgs: list[dict], enc: dict):
    """
    Set labels to -100 everywhere except tokens inside assistant messages.

    Training the model to predict the system prompt and the issue text back is
    wasted capacity on a 59-example corpus. Returns None if the offsets needed
    for masking are unavailable, so the caller can fall back safely.
    """
    try:
        full = tok(text, truncation=True, max_length=enc["input_ids"].shape[-1],
                   return_offsets_mapping=True, return_tensors="pt")
    except Exception:
        return None
    offsets = full.get("offset_mapping")
    if offsets is None:
        return None
    offsets = offsets[0].tolist()

    spans, cursor = [], 0
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        c = m.get("content", "")
        if not c:
            continue
        idx = text.find(c, cursor)
        if idx < 0:            # template reformatted the content -> not safe
            return None
        spans.append((idx, idx + len(c)))
        cursor = idx + len(c)

    if not spans:
        return None

    ids = enc["input_ids"][0].tolist()
    labels = [-100] * len(ids)
    hit = 0
    for t, (s, e) in enumerate(offsets):
        if s == e:             # special token, no source span
            continue
        if any(s < e2 and s2 < e for (s2, e2) in spans):
            labels[t] = ids[t]
            hit += 1
    if hit == 0:
        return None
    return {"hit": hit, "labels": labels}


# ------------------------------------------------------------------- training
def build_model(model_id: str, lora_r: int, lora_alpha: int, seed: int):
    """4-bit QLoRA on the mandated Gemma 4 base. Returns (model, tokenizer)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(seed)

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb,
        device_map="auto",
        attn_implementation="sdpa",
    )
    lora = LoraConfig(
        r=lora_r, lora_alpha=lora_alpha, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    return model, tok


def train(args):
    import torch
    from transformers import TrainingArguments, Trainer, DataCollatorForSeq2Seq
    from torch.utils.data import Dataset

    model, tok = build_model(args.model_id, args.lora_r, args.lora_alpha, args.seed)
    rows = load_dataset(args.data)

    # deterministic holdout: keep the last N out so ablations are comparable
    hold = max(0, min(args.holdout, len(rows) - 1))
    train_rows, val_rows = rows[:len(rows) - hold], rows[len(rows) - hold:]
    print(f"[GemmaPilot] train={len(train_rows)} holdout={len(val_rows)}")

    masked_any = 0

    class TrajDS(Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, i):
            msgs = self.data[i]["messages"]
            text = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=False)
            enc = tok(text, truncation=True, max_length=args.max_len,
                      return_tensors="pt")
            enc = {k: v.squeeze(0) for k, v in enc.items()}
            ids = enc["input_ids"].tolist()
            labels = list(ids)

            if args.mask_prompt:
                nonlocal masked_any
                res = mask_prompt_tokens(tok, text, msgs, enc)
                if res is None:
                    print("[GemmaPilot] WARN: could not mask prompt for one "
                          "example (offsets unavailable) — falling back to "
                          "full-sequence loss for it")
                else:
                    labels = res["labels"]
                    masked_any += 1

            enc["labels"] = torch.tensor(labels, dtype=torch.long)
            return enc

    ds = TrajDS(train_rows)
    training_args = TrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        bf16=True,
        optim="paged_adamw_8bit",
        logging_steps=10,
        save_strategy="epoch",
        gradient_checkpointing=True,
        seed=args.seed,
        report_to=[],
    )
    trainer = Trainer(
        model=model, args=training_args, train_dataset=ds,
        data_collator=DataCollatorForSeq2Seq(tok, padding=True),
        eval_dataset=TrajDS(val_rows) if val_rows else None,
    )
    trainer.train()

    # Adapter must contain adapter_config.json + adapter_model.safetensors.
    # Tokenizer files go next to it, NOT inside — keep the adapter dir clean.
    os.makedirs(args.adapter_dir, exist_ok=True)
    model.save_pretrained(args.adapter_dir, safe_serialization=True)
    tok.save_pretrained(os.path.dirname(args.adapter_dir.rstrip("/")) or ".")
    print(f"[GemmaPilot] adapter saved -> {args.adapter_dir}")
    print(f"[GemmaPilot] prompt-masked examples: {masked_any}/{len(train_rows)}")
    if val_rows:
        print("[GemmaPilot] holdout metrics:", trainer.evaluate())


def main() -> int:
    ap = argparse.ArgumentParser()
    # NOTE: L4 sessions have no internet — point this at the attached
    # Kaggle model input, e.g.
    #   /kaggle/input/gemma-4/transformers/gemma-4-31b-it-qat-w4a16-ct/1
    # Verify the exact path on the competition's Data page before running.
    ap.add_argument("--model_id", default="google/gemma-4-31b-it-qat-w4a16-ct")
    ap.add_argument("--data", default="/kaggle/input/gemmapilot-trajectories/train.jsonl")
    ap.add_argument("--out", default="/kaggle/working/checkpoints")
    ap.add_argument("--adapter_dir", default="/kaggle/working/adapters/main_lora")
    ap.add_argument("--lora_r", type=int, default=64)
    ap.add_argument("--lora_alpha", type=int, default=128)
    # 8192, not 4096: the longest mined trajectory measures ~3999 tokens, so a
    # 4096 window leaves ~97 tokens of slack. Any longer task would be truncated
    # exactly where it matters — the trailing submit_patch action.
    ap.add_argument("--max_len", type=int, default=8192)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--holdout", type=int, default=0,
                    help="last N rows held out for eval (0 = none)")
    ap.add_argument("--mask-prompt", dest="mask_prompt", action="store_true",
                    default=True, help="train loss on assistant tokens only")
    ap.add_argument("--no-mask-prompt", dest="mask_prompt", action="store_false")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the dataset only; no torch, no GPU")
    a = ap.parse_args()

    rows = load_dataset(a.data)
    if a.dry_run:
        return dry_run(rows, a)

    # Cheap pre-flight before loading a 31B model — fail fast, not after 20 min.
    rc = dry_run(rows, a)
    if rc != 0:
        print("[GemmaPilot] refusing to start training on a dataset that "
              "failed pre-flight (override by fixing the data)")
        return rc
    train(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
