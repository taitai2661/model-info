#!/usr/bin/env python3
"""Scaffold source data by hand (the only way data is added now).

There are no collectors any more: every model, provider and relationship in
`data/` is written by a person. This script removes the tedium — it writes a
correctly shaped, schema-valid stub in the right place, refuses to clobber an
existing document, and points you at the fields you still have to fill in from
a citable source.

Usage:
    python scripts/new.py provider  openai --name OpenAI --type model_provider --type api_provider \
        --website https://openai.com --base-url https://api.openai.com/v1 \
        --api-style openai_compatible --auth bearer --source https://platform.openai.com/docs
    python scripts/new.py model my-model --name "My Model" --provider acme \
        --context 200000 --modalities text,image --source https://acme.example/models/my-model
    python scripts/new.py relationship my-model --entry acme:my-model-2026 --source https://acme.example/docs
    python scripts/new.py list

Then run `python scripts/validate.py` and `python scripts/build.py`.
`new.py` runs validation for you and reports what is still missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

PROVIDER_TYPES = ("model_provider", "api_provider", "aggregator", "gateway", "runtime", "platform")
STATUSES = ("active", "preview", "experimental", "deprecated", "retired", "unknown")
API_STYLES = ("openai_compatible", "anthropic", "google_generative_ai", "custom")
AUTH_TYPES = ("bearer", "api_key", "oauth", "none", "custom")
SOURCE_TYPES = ("official", "documentation", "community", "manual")


def today() -> str:
    return date.today().isoformat()


def data_dir(root: Path, kind: str) -> Path:
    return root / "data" / kind


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite {path} (use --force to replace it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_source(url: str | None, source_type: str) -> list | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        raise SystemExit(f"--source must be an http(s) URL, got {url!r}")
    return [{"type": source_type, "url": url, "retrieved_at": today()}]


def check_provider_exists(root: Path, provider_id: str) -> None:
    if not (data_dir(root, "providers") / f"{provider_id}.json").is_file():
        raise SystemExit(
            f"provider {provider_id!r} is not registered yet — "
            f"create data/providers/{provider_id}.json first "
            f"(python scripts/new.py provider {provider_id} ...)"
        )


def cmd_provider(root: Path, args) -> int:
    if not PROVIDER_ID_RE.match(args.provider_id):
        raise SystemExit(
            f"invalid provider id {args.provider_id!r}: use lowercase letters, digits, _ and -"
        )
    doc: dict = {
        "id": args.provider_id,
        "name": args.name,
        "types": args.type,
        "status": args.status,
    }
    if args.website:
        doc["website"] = args.website
    if args.docs:
        doc["documentation_url"] = args.docs

    api: dict = {}
    if args.base_url:
        api["base_url"] = args.base_url
    if args.protocol:
        api["protocol"] = args.protocol
    if args.api_style:
        api["api_style"] = args.api_style
    if args.auth:
        api["authentication"] = {"type": args.auth}
    if api:
        doc["api"] = api

    doc["updated_at"] = today()
    sources = make_source(args.source, args.source_type)
    if sources:
        doc["sources"] = sources

    path = data_dir(root, "providers") / f"{args.provider_id}.json"
    write_json(path, doc, args.force)
    print(f"created {path.relative_to(root)}")
    return 0


def cmd_model(root: Path, args) -> int:
    if not MODEL_ID_RE.match(args.model_id):
        raise SystemExit(
            f"invalid model id {args.model_id!r}: start with a letter/digit, then letters, "
            f"digits, '.', '_' or '-'"
        )
    check_provider_exists(root, args.provider)
    name = args.name or args.model_id
    doc: dict = {
        "model_id": args.model_id,
        "name": name,
        "model_provider": args.provider,
        "status": args.status,
    }
    if args.release_date:
        doc["release_date"] = args.release_date
    if args.context is not None:
        doc["context"] = {"window": args.context}
    if args.max_output is not None:
        doc.setdefault("context", {})["max_output_tokens"] = args.max_output
    if args.modalities:
        doc["modalities"] = {"input": _split(args.modalities), "output": [args.output or "text"]}
    doc["updated_at"] = today()
    sources = make_source(args.source, args.source_type)
    if sources:
        doc["sources"] = sources

    path = data_dir(root, "models") / f"{args.model_id}.json"
    write_json(path, doc, args.force)
    print(f"created {path.relative_to(root)}")
    if not args.source:
        print("  note: add a `sources` entry — every fact must cite a page")
    return 0


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def cmd_relationship(root: Path, args) -> int:
    model_path = data_dir(root, "models") / f"{args.model_id}.json"
    if not model_path.is_file():
        raise SystemExit(f"model {args.model_id!r} is not registered — create {model_path} first")

    entries = []
    for raw in args.entry:
        provider_id, _, provider_model_id = raw.partition(":")
        provider_id = provider_id.strip()
        provider_model_id = provider_model_id.strip() or args.model_id
        check_provider_exists(root, provider_id)
        entries.append({"provider_id": provider_id, "model_id": provider_model_id})

    path = data_dir(root, "relationships") / f"{args.model_id}.json"
    if path.exists() and not args.force:
        doc = load_json(path)
        existing = {(e["provider_id"], e["model_id"]) for e in doc.get("providers", [])}
        added = [e for e in entries if (e["provider_id"], e["model_id"]) not in existing]
        if not added:
            print(f"{path.relative_to(root)} already lists every requested provider")
            return 0
        doc["providers"].extend(added)
        doc["updated_at"] = today()
        write_json(path, doc, True)
        print(f"updated {path.relative_to(root)} (+{len(added)} entr{'y' if len(added) == 1 else 'ies'})")
    else:
        doc = {"model_id": args.model_id, "updated_at": today(), "providers": entries}
        sources = make_source(args.source, args.source_type)
        if sources:
            for entry in doc["providers"]:
                entry["sources"] = sources
        write_json(path, doc, args.force)
        print(f"created {path.relative_to(root)}")
    return 0


def cmd_list(root: Path, args) -> int:
    providers = sorted(data_dir(root, "providers").glob("*.json"))
    models = sorted(data_dir(root, "models").glob("*.json"))
    print(f"providers ({len(providers)}):")
    for path in providers:
        doc = load_json(path)
        print(f"  {path.stem:24s} {doc.get('name', '')}  [{', '.join(doc.get('types', []))}]")
    print(f"\nmodels ({len(models)}):")
    for path in models:
        doc = load_json(path)
        print(f"  {path.stem:32s} {doc.get('name', '')}  ({doc.get('model_provider', '?')})")
    return 0


def run_validation(root: Path) -> None:
    try:
        from validate import validate_all
    except Exception as exc:  # noqa: BLE001
        print(f"  (skipped validation: {exc})")
        return
    errors, warnings = validate_all(root)
    for warning in warnings[:5]:
        print(f"  warning: {warning}")
    if len(warnings) > 5:
        print(f"  ... and {len(warnings) - 5} more warning(s)")
    if errors:
        print(f"  validation: {len(errors)} error(s)")
        for error in errors[:10]:
            print(f"    - {error}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
    else:
        print("  validation: OK")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/new.py",
        description="Scaffold a model, provider or relationship document in data/.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("provider", help="create data/providers/{id}.json")
    p.add_argument("provider_id")
    p.add_argument("--name", required=True)
    p.add_argument("--type", action="append", required=True, choices=PROVIDER_TYPES,
                   help="role; repeat for several (model_provider, api_provider, ...)")
    p.add_argument("--status", default="active", choices=STATUSES)
    p.add_argument("--website")
    p.add_argument("--docs", help="documentation URL")
    p.add_argument("--base-url", help="API root, e.g. https://api.example.com/v1")
    p.add_argument("--protocol", choices=("https", "http"))
    p.add_argument("--api-style", choices=API_STYLES)
    p.add_argument("--auth", choices=AUTH_TYPES)
    p.add_argument("--source", help="citable page that proves these facts")
    p.add_argument("--source-type", default="official", choices=SOURCE_TYPES)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_provider)

    m = sub.add_parser("model", help="create data/models/{id}.json")
    m.add_argument("model_id")
    m.add_argument("--name")
    m.add_argument("--provider", required=True, help="model_provider id (must already exist)")
    m.add_argument("--status", default="active", choices=STATUSES)
    m.add_argument("--release-date")
    m.add_argument("--context", type=int, help="context window in tokens")
    m.add_argument("--max-output", type=int, help="max output tokens")
    m.add_argument("--modalities", help="comma-separated input modalities, e.g. text,image")
    m.add_argument("--output", help="output modality (default: text)")
    m.add_argument("--source", help="citable page that proves these facts")
    m.add_argument("--source-type", default="official", choices=SOURCE_TYPES)
    m.add_argument("--force", action="store_true")
    m.set_defaults(func=cmd_model)

    r = sub.add_parser("relationship", help="create or extend data/relationships/{model_id}.json")
    r.add_argument("model_id")
    r.add_argument("--entry", action="append", required=True,
                   help="provider[:provider_model_id]; repeat for each provider "
                        "(provider_model_id defaults to the model id)")
    r.add_argument("--source", help="citable page for the new entries")
    r.add_argument("--source-type", default="official", choices=SOURCE_TYPES)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_relationship)

    lst = sub.add_parser("list", help="list registered providers and models")
    lst.set_defaults(func=cmd_list)

    parser.add_argument("--root", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root) if getattr(args, "root", None) else REPO_ROOT
    status = args.func(root, args)
    if args.command != "list":
        run_validation(root)
        print("next: python scripts/build.py   then commit data/ and v1/")
    return status


if __name__ == "__main__":
    sys.exit(main())
