from __future__ import annotations

from .base import BaseCollector, api_source, normalize_effort_levels


def _per_million(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


_MODALITY_ALIASES = {"pdf": "file"}
_VALID_MODALITIES = {"text", "image", "audio", "video", "file"}


def _normalize_modalities(values):
    """Map Vercel's modality labels onto the project enum.

    'pdf' is treated as 'file' (PDFs are file inputs); anything outside the
    enum is dropped with no guessing.
    """
    if not values:
        return None
    out = []
    for value in values:
        if not isinstance(value, str):
            continue
        canonical = _MODALITY_ALIASES.get(value.lower(), value.lower())
        if canonical in _VALID_MODALITIES and canonical not in out:
            out.append(canonical)
    return out or None


def _normalize_reasoning_options(options):
    if not isinstance(options, list):
        return None
    effort = next(
        (item for item in options
         if isinstance(item, dict) and item.get("type") == "effort"),
        None,
    )
    values = effort.get("values") if effort else None
    if not isinstance(values, list) or not values or not all(
        isinstance(item, str) for item in values
    ):
        return None
    return {
        "parameter": "reasoning.effort",
        "effort_levels": normalize_effort_levels(values),
        # The public catalogue does not publish a default effort.
        "default_effort": None,
        "supports_none": "none" in values,
    }


class VercelAIGatewayCollector(BaseCollector):
    name = "vercel-ai-gateway"
    provider_id = "vercel-ai-gateway"
    base_url = "https://ai-gateway.vercel.sh/v1"
    api_url = "https://ai-gateway.vercel.sh/v1/models"
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Provider model ids, context window, modalities, capabilities and prices from the Vercel AI Gateway public model list (GET /v1/models). Pricing values are converted from per-token to per-million.",
        )]
        provider_models = {}
        for item in payload.get("data", []):
            api_model_id = item.get("id")
            if not api_model_id:
                continue
            patch = {"model_id": api_model_id, "sources": source}

            pricing_obj = item.get("pricing") or {}
            input_price = _per_million(pricing_obj.get("input"))
            output_price = _per_million(pricing_obj.get("output"))
            cached_price = _per_million(pricing_obj.get("input_cache_read"))
            if input_price is not None or output_price is not None:
                entry = {"currency": "USD", "unit": "1M_tokens",
                         "input": input_price, "output": output_price}
                if cached_price is not None:
                    entry["cached_input"] = cached_price
                patch["pricing"] = entry

            context = {}
            if item.get("context_window"):
                context["window"] = int(item["context_window"])
            if item.get("max_tokens"):
                context["max_output_tokens"] = int(item["max_tokens"])
            if context:
                patch["context"] = context

            modalities = item.get("modalities") or {}
            mod_in = _normalize_modalities(modalities.get("input"))
            mod_out = _normalize_modalities(modalities.get("output"))
            if mod_in and mod_out:
                patch["modalities"] = {"input": mod_in, "output": mod_out}

            reasoning = _normalize_reasoning_options(item.get("reasoning_options"))
            if reasoning:
                patch["reasoning"] = reasoning

            provider_models[api_model_id] = patch
        return {"provider_models": provider_models}
