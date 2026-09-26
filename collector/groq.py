from __future__ import annotations

from .base import api_source
from .docs import (DocsCollector, column_index, link_targets, money_values,
                   parse_int, parse_tables)

NOTES = ("Provider model id, price, context window, and max completion tokens "
         "from Groq's supported-models page.")


class GroqCollector(DocsCollector):
    """Reads Groq's supported-models table (the API itself requires a key)."""

    name = "groq"
    provider_id = "groq"
    base_url = "https://api.groq.com/openai/v1"
    api_url = "https://console.groq.com/docs/models.md"
    creates_models = False

    def normalize(self, text: str) -> dict:
        source = [api_source(self.api_url, NOTES)]
        provider_models = {}
        for table in parse_tables(text):
            header = table["header"]
            id_col = column_index(header, "model id")
            price_col = column_index(header, "price per 1m tokens")
            if id_col is None or price_col is None:
                continue
            ctx_col = column_index(header, "context window (tokens)")
            out_col = column_index(header, "max completion tokens")
            for row in table["rows"]:
                if max(c for c in (id_col, price_col, ctx_col, out_col) if c is not None) >= len(row):
                    continue
                model_id = self._model_id(row[id_col])
                if not model_id:
                    continue
                patch = {"model_id": model_id, "sources": source}
                prices = money_values(row[price_col])
                if len(prices) >= 2:
                    patch["pricing"] = {"currency": "USD", "unit": "1M_tokens",
                                        "input": prices[0], "output": prices[1]}
                context = {}
                window = parse_int(row[ctx_col]) if ctx_col is not None else None
                max_out = parse_int(row[out_col]) if out_col is not None else None
                if window is not None:
                    context["window"] = window
                if max_out is not None:
                    context["max_output_tokens"] = max_out
                if context:
                    patch["context"] = context
                provider_models[model_id] = patch
        return {"provider_models": provider_models}

    @staticmethod
    def _model_id(cell: str) -> str | None:
        """Groq identifies each model by the target of its ``/docs/model/`` link."""
        for target in link_targets(cell):
            if "/docs/model/" in target:
                return target.split("/docs/model/", 1)[1].strip("/")
        return None
