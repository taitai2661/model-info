from __future__ import annotations

from .base import BaseCollector, api_source


class OpenAICollector(BaseCollector):
    name = "openai"
    provider_id = "openai"
    base_url = "https://api.openai.com/v1"
    api_url = "https://api.openai.com/v1/models"
    env_var = "OPENAI_API_KEY"

    def normalize(self, payload) -> dict:
        models, relationships = {}, {}
        source = [api_source(self.api_url, "Model ids listed by GET /v1/models.")]
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            models[model_id] = {
                "required_fields": {
                    "model_id": model_id,
                    "name": model_id,
                    "model_provider": "openai",
                    "status": "active",
                },
                "sources": source,
            }
            relationships[model_id] = [{"model_id": model_id, "sources": source}]
        return {"models": models, "relationships": relationships}
