import json

import pytest

from collector.anthropic import AnthropicCollector
from collector.base import CollectorError, discover
from collector.openrouter import OpenRouterCollector


def test_registry_lists_collectors():
    registry = discover()
    assert {"openai", "anthropic", "google", "deepseek", "mistral",
            "openrouter", "opencode", "opencode-go",
            "groq", "together", "fireworks", "nvidia",
            "vercel-ai-gateway", "deepinfra", "novita", "ppio", "sambanova",
            "featherless", "huggingface"} <= set(registry)


def test_docs_collectors_need_no_api_key():
    registry = discover()
    for name in ("groq", "together", "fireworks"):
        collector = registry[name]
        assert collector.env_var is None, f"{name} must not require a key"
        assert collector.creates_models is False
        assert collector.api_url.endswith(".md")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    collector = discover()["openai"]
    with pytest.raises(CollectorError):
        collector.fetch()


def test_openrouter_normalize_prices_are_per_million():
    payload = {"data": [{
        "id": "openai/gpt-6-astra",
        "pricing": {"prompt": "0.00001", "completion": "0.00005",
                    "input_cache_read": "0.000001"},
        "context_length": 1050000,
        "top_provider": {"max_completion_tokens": 128000},
        "architecture": {"input_modalities": ["text", "image"],
                         "output_modalities": ["text"]},
    }]}
    results = OpenRouterCollector().normalize(payload)
    patch = results["provider_models"]["openai/gpt-6-astra"]
    assert patch["pricing"] == {"currency": "USD", "unit": "1M_tokens",
                                "input": 10.0, "output": 50.0, "cached_input": 1.0}
    assert patch["context"] == {"window": 1050000, "max_output_tokens": 128000}
    assert patch["modalities"] == {"input": ["text", "image"], "output": ["text"]}


def test_openrouter_drops_negative_price_sentinels():
    payload = {"data": [{
        "id": "jev-router",
        "pricing": {"prompt": "-1", "completion": "-1"},
    }]}
    results = OpenRouterCollector().normalize(payload)
    assert "pricing" not in results["provider_models"]["jev-router"]


def test_openrouter_apply_reports_unmatched_ids(repo_root, sandbox):
    # The context window is deliberately not the stored one so the run always
    # has something to write, whatever state data/ is in.
    payload = {"data": [
        {"id": "openai/gpt-6-astra", "context_length": 1234567,
         "top_provider": {"max_completion_tokens": 128000}},
        {"id": "nobody/unknown-model", "context_length": 1},
    ]}
    collector = OpenRouterCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=False)
    assert "gpt-6-astra" in report["relationships"]
    assert "nobody/unknown-model" in report["unmatched"]


def test_openrouter_write_is_idempotent(repo_root, sandbox):
    payload = {"data": [{
        "id": "openai/gpt-6-astra",
        "pricing": {"prompt": "0.00001", "completion": "0.00005"},
        "context_length": 1234567,
        "top_provider": {"max_completion_tokens": 128000},
        "architecture": {"input_modalities": ["text", "image"],
                         "output_modalities": ["text"]},
    }]}
    collector = OpenRouterCollector()
    first = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert first["relationships"] == ["gpt-6-astra"]
    second = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert second["relationships"] == []
    assert second["unchanged"]


def test_aggregator_never_creates_models(repo_root, sandbox):
    payload = {"data": [{"id": "brand-new/model", "context_length": 1}]}
    collector = OpenRouterCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["created"] == []
    assert not (sandbox / "data/models/brand-new/model.json").exists()
    assert "brand-new/model" in report["unmatched"]


def test_anthropic_normalize_maps_capabilities():
    payload = {"data": [{
        "id": "claude-sonnet-5",
        "display_name": "Claude Sonnet 5",
        "max_input_tokens": 1000000,
        "max_tokens": 128000,
        "capabilities": {
            "image_input": {"supported": True},
            "pdf_input": {"supported": True},
            "structured_outputs": {"supported": True},
            "thinking": {"supported": True},
        },
    }]}
    results = AnthropicCollector().normalize(payload)
    patch = results["models"]["claude-sonnet-5"]
    assert patch["context"] == {"window": 1000000, "max_output_tokens": 128000}
    assert patch["capabilities"]["vision"] is True
    assert patch["capabilities"]["structured_output"] is True
    assert patch["capabilities"]["reasoning"] is True
    assert patch["modalities"]["input"] == ["text", "image", "file"]


def test_anthropic_merge_preserves_hand_written_fields(sandbox):
    payload = {"data": [{
        "id": "claude-sonnet-5",
        "display_name": "Claude Sonnet 5",
        "max_input_tokens": 1000000,
        "max_tokens": 128000,
        "capabilities": {"image_input": {"supported": True}},
    }]}
    collector = AnthropicCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert "claude-sonnet-5" in report["updated"]
    doc = json.loads((sandbox / "data/models/claude-sonnet-5.json").read_text())
    assert doc["pricing"]["input"] == 2
    assert doc["family"] == "Claude"
    assert doc["context"]["window"] == 1000000


