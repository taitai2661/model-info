#!/usr/bin/env python3
"""Validate all Model Info source data (data/) against the JSON Schemas and
additional integrity rules.

Usage:
    python scripts/validate.py [--root PATH]

Exit code 0 = valid, 1 = errors found. Warnings do not fail the run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

SCHEMA_FILES = {
    "model": "schemas/v1/model.schema.json",
    "provider": "schemas/v1/provider.schema.json",
    "relationship": "schemas/v1/model-provider.schema.json",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Patterns that look like real credentials. API keys must never be stored.
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "OpenAI-style secret key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic-style secret key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "Google API key"),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "Groq API key"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "Hugging Face token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer credential"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private key material"),
]

VALID_URL_SCHEMES = ("http", "https")


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{path}: invalid JSON ({exc})"


def _load_schemas(root: Path):
    schemas = {}
    errors = []
    for key, rel in SCHEMA_FILES.items():
        path = root / rel
        if not path.is_file():
            errors.append(f"missing schema file: {rel}")
            continue
        data, err = _load_json(path)
        if err:
            errors.append(err)
            continue
        try:
            Draft202012Validator.check_schema(data)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: schema itself is invalid ({exc})")
            continue
        schemas[key] = (data, Draft202012Validator(data))
    return schemas, errors


def _check_date(value, where, errors):
    if value is None:
        return
    if not isinstance(value, str) or not DATE_RE.match(value):
        errors.append(f"{where}: date must be YYYY-MM-DD, got {value!r}")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where}: {value!r} is not a real calendar date")


def _check_url(value, where, errors):
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"{where}: expected URL string, got {type(value).__name__}")
        return
    parsed = urlparse(value)
    if parsed.scheme not in VALID_URL_SCHEMES:
        errors.append(f"{where}: URL scheme must be http/https, got {value!r}")
    elif not parsed.netloc:
        errors.append(f"{where}: URL is missing a host: {value!r}")
    if parsed.query or parsed.fragment:
        errors.append(f"{where}: URL must not contain a query or fragment: {value!r}")


def _check_base_url(value, where, errors):
    if value is None:
        return
    _check_url(value, where, errors)
    if isinstance(value, str) and "//" in value:
        path = urlparse(value).path
        if " " in path:
            errors.append(f"{where}: base URL must not contain spaces: {value!r}")


def _check_endpoint(value, where, errors):
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"{where}: endpoint must be a string or null")
        return
    if not value.startswith("/"):
        errors.append(f"{where}: endpoint must start with '/': {value!r}")
    if "://" in value:
        errors.append(f"{where}: endpoint must be a path, not a URL: {value!r}")
    if "?" in value or "#" in value:
        errors.append(f"{where}: endpoint must not contain a query or fragment: {value!r}")


def _check_context(context, where, errors):
    """A context size of 0 is never a fact: it means "not applicable" upstream.

    `0` is meaningful for a price (an explicitly free tier) but not for a token
    budget, so unknown sizes must stay null or be omitted.
    """
    if not isinstance(context, dict):
        return
    for key, value in context.items():
        if value == 0:
            errors.append(
                f"{where}.{key}: must be omitted or null when unknown, not 0"
            )


def _check_pricing(pricing, where, errors):
    if pricing is None or not isinstance(pricing, dict):
        return
    values = [pricing.get(k) for k in ("input", "output", "cached_input")]
    has_number = any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
    if has_number:
        if not pricing.get("currency"):
            errors.append(f"{where}: currency is required when a price is set (use null only for unknown prices)")
        if not pricing.get("unit"):
            errors.append(f"{where}: unit is required when a price is set")
    for key in ("input", "output", "cached_input"):
        value = pricing.get(key)
        if isinstance(value, bool) or (value is not None and not isinstance(value, (int, float))):
            errors.append(f"{where}.{key}: price must be a non-negative number or null")


def _iter_sources(doc, where, errors):
    sources = doc.get("sources")
    if sources is None:
        return
    if not isinstance(sources, list):
        errors.append(f"{where}.sources: must be an array")
        return
    for i, s in enumerate(sources):
        _check_url(s.get("url") if isinstance(s, dict) else None, f"{where}.sources[{i}].url", errors)
        _check_date(s.get("retrieved_at") if isinstance(s, dict) else None,
                    f"{where}.sources[{i}].retrieved_at", errors)


def _scan_secrets(path: Path, text: str, errors: list):
    for pattern, label in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            errors.append(f"{path}: possible {label} stored in file ({match.group(0)[:8]}...)")


def validate_model_doc(doc, where, errors):
    _check_date(doc.get("updated_at"), f"{where}.updated_at", errors)
    _check_date(doc.get("release_date"), f"{where}.release_date", errors)
    _check_context(doc.get("context"), where, errors)
    _check_pricing(doc.get("pricing"), f"{where}.pricing", errors)
    for pid, pricing in (doc.get("provider_pricing") or {}).items():
        _check_pricing(pricing, f"{where}.provider_pricing.{pid}", errors)
    _iter_sources(doc, where, errors)


def validate_provider_doc(doc, where, errors):
    _check_date(doc.get("updated_at"), f"{where}.updated_at", errors)
    _check_url(doc.get("website"), f"{where}.website", errors)
    _check_url(doc.get("documentation_url"), f"{where}.documentation_url", errors)
    api = doc.get("api")
    if isinstance(api, dict):
        _check_base_url(api.get("base_url"), f"{where}.api.base_url", errors)
        protocol = api.get("protocol")
        base_url = api.get("base_url")
        if protocol and isinstance(base_url, str) and base_url.startswith(protocol + "://"):
            pass
        elif protocol and isinstance(base_url, str):
            errors.append(
                f"{where}.api: protocol {protocol!r} does not match base_url {base_url!r}"
            )
        endpoints = api.get("endpoints")
        if isinstance(endpoints, dict):
            for key, value in endpoints.items():
                _check_endpoint(value, f"{where}.api.endpoints.{key}", errors)
    _iter_sources(doc, where, errors)


def validate_relationship_doc(doc, where, errors, model_ids, provider_ids):
    _check_date(doc.get("updated_at"), f"{where}.updated_at", errors)
    entries = doc.get("providers") or []
    seen = set()
    for i, entry in enumerate(entries):
        ewhere = f"{where}.providers[{i}]"
        pid = entry.get("provider_id")
        mid = entry.get("model_id")
        key = (pid, mid)
        if key in seen:
            errors.append(f"{where}: duplicate entry for provider_id {pid!r} with model_id {mid!r}")
        seen.add(key)
        _check_date(entry.get("updated_at"), f"{ewhere}.updated_at", errors)
        _check_context(entry.get("context"), ewhere, errors)
        _check_pricing(entry.get("pricing"), f"{ewhere}.pricing", errors)
        _iter_sources(entry, ewhere, errors)


def validate_all(root: Path):
    errors: list[str] = []
    warnings: list[str] = []

    schemas, schema_errors = _load_schemas(root)
    errors.extend(schema_errors)
    if len(schemas) != len(SCHEMA_FILES):
        return errors, warnings

    model_validator = schemas["model"][1]
    provider_validator = schemas["provider"][1]
    rel_validator = schemas["relationship"][1]

    models: dict[str, dict] = {}
    providers: dict[str, dict] = {}
    relationships: dict[str, dict] = {}

    def load_dir(kind, directory, validator, id_field, store):
        base = root / "data" / directory
        if not base.is_dir():
            errors.append(f"missing data directory: data/{directory}")
            return
        for path in sorted(base.glob("*.json")):
            text = path.read_text(encoding="utf-8")
            _scan_secrets(path.relative_to(root), text, errors)
            doc, err = _load_json(path)
            if err:
                errors.append(err)
                continue
            for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
                location = "/".join(str(p) for p in e.path) or "<root>"
                errors.append(f"{path.relative_to(root)}: {location}: {e.message}")
            ident = doc.get(id_field)
            if ident != path.stem:
                errors.append(
                    f"{path.relative_to(root)}: {id_field} {ident!r} does not match file name {path.stem!r}"
                )
            if ident in store:
                errors.append(f"duplicate {id_field}: {ident!r}")
            store[ident] = doc

    load_dir("model", "models", model_validator, "model_id", models)
    load_dir("provider", "providers", provider_validator, "id", providers)
    load_dir("relationship", "relationships", rel_validator, "model_id", relationships)

    # per-document semantic checks
    for mid, doc in models.items():
        validate_model_doc(doc, f"data/models/{mid}.json", errors)
        mp = doc.get("model_provider")
        if mp not in providers:
            errors.append(f"data/models/{mid}.json: model_provider {mp!r} is not a registered provider")
    for pid, doc in providers.items():
        validate_provider_doc(doc, f"data/providers/{pid}.json", errors)
    for mid, doc in relationships.items():
        where = f"data/relationships/{mid}.json"
        if mid not in models:
            errors.append(f"{where}: model_id {mid!r} is not a registered model")
        validate_relationship_doc(doc, where, errors, models, providers)
        for i, entry in enumerate(doc.get("providers") or []):
            pid = entry.get("provider_id")
            if pid not in providers:
                errors.append(f"{where}.providers[{i}]: provider_id {pid!r} is not a registered provider")
            # cross-check model-level provider_pricing with relationship pricing
            model = models.get(mid, {})
            alt = (model.get("provider_pricing") or {}).get(pid)
            if alt is not None and entry.get("pricing") is not None and alt != entry.get("pricing"):
                errors.append(
                    f"{where}.providers[{i}]: pricing disagrees with model.provider_pricing.{pid}"
                )

    # coverage warnings
    for mid in models:
        if mid not in relationships:
            warnings.append(f"model {mid!r} has no relationship file (no known API provider)")
    serving_types = {"api_provider", "aggregator", "gateway"}
    for pid, doc in providers.items():
        used = any(
            pid in {e.get("provider_id") for e in (r.get("providers") or [])}
            for r in relationships.values()
        )
        if not used and serving_types & set(doc.get("types") or []):
            warnings.append(f"provider {pid!r} does not serve any model yet")
        if "model_provider" in (doc.get("types") or []) and not any(
            m.get("model_provider") == pid for m in models.values()
        ):
            warnings.append(f"provider {pid!r} is a model_provider but owns no model")

    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate Model Info data files")
    parser.add_argument("--root", default=None, help="repository root (default: auto-detect)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent

    errors, warnings = validate_all(root)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    n_models = len(list((root / "data" / "models").glob("*.json")))
    n_providers = len(list((root / "data" / "providers").glob("*.json")))
    n_rels = len(list((root / "data" / "relationships").glob("*.json")))
    print(
        f"checked {n_models} models, {n_providers} providers, {n_rels} relationships "
        f"-> {len(errors)} error(s), {len(warnings)} warning(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
