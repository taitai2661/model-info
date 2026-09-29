from __future__ import annotations

from .base import BaseCollector, api_source


class StabilityAICollector(BaseCollector):
    """Reads Stability AI's public model list (API key required).

    Stability AI uses a custom API format. The model list endpoint returns a
    JSON array of model objects with ``id``, ``name``, ``description``, and
    ``pricing`` fields.
    """

    name = "stability"
    provider_id = "stability-ai"
    base_url = "https://api.stability.ai/v1"
    api_url = "https://api.stability.ai/v1/models"
    env_var = "STABILITY_API_KEY"
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Model ids from Stability AI's model list (GET /v1/models, bearer "
            "authentication required).",
        )]
        provider_models = {}
        if isinstance(payload, list):
            items = payload
        else:
            items = payload.get("data", [])
        for item in items:
            model_id = item.get("id")
            if not model_id:
                continue
            provider_models[model_id] = {"model_id": model_id, "sources": source}
        return {"provider_models": provider_models}
