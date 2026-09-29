from __future__ import annotations

from .openai_compatible import OpenAICompatibleCollector


class LambdaLabsCollector(OpenAICompatibleCollector):
    """Reads Lambda Labs' public model list (API key required).

    Lambda Labs uses the same OpenAI-compatible ``GET /models`` envelope as
    the other OpenAI-compatible providers.
    """

    name = "lambda_labs"
    provider_id = "lambda-labs"
    base_url = "https://api.lambda.ai/v1"
    api_url = "https://api.lambda.ai/v1/models"
    env_var = "LAMBDA_LABS_API_KEY"
    context_window_key = "context_window"
    max_output_key = "max_output_tokens"
    input_price_key = "input_price"
    output_price_key = "output_price"
    source_notes = (
        "Model ids, context window and prices from Lambda Labs' model list "
        "(GET /v1/models, bearer authentication required)."
    )
