from __future__ import annotations

from .base import BaseCollector, api_source


class MistralCollector(BaseCollector):
    name = "mistral"
    provider_id = "mistral"
    base_url = "https://api.mistral.ai/v1"
    api_url = "https://api.mistral.ai/v1/models"
    env_var = "MISTRAL_API_KEY"

    def normalize(self, payload) -> dict:
        source = [api_source(self.api_url, "Model ids listed by GET /v1/models.")]
        models, relationships = {}, {}
        data = payload.get("data") or payload.get("models") or []
        for item in data:
            model_id = item.get("id") or item.get("model")
            if not model_id:
                continue
            patch = {"sources": source, "required_fields": {
                "model_id": model_id,
                "name": item.get("name") or model_id,
                "model_provider": "mistral",
                "status": "active",
            }}
            context = {}
            for key, field in (("context_window", "window"),
                               ("max_context_length", "window"),
                               ("max_output_tokens", "max_output_tokens")):
                value = item.get(key)
                if isinstance(value, int) and value > 0:
                    context[field] = value
            if context:
                patch["context"] = context
            if item.get("description"):
                patch["description"] = item["description"]
            models[model_id] = patch
            relationships[model_id] = [{"model_id": model_id, "sources": source}]
        return {"models": models, "relationships": relationships}