def test_invalid_collector_output_is_not_written(sandbox):
    collector = AnthropicCollector()
    results = {"models": {"claude-sonnet-5": {"context": {"window": -5}}}}
    report = collector.apply(sandbox, results, write=True)
    assert report["invalid"], "negative context window must fail schema validation"
    doc = json.loads((sandbox / "data/models/claude-sonnet-5.json").read_text())
    assert doc["context"]["window"] == 1000000


def test_collector_drops_negative_token_limits(sandbox):
    payload = {"data": [{"id": "claude-sonnet-5", "max_input_tokens": -5}]}
    results = AnthropicCollector().normalize(payload)
    assert "context" not in results["models"]["claude-sonnet-5"]


def test_model_provider_collector_creates_minimal_model(sandbox):
    from collector.openai import OpenAICollector
    from validate import validate_all

    payload = {"data": [{"id": "gpt-6-astra"}, {"id": "brand-new-gpt"}]}
    collector = OpenAICollector()

    dry = collector.apply(sandbox, collector.normalize(payload), write=False)
    assert "brand-new-gpt" in dry["created"]
    assert not (sandbox / "data/models/brand-new-gpt.json").exists()

    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["created"] == ["brand-new-gpt"]
    doc = json.loads((sandbox / "data/models/brand-new-gpt.json").read_text())
    assert doc["model_provider"] == "openai"
    assert doc["status"] == "active"
    rel = json.loads((sandbox / "data/relationships/brand-new-gpt.json").read_text())
    assert rel["providers"][0] == {
        "provider_id": "openai",
        "model_id": "brand-new-gpt",
        "sources": rel["providers"][0]["sources"],
    }
    errors, _ = validate_all(sandbox)
    assert errors == [], errors


def test_registry_includes_opencode_go():
    registry = discover()
    assert "opencode-go" in registry
    collector = registry["opencode-go"]
    assert collector.api_url == "https://opencode.ai/zen/go/v1/models"
    assert collector.env_var is None
    assert collector.creates_models is False


def test_opencode_go_collector_updates_existing_entry(sandbox):
    from collector.opencode_go import OpenCodeGoCollector

    # Drop the source list so the run has something to repair, whatever state
    # data/ is in.
    rel_path = sandbox / "data/relationships/deepseek-flash.json"
    stored = json.loads(rel_path.read_text())
    stale = next(e for e in stored["providers"]
                 if e["provider_id"] == "opencode-go" and e["model_id"] == "deepseek-v4.1-flash")
    stale.pop("sources", None)
    rel_path.write_text(json.dumps(stored))

    payload = {"data": [
        {"id": "deepseek-v4.1-flash"},
        {"id": "brand-new-model"},
    ]}
    collector = OpenCodeGoCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["relationships"] == ["deepseek-flash"]
    assert report["created"] == []
    assert "brand-new-model" in report["unmatched"]
    doc = json.loads(rel_path.read_text())
    entry = next(e for e in doc["providers"]
                 if e["provider_id"] == "opencode-go" and e["model_id"] == "deepseek-v4.1-flash")
    assert any(s["url"].endswith("/zen/go/v1/models") for s in entry["sources"])


GROQ_DOC = """
## Production Models

| MODEL ID | SPEED (T/SEC) | PRICE PER 1M TOKENS | RATE LIMITS (DEVELOPER PLAN) | CONTEXT WINDOW (TOKENS) | MAX COMPLETION TOKENS | MAX FILE SIZE |
| --- | --- | --- | --- | --- | --- | --- |
| [![Meta](https://example.com/m.png)Llama 3.3 70B](/docs/model/llama-3.3-70b-versatile)Enterprisellama-3.3-70b-versatile | 280 | ContactSales | ContactSales | 131,072 | 32,768 | \\- |
| [![Qwen](https://example.com/q.png)Qwen/Qwen3.8-27B](/docs/model/qwen/qwen3.8-27b)qwen/qwen3.8-27b | 450 | $0.80 input$4.00 output | 250K TPM | 131,072 | 16,384 | 20 MB |
| [![OpenAI](https://example.com/o.png)Whisper](/docs/model/whisper-large-v3)whisper-large-v3 | \\- | $0.111 per hour | 200K ASH | \\- | \\- | 100 MB |
"""

TOGETHER_DOC = """
| Organization | Model name | API model string | Context length | Input pricing (per 1M tokens) | Cached input pricing (per 1M tokens) | Output pricing (per 1M tokens) | Quantization | Function calling | Structured outputs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Z.ai | GLM-5.3 | zai-org/GLM-5.3 | 1048575 | \\$1.40 | \\$0.26 | \\$4.40 | FP4 | Yes | Yes |
| Together AI | Tev1 4B | together/Tev1-4B-experimental | 32768 | \\$0.042 | - | Free | FP8 | - | - |
"""

