# Model Info

**Model Info** is a static, open-source JSON data source for AI models and the API providers that serve them.

It answers two questions in one place:

1. **What are this model's specs?** (context window, modalities, capabilities, pricing, status)
2. **Through which provider can I use it, and how do I connect?** (model id per provider, base URL, API style, endpoints, authentication, per-provider pricing)

Model Info does **not** execute models, proxy API requests, rank models, or recommend models. It stores verified facts, validates them against JSON Schemas, and serves them as static JSON — nothing else.

A static search site for the data lives at the repository root (`index.html` + `web/`), published by two static hosts that serve the same files: **Cloudflare Pages** at https://model-info.ta26.top/ and **GitHub Pages** at https://taitai2661.github.io/model-info/. Open the repo root in a browser to browse models and providers by keyword, filter by capability/modalities/status, and view per-provider connection details. No build step, no framework — vanilla HTML/CSS/JS fetching the committed `v1/` JSON at runtime. A standalone, bilingual reference for the `v1/` files is at `api.html`.

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

**OpenCode Zen and OpenCode Go** are two separate providers (`opencode` and `opencode-go`): different base URLs, different model catalogs, different pricing. Because a service can offer several ids for the same model (aliases, free tiers), one relationship may list the same provider more than once, each entry with its own `model_id`. **Vercel AI Gateway** (`vercel-ai-gateway`) is another such aggregator: one OpenAI-compatible endpoint routing to hundreds of third-party models with vendor-prefixed ids (`openai/gpt-5`, `anthropic/claude-sonnet-4-5`, …), BYOK or OIDC.

Runtimes such as Ollama, llama.cpp, or vLLM are **not** API providers. Runtime support is recorded on the model itself via the optional `runtime` map.

