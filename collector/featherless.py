from __future__ import annotations

from .openai_compatible import OpenAICompatibleCollector


class FeatherlessCollector(OpenAICompatibleCollector):
    """Reads Featherless' public model list (no API key required).

    The catalogue is enormous (tens of thousands of community fine-tunes), and
    almost none of those ids are registered models, so most of the run ends up
    in the *needs manual review* report. That is the intended behaviour: a
    provider serving a model the registry has never heard of must not cause a
    model document to be invented.

    The ``pricing`` object quotes the same figure twice — per-token under
    ``prompt``/``completion`` and per-million under ``input``/``output``. The
    per-million pair is used. ``image`` and ``request`` are per-image and
    per-request units, not token prices, and are ignored.
    """

    name = "featherless"
    provider_id = "featherless"
    base_url = "https://api.featherless.ai/v1"
    api_url = "https://api.featherless.ai/v1/models"
    env_var = None
    context_window_key = "context_length"
    max_output_key = "max_completion_tokens"
    prices_are_per_million = True
    input_price_key = "input"
    output_price_key = "output"
    source_notes = (
        "Provider model ids, context window, max output tokens and per-million "
        "prices from the public model list (GET /v1/models, no authentication "
        "required). Per-image and per-request prices are not token prices and "
        "are not recorded."
    )

    def normalize(self, payload) -> dict:
        results = super().normalize(payload)
        features_by_id = {
            item.get("id"): item.get("features") for item in payload.get("data", [])
        }
        for model_id, patch in results["provider_models"].items():
            features = features_by_id.get(model_id) or {}
            if isinstance(features, dict) and features.get("tool_use") is not None:
                patch["capabilities"] = {"tool_use": bool(features["tool_use"])}
        return results
