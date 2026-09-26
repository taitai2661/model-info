from __future__ import annotations

from .base import BaseCollector, CollectorError, api_source


class AnthropicCollector(BaseCollector):
    name = "anthropic"
    provider_id = "anthropic"
    base_url = "https://api.anthropic.com"
    api_url = "https://api.anthropic.com/v1/models?limit=1000"
    env_var = "ANTHROPIC_API_KEY"
    auth_header = "x-api-key"

    def fetch(self):
        items, after = [], None
        while True:
            url = self.api_url if after is None else f"{self.api_url}&after_id={after}"
            try:
                import httpx
                response = httpx.get(url, headers=self.auth_headers(), timeout=30,
                                     follow_redirects=True)
            except httpx.HTTPError as exc:
                raise CollectorError(f"anthropic: request failed: {exc}") from exc
            if response.status_code >= 400:
                raise CollectorError(
                    f"anthropic: HTTP {response.status_code}: {response.text[:200]}"
                )
            payload = response.json()
            items.extend(payload.get("data", []))
            if not payload.get("has_more"):
                break
            after = payload.get("last_id")
            if not after:
                break
        return {"data": items}

    def normalize(self, payload) -> dict:
        source = [api_source(
            "https://api.anthropic.com/v1/models",
            "Capabilities and token limits from the Models API (max_input_tokens mapped to context.window).",
        )]
        models, relationships = {}, {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            patch = {"sources": source}
            caps = item.get("capabilities") or {}
            max_in = item.get("max_input_tokens") or 0
            max_out = item.get("max_tokens") or 0
            context = {}
            if max_in > 0:
                context["window"] = max_in
            if max_out > 0:
                context["max_output_tokens"] = max_out
            if context:
                patch["context"] = context
            capabilities = {}
            if isinstance(caps.get("image_input"), dict):
                capabilities["vision"] = bool(caps["image_input"].get("supported"))
            if isinstance(caps.get("pdf_input"), dict):
                file_input = bool(caps["pdf_input"].get("supported"))
            else:
                file_input = None
            if isinstance(caps.get("structured_outputs"), dict):
                capabilities["structured_output"] = bool(
                    caps["structured_outputs"].get("supported")
                )
            thinking = caps.get("thinking")
            if isinstance(thinking, dict):
                capabilities["reasoning"] = bool(thinking.get("supported"))
            if capabilities:
                patch["capabilities"] = capabilities
            if "vision" in capabilities:
                modalities_in = ["text"]
                if capabilities["vision"]:
                    modalities_in.append("image")
                if file_input:
                    modalities_in.append("file")
                patch["modalities"] = {"input": modalities_in, "output": ["text"]}
            display = item.get("display_name")
            if display:
                patch["display_name"] = display
            patch["required_fields"] = {
                "model_id": model_id,
                "name": display or model_id,
                "model_provider": "anthropic",
                "status": "active",
            }
            models[model_id] = patch
            relationships[model_id] = [{"model_id": model_id, "sources": source}]
        return {"models": models, "relationships": relationships}
