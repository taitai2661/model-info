"""Base class and helpers shared by the per-provider collectors.

Collectors are run manually by an administrator (`python -m collector <name>`).
They never commit, never store credentials, and never invent facts: anything
that cannot be read from the upstream API is left unset, so a merge keeps the
existing (hand-verified) value.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_RE = re.compile(r"^\d{4}-?\d{2}-?\d{2}$")
# Fireworks escapes a decimal point as "p" in model ids (glm-5p3 -> glm-5.3).
DECIMAL_P_RE = re.compile(r"(?<=\d)p(?=\d)")


class CollectorError(Exception):
    pass


def normalize_model_key(value: str) -> str:
    """Case- and separator-insensitive form used to compare model ids."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def id_candidates(api_model_id: str) -> list[str]:
    """Deterministic spellings of a provider model id, most specific first.

    Providers differ only in well-known, mechanical ways: a vendor prefix
    (``Qwen/Qwen3.7-Max``), letter case (``Kimi-K3`` -> ``kimi-k3``) or
    Fireworks' ``p`` decimal escape (``glm-5p3`` -> ``glm-5.3``). Anything that
    still does not match a registered model is reported for manual review —
    nothing here may invent a mapping.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            out.append(value)

    add(api_model_id)
    for depth in range(1, api_model_id.count("/") + 1):
        add("/".join(api_model_id.split("/")[depth:]))
    for candidate in list(out):
        add(DECIMAL_P_RE.sub(".", candidate))
    for candidate in list(out):
        add(candidate.lower())
    return out


def today() -> str:
    return date.today().isoformat()


def load_schema(root: Path, name: str) -> Draft202012Validator:
    schema = json.loads((root / "schemas" / "v1" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def load_json(path: Path):
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_sources(existing: list, incoming: list) -> list:
    merged = [s for s in (existing or []) if isinstance(s, dict)]
    by_url = {s.get("url"): i for i, s in enumerate(merged)}
    for s in incoming:
        url = s.get("url")
        if url in by_url:
            merged[by_url[url]] = s
        else:
            merged.append(s)
    return merged


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            continue
        out[key] = value
    return out


def api_source(url: str, notes: str | None = None) -> dict:
    source = {"type": "official", "url": url, "retrieved_at": today()}
    if notes:
        source["notes"] = notes
    return source


class BaseCollector:
    name: str = ""
    provider_id: str = ""
    base_url: str = ""
    api_url: str = ""
    env_var: str | None = None
    auth_header: str | None = None
    creates_models: bool = True

    def auth_headers(self) -> dict:
        headers = {"User-Agent": "model-info-collector/1.0", "Accept": "application/json"}
        if self.env_var:
            key = os.environ.get(self.env_var)
            if not key:
                raise CollectorError(
                    f"{self.name}: set {self.env_var} in the environment (never hardcode keys)"
                )
            if self.auth_header and self.auth_header.lower() != "authorization":
                headers[self.auth_header] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def fetch(self):
        try:
            response = httpx.get(self.api_url, headers=self.auth_headers(), timeout=30,
                                 follow_redirects=True)
        except httpx.HTTPError as exc:
            raise CollectorError(f"{self.name}: request failed: {exc}") from exc
        if response.status_code >= 400:
            raise CollectorError(
                f"{self.name}: HTTP {response.status_code} from {self.api_url}: "
                f"{response.text[:200]}"
            )
        return response.json()

    def normalize(self, payload) -> dict:
        raise NotImplementedError

    # -- matching -----------------------------------------------------------

    def resolve_model(self, root: Path, api_model_id: str):
        """Map a provider model id onto a registered model.

        Returns ``(model_doc, canonical_id)`` or ``(None, None)``. Lookup order:
        exact file name, vendor-prefix / case / decimal-escape variants, the
        existing snapshot-suffix rule, then the model's own ``version`` field.
        """
        candidates = id_candidates(api_model_id)
        for candidate in candidates:
            doc = load_json(root / "data" / "models" / f"{candidate}.json")
            if doc:
                return doc, doc.get("model_id", candidate)

        docs = [load_json(p) for p in sorted((root / "data" / "models").glob("*.json"))]
        for doc in docs:
            if not doc:
                continue
            canonical = doc.get("model_id", "")
            for candidate in candidates:
                if candidate.startswith(canonical + "-") and SNAPSHOT_RE.match(
                    candidate[len(canonical) + 1:]
                ):
                    return doc, canonical

        wanted = {normalize_model_key(c) for c in candidates}
        for doc in docs:
            if not doc:
                continue
            version = normalize_model_key(doc.get("version") or "")
            if version and version in wanted:
                return doc, doc.get("model_id", "")
        return None, None

    def find_relationship(self, root: Path, provider_model_id: str):
        for path in sorted((root / "data" / "relationships").glob("*.json")):
            doc = load_json(path)
            if not doc:
                continue
            for entry in doc.get("providers", []):
                if entry.get("provider_id") == self.provider_id and entry.get("model_id") == provider_model_id:
                    return path, doc
        return None, None

    # -- writing ------------------------------------------------------------

    def apply(self, root: Path, results: dict, write: bool = False) -> dict:
        report = {"created": [], "updated": [], "relationships": [], "aliases": [],
                  "unmatched": [], "unchanged": [], "invalid": []}
        model_validator = load_schema(root, "model.schema.json")
        rel_validator = load_schema(root, "model-provider.schema.json")

        resolved: set[str] = set()
        for api_id, raw_patch in sorted(results.get("models", {}).items()):
            patch = {k: v for k, v in raw_patch.items() if k != "required_fields"}
            doc, canonical = self.resolve_model(root, api_id)
            if doc is not None and canonical != api_id:
                report["aliases"].append(api_id)
                continue
            if doc is None:
                if not self.creates_models or "required_fields" not in raw_patch:
                    report["unmatched"].append(api_id)
                    continue
                path = root / "data" / "models" / f"{api_id}.json"
                doc = {**raw_patch["required_fields"], **patch}
                doc["updated_at"] = today()
                doc["sources"] = merge_sources([], patch.get("sources", []))
                errors = [e.message for e in model_validator.iter_errors(doc)]
                if errors:
                    report["invalid"].append((api_id, errors))
                    continue
                if write:
                    save_json(path, doc)
                report["created"].append(api_id)
                resolved.add(api_id)
                continue
            resolved.add(canonical)
            before = json.dumps(doc, sort_keys=True)
            merged = deep_merge(doc, patch)
            merged["updated_at"] = today()
            if patch.get("sources"):
                merged["sources"] = merge_sources(doc.get("sources", []), patch["sources"])
            errors = [e.message for e in model_validator.iter_errors(merged)]
            if errors:
                report["invalid"].append((api_id, errors))
                continue
            if json.dumps(merged, sort_keys=True) == before:
                report["unchanged"].append(api_id)
                continue
            if write:
                save_json(root / "data" / "models" / f"{canonical}.json", merged)
            report["updated"].append(api_id)

        for key, entries in sorted(results.get("relationships", {}).items()):
            if key in resolved:
                canonical = key
            else:
                _, canonical = self.resolve_model(root, key)
                if canonical is None:
                    report["unmatched"].append(f"{key} (no matching model)")
                    continue
                if canonical != key:
                    report["aliases"].append(key)
                    continue
            rel_path = root / "data" / "relationships" / f"{canonical}.json"
            rel = load_json(rel_path)
            fresh = rel is None
            if fresh:
                if not self.creates_models:
                    report["unmatched"].append(f"{canonical} (no relationship file)")
                    continue
                rel = {"model_id": canonical, "updated_at": today(), "providers": []}
            changed = fresh
            for patch in entries:
                entry = next(
                    (e for e in rel["providers"]
                     if e["provider_id"] == self.provider_id
                     and e["model_id"] == patch["model_id"]),
                    None,
                )
                if entry is None:
                    entry = {"provider_id": self.provider_id, "model_id": patch["model_id"]}
                    rel["providers"].append(entry)
                    changed = True
                before = json.dumps(entry, sort_keys=True)
                merged = deep_merge(entry, patch)
                if patch.get("sources"):
                    merged["sources"] = merge_sources(entry.get("sources", []), patch["sources"])
                if json.dumps(merged, sort_keys=True) != before:
                    entry.clear()
                    entry.update(merged)
                    changed = True
            if changed:
                rel["updated_at"] = today()
                errors = [e.message for e in rel_validator.iter_errors(rel)]
                if errors:
                    report["invalid"].append((canonical, errors))
                    continue
                if write:
                    save_json(rel_path, rel)
                report["relationships"].append(canonical)
            else:
                report["unchanged"].append(canonical)

        for api_id, patch in sorted(results.get("provider_models", {}).items()):
            rel_path, rel = self.find_relationship(root, api_id)
            created = False
            if rel is None:
                # The provider lists an id we have no entry for yet. Create one
                # only when the id resolves to a model that is already
                # registered; otherwise it stays in `unmatched` for review.
                doc, canonical = self.resolve_model(root, api_id)
                if doc is None:
                    report["unmatched"].append(api_id)
                    continue
                rel_path = root / "data" / "relationships" / f"{canonical}.json"
                rel = load_json(rel_path)
                if rel is None:
                    rel = {"model_id": canonical, "updated_at": today(), "providers": []}
                rel["providers"].append(
                    {"provider_id": self.provider_id, "model_id": api_id}
                )
                created = True
            canonical = rel["model_id"]
            model_doc = load_json(root / "data" / "models" / f"{canonical}.json") or {}
            index = next(
                i for i, e in enumerate(rel["providers"])
                if e["provider_id"] == self.provider_id and e["model_id"] == api_id
            )
            entry = rel["providers"][index]
            pruned = {}
            for key, value in patch.items():
                if key == "sources" or value is None:
                    continue
                base_value = model_doc.get(key)
                if isinstance(value, dict) and isinstance(base_value, dict):
                    if any(base_value.get(kk) != vv for kk, vv in value.items()):
                        pruned[key] = value
                elif key != "model_id" and base_value != value:
                    pruned[key] = value
            before = json.dumps(entry, sort_keys=True)
            merged = deep_merge(entry, pruned)
            if patch.get("sources"):
                merged["sources"] = merge_sources(entry.get("sources", []), patch["sources"])
            if not created and json.dumps(merged, sort_keys=True) == before:
                report["unchanged"].append(api_id)
                continue
            entry.clear()
            entry.update(merged)
            rel["updated_at"] = today()
            errors = [e.message for e in rel_validator.iter_errors(rel)]
            if errors:
                if created:
                    del rel["providers"][index]
                report["invalid"].append((canonical, errors))
                continue
            if write:
                save_json(rel_path, rel)
            report["relationships"].append(canonical)
        return report


    def run(self, root: Path, write: bool = False) -> dict:
        payload = self.fetch()
        results = self.normalize(payload)
        return self.apply(root, results, write=write)

    @staticmethod
    def print_report(report: dict, write: bool) -> None:
        for key in ("created", "updated", "relationships", "aliases", "unchanged"):
            items = report.get(key) or []
            if items:
                print(f"{key} ({len(items)}): {', '.join(sorted(set(items)))}")
        if report.get("unmatched"):
            print("needs manual review (no matching entry in data/):")
            for item in report["unmatched"][:40]:
                print(f"  - {item}")
            extra = len(report["unmatched"]) - 40
            if extra > 0:
                print(f"  ... and {extra} more")
        if report.get("invalid"):
            print("INVALID results (not written):")
            for name, errors in report["invalid"]:
                print(f"  - {name}: {'; '.join(errors)}")
        if not write:
            print("dry run: nothing written (re-run with --write to apply the changes)")


def discover():
    from . import (anthropic, deepseek, fireworks, google, groq, mistral,
                   opencode, opencode_go, openrouter, openai, together)

    collectors = [openai.OpenAICollector(), anthropic.AnthropicCollector(),
                  google.GoogleCollector(), deepseek.DeepSeekCollector(),
                  mistral.MistralCollector(), openrouter.OpenRouterCollector(),
                  opencode.OpenCodeCollector(), opencode_go.OpenCodeGoCollector(),
                  groq.GroqCollector(), together.TogetherCollector(),
                  fireworks.FireworksCollector()]
    return {c.name: c for c in collectors}
