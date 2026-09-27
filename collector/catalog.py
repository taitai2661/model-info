"""Bulk import of models that only exist in an aggregator's public catalogue.

The other collectors each own one provider and only ever touch that provider's
own relationship entries. This one is different: it reads the two large public
aggregator catalogues (Vercel AI Gateway and OpenRouter), and for every model
that is **not registered yet** it writes a model document plus the relationship
entries that expose it through those two providers.

Three rules keep this from turning the registry into a mirror of an upstream
JSON blob:

1. **New models only.** A model that already has a document is left completely
   alone — its specs stay hand-verified and its existing provider entries stay
   with the collector that owns them. Only the relationship entries of the two
   catalogues this collector owns are written.
2. **No guessed vendors.** ``vendors.json`` maps a catalogue vendor key onto a
   registered ``model_provider``. A vendor that is not in that file is reported
   as *needs manual review* and nothing is written, so the mapping is always a
   deliberate human decision rather than a prefix heuristic.
3. **No invented facts.** ``model_id`` comes from the catalogue suffix and
   ``name`` from the catalogue name (Vercel's carries no vendor prefix, so it
   wins). ``family`` and ``version`` stay unset because nothing in the payload
   states them. Prices are provider facts and therefore only ever land on the
   relationship entry, never on the model document.

Vercel is preferred over OpenRouter wherever both report a field: its
``owned_by`` is the vendor's own identifier, its ``name`` is the clean product
name rather than ``"Vendor: Model"``, and it carries a real ``released``
timestamp. OpenRouter fills in what Vercel does not, and contributes
``hugging_face_id`` (open weights) and ``expiration_date`` (deprecation).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .base import (
    VARIANT_RE,
    BaseCollector,
    CollectorError,
    load_schema,
    save_json,
    today,
)

VERCEL_URL = "https://ai-gateway.vercel.sh/v1/models"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
VENDOR_MAP = Path(__file__).resolve().parent / "vendors.json"

# A model id is a file name and a URL path segment; anything the catalogues
# publish that does not fit the schema pattern is reported, not coerced.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# OpenRouter labels its names "Vendor: Model"; the vendor is already recorded
# in `model_provider`, so the prefix is dropped mechanically.
NAME_PREFIX_RE = re.compile(r"^[^:]{1,32}:\s+")

_MODALITY_ALIASES = {"pdf": "file"}
_VALID_MODALITIES = {"text", "image", "audio", "video", "file"}

# Catalogue capability labels -> the project's `capabilities` enum. Labels with
# no counterpart (caching, web search, region availability) are dropped rather
# than forced into an unrelated field.
_TAG_CAPABILITIES = {
    "tool-use": "tool_use",
    "reasoning": "reasoning",
    "vision": "vision",
    "structured-output": "structured_output",
    "json-mode": "json_mode",
}
_PARAMETER_CAPABILITIES = {
    "tools": "tool_use",
    "tool_choice": "tool_use",
    "structured_outputs": "structured_output",
    "response_format": "json_mode",
    "reasoning": "reasoning",
    "include_reasoning": "reasoning",
}


def _per_million(value):
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    # Aggregators use a negative sentinel for "not priced" / "route dynamically".
    if price < 0:
        return None
    return round(price * 1_000_000, 6)


def _unix_to_date(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _modality_list(values):
    if not values:
        return None
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        canonical = _MODALITY_ALIASES.get(value.lower(), value.lower())
        if canonical in _VALID_MODALITIES and canonical not in out:
            out.append(canonical)
    return out or None


def _modalities(inputs, outputs):
    ins = _modality_list(inputs)
    outs = _modality_list(outputs)
    return {"input": ins, "output": outs} if ins and outs else None


def _context(window, max_output):
    """Keep only real context sizes.

    The catalogues report ``0`` for models that have no token budget at all
    (image, video and embedding models). That is "not applicable", not a window
    of zero tokens, so the key is dropped rather than recorded as 0.
    """
    out: dict[str, int] = {}
    for key, value in (("window", window), ("max_output_tokens", max_output)):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            out[key] = value
    return out or None


def _pricing(pricing_obj):
    if not isinstance(pricing_obj, dict):
        return None
    input_price = _per_million(pricing_obj.get("input") or pricing_obj.get("prompt"))
    output_price = _per_million(pricing_obj.get("output") or pricing_obj.get("completion"))
    if input_price is None and output_price is None:
        return None
    entry = {"currency": "USD", "unit": "1M_tokens", "input": input_price,
             "output": output_price}
    cached = _per_million(pricing_obj.get("input_cache_read"))
    if cached is not None:
        entry["cached_input"] = cached
    return entry


def _capabilities(tags, parameters):
    """Only the capabilities the catalogue actually states; no defaults."""
    out: dict[str, bool] = {}
    for label in list(tags or []) + list(parameters or []):
        key = (_TAG_CAPABILITIES.get(str(label).lower())
               or _PARAMETER_CAPABILITIES.get(str(label).lower()))
        if key:
            out[key] = True
    return out or None


def _prune(patch: dict) -> dict:
    """Drop unknown facts so they stay absent rather than becoming null."""
    return {k: v for k, v in patch.items() if v is not None}


class CatalogCollector(BaseCollector):
    """Imports not-yet-registered models from the Vercel and OpenRouter lists."""

    name = "catalog"
    provider_id = "openrouter"
    base_url = "https://ai-gateway.vercel.sh/v1"
    api_url = f"{VERCEL_URL}, {OPENROUTER_URL}"
    env_var = None
    creates_models = True

    def __init__(self):
        self.vendors = json.loads(VENDOR_MAP.read_text(encoding="utf-8"))
        self.ignored_vendors = self.vendors.get("ignored", {})
        self.aliases = self.vendors.get("aliases", {})
        self.new_providers = self.vendors.get("providers", {})
        self._records: dict[str, dict] = {}

    # -- catalogue reading --------------------------------------------------

    def _fetch(self, url: str):
        try:
            response = httpx.get(url, timeout=60, follow_redirects=True,
                                 headers={"User-Agent": "model-info-collector/1.0",
                                          "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise CollectorError(f"catalog: request failed for {url}: {exc}") from exc
        if response.status_code >= 400:
            raise CollectorError(
                f"catalog: HTTP {response.status_code} from {url}: {response.text[:200]}"
            )
        return response.json().get("data", [])

    @staticmethod
    def _vercel_entry(item: dict) -> dict | None:
        api_id = item.get("id")
        if not api_id or "/" not in api_id:
            return None
        vendor, suffix = api_id.split("/", 1)
        modalities = item.get("modalities") or {}
        return {
            "catalog": "vercel-ai-gateway",
            "api_id": api_id,
            "vendor": item.get("owned_by") or vendor,
            "suffix": suffix,
            "name": item.get("name"),
            "description": item.get("description"),
            "released": item.get("released"),
            "open_weights": None,
            "expiration_date": None,
            "context": _context(item.get("context_window"), item.get("max_tokens")),
            "modalities": _modalities(modalities.get("input"), modalities.get("output")),
            "capabilities": _capabilities(item.get("tags"),
                                         item.get("supported_parameters")),
            "pricing": _pricing(item.get("pricing")),
        }

    @staticmethod
    def _openrouter_entry(item: dict) -> dict | None:
        api_id = item.get("id")
        if not api_id or "/" not in api_id:
            return None
        vendor, suffix = api_id.split("/", 1)
        architecture = item.get("architecture") or {}
        top = item.get("top_provider") or {}
        modalities = _modalities(architecture.get("input_modalities"),
                                 architecture.get("output_modalities"))
        if modalities is None and architecture.get("modality"):
            # A few rows only carry the coarse single-value label.
            single = _modality_list([architecture["modality"]])
            if single:
                modalities = {"input": single, "output": ["text"]}
        return {
            "catalog": "openrouter",
            "api_id": api_id,
            "vendor": vendor,
            "suffix": suffix,
            "name": item.get("name"),
            "description": None,  # markdown marketing copy, not a spec
            "released": None,      # `created` is when OpenRouter listed it
            "open_weights": bool(item.get("hugging_face_id")),
            "expiration_date": _unix_to_date(item.get("expiration_date")),
            "context": _context(item.get("context_length"),
                                top.get("max_completion_tokens")),
            "modalities": modalities,
            "capabilities": _capabilities(None, item.get("supported_parameters")),
            "pricing": _pricing(item.get("pricing")),
        }

    def collect_entries(self, root: Path) -> dict:
        """Group every catalogue row by the model id it would be registered as."""
        registered = {p.stem for p in (root / "data" / "providers").glob("*.json")}
        records: dict[str, dict] = {}
        unmapped: set[str] = set()
        bad_id: set[str] = set()
        ignored: set[str] = set()

        for item in self._fetch(OPENROUTER_URL):
            entry = self._openrouter_entry(item)
            if entry is not None:
                self._add(records, entry, root, registered, unmapped, bad_id, ignored)
        for item in self._fetch(VERCEL_URL):
            entry = self._vercel_entry(item)
            if entry is not None:
                self._add(records, entry, root, registered, unmapped, bad_id, ignored)

        self._records = records
        return {"registered": registered, "unmapped": unmapped, "bad_id": bad_id,
                "ignored": ignored}

    def _add(self, records, entry, root, registered, unmapped, bad_id, ignored) -> None:
        vendor = entry["vendor"]
        if vendor in self.ignored_vendors:
            ignored.add(f"{vendor} ({self.ignored_vendors[vendor]})")
            return
        provider_id = self.aliases.get(vendor) or vendor
        if not (provider_id in registered or provider_id in self.new_providers):
            unmapped.add(f"vendor {vendor!r} is not mapped in collector/vendors.json")
            return

        canonical = VARIANT_RE.sub("", entry["suffix"])
        if not MODEL_ID_RE.match(canonical):
            bad_id.add(f"{entry['api_id']} (model id is not schema-compatible)")
            return
        if (root / "data" / "models" / f"{canonical}.json").is_file():
            return  # already registered: the collectors that own it handle it

        records.setdefault(canonical, {
            "model_id": canonical, "provider_id": provider_id, "entries": [],
        })["entries"].append(entry)

    # -- provider documents -------------------------------------------------

    def ensure_providers(self, root: Path, write: bool) -> list[str]:
        """Create a `model_provider` document for each newly needed vendor."""
        created: list[str] = []
        validator = load_schema(root, "provider.schema.json")
        wanted = sorted({r["provider_id"] for r in self._records.values()})
        for provider_id in wanted:
            path = root / "data" / "providers" / f"{provider_id}.json"
            if path.is_file():
                continue
            spec = self.new_providers.get(provider_id)
            if spec is None:
                continue
            source_url = spec.get("website") or spec.get("documentation_url")
            if not source_url:
                raise CollectorError(
                    f"catalog: vendors.json entry for {provider_id!r} has no website "
                    "or documentation_url to cite"
                )
            doc = {
                "id": provider_id,
                "name": spec["name"],
                "types": ["model_provider"],
                "status": "active",
                "description": spec.get("description"),
                "website": spec.get("website"),
                "documentation_url": spec.get("documentation_url"),
                "updated_at": today(),
                "sources": [{
                    "type": "official",
                    "url": source_url,
                    "retrieved_at": today(),
                    "title": f"{spec['name']} official site",
                    "notes": ("Vendor of the models imported from the OpenRouter / Vercel "
                              "AI Gateway catalogues. Only its role as a model developer is "
                              "recorded here; it has no API of its own in Model Info."),
                }],
            }
            doc = _prune(doc)
            errors = [e.message for e in validator.iter_errors(doc)]
            if errors:
                raise CollectorError(
                    f"catalog: vendors.json entry for {provider_id!r} is invalid: "
                    + "; ".join(errors)
                )
            if write:
                save_json(path, doc)
            created.append(provider_id)
        return created

    # -- assembly -----------------------------------------------------------

    def _build_results(self) -> dict:
        sources = {
            "openrouter": {
                "type": "documentation",
                "url": OPENROUTER_URL,
                "retrieved_at": today(),
                "title": "OpenRouter public model list",
                "notes": ("Provider model id, name, context window, modalities, "
                          "capabilities and prices as published by an aggregator rather "
                          "than by the model developer."),
            },
            "vercel-ai-gateway": {
                "type": "documentation",
                "url": VERCEL_URL,
                "retrieved_at": today(),
                "title": "Vercel AI Gateway public model list",
                "notes": ("Provider model id, name, release date, context window, "
                          "modalities, capabilities and prices as published by an "
                          "aggregator rather than by the model developer."),
            },
        }
        models: dict[str, dict] = {}
        relationships: dict[str, list[dict]] = {}

        for canonical, record in sorted(self._records.items()):
            # OpenRouter lists one model under several route ids (base, :free,
            # :batch). All of them are kept, but the plain id decides the specs.
            entries = sorted(record["entries"],
                             key=lambda e: (VARIANT_RE.search(e["api_id"]) is not None,
                                            e["catalog"], e["api_id"]))
            vercel = next((e for e in entries if e["catalog"] == "vercel-ai-gateway"), None)
            openrouter = next((e for e in entries if e["catalog"] == "openrouter"), None)
            primary = vercel or openrouter
            if primary is None:
                continue

            # Model level: context, modalities and capabilities describe the
            # model itself, so they come from the richest catalogue that has them.
            context = primary["context"]
            modalities = primary["modalities"]
            capabilities = primary["capabilities"]

            name = NAME_PREFIX_RE.sub("", primary.get("name") or "").strip() or canonical
            description = primary.get("description")
            if description and len(description) > 4000:
                description = None

            availability = {"api": True}
            if any(e["open_weights"] for e in entries):
                availability["open_weights"] = True

            deprecated = any(e["expiration_date"] for e in entries)
            models[canonical] = _prune({
                "name": name,
                "display_name": name,
                "description": description,
                "context": context,
                "modalities": modalities,
                "capabilities": capabilities,
                "availability": availability,
                "release_date": _unix_to_date(vercel["released"]) if vercel else None,
                "sources": [sources[e["catalog"]] for e in entries],
                "required_fields": {
                    "model_id": canonical,
                    "name": name,
                    "model_provider": record["provider_id"],
                    # Listed in a live provider catalogue; an announced
                    # retirement downgrades it to deprecated.
                    "status": "deprecated" if deprecated else "active",
                },
            })

            # Relationship level: the provider's own model id and price, plus
            # only the specs that actually differ from the model document.
            relationships[canonical] = [
                _prune({
                    "provider_id": e["catalog"],
                    "model_id": e["api_id"],
                    "pricing": e["pricing"],
                    "context": e["context"] if e["context"] != context else None,
                    "modalities": e["modalities"] if e["modalities"] != modalities else None,
                    "sources": [sources[e["catalog"]]],
                })
                for e in entries
            ]

        return {"models": models, "relationships": relationships}

    # -- entry point --------------------------------------------------------

    def run(self, root: Path, write: bool = False) -> dict:
        notes = self.collect_entries(root)
        created_providers = self.ensure_providers(root, write=write)
        report = self.apply(root, self._build_results(), write=write)
        report["providers"] = created_providers
        report["unmatched"].extend(sorted(notes["unmapped"] | notes["bad_id"]))
        report["ignored"] = sorted(notes["ignored"])
        return report
