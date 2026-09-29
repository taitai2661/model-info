from __future__ import annotations

from .openai_compatible import OpenAICompatibleCollector


class DeepInfraCollector(OpenAICompatibleCollector):
    """Reads DeepInfra's public model list (no API key required).

    Everything useful sits under a per-model ``metadata`` object. Its price
    table mixes token prices with non-token units (``per_image_unit``,
    ``input_characters``, ``input_seconds``, ``output_seconds``), so only the
    three token keys are read.

    The three token keys are named ``input_tokens`` / ``output_tokens`` but hold
    a price **per 1M tokens**, not per token: DeepInfra's own pricing page labels
    the column "$ per 1M input tokens" and quotes "$X / 1M tokens". Multiplying
    by a million here would inflate every price by 10^6, so the values are used
    as they stand.
    """

    name = "deepinfra"
    provider_id = "deepinfra"
    base_url = "https://api.deepinfra.com/v1/openai"
    api_url = "https://api.deepinfra.com/v1/openai/models"
    env_var = None
    prices_are_per_million = True
    context_window_key = "context_length"
    max_output_key = "max_tokens"
    input_price_key = "input_tokens"
    output_price_key = "output_tokens"
    cached_input_price_key = "cache_read_tokens"
    source_notes = (
        "Provider model ids, context window, max output tokens and prices from "
        "the public model list (GET /v1/openai/models, no authentication "
        "required). Despite the key names, input_tokens / output_tokens / "
        "cache_read_tokens are prices per 1M tokens. Non-token prices (per "
        "image, per character, per second of audio) are not recorded."
    )

    def item_scope(self, item) -> dict:
        metadata = item.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