FIREWORKS_DOC = """
| Model | Standard | Priority |
| --- | --- | --- |
| [Kimi K3](https://app.fireworks.ai/models/fireworks/kimi-k3) | \\$3.00 / \\$0.30 / \\$15.00 | \\$3.75 / \\$0.375 / \\$18.75 |
| [Kimi K3 Fast](https://app.fireworks.ai/models/fireworks/kimi-k3) | \\$4.50 / \\$0.45 / \\$22.50 | — |
| [GLM 5.3](https://app.fireworks.ai/models/fireworks/glm-5p3) | \\$1.40 / \\$0.26 / \\$4.40 | — |
"""


def test_groq_normalize_reads_the_markdown_table():
    from collector.groq import GroqCollector

    results = GroqCollector().normalize(GROQ_DOC)
    models = results["provider_models"]
    assert set(models) == {"llama-3.3-70b-versatile", "qwen/qwen3.8-27b",
                           "whisper-large-v3"}
    assert "pricing" not in models["llama-3.3-70b-versatile"]   # ContactSales
    assert models["llama-3.3-70b-versatile"]["context"] == {
        "window": 131072, "max_output_tokens": 32768}
    assert models["qwen/qwen3.8-27b"]["pricing"] == {
        "currency": "USD", "unit": "1M_tokens", "input": 0.8, "output": 4.0}
    # An hourly rate is not a 1M_tokens price, and dashes mean "unknown".
    assert "pricing" not in models["whisper-large-v3"]
    assert "context" not in models["whisper-large-v3"]


def test_together_normalize_reads_the_markdown_table():
    from collector.together import TogetherCollector

    results = TogetherCollector().normalize(TOGETHER_DOC)
    models = results["provider_models"]
    assert models["zai-org/GLM-5.3"]["context"] == {"window": 1048575}
    assert models["zai-org/GLM-5.3"]["pricing"] == {
        "currency": "USD", "unit": "1M_tokens",
        "input": 1.4, "output": 4.4, "cached_input": 0.26}
    tev1 = models["together/Tev1-4B-experimental"]["pricing"]
    assert tev1["input"] == 0.042
    assert tev1["output"] == 0.0        # "Free" is an explicit zero, not unknown
    assert "cached_input" not in tev1   # a dash is unknown


def test_fireworks_normalize_reads_the_markdown_table():
    from collector.fireworks import FireworksCollector

    results = FireworksCollector().normalize(FIREWORKS_DOC)
    models = results["provider_models"]
    # Fast/US rows share the model id, so the first (standard) row wins.
    assert set(models) == {"accounts/fireworks/models/kimi-k3",
                           "accounts/fireworks/models/glm-5p3"}
    assert models["accounts/fireworks/models/kimi-k3"]["pricing"] == {
        "currency": "USD", "unit": "1M_tokens",
        "input": 3.0, "output": 15.0, "cached_input": 0.3}
    # The "p" decimal escape resolves to the canonical id on write.
    assert "glm-5p3" not in models


def test_aggregator_creates_relationship_entry_when_model_resolves(sandbox):
    """An id the aggregator can resolve gets an entry; an unknown one does not."""
    rel_path = sandbox / "data/relationships/glm-5.json"
    stored = json.loads(rel_path.read_text())
    stored["providers"] = [e for e in stored["providers"]
                           if e["provider_id"] != "openrouter"]
    rel_path.write_text(json.dumps(stored))

    payload = {"data": [
        {"id": "z-ai/glm-5", "context_length": 204800},
        {"id": "nobody/unknown-model", "context_length": 1},
    ]}
    collector = OpenRouterCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)

    assert report["relationships"] == ["glm-5"]
    assert "nobody/unknown-model" in report["unmatched"]
    assert report["created"] == []        # never invents a model document
    stored = json.loads(rel_path.read_text())
    entry = next(e for e in stored["providers"] if e["provider_id"] == "openrouter")
    assert entry["model_id"] == "z-ai/glm-5"


def test_nvidia_collector_registers_public_endpoint():
    from collector.nvidia import NvidiaCollector

    registry = discover()
    collector = registry["nvidia"]
    assert collector.api_url == "https://integrate.api.nvidia.com/v1/models"
    assert collector.provider_id == "nvidia"
    assert collector.env_var is None           # public endpoint, no key
    assert collector.creates_models is False   # models are hand-authored


