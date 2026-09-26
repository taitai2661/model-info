from __future__ import annotations

from .base import api_source
from .docs import (DocsCollector, column_index, money_values, parse_int,
                   parse_tables, strip_markdown)

NOTES = ("Provider model id, context window, and per-1M-token prices from "
         "Together AI's available-models page (chat models table).")


class TogetherCollector(DocsCollector):
    """Reads Together AI's chat-model table (the API itself requires a key)."""

    name = "together"
    provider_id = "together"
    base_url = "https://api.together.ai/v1"
    api_url = "https://docs.together.ai/docs/inference-models.md"
    creates_models = False

    def normalize(self, text: str) -> dict:
        source = [api_source(self.api_url, NOTES)]
        provider_models = {}
        for table in parse_tables(text):
            header = table["header"]
            id_col = column_index(header, "api model string")
            if id_col is None:
                continue
            ctx_col = column_index(header, "context length")
            in_col = column_index(header, "input pricing (per 1m tokens)")
            cache_col = column_index(header, "cached input pricing (per 1m tokens)")
            out_col = column_index(header, "output pricing (per 1m tokens)")
            for row in table["rows"]:
                if id_col >= len(row):
                    continue
                model_id = strip_markdown(row[id_col])
                if not model_id:
                    continue
                patch = {"model_id": model_id, "sources": source}
                window = parse_int(row[ctx_col]) if ctx_col is not None else None
                if window is not None:
                    patch["context"] = {"window": window}
                pricing = self._pricing(row, in_col, cache_col, out_col)
                if pricing:
                    patch["pricing"] = pricing
                provider_models[model_id] = patch
        return {"provider_models": provider_models}

    @staticmethod
    def _pricing(row: list[str], in_col, cache_col, out_col) -> dict | None:
        def value(col):
            if col is None or col >= len(row):
                return None
            values = money_values(row[col])
            return values[0] if values else None

        pricing = {"currency": "USD", "unit": "1M_tokens",
                   "input": value(in_col), "output": value(out_col)}
        cached = value(cache_col)
        if cached is not None:
            pricing["cached_input"] = cached
        if pricing["input"] is None and pricing["output"] is None:
            return None
        return pricing
