"""
Fine-tunes the base model with LoRA using Unsloth, per ml/configs/lora_config.yaml.
Run from src/ml/scripts with the lorekeeper-train conda env active (GPU required).

Usage: python train.py --config ../configs/lora_config.yaml
"""
import argparse
from pathlib import Path

import yaml
from datasets import load_dataset


def format_prompt(record: dict) -> str:
    return (
        f"{record['instruction']}\n\nInput: {record['input']}\nOutput: {record['output']}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="../configs/lora_config.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg["model_name"],
        max_seq_length=cfg["max_seq_length"],
        load_in_4bit=cfg["load_in_4bit"],
        dtype=None,
    )

    lora_cfg = cfg["lora"]
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_cfg["r"],
        target_modules=lora_cfg["target_modules"],
        lora_alpha=lora_cfg["lora_alpha"],
        lora_dropout=lora_cfg["lora_dropout"],
        bias=lora_cfg["bias"],
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    train_cfg = cfg["training"]
    dataset = load_dataset("json", data_files=train_cfg["dataset_path"], split="train")
    dataset = dataset.map(lambda r: {"text": format_prompt(r)})

    output_dir = train_cfg["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    sft_config = SFTConfig(
        output_dir=output_dir,
        per_device_train_batch_size=train_cfg["per_device_train_batch_size"],
        gradient_accumulation_steps=train_cfg["gradient_accumulation_steps"],
        warmup_steps=train_cfg["warmup_steps"],
        num_train_epochs=train_cfg["num_train_epochs"],
        learning_rate=train_cfg["learning_rate"],
        fp16=train_cfg["fp16"],
        bf16=train_cfg["bf16"],
        logging_steps=train_cfg["logging_steps"],
        save_steps=train_cfg["save_steps"],
        max_seq_length=cfg["max_seq_length"],
        dataset_text_field="text",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=sft_config,
    )

    trainer.train()

    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"LoRA adapter saved to {output_dir}")

    export_cfg = cfg.get("export", {})
    gguf_output = export_cfg.get("gguf_output")
    quant = export_cfg.get("quantization", "q4_k_m")
    if gguf_output:
        print(f"Exporting merged model to GGUF ({quant}) at {gguf_output}...")
        gguf_dir = str(Path(gguf_output).parent)
        model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method=quant)

        # Unsloth writes into a sibling "{gguf_dir}_gguf" directory using the base
        # model's own name, not gguf_output — relocate it to the configured path.
        produced_dir = Path(f"{gguf_dir}_gguf")
        matches = sorted(produced_dir.glob(f"*.{quant.upper()}.gguf"))
        if matches:
            Path(gguf_output).parent.mkdir(parents=True, exist_ok=True)
            matches[0].rename(gguf_output)
            modelfile = produced_dir / "Modelfile"
            if modelfile.exists():
                modelfile.rename(Path(gguf_output).with_name(Path(gguf_output).stem + "-Modelfile"))
            if not any(produced_dir.iterdir()):
                produced_dir.rmdir()
            print(f"GGUF export complete: {gguf_output}")
        else:
            print(f"GGUF export complete, but expected output not found in {produced_dir} — check unsloth's logged path.")


if __name__ == "__main__":
    main()
