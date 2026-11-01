"""
Publishes a trained Lorekeeper fine-tune to the Hugging Face Hub as TWO repos:

  <user>/Lorekeeper-Mistral-7B-GGUF   merged, quantized GGUF + Ollama Modelfile + card
  <user>/Lorekeeper-Mistral-7B-LoRA   the PEFT/LoRA adapter (safetensors) + card

They must stay separate: Ollama's `ollama pull hf.co/<user>/<repo>` (used by
the in-app Model Library installer) only accepts repos the Hub recognises as
GGUF. Putting the LoRA's safetensors next to the GGUF makes the pull fail with
"Repository is not GGUF or is not compatible with llama.cpp" — so this script
refuses to upload anything except GGUF / Modelfile / README to the GGUF repo.

Reads artifact paths from the same config train.py uses. Run from src/ml/scripts:

    hf auth login                      # once; token needs write access
    python publish_to_hub.py --dry-run # show what would be uploaded
    python publish_to_hub.py           # upload both repos
    python publish_to_hub.py --only gguf --verify-ollama http://localhost:11434
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

import yaml

GGUF_REPO_ALLOWED = re.compile(r"(\.gguf|Modelfile|README\.md)$")
HUB_MODELFILE_NAME = "lorekeeper-Modelfile"  # name the app installer + README expect


def gguf_card(user: str, base_model: str, gguf_name: str, lora_repo: str, quant: str) -> str:
    return f"""---
base_model: {base_model}
tags: [gguf, ollama, llama.cpp, mistral, ttrpg, lorekeeper]
license: apache-2.0
---
# Lorekeeper-Mistral-7B (GGUF)

