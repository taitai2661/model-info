from __future__ import annotations

from .base import BaseCollector, api_source


class NvidiaCollector(BaseCollector):
    """Reads NVIDIA NIM's public model catalog (no API key required).

    NIM's ``GET /v1/models`` lists every model the API catalog serves, but it
    only exposes ``id`` and ``owned_by`` — context windows, modalities, and
    prices are not part of that endpoint. The collector therefore only
    registers provider model ids; model documents and their full specs
    (context, modalities, capabilities, sources) are hand-written so the
    registry stays a verified facts source, not a mirror of an upstream JSON
    blob.
    """

    name = "nvidia"
    provider_id = "nvidia"
    base_url = "https://integrate.api.nvidia.com/v1"
    api_url = "https://integrate.api.nvidia.com/v1/models"
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Provider model ids from the NVIDIA NIM public model catalog "
            "(GET /v1/models, no authentication required).",
        )]
        provider_models = {}
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            provider_models[model_id] = {"model_id": model_id, "sources": source}
        return {"provider_models": provider_models}
