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
            "vercel-ai-gateway"} <= set(registry)


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

