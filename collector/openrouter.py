from __future__ import annotations

from .base import BaseCollector, api_source, normalize_effort_levels


def _per_million(value):
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    # OpenRouter uses a negative sentinel for dynamically routed or unpriced
    # models; it is not a charge and must not become a negative token price.
    return round(price * 1_000_000, 6) if price >= 0 else None


def _reasoning_config(value):
    if not isinstance(value, dict):
        return None
    supported = value.get("supported_efforts")
    if not isinstance(supported, list) or not supported or not all(
        isinstance(item, str) for item in supported
    ):
        return None
    return {
        "parameter": "reasoning.effort",
        "effort_levels": normalize_effort_levels(supported),
        "default_effort": value.get("default_effort"),
        "supports_none": "none" in supported,
    }


class OpenRouterCollector(BaseCollector):
    name = "openrouter"
    provider_id = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    api_url = "https://openrouter.ai/api/v1/models"
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Provider model id, context window, modalities, prices, and supported reasoning effort values/defaults from the public model list.",
        )]
        provider_models = {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            patch = {"model_id": model_id, "sources": source}
            pricing = item.get("pricing") or {}
            input_price = _per_million(pricing.get("prompt"))
            output_price = _per_million(pricing.get("completion"))
            cached_price = _per_million(pricing.get("input_cache_read"))
            if input_price is not None or output_price is not None:
                entry = {"currency": "USD", "unit": "1M_tokens",
                         "input": input_price, "output": output_price}
                if cached_price is not None:
                    entry["cached_input"] = cached_price
                patch["pricing"] = entry
            context = {}
            if item.get("context_length"):
                context["window"] = int(item["context_length"])
            top = item.get("top_provider") or {}
            if top.get("max_completion_tokens"):
                context["max_output_tokens"] = int(top["max_completion_tokens"])
            if context:
                patch["context"] = context
            reasoning = _reasoning_config(item.get("reasoning"))
            if reasoning:
                patch["reasoning"] = reasoning
            architecture = item.get("architecture") or {}
            input_modalities = architecture.get("input_modalities")
            output_modalities = architecture.get("output_modalities")
            if input_modalities and output_modalities:
                patch["modalities"] = {"input": input_modalities,
                                       "output": output_modalities}
            provider_models[model_id] = patch
        return {"provider_models": provider_models}
