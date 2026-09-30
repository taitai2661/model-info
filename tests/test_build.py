import json
from pathlib import Path

from jsonschema import Draft202012Validator

from build import assemble, write_outputs


def _schema(repo_root, name):
    return Draft202012Validator(
        json.loads((repo_root / "schemas/v1" / name).read_text(encoding="utf-8")))


def _load_outputs(outputs, path):
    return json.loads(outputs[path])


def test_assemble_produces_all_endpoints(repo_root):
    outputs = assemble(repo_root)
    model_ids = sorted(p.stem for p in (repo_root / "data/models").glob("*.json"))
    provider_ids = sorted(p.stem for p in (repo_root / "data/providers").glob("*.json"))
    assert "models.json" in outputs
    assert "providers.json" in outputs
    for mid in model_ids:
        assert f"models/{mid}.json" in outputs
        assert f"models/{mid}/index.json" in outputs
    for pid in provider_ids:
        assert f"providers/{pid}.json" in outputs
        assert f"providers/{pid}/models.json" in outputs
        assert f"providers/{pid}/models/index.json" in outputs


def test_index_files_mirror_json_files(repo_root):
    outputs = assemble(repo_root)
    mirrored = [(p, p.rsplit(".json", 1)[0] + "/index.json") for p in outputs
                if not p.endswith("/index.json")]
    for plain, index in mirrored:
        assert outputs[plain] == outputs[index], f"{plain} != {index}"


def test_model_list_items_match_model_schema(repo_root):
    outputs = assemble(repo_root)
    validator = _schema(repo_root, "model.schema.json")
    items = _load_outputs(outputs, "models.json")
    assert isinstance(items, list) and items
    for item in items:
        assert list(validator.iter_errors(item)) == []


def test_model_detail_shape(repo_root):
    outputs = assemble(repo_root)
    model_validator = _schema(repo_root, "model.schema.json")
    entry_validator = Draft202012Validator({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": json.loads(
            (repo_root / "schemas/v1/model-provider.schema.json").read_text()
        )["$defs"],
        "$ref": "#/$defs/providerEntry",
    })
    provider_validator = _schema(repo_root, "provider.schema.json")
    for path in [p for p in outputs if p.startswith("models/") and p.endswith(".json")
                 and "/index" not in p]:
        detail = _load_outputs(outputs, path)
        assert set(detail) == {"model", "providers"}
        assert list(model_validator.iter_errors(detail["model"])) == []
        for entry in detail["providers"]:
            provider_doc = entry.pop("provider")
            assert list(entry_validator.iter_errors(entry)) == []
            assert list(provider_validator.iter_errors(provider_doc)) == []
            assert provider_doc["id"] == entry["provider_id"]
            entry["provider"] = provider_doc


def test_provider_detail_and_models(repo_root):
    outputs = assemble(repo_root)
    provider_validator = _schema(repo_root, "provider.schema.json")
    model_validator = _schema(repo_root, "model.schema.json")
    for path in [p for p in outputs if p.startswith("providers/") and p.endswith(".json")
                 and p.count("/") == 1 and not p.endswith("/index.json")]:
        detail = _load_outputs(outputs, path)
        assert set(detail) == {"provider", "model_ids"}
        assert list(provider_validator.iter_errors(detail["provider"])) == []
    for path in [p for p in outputs if p.endswith("/models.json")]:
        items = _load_outputs(outputs, path)
        for item in items:
            assert set(item) == {"model", "relationship"}
            assert list(model_validator.iter_errors(item["model"])) == []


def test_build_is_deterministic(repo_root):
    first = assemble(repo_root)
    second = assemble(repo_root)
    assert first == second
    for rel, content in first.items():
        existing = repo_root / "v1" / rel
        if existing.is_file():
            assert existing.read_text(encoding="utf-8") == content, (
                f"committed {rel} is stale; re-run scripts/build.py"
            )


def test_write_outputs_roundtrip(repo_root, tmp_path):
    outputs = assemble(repo_root)
    write_outputs(tmp_path, outputs)
    rebuilt = assemble(repo_root)
    for rel, content in rebuilt.items():
        assert (tmp_path / rel).read_text(encoding="utf-8") == content


