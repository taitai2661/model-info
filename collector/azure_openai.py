from __future__ import annotations

import os

from .openai_compatible import OpenAICompatibleCollector


class AzureOpenAICollector(OpenAICompatibleCollector):
    """Reads Azure OpenAI's model list (API key required).

    Azure OpenAI uses the same OpenAI-compatible ``GET /models`` envelope as
    the other OpenAI-compatible providers, but the endpoint includes the
    deployment name and requires an ``api-key`` header instead of a bearer
    token.
    """

    name = "azure_openai"
    provider_id = "azure-openai"
    base_url = ""
    api_url = ""
    env_var = "AZURE_OPENAI_API_KEY"
    auth_header = "api-key"
    context_window_key = "context_window"
    max_output_key = "max_output_tokens"
    input_price_key = "input_price"
    output_price_key = "output_price"
    source_notes = (
        "Model ids, context window and prices from Azure OpenAI's model list "
        "(GET /openai/models, api-key authentication required)."
    )

    def __init__(self):
        instance = os.environ.get("AZURE_OPENAI_INSTANCE", "")
        if not instance:
            raise ValueError(
                "azure_openai: set AZURE_OPENAI_INSTANCE in the environment "
                "(e.g. 'my-instance' for https://my-instance.openai.azure.com)"
            )
        self.base_url = f"https://{instance}.openai.azure.com"
        self.api_url = f"{self.base_url}/openai/models"
