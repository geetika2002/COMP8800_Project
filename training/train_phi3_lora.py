import json
import argparse
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model

def row_to_text(row: dict) -> str:
    # Common formats your builder might create
    if "text" in row and row["text"]:
        return row["text"]

    if "messages" in row and row["messages"]:
        parts = []
        for m in row["messages"]:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            parts.append(f"{role}: {content}")
        return "\n".join(parts) + "\nassistant:"

    # Sometimes people store prompt/completion
    if "prompt" in row and "completion" in row and row["prompt"] is not None:
        return str(row["prompt"]) + str(row["completion"] or "")

    return json.dumps(row)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--valid", required=True)
    ap.add_argument("--base_model", default="microsoft/Phi-3-mini-4k-instruct")
    ap.add_argument("--out", default="ft/outputs/phi3-lora")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max_len", type=int, default=256)
    args = ap.parse_args()

    ds = load_dataset("json", data_files={"train": args.train, "validation": args.valid})

    # Print columns so we know what format your JSONL is
    print("Train columns:", ds["train"].column_names)

    tok = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)

    def tokenize_batch(batch):
        # batch is dict: {col: [v1, v2, ...]}
        cols = list(batch.keys())
        n = len(batch[cols[0]]) if cols else 0

        rows = []
        for i in range(n):
            r = {c: batch[c][i] for c in cols}
            rows.append(r)

        texts = [row_to_text(r) for r in rows]
        return tok(texts, truncation=True, max_length=args.max_len)

    train = ds["train"].map(tokenize_batch, batched=True, remove_columns=ds["train"].column_names)
    valid = ds["validation"].map(tokenize_batch, batched=True, remove_columns=ds["validation"].column_names)

    model = AutoModelForCausalLM.from_pretrained(args.base_model)

    # Phi-3 projection module names
    lora = LoraConfig(
        r=4,
        lora_alpha=8,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    collator = DataCollatorForLanguageModeling(tok, mlm=False)

    targs = TrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        logging_steps=1,
        eval_strategy="no",     # valid set is 1 sample; keep it simple/fast
        save_strategy="epoch",
        report_to="none",
        fp16=False,
    )

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train,
        eval_dataset=valid,
        data_collator=collator,
    )

    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print("Saved adapter + tokenizer to:", args.out)

if __name__ == "__main__":
    main()