**Every fact is entered by hand.** There are no collectors, no scrapers and no import jobs — a person reads a source and writes the JSON. See [Adding data by hand](#adding-data-by-hand).

## Repository layout

```text
model-info/
├── data/                      # source of truth, hand-edited
│   ├── models/{model_id}.json
│   ├── providers/{provider_id}.json
│   └── relationships/{model_id}.json
├── schemas/v1/                # JSON Schemas (draft 2020-12)
│   ├── model.schema.json
│   ├── provider.schema.json
│   └── model-provider.schema.json
├── v1/                        # generated static API (committed, served by Cloudflare Pages + GitHub Pages)
├── scripts/
│   ├── new.py                 # scaffold a model / provider / relationship document
│   ├── validate.py            # schema + integrity + secret scanning
│   ├── build.py               # validate -> generate v1/
│   └── make_icons.py          # regenerate the PNG app icons from favicon.svg
├── web/                       # search site (HTML/CSS/JS) + api.html
├── favicon.svg / icon-*.png   # site icon set
├── tests/                     # pytest
├── README.md / README.ja.md
└── .nojekyll
```

## API (static files)

Model Info is served as plain files — each logical endpoint has two URLs: `….json` and `…/index.json` (static hosting cannot serve extensionless paths).

| Logical request | Static file |
| --- | --- |
| `GET /v1/models` | `v1/models.json` or `v1/models/index.json` |
| `GET /v1/models/{model_id}` | `v1/models/{model_id}.json` or `v1/models/{model_id}/index.json` |
| `GET /v1/providers` | `v1/providers.json` or `v1/providers/index.json` |
| `GET /v1/providers/{provider_id}` | `v1/providers/{provider_id}.json` or `v1/providers/{provider_id}/index.json` |
| `GET /v1/providers/{provider_id}/models` | `v1/providers/{provider_id}/models.json` or `…/models/index.json` |

Both hosts publish identical files from the deployment root, e.g.
`https://model-info.ta26.top/v1/models.json` and
`https://taitai2661.github.io/model-info/v1/models.json`.

`api.html` renders this section as a browsable page, with the endpoint table,
copyable request examples and links to the JSON Schemas.

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
    },
    {
      "provider_id": "vercel-ai-gateway",
      "model_id": "deepseek/deepseek-v4-pro",
      "context": { "window": 1000000, "max_output_tokens": 384000 }
    }
  ]
}
```

Reasoning mode and effort are separate controls. `model.reasoning` describes the supported `reasoning.mode` options (`standard`, `pro`) and `reasoning.effort` levels; `model.service_tier` describes request processing options such as `fast`. `providers[].api_variant` identifies a provider-specific alias that selects a mode or tier while remaining attached to the same base model.

```json
{
  "reasoning": {
    "parameter": "reasoning.effort",
    "effort_levels": ["low", "medium", "high", "xhigh", "max"],
    "default_effort": "medium",
    "supports_none": false,
    "mode_parameter": "reasoning.mode",
    "modes": ["standard", "pro"],
    "default_mode": "standard"
  },
  "service_tier": {
    "parameter": "service_tier",
    "options": ["fast"]
  }
}
```

A provider-specific alias keeps its provider model ID and the setting selected by that alias in `providers[].api_variant`. The selected reasoning effort and non-parameter throughput variants are also represented separately:

```json
{
  "provider_id": "openrouter",
  "model_id": "openai/gpt-6-sol-pro",
  "api_variant": { "reasoning_mode": "pro" }
}
```

```json
{
  "provider_id": "vercel-ai-gateway",
  "model_id": "moonshotai/kimi-k2.7-code-highspeed",
  "api_variant": { "performance_variant": "highspeed" }
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

Nested objects inside a relationship entry (`pricing`, `context`, `modalities`, `capabilities`, `reasoning`, `service_tier`, `api_variant`, `api_capabilities`) **replace the model-level object wholesale**: fields omitted inside the replacement are unknown at that provider, not inherited.

## Data rules

- **Never guess.** Unknown context windows, prices, or capabilities are `null` (or the key is omitted) — never `0`, never inferred. `0` is only meaningful for a price (an explicitly free tier); a context size of `0` is rejected by `validate.py`, because upstream it means "not applicable" (image, video and embedding models have no token budget).
- **Every fact has sources.** `sources[]` records `type` (`official`/`documentation`/`community`/`manual`), `url`, and `retrieved_at`. `official` is the vendor's own page; `documentation` is a third party describing the vendor's model.
- **No secrets, ever.** API keys are never stored. Validation scans all data files for credential-like strings and fails the build.
- **Enums**: `status` = `active | preview | experimental | deprecated | retired | unknown`; `api_style` = `openai_compatible | anthropic | google_generative_ai | custom`; `authentication.type` = `bearer | api_key | oauth | none | custom`; modalities = `text | image | audio | video | file`.
- Dates are `YYYY-MM-DD`. Prices are per `unit` (`1M_tokens` by default) in `currency`.

See `schemas/v1/*.schema.json` for the full field reference — the schemas are the contract.

## Workflow

Everything is manual by design: no GitHub Actions, no cron, no auto-update, no scrapers, no admin UI.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/new.py ...     # scaffold a document (optional but recommended)
.venv/bin/python scripts/validate.py    # validate data/ against the schemas + rules
.venv/bin/python scripts/build.py       # regenerate v1/ (refuses to build on errors)
.venv/bin/python -m pytest              # tests
```

Commit `data/` changes together with the regenerated `v1/` output.

## Adding data by hand

This is the only way data gets added. Three documents describe each fact; write them in this order and cite a source for every number.

### 1. Provider — `data/providers/{provider_id}.json`

Required: `id`, `name`, `types`, `status`, `updated_at`. A provider can hold several roles at once — list every one that applies:

| type | Meaning |
| --- | --- |
| `model_provider` | develops the models |
| `api_provider` | sells API access to its own (or others') models |
| `aggregator` / `gateway` | resells many third-party models through one endpoint |
| `runtime` / `platform` | executes models (Ollama, vLLM, …) — never an API provider |

Connection details live under `api`: `base_url` (the API root only, no path, query or fragment), `api_style` (`openai_compatible` / `anthropic` / `google_generative_ai` / `custom`), `authentication.type`, and endpoint **paths** under `endpoints` (e.g. `"chat_completions": "/chat/completions"` — a path, never a URL).

### 2. Model — `data/models/{model_id}.json`

Required: `model_id`, `name`, `model_provider`, `status`, `updated_at`. `model_provider` must be a registered provider whose types include `model_provider`. `model_id` must equal the file name and follow `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.

Optional but valuable: `context` (`window`, `max_output_tokens`, `max_input_tokens`, `reasoning_tokens`, …), `modalities`, `capabilities`, `reasoning`, `service_tier`, `pricing`, `runtime`, `availability`, `release_date`, `family`, `version`, `provider_pricing`.

### 3. Relationship — `data/relationships/{model_id}.json`

Required: `model_id`, `providers[]` (at least one entry). Each entry lists a `provider_id` and that provider's own `model_id` for the model, plus any per-provider override (see [override semantics](#override-semantics-model--provider)). List the same provider multiple times to record aliases or free tiers — one entry per `model_id`.

Providers whose id resolves through a vendor prefix (e.g. OpenRouter's `deepseek/deepseek-v4-pro`) keep that id here; the canonical model stays one document.

### Scaffold it instead of typing JSON

`scripts/new.py` writes a correctly shaped, schema-valid stub and then runs validation:

```bash
# a provider (repeat --type for several roles)
.venv/bin/python scripts/new.py provider acme \
  --name "Acme AI" --type model_provider --type api_provider \
  --website https://acme.example --base-url https://api.acme.example/v1 \
  --api-style openai_compatible --auth bearer \
  --source https://acme.example/docs

# a model owned by that provider
.venv/bin/python scripts/new.py model acme-1 \
  --name "Acme One" --provider acme --context 200000 --modalities text,image \
  --source https://acme.example/models/acme-1

# one or more providers that serve it (provider[:provider_model_id])
.venv/bin/python scripts/new.py relationship acme-1 \
  --entry acme:acme-1-2026 --entry openrouter:acme/acme-1 \
  --source https://acme.example/docs

.venv/bin/python scripts/new.py list     # list registered providers and models
```

`new.py` never overwrites an existing document unless you pass `--force`, and it will not let you invent a model provider that is not registered. Re-running `relationship` **extends** an existing file with any new providers you name. After scaffolding, fill in the facts you know from the cited source, then:

```bash
.venv/bin/python scripts/validate.py    # catches schema and integrity mistakes
.venv/bin/python scripts/build.py       # regenerate v1/
```

### Publishing

The same committed files are published by **two static hosts** that serve identical content:

- **Cloudflare Pages** — https://model-info.ta26.top/ (connect the repository to a Pages project with no build command and the repository root as the output directory).
- **GitHub Pages** — https://taitai2661.github.io/model-info/ (serve from the branch root).

The tree is plain static files, so nothing needs compiling; `.nojekyll` is included for GitHub Pages. No Actions workflow is needed or wanted. Updates happen only when someone edits `data/`, runs the build, and commits — both hosts then redeploy.

## Site icons

`favicon.svg` is the source of truth for the icon and is used directly by browsers. `scripts/make_icons.py` renders the same design to `apple-touch-icon.png`, `icon-192.png` and `icon-512.png` (referenced by `site.webmanifest`) with no third-party dependencies:

```bash
python3 scripts/make_icons.py
```

## Non-goals

No collectors, no auto-updates, no scraping schedules, no GitHub Actions, no update buttons, no admin panel, no database, no server-side API, no API key storage, no proxying, no rankings, no recommendations, no benchmarks, no usage metering.
