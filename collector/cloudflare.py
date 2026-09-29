from __future__ import annotations

import os

from .openai_compatible import OpenAICompatibleCollector


class CloudflareWorkersAICollector(OpenAICompatibleCollector):
    """Reads Cloudflare Workers AI's public model list (API key required).

    Cloudflare Workers AI uses the same OpenAI-compatible ``GET /models``
    envelope as the other OpenAI-compatible providers, but the endpoint
    includes the account ID and requires a bearer token.
    """

    name = "cloudflare"
    provider_id = "cloudflare"
    base_url = ""
    api_url = ""
    env_var = "CLOUDFLARE_API_KEY"
    context_window_key = "context_window"
    max_output_key = "max_output_tokens"
    input_price_key = "input_price"
    output_price_key = "output_price"
    source_notes = (
        "Model ids, context window and prices from Cloudflare Workers AI's "
        "model list (GET /client/v4/accounts/{account}/ai/v1/models, bearer "
        "authentication required)."
    )

    def __init__(self):
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not account_id:
            raise ValueError(
                "cloudflare: set CLOUDFLARE_ACCOUNT_ID in the environment"
            )
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        self.api_url = f"{self.base_url}/ai/v1/models"
