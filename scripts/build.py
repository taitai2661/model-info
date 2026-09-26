#!/usr/bin/env python3
"""Build the static JSON API (v1/) from the source data (data/).

Usage:
    python scripts/build.py [--root PATH] [--out DIR]

The build refuses to write anything if validation fails. Output is
deterministic: the same input always produces byte-identical files.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import validate_all  # noqa: E402

def _dump(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _load_dir(base: Path) -> dict:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(base.glob("*.json"))
    }


def _entry_validator(root: Path) -> Draft202012Validator:
    schema = json.loads((root / "schemas/v1/model-provider.schema.json").read_text(encoding="utf-8"))
    entry_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        "$ref": "#/$defs/providerEntry",
    }
    return Draft202012Validator(entry_schema)


def assemble(root: Path) -> dict[str, str]:
    """Return {relative output path: file content} for every static API file."""
    models = _load_dir(root / "data/models")
    providers = _load_dir(root / "data/providers")
    relationships = _load_dir(root / "data/relationships")

    entry_validator = _entry_validator(root)
    outputs: dict[str, str] = {}
    problems: list[str] = []

    def emit(path: str, doc):
        content = _dump(doc)
        outputs[path] = content
        outputs[str(Path(path).parent / Path(path).stem / "index.json")] = content

    # GET /v1/models  -> models.json
    model_list = [models[mid] for mid in sorted(models)]
    emit("models.json", model_list)

    # GET /v1/models/{model_id}  (+ relationship/provider details)
    for mid in sorted(models):
        rel = relationships.get(mid, {"model_id": mid, "providers": []})
        entries = []
        for entry in rel["providers"]:
            for e in entry_validator.iter_errors({**entry}):
                problems.append(f"{mid}/{entry.get('provider_id')}: {e.message}")
            provider = providers.get(entry["provider_id"])
            if provider is None:
                problems.append(f"{mid}: unknown provider {entry['provider_id']!r}")
                continue
            entries.append({**entry, "provider": provider})
        emit(f"models/{mid}.json", {"model": models[mid], "providers": entries})

    # GET /v1/providers
    emit("providers.json", [providers[pid] for pid in sorted(providers)])

    # GET /v1/providers/{provider_id}
    # GET /v1/providers/{provider_id}/models
    for pid in sorted(providers):
        served = []
        for mid in sorted(models):
            rel = relationships.get(mid, {})
            for entry in rel.get("providers", []):
                if entry.get("provider_id") == pid:
                    for e in entry_validator.iter_errors(entry):
                        problems.append(f"{mid}/{pid}: {e.message}")
                    served.append({"model": models[mid], "relationship": entry})
        emit(f"providers/{pid}.json",
             {"provider": providers[pid], "model_ids": [s["model"]["model_id"] for s in served]})
        emit(f"providers/{pid}/models.json", served)

    if problems:
        raise SystemExit("assembly failed:\n" + "\n".join("  " + p for p in problems))
    return outputs


def write_outputs(out_root: Path, outputs: dict[str, str]):
    if out_root.exists():
        shutil.rmtree(out_root)
    for rel, content in sorted(outputs.items()):
        path = out_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the static Model Info API")
    parser.add_argument("--root", default=None, help="repository root (default: auto-detect)")
    parser.add_argument("--out", default=None, help="output directory (default: <root>/v1)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root / "v1"

    errors, warnings = validate_all(root)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"error: {e}")
        print("build aborted: validation failed")
        return 1

    outputs = assemble(root)
    write_outputs(out, outputs)
    n_models = len(list((root / "data/models").glob("*.json")))
    n_providers = len(list((root / "data/providers").glob("*.json")))
    print(f"built {len(outputs)} files under {out} ({n_models} models, {n_providers} providers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