Fine-tune of `{base_model}` for tabletop-RPG campaign journaling (shorthand session
notes → genre-voiced narrative), merged and quantized to **{quant}** for local
inference with [Lorekeeper](https://lorekeeper.quest).

The LoRA adapter lives in a separate repo: [`{user}/{lora_repo}`](https://huggingface.co/{user}/{lora_repo}).

## Ollama
```bash
ollama pull hf.co/{user}/{gguf_name}
ollama cp hf.co/{user}/{gguf_name} lorekeeper
```
Or build it with the bundled Modelfile (exact chat template + stop tokens):
```bash
curl -LO https://huggingface.co/{user}/{gguf_name}/resolve/main/<file>.gguf
curl -LO https://huggingface.co/{user}/{gguf_name}/resolve/main/{HUB_MODELFILE_NAME}
ollama create lorekeeper -f {HUB_MODELFILE_NAME}
```
"""


def lora_card(user: str, base_model: str, gguf_repo: str) -> str:
    return f"""---
base_model: {base_model}
library_name: peft
tags: [lora, unsloth, mistral, ttrpg, lorekeeper]
license: apache-2.0
---
# Lorekeeper-Mistral-7B (LoRA adapter)

PEFT/LoRA adapter for `{base_model}`, trained with Unsloth for tabletop-RPG campaign
journaling. For local inference use the merged GGUF instead:
[`{user}/{gguf_repo}`](https://huggingface.co/{user}/{gguf_repo}).
"""


def hub_modelfile(local_modelfile: Path, gguf_filename: str) -> str:
    """Rewrite FROM to the uploaded GGUF's bare filename so the Modelfile works
    from a directory where both files were downloaded side by side."""
    text = local_modelfile.read_text()
    text, n = re.subn(r"(?m)^FROM\s+.*$", f"FROM {gguf_filename}", text, count=1)
    if n == 0:
        text = f"FROM {gguf_filename}\n" + text
    return text


def plan_gguf(gguf: Path, modelfile: Path | None) -> list[tuple[str, Path | None]]:
    if not gguf.is_file():
        sys.exit(f"GGUF not found: {gguf} (did train.py's export step run?)")
    files = [(gguf.name, gguf)]
    if modelfile and modelfile.is_file():
        files.append((HUB_MODELFILE_NAME, None))  # generated from modelfile
    else:
        print(f"warning: no Modelfile at {modelfile}; publishing GGUF without one")
    for name, _ in files:
        if not GGUF_REPO_ALLOWED.search(name):
            sys.exit(f"refusing to put {name!r} in the GGUF repo (would break `ollama pull`)")
    return files


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="../configs/lora_config.yaml")
    p.add_argument("--user", help="Hub namespace (default: the logged-in account)")
    p.add_argument("--gguf-repo", default="Lorekeeper-Mistral-7B-GGUF")
    p.add_argument("--lora-repo", default="Lorekeeper-Mistral-7B-LoRA")
    p.add_argument("--only", choices=["gguf", "lora"], help="publish just one of the two repos")
    p.add_argument("--private", action="store_true", help="create new repos as private")
    p.add_argument("--write-card", action="store_true",
                   help="overwrite an existing README.md model card (always written for new repos)")
    p.add_argument("--message", default="Publish Lorekeeper fine-tune")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verify-ollama", metavar="OLLAMA_URL",
                   help="after upload, ask this Ollama server to pull the GGUF repo to prove it's pullable")
    args = p.parse_args()

    cfg_path = Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text())
    root = Path.cwd()  # config paths are relative to the cwd (src/ml/scripts), as in train.py
    gguf = (root / cfg["export"]["gguf_output"]).resolve()
    modelfile = gguf.with_name(gguf.stem + "-Modelfile")
    lora_dir = (root / cfg["training"]["output_dir"]).resolve()
    quant = cfg["export"].get("quantization", "q4_k_m")
    base_model = cfg["model_name"]

    from huggingface_hub import HfApi  # imported late so --help works without it
    api = HfApi()
    user = args.user or (None if args.dry_run else api.whoami()["name"]) or "<you>"
    gguf_id, lora_id = f"{user}/{args.gguf_repo}", f"{user}/{args.lora_repo}"

    jobs = []
    if args.only in (None, "gguf"):
        jobs.append(("gguf", gguf_id, plan_gguf(gguf, modelfile)))
    if args.only in (None, "lora"):
        if not (lora_dir / "adapter_config.json").is_file():
            sys.exit(f"LoRA adapter not found in {lora_dir} (expected adapter_config.json)")
        jobs.append(("lora", lora_id, [(f.relative_to(lora_dir).as_posix(), f)
                                       for f in sorted(lora_dir.rglob("*")) if f.is_file()
                                       and "checkpoint-" not in f.as_posix()]))

    for kind, repo_id, files in jobs:
        print(f"\n== {kind}: {repo_id}")
        for name, src in files:
            size = f"{src.stat().st_size / 1e9:.2f} GB" if src else "generated"
            print(f"   {name:45s} {size}")
        if args.dry_run:
            continue
        api.create_repo(repo_id, repo_type="model", private=args.private, exist_ok=True)
        has_card = api.file_exists(repo_id, "README.md")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            for name, src in files:
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if kind == "gguf" and name == HUB_MODELFILE_NAME:
                    dest.write_text(hub_modelfile(modelfile, gguf.name))
                else:
                    dest.symlink_to(src)
            if args.write_card or not has_card:
                card = (gguf_card(user, base_model, args.gguf_repo, args.lora_repo, quant)
                        if kind == "gguf" else lora_card(user, base_model, args.gguf_repo))
                (stage / "README.md").write_text(card)
            api.upload_folder(repo_id=repo_id, folder_path=stage, commit_message=args.message)
        if kind == "gguf":
            stray = [f for f in api.list_repo_files(repo_id) if not GGUF_REPO_ALLOWED.search(f)
                     and f != ".gitattributes"]
            if stray:
                print(f"   WARNING: {repo_id} still contains non-GGUF files {stray}; "
                      "`ollama pull` will fail until they're removed.")
        print(f"   uploaded → https://huggingface.co/{repo_id}")

    if args.verify_ollama and not args.dry_run and args.only != "lora":
        import json
        import urllib.request
        req = urllib.request.Request(f"{args.verify_ollama.rstrip('/')}/api/pull",
                                     data=json.dumps({"model": f"hf.co/{gguf_id}", "stream": False}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            result = json.loads(r.read())
        if result.get("status") != "success":
            sys.exit(f"ollama pull failed: {result}")
        print(f"\nverified: Ollama at {args.verify_ollama} pulled hf.co/{gguf_id}")


if __name__ == "__main__":
    main()
