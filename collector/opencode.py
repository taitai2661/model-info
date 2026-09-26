from __future__ import annotations

from .base import BaseCollector, api_source


class OpenCodeCollector(BaseCollector):
    name = "opencode"
    provider_id = "opencode"
    base_url = "https://opencode.ai/zen/v1"
    api_url = "https://opencode.ai/zen/v1/models"
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Provider model ids from the public Zen model list (GET /v1/models).",
        )]
        provider_models = {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            provider_models[model_id] = {"model_id": model_id, "sources": source}
        return {"provider_models": provider_models}
