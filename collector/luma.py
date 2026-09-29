from __future__ import annotations

from .base import BaseCollector, api_source


class LumaAICollector(BaseCollector):
    """Reads Luma AI's public model list (API key required).

    Luma AI uses a custom API format. The model list endpoint returns a JSON
    array of model objects with ``id``, ``name``, ``description``, and
    ``pricing`` fields.
    """

    name = "luma"
    provider_id = "luma"
    base_url = "https://api.lumalabs.ai/dream-machine/v1"
    api_url = "https://api.lumalabs.ai/dream-machine/v1/models"
    env_var = "LUMA_API_KEY"
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Model ids from Luma AI's model list (GET /dream-machine/v1/models, "
            "bearer authentication required).",
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
