# Model Info

**Model Info** is a static, open-source JSON data source for AI models and the API providers that serve them.

It answers two questions in one place:

1. **What are this model's specs?** (context window, modalities, capabilities, pricing, status)
2. **Through which provider can I use it, and how do I connect?** (model id per provider, base URL, API style, endpoints, authentication, per-provider pricing)

Model Info does **not** execute models, proxy API requests, rank models, or recommend models. It stores verified facts, validates them against JSON Schemas, and serves them as static JSON — nothing else.

日本語版: [README.ja.md](README.ja.md)

## Core concepts

```text
Model          -> specs of one model (developed by a model provider)
Provider       -> one service (may be a model provider, an API provider, ...)
Model x Provider -> "this model is available through this provider"
```

**Model Provider ≠ API Provider.** A DeepSeek model may be served by DeepSeek itself, by OpenRouter, and by OpenCode. Model Info models this explicitly:

- `data/models/*.json` — the model itself (`model_provider` = who develops it)
- `data/providers/*.json` — each service (`types` = which roles it plays: `model_provider`, `api_provider`, `aggregator`, `gateway`, `runtime`, `platform`)
- `data/relationships/*.json` — per-provider availability, including provider-specific model ids and overrides

**OpenCode Zen and OpenCode Go** are two separate providers (`opencode` and `opencode-go`): different base URLs, different model catalogs, different pricing. Because a service can offer several ids for the same model (aliases, free tiers), one relationship may list the same provider more than once, each entry with its own `model_id`.

Runtimes such as Ollama, llama.cpp, or vLLM are **not** API providers. Runtime support is recorded on the model itself via the optional `runtime` map.

## Repository layout

```text
model-info/
├── data/                      # source of truth (hand-edited / collector output)
│   ├── models/{model_id}.json
│   ├── providers/{provider_id}.json
│   └── relationships/{model_id}.json
├── schemas/v1/                # JSON Schemas (draft 2020-12)
│   ├── model.schema.json
│   ├── provider.schema.json
│   └── model-provider.schema.json
├── v1/                        # generated static API (committed, served by GitHub Pages)
├── collector/                 # manual Python collectors (never run automatically)
├── scripts/
│   ├── validate.py            # schema + integrity + secret scanning
│   └── build.py               # validate -> generate v1/
├── tests/                     # pytest
├── README.md / README.ja.md
└── .nojekyll
```

## API (static files)

Model Info is served as plain files — each logical endpoint has two URLs: `….json` and `…/index.json` (GitHub Pages cannot serve extensionless paths).

| Logical request | Static file |
| --- | --- |
| `GET /v1/models` | `v1/models.json` or `v1/models/index.json` |
| `GET /v1/models/{model_id}` | `v1/models/{model_id}.json` or `v1/models/{model_id}/index.json` |
| `GET /v1/providers` | `v1/providers.json` or `v1/providers/index.json` |
| `GET /v1/providers/{provider_id}` | `v1/providers/{provider_id}.json` or `v1/providers/{provider_id}/index.json` |
| `GET /v1/providers/{provider_id}/models` | `v1/providers/{provider_id}/models.json` or `…/models/index.json` |

On GitHub Pages the files are served from the repository root, e.g.
`https://<user>.github.io/<repo>/v1/models.json`.

A model detail response bundles everything a client needs to connect:

```json
{
  "model": { "model_id": "deepseek-v4-pro", "context": { "window": 1048576 }, "...": "..." },
  "providers": [
    {
      "provider_id": "deepseek",
      "model_id": "deepseek-v4-pro",
      "provider": {
        "api": {
          "base_url": "https://api.deepseek.com",
          "api_style": "openai_compatible",
          "authentication": { "type": "bearer" }
        }
      }
    },
    {
      "provider_id": "openrouter",
      "model_id": "deepseek/deepseek-v4-pro",
      "pricing": { "currency": "USD", "unit": "1M_tokens", "input": 0.7433, "output": 1.4867 },
      "provider": { "...": "..." }
    },
    {
      "provider_id": "opencode",
      "model_id": "deepseek-v4-pro",
      "pricing": { "currency": "USD", "unit": "1M_tokens", "input": 1.74, "output": 3.48, "cached_input": 0.145 }
    },
    {
      "provider_id": "opencode-go",
      "model_id": "deepseek-v4-pro",
      "pricing": { "currency": "USD", "unit": "1M_tokens", "input": 0.66, "output": 1.98, "cached_input": 0.022 }
    }
  ]
}
```

