from __future__ import annotations

from .openai_compatible import OpenAICompatibleCollector


class SambaNovaCollector(OpenAICompatibleCollector):
    """Reads SambaNova Cloud's public model list (no API key required).

    Prices are per-token strings, including the cached input and cache write
    rates for the models that bill them.
    """

    name = "sambanova"
    provider_id = "sambanova"
    base_url = "https://api.sambanova.ai/v1"
    api_url = "https://api.sambanova.ai/v1/models"
    env_var = None
    context_window_key = "context_length"
    max_output_key = "max_completion_tokens"
    input_price_key = "prompt"
    output_price_key = "completion"
    cached_input_price_key = "input_cache_read"
    cached_write_price_key = "input_cache_write"
    source_notes = (
        "Provider model ids, context window, max output tokens and per-token "
        "prices from the public model list (GET /v1/models, no authentication "
        "required). Prices are converted from per-token to per-million."
    )
