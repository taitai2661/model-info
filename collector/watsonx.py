from __future__ import annotations

import os

from .base import BaseCollector, api_source


class WatsonXCollector(BaseCollector):
    """Reads IBM WatsonX's public model list (API key required).

    WatsonX uses a custom API format. The model list endpoint returns a JSON
    object with ``resources`` array of model objects with ``model_id``,
    ``label``, ``provider``, and ``pricing`` fields.
    """

    name = "watsonx"
    provider_id = "watsonx"
    base_url = ""
    api_url = ""
    env_var = "WATSONX_API_KEY"
    creates_models = False

    def __init__(self):
        project_id = os.environ.get("WATSONX_PROJECT_ID", "")
        if not project_id:
            raise ValueError(
                "watsonx: set WATSONX_PROJECT_ID in the environment"
            )
        self.base_url = "https://us-south.ml.cloud.ibm.com/ml/v1"
        self.api_url = f"{self.base_url}/text/models?project_id={project_id}"

    def normalize(self, payload) -> dict:
        source = [api_source(
            self.api_url,
            "Model ids from IBM WatsonX's model list (GET /ml/v1/text/models, "
            "IAM authentication required).",
        )]
        provider_models = {}
        resources = payload.get("resources", [])
        for item in resources:
            model_id = item.get("model_id")
            if not model_id:
                continue
            provider_models[model_id] = {"model_id": model_id, "sources": source}
        return {"provider_models": provider_models}
