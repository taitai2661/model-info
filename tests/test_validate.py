import json
from pathlib import Path

from jsonschema import Draft202012Validator

from validate import validate_all


def test_schemas_are_valid(repo_root):
    for name in ("model.schema.json", "provider.schema.json", "model-provider.schema.json"):
        schema = json.loads((repo_root / "schemas/v1" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_all_source_data_is_valid(repo_root):
    errors, _ = validate_all(repo_root)
    assert errors == [], "\n".join(errors)


def test_invalid_status_is_rejected(sandbox):
    path = sandbox / "data/models/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["status"] = "deprecatedd"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("status" in e for e in errors)


def test_unknown_field_is_rejected(sandbox):
    path = sandbox / "data/providers/openai.json"
    doc = json.loads(path.read_text())
    doc["base_urll"] = "https://example.com"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("base_urll" in e for e in errors)


def test_bad_url_is_rejected(sandbox):
    path = sandbox / "data/providers/openai.json"
    doc = json.loads(path.read_text())
    doc["website"] = "ftp://openai.com"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("scheme" in e for e in errors)


def test_base_url_with_query_is_rejected(sandbox):
    path = sandbox / "data/providers/openai.json"
    doc = json.loads(path.read_text())
    doc["api"]["base_url"] = "https://api.openai.com/v1?apikey=abc"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("query or fragment" in e for e in errors)


def test_endpoint_must_be_a_path(sandbox):
    path = sandbox / "data/providers/openai.json"
    doc = json.loads(path.read_text())
    doc["api"]["endpoints"]["chat_completions"] = "https://api.openai.com/v1/chat/completions"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("endpoint" in e or "path" in e for e in errors)


def test_missing_relationship_provider_is_rejected(sandbox):
    path = sandbox / "data/relationships/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["providers"].append({"provider_id": "nope", "model_id": "nope"})
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("not a registered provider" in e for e in errors)


def test_duplicate_provider_entry_is_rejected(sandbox):
    path = sandbox / "data/relationships/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["providers"].append(dict(doc["providers"][0]))
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("duplicate entry for provider_id" in e for e in errors)


def test_multiple_entries_per_provider_are_allowed(sandbox):
    path = sandbox / "data/relationships/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    base = doc["providers"][0]
    doc["providers"].append({**base, "model_id": base["model_id"] + "-free"})
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert errors == [], errors


def test_filename_must_match_id(sandbox):
    path = sandbox / "data/models/some-other-name.json"
    doc = json.loads((sandbox / "data/models/gpt-6-astra.json").read_text())
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("does not match file name" in e for e in errors)


def test_bad_date_is_rejected(sandbox):
    path = sandbox / "data/models/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["updated_at"] = "2026-13-45"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("updated_at" in e for e in errors)


def test_pricing_requires_currency_and_unit(sandbox):
    path = sandbox / "data/models/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["pricing"]["currency"] = None
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("currency is required" in e for e in errors)


def test_stored_secret_is_rejected(sandbox):
    path = sandbox / "data/providers/openai.json"
    doc = json.loads(path.read_text())
    doc["description"] = "key is sk-proj-abcdefghijklmnopqrstuvwx"
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("secret" in e for e in errors)


def test_invalid_modality_is_rejected(sandbox):
    path = sandbox / "data/models/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["modalities"]["input"].append("smell")
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("modalities" in e or "smell" in e for e in errors)


def test_every_model_has_at_least_one_source(repo_root):
    for path in (repo_root / "data/models").glob("*.json"):
        doc = json.loads(path.read_text())
        assert doc.get("sources"), f"{path.name} has no sources"


def test_partial_pricing_without_currency_is_rejected(sandbox):
    path = sandbox / "data/relationships/gpt-6-astra.json"
    doc = json.loads(path.read_text())
    doc["providers"][0]["pricing"] = {"input": 1}
    path.write_text(json.dumps(doc))
    errors, _ = validate_all(sandbox)
    assert any("currency is required" in e for e in errors)


def test_opencode_go_provider_is_registered(repo_root):
    doc = json.loads((repo_root / "data/providers/opencode-go.json").read_text())
    assert doc["types"] == ["api_provider", "aggregator", "gateway"]
    assert doc["api"]["base_url"] == "https://opencode.ai/zen/go/v1"
    assert doc["api"]["endpoints"]["messages"] == "/messages"


def test_zen_and_go_are_separate_providers(repo_root):
    zen = json.loads((repo_root / "data/providers/opencode.json").read_text())
    go = json.loads((repo_root / "data/providers/opencode-go.json").read_text())
    assert zen["id"] == "opencode" and zen["name"] == "OpenCode Zen"
    assert go["id"] == "opencode-go"
    assert zen["api"]["base_url"] != go["api"]["base_url"]


def test_provider_can_have_several_model_ids(repo_root):
    doc = json.loads((repo_root / "data/relationships/deepseek-flash.json").read_text())
    go_ids = sorted(e["model_id"] for e in doc["providers"]
                    if e["provider_id"] == "opencode-go")
    assert go_ids == ["deepseek-flash", "deepseek-v4.1-flash"]
    zen_ids = [e["model_id"] for e in doc["providers"] if e["provider_id"] == "opencode"]
    assert zen_ids == ["deepseek-v4.1-flash"]


def test_zen_deprecation_is_entry_level(repo_root):
    doc = json.loads((repo_root / "data/relationships/glm-5.json").read_text())
    model = json.loads((repo_root / "data/models/glm-5.json").read_text())
    assert model["status"] == "active", "upstream model is still listed by Z.ai"
    zen = next(e for e in doc["providers"] if e["provider_id"] == "opencode")
    assert zen["status"] == "deprecated"
    assert "2026-05-14" in zen["notes"]


def test_provider_pricing_differences_are_recorded(repo_root):
    doc = json.loads((repo_root / "data/relationships/deepseek-v4-pro.json").read_text())
    model = json.loads((repo_root / "data/models/deepseek-v4-pro.json").read_text())
    assert model["pricing"]["input"] == 0.66
    by = {(e["provider_id"], e["model_id"]): e for e in doc["providers"]}
    assert by[("opencode", "deepseek-v4-pro")]["pricing"]["input"] == 1.74      # Zen price
    assert by[("opencode-go", "deepseek-v4-pro")]["pricing"]["input"] == 0.66   # Go off-peak price
    # OpenRouter serves this model under more than one id and prices each of
    # them itself, so every entry carries a price instead of inheriting the
    # model-level one (a match with the model price would be pruned away).
    openrouter = [e for (pid, _), e in by.items() if pid == "openrouter"]
    assert openrouter
    for entry in openrouter:
        assert entry["pricing"]["input"] > 0
