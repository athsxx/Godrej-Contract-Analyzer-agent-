#!/usr/bin/env python3
"""
PEFT/LoRA training for contract clause LLM.

Loads JSONL from data/peft_clause_train.jsonl (chat format).
Uses transformers + peft (LoRA) on a small model for quick testing.

Compatibility note: 8B training should be run with --use_4bit on local GPU setups.
"""

import argparse
import json
from pathlib import Path

from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForLanguageModeling,
    TrainingArguments,
    Trainer,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "peft_clause_train.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "peft_adapters"
DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def load_jsonl(path: Path) -> list[dict]:
    """Load chat-format JSONL."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def format_chat_to_prompt(messages: list[dict], tokenizer) -> str:
    """Format messages into a single string using the model's chat template if available."""
    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template is not None:
        # Use model's chat template (e.g. Llama)
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    # Fallback: simple concatenation
    parts = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"<|system|>\n{content}\n")
        elif role == "user":
            parts.append(f"<|user|>\n{content}\n")
        elif role == "assistant":
            parts.append(f"<|assistant|>\n{content}\n")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="PEFT/LoRA training for contract clause LLM")
    parser.add_argument(
        "--data_path",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=f"Path to JSONL training data (default: {DEFAULT_DATA_PATH})",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save adapters (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Base model (default: {DEFAULT_MODEL}). Use smaller models for CPU/low-GPU.",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=2e-5,
        help="Learning rate (default: 2e-5)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=2,
        help="Per-device batch size (default: 2). Reduce if OOM.",
    )
    parser.add_argument(
        "--use_4bit",
        action="store_true",
        help="Use 4-bit quantization to reduce memory (recommended for 8GB GPU)",
    )
    args = parser.parse_args()

    if not args.data_path.exists():
        raise FileNotFoundError(
            f"Training data not found: {args.data_path}. "
            "Run scripts/prepare_peft_data.py first."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load tokenizer
    print(f"Loading tokenizer: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    # Load model
    model_kwargs = {}
    if args.use_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype="float16",
            bnb_4bit_quant_type="nf4",
        )
    print(f"Loading model: {args.model}")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        trust_remote_code=True,
        **model_kwargs,
    )

    if args.use_4bit:
        model = prepare_model_for_kbit_training(model)

    # LoRA config
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Load and prepare data
    records = load_jsonl(args.data_path)
    texts = []
    for r in records:
        messages = r.get("messages", [])
        if not messages:
            continue
        text = format_chat_to_prompt(messages, tokenizer)
        texts.append({"text": text})

    dataset = Dataset.from_list(texts)

    def tokenize_fn(examples):
        return tokenizer(
            examples["text"],
            truncation=True,
            max_length=2048,
            padding="max_length",
            return_tensors=None,
        )

    tokenized = dataset.map(
        tokenize_fn,
        batched=True,
        remove_columns=dataset.column_names,
    )

    # Training
    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=2,
        fp16=not args.use_4bit,  # fp16 when not using 4bit
        report_to="none",
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=data_collator,
    )

    print("Starting training...")
    trainer.train()
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"Adapters saved to {args.output_dir}")


if __name__ == "__main__":
    main()
