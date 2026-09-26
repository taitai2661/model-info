from __future__ import annotations

from .base import BaseCollector, api_source


class GoogleCollector(BaseCollector):
    name = "google"
    provider_id = "google"
    base_url = "https://generativelanguage.googleapis.com"
    api_url = "https://generativelanguage.googleapis.com/v1beta/models"
    env_var = "GEMINI_API_KEY"
    auth_header = "x-goog-api-key"

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Token limits from GET /v1beta/models (inputTokenLimit/outputTokenLimit).",
        )]
        models, relationships = {}, {}
        for item in payload.get("models", []):
            name = item.get("name", "")
            model_id = name[len("models/"):] if name.startswith("models/") else name
            if not model_id:
                continue
            patch = {"sources": source}
            context = {}
            if item.get("inputTokenLimit"):
                context["window"] = int(item["inputTokenLimit"])
            if item.get("outputTokenLimit"):
                context["max_output_tokens"] = int(item["outputTokenLimit"])
            if context:
                patch["context"] = context
            methods = item.get("supportedGenerationMethods") or []
            if "streamGenerateContent" in methods:
                patch["capabilities"] = {"streaming": True}
            display = item.get("displayName")
            if display:
                patch["display_name"] = display
            description = item.get("description")
            if description:
                patch["description"] = description
            patch["required_fields"] = {
                "model_id": model_id,
                "name": display or model_id,
                "model_provider": "google",
                "status": "active",
            }
            models[model_id] = patch
            relationships[model_id] = [{"model_id": model_id, "sources": source}]
        return {"models": models, "relationships": relationships}
