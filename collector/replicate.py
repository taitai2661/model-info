from __future__ import annotations

from .base import BaseCollector, api_source


class ReplicateCollector(BaseCollector):
    """Reads Replicate's public model list (API key required).

    Replicate uses a custom API format. The model list endpoint returns a JSON
    object with ``results`` array of model objects with ``name``, ``owner``,
    ``description``, and ``pricing`` fields.
    """

    name = "replicate"
    provider_id = "replicate"
    base_url = "https://api.replicate.com/v1"
    api_url = "https://api.replicate.com/v1/models"
    env_var = "REPLICATE_API_TOKEN"
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Model ids from Replicate's model list (GET /v1/models, token "
            "authentication required).",
        )]
        provider_models = {}
        results = payload.get("results", [])
        for item in results:
            model_id = item.get("name")
            if not model_id:
                continue
            owner = item.get("owner", "")
            full_id = f"{owner}/{model_id}" if owner else model_id
            provider_models[full_id] = {"model_id": full_id, "sources": source}
        return {"provider_models": provider_models}