### Override semantics (Model × Provider)

For optional keys inside a relationship entry:

| Form | Meaning |
| --- | --- |
| key omitted | inherit the value from the model document |
| `null` | unknown at this provider |
| value present | override the model-level value |

The same rule applies to `model.provider_pricing` (a model-level shortcut keyed by `provider_id`); if both are present they must agree — validation enforces it.

Nested objects inside a relationship entry (`pricing`, `context`, `modalities`, `capabilities`, `api_capabilities`) **replace the model-level object wholesale**: fields omitted inside the replacement are unknown at that provider, not inherited.

## Data rules

- **Never guess.** Unknown context windows, prices, or capabilities are `null` (or the key is omitted) — never `0`, never inferred.
- **Every fact has sources.** `sources[]` records `type` (`official`/`documentation`/`community`/`manual`), `url`, and `retrieved_at`.
- **No secrets, ever.** API keys are never stored. Validation scans all data files for credential-like strings and fails the build.
- **Enums**: `status` = `active | preview | experimental | deprecated | retired | unknown`; `api_style` = `openai_compatible | anthropic | google_generative_ai | custom`; `authentication.type` = `bearer | api_key | oauth | none | custom`; modalities = `text | image | audio | video | file`.
- Dates are `YYYY-MM-DD`. Prices are per `unit` (`1M_tokens` by default) in `currency`.

See `schemas/v1/*.schema.json` for the full field reference — the schemas are the contract.

## Workflow

Everything is manual by design: no GitHub Actions, no cron, no auto-update, no admin UI.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/validate.py    # validate data/ against the schemas + rules
.venv/bin/python scripts/build.py       # regenerate v1/ (refuses to build on errors)
.venv/bin/python -m pytest              # tests
```

Commit `data/` changes together with the regenerated `v1/` output.

### Collectors (manual)

Collectors fetch official endpoints, normalize the response, and merge it into `data/` — they never commit and never store keys (keys come from environment variables only).

```bash
.venv/bin/python -m collector --list
.venv/bin/python -m collector openrouter          # dry run (no key required)
.venv/bin/python -m collector openrouter --write  # apply
export OPENAI_API_KEY=...                         # keys live only in your shell
.venv/bin/python -m collector openai --write
```

Available collectors: `openai`, `anthropic`, `google`, `deepseek`, `mistral`, `openrouter` (public, no key), `opencode` (public, no key), `opencode-go` (public, no key), `groq` (public, no key), `together` (public, no key), `fireworks` (public, no key).

`groq`, `together` and `fireworks` publish their catalogues as Markdown documentation rather than as a JSON API, so they read the `.md` page instead (`collector/docs.py`) — still no key involved. `normalize()` receives the raw text and each collector decides which column is the context window and which one is the price.

Collectors only **update facts they can read from the source**. Anything else keeps its hand-verified value; ids that do not match a registered model are reported as *needs manual review* instead of being invented. A provider model id that *does* resolve to a registered model gets its relationship entry created (vendor prefix, letter case, Fireworks' `p` decimal escape, snapshot suffixes and the model's own `version` are the only rewrites applied) — but a collector never creates a model document. Run `validate.py` and `build.py` afterwards.

### Adding data by hand

1. **Model**: create `data/models/{model_id}.json` (required: `model_id`, `name`, `model_provider`, `status`, `updated_at`).
2. **Provider**: create `data/providers/{provider_id}.json` (required: `id`, `name`, `types`, `status`, `updated_at`); put `base_url`, `api_style`, endpoints, and authentication under `api`.
3. **Relationship**: create `data/relationships/{model_id}.json` listing every provider that serves the model (with its provider-specific `model_id`).
4. Run `scripts/validate.py`, then `scripts/build.py`, then commit both `data/` and `v1/`.

### Publishing on GitHub Pages

Push the repository and enable GitHub Pages (serve from the branch root). `.nojekyll` is included; no Actions workflow is needed or wanted. Updates happen only when someone edits `data/`, runs the build, and commits.

## Non-goals

No auto-updates, no scraping schedules, no GitHub Actions, no update buttons, no admin panel, no database, no server-side API, no API key storage, no proxying, no rankings, no recommendations, no benchmarks, no usage metering.
