from __future__ import annotations

from .base import api_source
from .docs import (DocsCollector, column_index, link_targets, money_values,
                   parse_tables)

NOTES = ("Provider model id and Standard-tier prices (input / cached input / "
         "output per 1M tokens) from Fireworks' serverless pricing page. "
         "Fast, US and Priority rows link to the same model id, so the first "
         "(standard, global) row for each id wins.")


class FireworksCollector(DocsCollector):
    """Reads Fireworks' serverless pricing table (the API itself requires a key)."""

    name = "fireworks"
    provider_id = "fireworks"
    base_url = "https://api.fireworks.ai/inference/v1"
    api_url = "https://docs.fireworks.ai/serverless/pricing.md"
    creates_models = False

    def normalize(self, text: str) -> dict:
        source = [api_source(self.api_url, NOTES)]
        provider_models = {}
        for table in parse_tables(text):
            header = table["header"]
            id_col = column_index(header, "model")
            standard_col = column_index(header, "standard")
            if id_col is None or standard_col is None:
                continue
            for row in table["rows"]:
                if max(id_col, standard_col) >= len(row):
                    continue
                model_id = self._model_id(row[id_col])
                if not model_id or model_id in provider_models:
                    continue
                patch = {"model_id": model_id, "sources": source}
                prices = money_values(row[standard_col])
                if len(prices) >= 3:
                    patch["pricing"] = {"currency": "USD", "unit": "1M_tokens",
                                        "input": prices[0], "output": prices[2],
                                        "cached_input": prices[1]}
                elif len(prices) == 1:
                    patch["pricing"] = {"currency": "USD", "unit": "1M_tokens",
                                        "input": prices[0], "output": None}
                provider_models[model_id] = patch
        return {"provider_models": provider_models}

    @staticmethod
    def _model_id(cell: str) -> str | None:
        """Fireworks links each row to ``/models/fireworks/<slug>``; the API id
        documented in their guides is ``accounts/fireworks/models/<slug>``."""
        for target in link_targets(cell):
            if "/models/fireworks/" in target:
                slug = target.split("/models/fireworks/", 1)[1].strip("/")
                if slug:
                    return f"accounts/fireworks/models/{slug}"
        return None