def test_detail_exposes_connection_info(repo_root):
    outputs = assemble(repo_root)
    detail = _load_outputs(outputs, "models/deepseek-v4-pro.json")
    by_provider = {e["provider_id"]: e for e in detail["providers"]}
    assert {"deepseek", "openrouter", "opencode", "opencode-go"} <= set(by_provider)
    # OpenRouter serves this model under more than one id; use the canonical one.
    openrouter = next(e for e in detail["providers"]
                      if e["provider_id"] == "openrouter"
                      and e["model_id"] == "deepseek/deepseek-v4-pro")
    assert openrouter["pricing"]["input"] > 0          # OpenRouter's own price
    assert openrouter["provider"]["api"]["base_url"] == "https://openrouter.ai/api/v1"
    assert by_provider["opencode"]["pricing"]["input"] == 1.74    # Zen price differs
    assert by_provider["opencode-go"]["pricing"]["input"] == 0.66  # Go off-peak price
    assert by_provider["deepseek"]["provider"]["api"]["api_style"] == "openai_compatible"
    glm = _load_outputs(outputs, "models/glm-5.json")
    glm_go = next(e for e in glm["providers"] if e["provider_id"] == "opencode-go")
    assert glm_go["pricing"] is None, "unknown Go price must stay null"
    # A gateway records its own model id and, when it publishes no price, says so
    # instead of inheriting the first-party one.
    bedrock = next(e for e in glm["providers"] if e["provider_id"] == "aws-bedrock")
    assert bedrock["model_id"] == "zai.glm-5"
    assert bedrock["pricing"] is None
    assert bedrock["provider"]["api"]["base_url"].startswith("https://bedrock-runtime.")


def test_gpt6_detail_exposes_model_and_provider_reasoning_levels(repo_root):
    outputs = assemble(repo_root)
    levels = ["low", "medium", "high", "xhigh", "max"]
    base_modes = {
        "gpt-5.6-sol": True,
        "gpt-5.6-luna": True,
        "gpt-5.6-terra": True,
        "gpt-6-astra": False,
        "gpt-6-sol": True,
        "gpt-6-luna": True,
        "gpt-6.1-sol": False,
    }
    for model_id, supports_none in base_modes.items():
        detail = _load_outputs(outputs, f"models/{model_id}.json")
        expected_default = None if model_id == "gpt-6-astra" else "medium"
        assert detail["model"]["reasoning"] == {
            "parameter": "reasoning.effort",
            "effort_levels": levels,
            "default_effort": expected_default,
            "supports_none": supports_none,
            "mode_parameter": "reasoning.mode",
            "modes": ["standard", "pro"],
            "default_mode": "standard",
        }
        assert "fast" in detail["model"]["service_tier"]["options"]

    pro_aliases = {
        "gpt-5.6-sol": ("openai/gpt-5.6-sol-pro", "openai/gpt-5.6-sol-pro:batch"),
        "gpt-5.6-luna": ("openai/gpt-5.6-luna-pro", "openai/gpt-5.6-luna-pro:batch"),
        "gpt-5.6-terra": ("openai/gpt-5.6-terra-pro", "openai/gpt-5.6-terra-pro:batch"),
        "gpt-6-astra": ("openai/gpt-6-astra-pro", "openai/gpt-6-astra-pro:batch"),
        "gpt-6-sol": ("openai/gpt-6-sol-pro", "openai/gpt-6-sol-pro:batch"),
        "gpt-6-luna": ("openai/gpt-6-luna-pro", "openai/gpt-6-luna-pro:batch"),
        "gpt-6.1-sol": ("openai/gpt-6.1-sol-pro", "openai/gpt-6.1-sol-pro:batch"),
    }
    for model_id, aliases in pro_aliases.items():
        detail = _load_outputs(outputs, f"models/{model_id}.json")
        openrouter = {e["model_id"]: e for e in detail["providers"]
                      if e["provider_id"] == "openrouter"}
        assert set(aliases) <= set(openrouter)
        assert all(openrouter[alias]["api_variant"]["reasoning_mode"] == "pro"
                   for alias in aliases)

    fast_aliases = {
        "gpt-5.6-sol": "openai/gpt-5.6-sol-fast",
        "gpt-5.6-luna": "openai/gpt-5.6-luna-fast",
        "gpt-5.6-terra": "openai/gpt-5.6-terra-fast",
        "gpt-6-astra": "openai/gpt-6-astra-fast",
        "gpt-6-sol": "openai/gpt-6-sol-fast",
        "gpt-6-luna": "openai/gpt-6-luna-fast",
    }
    for model_id, alias in fast_aliases.items():
        detail = _load_outputs(outputs, f"models/{model_id}.json")
        vercel = next(e for e in detail["providers"]
                      if e["provider_id"] == "vercel-ai-gateway"
                      and e["model_id"] == alias)
        assert vercel["api_variant"]["service_tier"] == "fast"

    all_models = {m["model_id"] for m in _load_outputs(outputs, "models.json")}
    pro_model_ids = {alias for group in pro_aliases.values() for alias in group}
    assert not (pro_model_ids & all_models)
    assert not (set(fast_aliases.values()) & all_models)


