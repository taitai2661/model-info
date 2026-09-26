from __future__ import annotations

from .base import BaseCollector, api_source


class DeepSeekCollector(BaseCollector):
    name = "deepseek"
    provider_id = "deepseek"
    base_url = "https://api.deepseek.com"
    api_url = "https://api.deepseek.com/models"
    env_var = "DEEPSEEK_API_KEY"

    def normalize(self, payload) -> dict:
        source = [api_source(self.api_url, "Model ids listed by GET /v1/models.")]
        models, relationships = {}, {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            models[model_id] = {
                "required_fields": {
                    "model_id": model_id,
                    "name": model_id,
                    "model_provider": "deepseek",
                    "status": "active",
                },
                "sources": source,
            }
            relationships[model_id] = [{"model_id": model_id, "sources": source}]
        return {"models": models, "relationships": relationships}
