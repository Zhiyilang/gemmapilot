#!/usr/bin/env python3
"""
GemmaPilot — LoRA fine-tuning recipe for the Gemma 4 Developer Agent Competition.

Target base model (mandated by the competition):
    gemma-4-31b-it-qat-w4a16-ct   (Gemma 4 31B Instruct, QAT W4A16)

This script is meant to run INSIDE a Kaggle notebook on the competition's
L4x4 accelerators (4x L4 ~= 96 GB). It produces a PEFT/LoRA adapter in the
exact layout the harness expects:

    adapters/main_lora/
        adapter_config.json
        adapter_model.safetensors

Then reference it from agent.yaml as `adapter: main_lora`.

Training objective: teach the model precise tool-calling + minimal-diff patching
on SWE trajectories, so the agent wins the "Unsloth Fine-Tuning Award" ($10k)
and lifts main-leaderboard pass@1.

Dataset format (you assemble from SWE-bench-style trajectories):
    {"messages": [
        {"role":"system","content":"<prompts/system.md content>"},
        {"role":"user","content":"<issue + repo graph snapshot + available tools>"},
        {"role":"assistant","content":"<one tool call OR one edit OR submit_patch>"}
    ]}
"""
from __future__ import annotations
import os, json, argparse

def build_model(model_id: str, lora_r: int = 64, lora_alpha: int = 128):
    """4-bit QLoRA on the mandated Gemma 4 base. Returns (model, tokenizer)."""
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)
    from peft import LoraConfig, get_peft_model

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb,
        device_map="auto",
        attn_implementation="sdpa",
    )
    # Target the attention + MLP projection layers for memory-efficient adapters.
    lora = LoraConfig(
        r=lora_r, lora_alpha=lora_alpha, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    return model, tok

def load_dataset(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def train(args):
    import torch
    from transformers import (TrainingArguments, Trainer,
                              DataCollatorForSeq2Seq)
    from torch.utils.data import Dataset

    model, tok = build_model(args.model_id, args.lora_r, args.lora_alpha)
    rows = load_dataset(args.data)

    class TrajDS(Dataset):
        def __init__(self, rows):
            self.rows = rows
        def __len__(self):
            return len(self.rows)
        def __getitem__(self, i):
            msgs = rows[i]["messages"]
            text = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=False)
            enc = tok(text, truncation=True, max_length=args.max_len,
                      return_tensors="pt")
            enc = {k: v.squeeze(0) for k, v in enc.items()}
            enc["labels"] = enc["input_ids"].clone()
            return enc

    training_args = TrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=args.epochs,
        learning_rate=2e-4,
        bf16=True,
        optim="paged_adamw_8bit",
        logging_steps=10,
        save_strategy="epoch",
        gradient_checkpointing=True,
        report_to=[],
    )
    trainer = Trainer(
        model=model, args=training_args,
        train_dataset=TrajDS(rows),
        data_collator=DataCollatorForSeq2Seq(tok, padding=True),
    )
    trainer.train()
    # Save ONLY the LoRA adapter in safetensors (harness-compatible).
    model.save_pretrained(args.adapter_dir, safe_serialization=True)
    tok.save_pretrained(args.adapter_dir)
    print(f"[GemmaPilot] adapter saved -> {args.adapter_dir}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_id", default="google/gemma-4-31b-it-qat-w4a16-ct")
    ap.add_argument("--data", default="/kaggle/input/gemmapilot-trajectories/train.jsonl")
    ap.add_argument("--out", default="/kaggle/working/checkpoints")
    ap.add_argument("--adapter_dir", default="/kaggle/working/adapters/main_lora")
    ap.add_argument("--lora_r", type=int, default=64)
    ap.add_argument("--lora_alpha", type=int, default=128)
    ap.add_argument("--max_len", type=int, default=4096)
    ap.add_argument("--epochs", type=float, default=1.0)
    train(ap.parse_args())