def test_verified_non_openai_aliases_are_attached_to_base_models(repo_root):
    outputs = assemble(repo_root)
    checks = {
        "kimi-k2.7-code": {
            "vercel-ai-gateway": "moonshotai/kimi-k2.7-code-highspeed",
        },
        "minimax-m2.1": {
            "vercel-ai-gateway": "minimax/minimax-m2.1-lightning",
            "minimax": "MiniMax-M2.1-highspeed",
        },
        "minimax-m2.5": {
            "minimax": "MiniMax-M2.5-highspeed",
            "vercel-ai-gateway": "minimax/minimax-m2.5-highspeed",
        },
        "minimax-m2.7": {
            "minimax": "MiniMax-M2.7-highspeed",
            "vercel-ai-gateway": "minimax/minimax-m2.7-highspeed",
        },
        "grok-4.3": {
            "xai": "grok-4-1-fast-reasoning",
            "vercel-ai-gateway": "spacexai/grok-4.1-fast-reasoning",
        },
    }
    for base_id, aliases in checks.items():
        detail = _load_outputs(outputs, f"models/{base_id}.json")
        ids = {(entry["provider_id"], entry["model_id"]): entry
               for entry in detail["providers"]}
        for provider_id, model_id in aliases.items():
            assert (provider_id, model_id) in ids
            assert ids[(provider_id, model_id)]["api_variant"]

    deepseek = _load_outputs(outputs, "models/deepseek-v4.1-flash.json")
    assert any(e["provider_id"] == "deepseek" and e["model_id"] == "deepseek-flash"
               for e in deepseek["providers"])

    all_models = {m["model_id"] for m in _load_outputs(outputs, "models.json")}
    removed_aliases = {
        "kimi-k2.7-code-highspeed",
        "minimax-m2.1-lightning",
        "minimax-m2.5-highspeed",
        "minimax-m2.7-highspeed",
        "grok-4.1-fast-reasoning",
        "grok-4.1-fast-non-reasoning",
    }
    assert not (removed_aliases & all_models)


def test_provider_models_endpoint_lists_models_with_overrides(repo_root):
    outputs = assemble(repo_root)
    items = _load_outputs(outputs, "providers/openrouter/models.json")
    rel_dir = repo_root / "data/relationships"
    expected = sum(
        1 for path in rel_dir.glob("*.json")
        for e in json.loads(path.read_text())["providers"]
        if e["provider_id"] == "openrouter"
    )
    assert len(items) == expected >= 15
    ids = {i["model"]["model_id"] for i in items}
    assert "deepseek-v4-pro" in ids
    entry = next(i["relationship"] for i in items
                 if i["model"]["model_id"] == "deepseek-v4-pro")
    assert entry["model_id"] == "deepseek/deepseek-v4-pro"
