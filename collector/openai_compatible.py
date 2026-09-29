from __future__ import annotations

from .base import BaseCollector, api_source

_MODALITY_ALIASES = {"pdf": "file"}
_VALID_MODALITIES = {"text", "image", "audio", "video", "file"}


def number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positive_int(value):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_modalities(values):
    """Map a provider's modality labels onto the project enum.

    'pdf' is treated as 'file' (PDFs are file inputs); anything outside the
    enum is dropped with no guessing.
    """
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


class OpenAICompatibleCollector(BaseCollector):
    """Shared behaviour for the public OpenAI-compatible ``GET /models`` lists.

    Several providers publish the same envelope: a ``data`` array whose items
    carry an OpenAI-style ``id`` plus prices, a context window and a max output
    length. Subclasses declare the endpoint and either map the price keys
    declaratively or override :meth:`prices` when the shape is bespoke.

    Two rules are enforced here rather than per collector:

    * A price is only read from a **token** key. Providers also bill per image,
      per second of audio, per character and per request; those are not token
      prices and are never converted into one (the same rule
      ``collector/docs.py`` applies to Markdown price tables).
    * Anything the payload does not state is left out entirely, so
      ``deep_merge`` keeps whatever was verified by hand.
    """

    creates_models = False
    context_window_key: str | None = None
    max_output_key: str | None = None
    input_price_key: str | None = None
    output_price_key: str | None = None
    cached_input_price_key: str | None = None
    cached_write_price_key: str | None = None
    # True when the provider already quotes per-million decimals.
    prices_are_per_million = False
    modality_keys: tuple[str, str] | None = None
    source_notes: str = "Model ids, context window and prices from the public model list."

    def item_scope(self, item) -> dict:
        """The mapping the context and modality keys are read from.

        Most providers put them at the top level of the item; DeepInfra nests
        them under ``metadata``.
        """
        return item

    def price_scope(self, item) -> dict:
        """The mapping the price keys are read from (some nest them)."""
        pricing = self.item_scope(item).get("pricing")
        return pricing if isinstance(pricing, dict) else {}

    def prices(self, item) -> dict:
        pricing = self.price_scope(item)
        scale = 1.0 if self.prices_are_per_million else 1_000_000
        out: dict = {}
        for key, source_key in (
            ("input", self.input_price_key),
            ("output", self.output_price_key),
            ("cached_input", self.cached_input_price_key),
            ("cached_write", self.cached_write_price_key),
        ):
            if not source_key:
                continue
            value = number(pricing.get(source_key))
            if value is not None and value >= 0:
                out[key] = round(value * scale, 6)
        return out

    def normalize(self, payload) -> dict:
        source = [api_source(self.api_url, self.source_notes)]
        provider_models = {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            fields = self.item_scope(item)
            patch: dict = {"model_id": model_id, "sources": source}

            prices = self.prices(item)
            if "input" in prices or "output" in prices:
                patch["pricing"] = {"currency": "USD", "unit": "1M_tokens", **prices}

            context = {}
            if self.context_window_key:
                window = positive_int(fields.get(self.context_window_key))
                if window:
                    context["window"] = window
            if self.max_output_key:
                max_output = positive_int(fields.get(self.max_output_key))
                if max_output:
                    context["max_output_tokens"] = max_output
            if context:
                patch["context"] = context

            if self.modality_keys:
                input_key, output_key = self.modality_keys
                mod_in = normalize_modalities(fields.get(input_key))
                mod_out = normalize_modalities(fields.get(output_key))
                if mod_in and mod_out:
                    patch["modalities"] = {"input": mod_in, "output": mod_out}

            provider_models[model_id] = patch
        return {"provider_models": provider_models}
