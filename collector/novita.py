from __future__ import annotations

from .openai_compatible import OpenAICompatibleCollector, number


class NovitaCollector(OpenAICompatibleCollector):
    """Reads Novita AI's public model list (no API key required).

    Prices are only read from the nested ``pricing`` object, whose
    ``price_per_m_decimal`` is the price in dollars per 1M tokens. The flat
    ``input_token_price_per_m`` / ``output_token_price_per_m`` fields that
    mirror the same prices are in units of 1e-4 $/1M (1500 means $0.15), so they
    are ignored rather than rescaled by a guessed factor. A model listed without
    a ``pricing`` object simply gets no price.
    """

    name = "novita"
    provider_id = "novita"
    base_url = "https://api.novita.ai/v3/openai"
    api_url = "https://api.novita.ai/v3/openai/models"
    env_var = None
    context_window_key = "context_size"
    max_output_key = "max_output_tokens"
    prices_are_per_million = True
    modality_keys = ("input_modalities", "output_modalities")
    source_notes = (
        "Provider model ids, context window, max output tokens, modalities and "
        "per-million prices from the public model list (GET /v3/openai/models, "
        "no authentication required)."
    )

    def prices(self, item) -> dict:
        pricing = item.get("pricing")
        if not isinstance(pricing, dict):
            return {}
        out: dict = {}
        for key, source_key in (
            ("input", "prompt"),
            ("output", "completion"),
            ("cached_input", "input_cache_read"),
            ("cached_write", "input_cache_write"),
        ):
            entry = pricing.get(source_key)
            if not isinstance(entry, dict):
                continue
            value = number(entry.get("price_per_m_decimal"))
            if value is None:
                value = number(entry.get("price_per_m"))
            if value is not None and value >= 0:
                out[key] = round(value, 6)
        return out