def test_nvidia_normalize_emits_provider_models():
    from collector.nvidia import NvidiaCollector

    payload = {"data": [
        {"id": "nvidia/nemotron-3-ultra-550b-a55b", "owned_by": "nvidia"},
        {"id": "meta/llama-3.1-70b-instruct", "owned_by": "meta"},
        {"id": "01-ai/yi-large", "owned_by": "01-ai"},
    ]}
    results = NvidiaCollector().normalize(payload)
    assert set(results["provider_models"]) == {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "meta/llama-3.1-70b-instruct",
        "01-ai/yi-large",
    }
    sample = results["provider_models"]["nvidia/nemotron-3-ultra-550b-a55b"]
    assert sample["model_id"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert sample["sources"][0]["url"].endswith("/v1/models")


def test_nvidia_apply_writes_relationship_entries_for_known_models(sandbox):
    from collector.nvidia import NvidiaCollector

    # mistralai/mistral-large resolves to a registered model doc (mistral-large)
    # whose relationship file exists and has no nvidia entry in the sandbox copy.
    rel_path = sandbox / "data/relationships/mistral-large.json"
    stored = json.loads(rel_path.read_text())
    stored["providers"] = [e for e in stored["providers"]
                           if e["provider_id"] != "nvidia"]
    rel_path.write_text(json.dumps(stored))

    payload = {"data": [
        {"id": "mistralai/mistral-large"},
        {"id": "nvidia/nobody-unknown-12345"},
    ]}
    collector = NvidiaCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["relationships"] == ["mistral-large"]
    assert report["created"] == []
    assert "nvidia/nobody-unknown-12345" in report["unmatched"]
    stored = json.loads(rel_path.read_text())
    entry = next(e for e in stored["providers"]
                 if e["provider_id"] == "nvidia"
                 and e["model_id"] == "mistralai/mistral-large")
    assert entry["sources"]


def test_vercel_ai_gateway_collector_registers_public_endpoint():
    from collector.vercel_ai_gateway import VercelAIGatewayCollector

    registry = discover()
    collector = registry["vercel-ai-gateway"]
    assert collector.api_url == "https://ai-gateway.vercel.sh/v1/models"
    assert collector.provider_id == "vercel-ai-gateway"
    assert collector.env_var is None
    assert collector.creates_models is False


def test_vercel_ai_gateway_normalize_converts_prices():
    from collector.vercel_ai_gateway import VercelAIGatewayCollector

    payload = {"data": [{
        "id": "openai/gpt-5",
        "name": "GPT-5",
        "owned_by": "openai",
        "context_window": 1050000,
        "max_tokens": 128000,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "pricing": {
            "input": "0.00000125",
            "output": "0.00001",
            "input_cache_read": "0.000000125",
        },
    }]}
    results = VercelAIGatewayCollector().normalize(payload)
    patch = results["provider_models"]["openai/gpt-5"]
    assert patch["context"] == {"window": 1050000, "max_output_tokens": 128000}
    assert patch["modalities"] == {"input": ["text", "image"], "output": ["text"]}
    assert patch["pricing"] == {
        "currency": "USD", "unit": "1M_tokens",
        "input": 1.25, "output": 10.0, "cached_input": 0.125,
    }


def test_vercel_ai_gateway_apply_creates_relationship_for_known_model(sandbox):
    from collector.vercel_ai_gateway import VercelAIGatewayCollector

    rel_path = sandbox / "data/relationships/gpt-5.json"
    stored = json.loads(rel_path.read_text())
    stored["providers"] = [e for e in stored["providers"]
                           if e["provider_id"] != "vercel-ai-gateway"]
    rel_path.write_text(json.dumps(stored))

    payload = {"data": [{
        "id": "openai/gpt-5",
        "context_window": 1050000,
        "modalities": {"input": ["text"], "output": ["text"]},
        "pricing": {"input": "0.00000125", "output": "0.00001"},
    }, {
        "id": "nobody/unknown-model",
    }]}
    collector = VercelAIGatewayCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["relationships"] == ["gpt-5"]
    assert report["created"] == []
    assert "nobody/unknown-model" in report["unmatched"]
    stored = json.loads(rel_path.read_text())
    entry = next(e for e in stored["providers"]
                 if e["provider_id"] == "vercel-ai-gateway"
                 and e["model_id"] == "openai/gpt-5")
    assert entry["sources"]



# -- the public OpenAI-compatible catalogues ---------------------------------


NEW_CATALOG_COLLECTORS = ("deepinfra", "novita", "ppio", "sambanova", "featherless")


def test_new_public_catalogues_are_registered_and_need_no_key():
    registry = discover()
    for name in NEW_CATALOG_COLLECTORS:
        collector = registry[name]
        assert collector.env_var is None, f"{name} must not require a key"
        assert collector.creates_models is False
        assert collector.api_url.startswith("https://")
        assert collector.api_url.endswith("/models")


def test_deepinfra_prices_are_already_per_million():
    from collector.deepinfra import DeepInfraCollector

    # Despite the key names, DeepInfra quotes dollars per 1M tokens. Multiplying
    # by a million here would inflate every price by 10^6.
    payload = {"data": [{
        "id": "openai/gpt-oss-120b",
        "metadata": {
            "context_length": 131072,
            "max_tokens": 32768,
            "pricing": {"input_tokens": 0.037, "output_tokens": 0.17,
                        "cache_read_tokens": 0.0037},
            "description": "gpt-oss-120b",
        },
    }]}
    patch = DeepInfraCollector().normalize(payload)["provider_models"]["openai/gpt-oss-120b"]
    assert patch["pricing"] == {
        "currency": "USD", "unit": "1M_tokens",
        "input": 0.037, "output": 0.17, "cached_input": 0.0037,
    }
    assert patch["context"] == {"window": 131072, "max_output_tokens": 32768}


def test_deepinfra_ignores_non_token_price_units():
    from collector.deepinfra import DeepInfraCollector

    # per-image, per-character and per-second prices are not token prices and
    # must never be folded into a token price.
    payload = {"data": [{
        "id": "Bria/fibo_edit",
        "metadata": {"pricing": {"per_image_unit": 0.01, "input_characters": 0.0001,
                                 "input_seconds": 0.00002}},
    }]}
    patch = DeepInfraCollector().normalize(payload)["provider_models"]["Bria/fibo_edit"]
    assert "pricing" not in patch
    assert "context" not in patch


def test_novita_and_ppio_read_the_decimal_price_only():
    from collector.novita import NovitaCollector
    from collector.ppio import PPIOCollector

    item = {
        "id": "zai-org/glm-5.3-flash",
        "context_size": 1000000,
        "max_output_tokens": 65536,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        # Mirrored in units of 1e-4 $/1M (1500 means $0.15); reading these
        # directly would be wrong by a factor of 10,000.
        "input_token_price_per_m": 1500,
        "output_token_price_per_m": 5000,
        "pricing": {
            "prompt": {"price_per_m": 1500, "price_per_m_decimal": "0.15"},
            "completion": {"price_per_m": 5000, "price_per_m_decimal": "0.5"},
            "input_cache_read": {"price_per_m": 300, "price_per_m_decimal": "0.03"},
        },
    }
    for collector in (NovitaCollector(), PPIOCollector()):
        patch = collector.normalize({"data": [item]})["provider_models"]["zai-org/glm-5.3-flash"]
        assert patch["pricing"] == {
            "currency": "USD", "unit": "1M_tokens",
            "input": 0.15, "output": 0.5, "cached_input": 0.03,
        }, collector.name
        assert patch["context"] == {"window": 1000000, "max_output_tokens": 65536}
        assert patch["modalities"] == {"input": ["text", "image"], "output": ["text"]}


def test_novita_leaves_price_unset_when_only_the_scaled_mirror_is_present():
    from collector.novita import NovitaCollector

    payload = {"data": [{"id": "deepseek/deepseek-v3.2",
                         "input_token_price_per_m": 20000,
                         "output_token_price_per_m": 30000}]}
    patch = NovitaCollector().normalize(payload)["provider_models"]["deepseek/deepseek-v3.2"]
    assert "pricing" not in patch


def test_featherless_reads_the_per_million_pair_and_ignores_per_image():
    from collector.featherless import FeatherlessCollector

    payload = {"data": [{
        "id": "openai/gpt-oss-120b",
        "context_length": 131072,
        "max_completion_tokens": 32768,
        "features": {"tool_use": True},
        # prompt/completion are per-token, input/output are the same figures per
        # million, image/request are not token prices at all.
        "pricing": {"prompt": "0.00000015", "completion": "0.0000006",
                    "input": 0.15, "output": 0.6, "image": "0.01", "request": "0"},
    }]}
    patch = FeatherlessCollector().normalize(payload)["provider_models"]["openai/gpt-oss-120b"]
    assert patch["pricing"] == {
        "currency": "USD", "unit": "1M_tokens", "input": 0.15, "output": 0.6,
    }
    assert patch["capabilities"] == {"tool_use": True}
    assert patch["context"] == {"window": 131072, "max_output_tokens": 32768}


def test_sambanova_converts_per_token_prices():
    from collector.sambanova import SambaNovaCollector

    payload = {"data": [{
        "id": "DeepSeek-V3.2",
        "context_length": 32768,
        "max_completion_tokens": 7168,
        "pricing": {"prompt": "0.00000450", "completion": "0.00001",
                    "input_cache_read": "0.00000045"},
    }]}
    patch = SambaNovaCollector().normalize(payload)["provider_models"]["DeepSeek-V3.2"]
    assert patch["pricing"] == {
        "currency": "USD", "unit": "1M_tokens",
        "input": 4.5, "output": 10.0, "cached_input": 0.45,
    }


def test_new_catalogues_create_relationship_entries_and_report_unknown_ids(sandbox):
    from collector.ppio import PPIOCollector

    rel_path = sandbox / "data/relationships/glm-5.json"
    stored = json.loads(rel_path.read_text())
    stored["providers"] = [e for e in stored["providers"] if e["provider_id"] != "ppio"]
    rel_path.write_text(json.dumps(stored))

    payload = {"data": [
        {"id": "zai-org/glm-5", "context_size": 202800,
         "pricing": {"prompt": {"price_per_m_decimal": "0.6"},
                     "completion": {"price_per_m_decimal": "2.4"}}},
        {"id": "nobody/never-heard-of-it"},
    ]}
    collector = PPIOCollector()
    report = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert report["relationships"] == ["glm-5"]
    assert report["created"] == []
    assert "nobody/never-heard-of-it" in report["unmatched"]
    doc = json.loads(rel_path.read_text())
    entry = next(e for e in doc["providers"]
                 if e["provider_id"] == "ppio" and e["model_id"] == "zai-org/glm-5")
    assert entry["pricing"]["input"] == 0.6
    # Kept because it differs from the model document's own window (204800);
    # a provider value identical to the model value is pruned instead.
    assert entry["context"]["window"] == 202800
    assert entry["sources"]

    # A second run over the same payload must change nothing. The unchanged
    # report is keyed by the provider's own model id.
    again = collector.apply(sandbox, collector.normalize(payload), write=True)
    assert again["relationships"] == []
    assert again["unchanged"] == ["zai-org/glm-5"]


def test_provider_context_identical_to_the_model_is_not_stored(sandbox):
    from collector.ppio import PPIOCollector

    # glm-5's own document already states a 204800 window, so repeating it on
    # the provider entry would be noise.
    payload = {"data": [{"id": "zai-org/glm-5", "context_size": 204800,
                         "max_output_tokens": 128000}]}
    collector = PPIOCollector()
    rel_path = sandbox / "data/relationships/glm-5.json"
    stored = json.loads(rel_path.read_text())
    stored["providers"] = [e for e in stored["providers"] if e["provider_id"] != "ppio"]
    rel_path.write_text(json.dumps(stored))

    collector.apply(sandbox, collector.normalize(payload), write=True)
    doc = json.loads(rel_path.read_text())
    entry = next(e for e in doc["providers"]
                 if e["provider_id"] == "ppio" and e["model_id"] == "zai-org/glm-5")
    assert "context" not in entry


def test_nested_objects_merge_instead_of_being_replaced():
    from collector.base import deep_merge

    # Two sources can each state a different part of the same entry: one
    # catalogue quotes a context window, a router quotes which tools that same
    # provider exposes. Replacing the whole object would make the second
    # collector erase the first one's field on every run.
    base = {"context": {"window": 131072}, "api_capabilities": {"tool_calling": True}}
    patch = {"context": {"max_output_tokens": 32768}}
    merged = deep_merge(base, patch)
    assert merged["context"] == {"window": 131072, "max_output_tokens": 32768}
    assert merged["api_capabilities"] == {"tool_calling": True}
    # Re-applying the same patch changes nothing, so a run converges.
    assert deep_merge(merged, patch) == merged


def test_null_in_a_patch_never_overwrites_a_verified_value():
    from collector.base import deep_merge

    assert deep_merge({"pricing": {"input": 1.5}}, {"pricing": None}) == {"pricing": {"input": 1.5}}


# -- the Hugging Face router ------------------------------------------------


def test_registry_includes_huggingface():
    collector = discover()["huggingface"]
    assert collector.api_url == "https://router.huggingface.co/v1/models"
    assert collector.provider_id == "huggingface"
    assert collector.env_var is None
    assert collector.creates_models is False


def test_huggingface_keeps_router_and_partner_facts_apart(sandbox):
    from collector.huggingface import HuggingFaceCollector, PARTNER_IDS

    # The router's own partner keys are mapped explicitly; unknown ones are not.
    assert PARTNER_IDS["featherless-ai"] == "featherless"
    assert PARTNER_IDS["zai-org"] == "zai"

    payload = {"data": [{
        "id": "Qwen/Qwen3-8B",
        "providers": [
            {"provider": "novita", "context_length": 1000000,
             "supports_tools": True, "supports_structured_output": False,
             "pricing": {"input": 0.3, "output": 1.2}},
            {"provider": "baseten", "context_length": 32768},
        ],
    }]}

    collector = HuggingFaceCollector()
    captured = {}
    original = collector.apply

    def spy(root, results, write=False):
        captured.update(results)
        return original(root, results, write=write)

    collector.apply = spy
    collector.fetch = lambda: payload
    report = collector.run(sandbox, write=False)

    entries = {e["provider_id"]: e for e in captured["relationships"]["qwen3-8b"]}
    assert set(entries) == {"novita", "huggingface"}

    # The partner gets the facts about that partner, and no price: the router's
    # figure is not the partner's own price.
    novita = entries["novita"]
    assert novita["model_id"] == "Qwen/Qwen3-8B"
    assert novita["context"] == {"window": 1000000}
    assert novita["api_capabilities"] == {"tool_calling": True, "structured_output": False}
    assert "pricing" not in novita

    # The router's own entry records the route and explains the missing price.
    router = entries["huggingface"]
    assert "pricing" not in router
    assert "per partner provider" in router["notes"]
    assert router["sources"]

    # An unregistered partner is reported rather than invented.
    assert any("baseten" in item for item in report["unmatched"])


def test_huggingface_resolves_repository_ids_to_registered_models(sandbox):
    from collector.huggingface import HuggingFaceCollector

    payload = {"data": [
        {"id": "Qwen/Qwen3-8B", "providers": [{"provider": "novita",
                                                "context_length": 1000000}]},
        {"id": "someone/entirely-unknown", "providers": [{"provider": "novita"}]},
    ]}
    collector = HuggingFaceCollector()
    captured = {}
    original = collector.apply
    collector.apply = lambda root, results, write=False: (
        captured.update(results) or original(root, results, write=write))
    collector.fetch = lambda: payload
    collector.run(sandbox, write=False)

    assert list(captured["relationships"]) == ["qwen3-8b"]


# -- catalog (bulk import from the two aggregator catalogues) ---------------


def _catalog():
    from collector.catalog import CatalogCollector

    return CatalogCollector()


def test_registry_includes_catalog(repo_root):
    collector = discover()["catalog"]
    assert collector.env_var is None
    assert collector.creates_models is True
    assert "openrouter.ai/api/v1/models" in collector.api_url
    assert "ai-gateway.vercel.sh/v1/models" in collector.api_url


def test_id_candidates_strips_route_variants_but_not_bedrock_versions():
    from collector.base import id_candidates

    assert "claude-opus-5.5" in id_candidates("anthropic/claude-opus-5.5:batch")
    assert "gpt-6-luna" in id_candidates("openai/gpt-6-luna:free")
    # A trailing ":0" is a Bedrock model version, never a route variant.
    assert id_candidates("meta.llama3-3-70b-instruct-v1:0") == [
        "meta.llama3-3-70b-instruct-v1:0"
    ]


def test_catalog_vendor_map_has_no_dangling_targets(sandbox):
    from collector.catalog import CatalogCollector

    collector = CatalogCollector()
    registered = {p.stem for p in (sandbox / "data/providers").glob("*.json")}
    known = registered | set(collector.new_providers)
    for vendor, provider_id in collector.aliases.items():
        assert provider_id in known, f"{vendor} -> {provider_id} is not a provider"
    for provider_id, spec in collector.new_providers.items():
        assert spec.get("website") or spec.get("documentation_url"), provider_id


def test_catalog_drops_negative_and_unparseable_prices(sandbox):
    collector = _catalog()
    assert collector._openrouter_entry(
        {"id": "a/b", "pricing": {"prompt": "-1", "completion": "0.000002"}}
    )["pricing"] == {"currency": "USD", "unit": "1M_tokens", "input": None, "output": 2.0}
    assert collector._openrouter_entry(
        {"id": "a/b", "pricing": {"prompt": "-1000000", "completion": "-1"}}
    )["pricing"] is None


def test_catalog_prefers_vercel_and_drops_markdown_descriptions(sandbox):
    collector = _catalog()
    vercel = collector._vercel_entry({
        "id": "anthropic/claude-opus-9", "name": "Claude Opus 9", "owned_by": "anthropic",
        "context_window": 200000, "max_tokens": 64000,
        "modalities": {"input": ["text", "pdf"], "output": ["text"]},
        "tags": ["tool-use", "reasoning", "explicit-caching"],
        "released": 1780000000, "description": "Short blurb.",
    })
    openrouter = collector._openrouter_entry({
        "id": "anthropic/claude-opus-9", "name": "Anthropic: Claude Opus 9",
        "context_length": 200000, "architecture": {"input_modalities": ["text"],
                                                    "output_modalities": ["text"]},
        "description": "# markdown marketing copy",
    })
    collector._records = {"claude-opus-9": {
        "model_id": "claude-opus-9", "provider_id": "anthropic",
        "entries": [openrouter, vercel],
    }}
    results = collector._build_results()
    model = results["models"]["claude-opus-9"]
    assert model["name"] == "Claude Opus 9"          # Vercel name, not the prefixed one
    assert model["description"] == "Short blurb."     # never the markdown copy
    assert model["context"] == {"window": 200000, "max_output_tokens": 64000}
    assert model["modalities"] == {"input": ["text", "file"], "output": ["text"]}
    assert model["capabilities"] == {"tool_use": True, "reasoning": True}
    assert model["release_date"] == "2026-05-28"
    assert model["required_fields"]["status"] == "active"
    # Identical specs are not repeated on the relationship entry.
    entries = {e["provider_id"]: e for e in results["relationships"]["claude-opus-9"]}
    assert set(entries) == {"vercel-ai-gateway", "openrouter"}
    assert "context" not in entries["vercel-ai-gateway"]
    assert entries["openrouter"]["model_id"] == "anthropic/claude-opus-9"


def test_catalog_records_route_variants_as_separate_provider_ids(sandbox):
    collector = _catalog()
    base = collector._openrouter_entry({"id": "poolside/laguna-s-2.1", "context_length": 1})
    free = collector._openrouter_entry(
        {"id": "poolside/laguna-s-2.1:free", "context_length": 1,
         "pricing": {"prompt": "0", "completion": "0"}}
    )
    collector._records = {"laguna-s-2.1": {
        "model_id": "laguna-s-2.1", "provider_id": "poolside",
        "entries": [free, base],
    }}
    entries = collector._build_results()["relationships"]["laguna-s-2.1"]
    assert [e["model_id"] for e in entries] == [
        "poolside/laguna-s-2.1", "poolside/laguna-s-2.1:free"
    ]
    assert entries[1]["pricing"]["input"] == 0.0


def test_catalog_downgrades_to_deprecated_on_expiration_date(sandbox):
    collector = _catalog()
    entry = collector._openrouter_entry(
        {"id": "a/b", "expiration_date": 1780000000, "context_length": 1}
    )
    collector._records = {"b": {"model_id": "b", "provider_id": "poolside",
                                "entries": [entry]}}
    model = collector._build_results()["models"]["b"]
    assert model["required_fields"]["status"] == "deprecated"


def test_catalog_never_creates_models_without_a_vendor_mapping(sandbox):
    collector = _catalog()
    entry = collector._openrouter_entry({"id": "nobody/unknown-model", "context_length": 1})
    records, unmapped, bad_id, ignored, registered = {}, set(), set(), set(), set()
    collector._add(records, entry, sandbox, registered, unmapped, bad_id, ignored)
    assert records == {}
    assert len(unmapped) == 1


def test_catalog_skips_routers_and_existing_models(sandbox):
    collector = _catalog()
    registered = {p.stem for p in (sandbox / "data/providers").glob("*.json")}
    records, unmapped, bad_id, ignored = {}, set(), set(), set()
    # openrouter/auto is a router, and gpt-5 is already registered.
    for api_id in ("openrouter/auto", "openai/gpt-5"):
        collector._add(records, collector._openrouter_entry({"id": api_id}), sandbox,
                       registered, unmapped, bad_id, ignored)
    assert records == {}
    assert any("openrouter" in item for item in ignored)


def test_catalog_writes_model_provider_document_for_a_new_vendor(sandbox):
    collector = _catalog()
    # A synthetic vendor keeps the test independent of which providers the real
    # catalogues happen to list today.
    collector.new_providers["test-vendor"] = {
        "name": "Test Vendor",
        "website": "https://example.com",
        "documentation_url": "https://example.com/docs",
        "description": "A vendor used by the tests.",
    }
    collector._records = {"brand-new-model": {
        "model_id": "brand-new-model", "provider_id": "test-vendor", "entries": [],
    }}
    created = collector.ensure_providers(sandbox, write=True)
    assert created == ["test-vendor"]
    doc = json.loads((sandbox / "data/providers/test-vendor.json").read_text())
    assert doc["id"] == "test-vendor"
    assert doc["name"] == "Test Vendor"
    assert doc["types"] == ["model_provider"]
    assert "api" not in doc                      # a model developer, not a service
    assert doc["sources"][0]["url"] == "https://example.com"
    # A provider that already has a document is never rewritten.
    assert collector.ensure_providers(sandbox, write=True) == []


def test_catalog_refuses_a_vendor_without_any_citable_url(sandbox):
    collector = _catalog()
    collector.new_providers["test-vendor"] = {"name": "Test Vendor"}
    collector._records = {"brand-new-model": {
        "model_id": "brand-new-model", "provider_id": "test-vendor", "entries": [],
    }}
    with pytest.raises(CollectorError):
        collector.ensure_providers(sandbox, write=True)


def test_catalog_leaves_registered_models_untouched(sandbox):
    collector = _catalog()
    before = json.loads((sandbox / "data/models/gpt-5.json").read_text())
    entry = collector._openrouter_entry({
        "id": "openai/gpt-5", "context_length": 4242,
        "pricing": {"prompt": "0.0000099", "completion": "0.000099"},
    })
    records, unmapped, bad_id, ignored = {}, set(), set(), set()
    registered = {p.stem for p in (sandbox / "data/providers").glob("*.json")}
    collector._add(records, entry, sandbox, registered, unmapped, bad_id, ignored)
    assert records == {}
    report = collector.apply(sandbox, collector._build_results(), write=True)
    assert report["created"] == []
    assert json.loads((sandbox / "data/models/gpt-5.json").read_text()) == before
