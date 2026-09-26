from __future__ import annotations

from .base import BaseCollector, api_source


class OpenCodeGoCollector(BaseCollector):
    name = "opencode-go"
    provider_id = "opencode-go"
    base_url = "https://opencode.ai/zen/go/v1"
    api_url = "https://opencode.ai/zen/go/v1/models"
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Provider model ids from the public Go model list (GET /v1/models).",
        )]
        provider_models = {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            provider_models[model_id] = {"model_id": model_id, "sources": source}
        return {"provider_models": provider_models}
