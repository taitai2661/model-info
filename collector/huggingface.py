from __future__ import annotations

from pathlib import Path

from .base import BaseCollector, api_source
from .openai_compatible import positive_int

ROUTER_URL = "https://router.huggingface.co/v1/models"

# The router names its partners with its own keys, which do not always match
# the provider ids used here. Only an explicit mapping is applied; a partner
# that is not registered is reported for manual review rather than guessed at.
PARTNER_IDS = {
    "cerebras": "cerebras",
    "cohere": "cohere",
    "deepinfra": "deepinfra",
    "featherless-ai": "featherless",
    "fireworks-ai": "fireworks",
    "groq": "groq",
    "novita": "novita",
    "together": "together",
    "zai-org": "zai",
}

ROUTER_NOTE = (
    "Served through the Hugging Face Inference Providers router. The router's "
    "price is set per partner provider and differs between them, so no single "
    "figure is recorded here; see the partner entries for the context window "
    "each one offers."
)


class HuggingFaceCollector(BaseCollector):
    """Reads the Hugging Face Inference Providers router's public model list.

    The router answers ``GET /v1/models`` without a key and reports, for every
    model it serves, one slot per partner provider. That is two different kinds
    of fact, and they are kept apart:

    * **The router serves this model** — a ``huggingface`` relationship entry
      with the route id. Its price is deliberately *not* recorded: the router
      quotes a different price per partner, so any single figure would be
      invented, and a partner's own price is not the router's to state.
    * **A partner serves this model** — the fact itself, plus the context window
      that partner actually offers and the features it reports, on the partner's
      own relationship entry.

    Model ids are Hugging Face repository ids (``Qwen/Qwen3.8-27B``) and are
    resolved against the registry with the same deterministic rules every other
    collector uses. Ids that do not resolve are reported, never invented.
    """

    name = "huggingface"
    provider_id = "huggingface"
    base_url = "https://router.huggingface.co/v1"
    api_url = ROUTER_URL
    env_var = None
    creates_models = False

    def normalize(self, payload) -> dict:
        raise NotImplementedError("use run(): this collector resolves ids against the registry")

    def run(self, root: Path, write: bool = False) -> dict:
        payload = self.fetch()
        router_source = [api_source(
            ROUTER_URL,
            "Provider model id from the Hugging Face Inference Providers public "
            "model list (GET /v1/models, no authentication required).",
        )]
        partner_source = [api_source(
            ROUTER_URL,
            "Which partner providers serve this model, the context window each "
            "one offers and the features it reports, as published by the router. "
            "The router's own price is not recorded on this entry because it is "
            "the router's price, not this provider's list price.",
        )]

        relationships: dict[str, list[dict]] = {}
        unknown_partners: set[str] = set()

        for item in payload.get("data", []):
            repo_id = item.get("id")
            if not repo_id:
                continue
            _, canonical = self.resolve_model(root, repo_id)
            if canonical is None:
                continue
            entries = relationships.setdefault(canonical, [])
            for slot in item.get("providers") or []:
                partner = slot.get("provider")
                if not partner:
                    continue
                partner_id = PARTNER_IDS.get(partner)
                if partner_id is None:
                    unknown_partners.add(partner)
                    continue
                entry = {"provider_id": partner_id, "model_id": repo_id,
                         "sources": partner_source}
                window = positive_int(slot.get("context_length"))
                if window:
                    entry["context"] = {"window": window}
                api_capabilities = {}
                if slot.get("supports_tools") is not None:
                    api_capabilities["tool_calling"] = bool(slot["supports_tools"])
                if slot.get("supports_structured_output") is not None:
                    api_capabilities["structured_output"] = bool(
                        slot["supports_structured_output"]
                    )
                if api_capabilities:
                    entry["api_capabilities"] = api_capabilities
                entries.append(entry)
            entries.append({
                "provider_id": self.provider_id,
                "model_id": repo_id,
                "notes": ROUTER_NOTE,
                "sources": router_source,
            })

        report = self.apply(root, {"relationships": relationships}, write=write)
        report["unmatched"].extend(
            f"partner provider {name!r} is not registered" for name in sorted(unknown_partners)
        )
        return report
