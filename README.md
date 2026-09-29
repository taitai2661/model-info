# Model Info

**Model Info** is a static, open-source JSON data source for AI models and the API providers that serve them.

It answers two questions in one place:

1. **What are this model's specs?** (context window, modalities, capabilities, pricing, status)
2. **Through which provider can I use it, and how do I connect?** (model id per provider, base URL, API style, endpoints, authentication, per-provider pricing)

Model Info does **not** execute models, proxy API requests, rank models, or recommend models. It stores verified facts, validates them against JSON Schemas, and serves them as static JSON — nothing else.

A static search site for the data lives at the repository root (`index.html` + `web/`), served from the same GitHub Pages deployment. Open the repo root in a browser to browse models and providers by keyword, filter by capability/modalities/status, and view per-provider connection details. No build step, no framework — vanilla HTML/CSS/JS fetching the committed `v1/` JSON at runtime.

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
│   └── vendors.json           # curated catalogue-vendor -> model_provider map
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
    },
    {
      "provider_id": "vercel-ai-gateway",
      "model_id": "deepseek/deepseek-v4-pro",
      "context": { "window": 1000000, "max_output_tokens": 384000 }
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

- **Never guess.** Unknown context windows, prices, or capabilities are `null` (or the key is omitted) — never `0`, never inferred. `0` is only meaningful for a price (an explicitly free tier); a context size of `0` is rejected by `validate.py`, because upstream it means "not applicable" (image, video and embedding models have no token budget).
- **Every fact has sources.** `sources[]` records `type` (`official`/`documentation`/`community`/`manual`), `url`, and `retrieved_at`. `official` is the vendor's own page; `documentation` is a third party describing the vendor's model, such as an aggregator catalogue.
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

Available collectors: `openai`, `anthropic`, `google`, `deepseek`, `mistral`, `openrouter` (public, no key), `opencode` (public, no key), `opencode-go` (public, no key), `groq` (public, no key), `together` (public, no key), `fireworks` (public, no key), `nvidia` (public, no key), `vercel-ai-gateway` (public, no key), `deepinfra` (public, no key), `novita` (public, no key), `ppio` (public, no key), `featherless` (public, no key), `sambanova` (public, no key), `huggingface` (public, no key), `catalog` (public, no key).

`groq`, `together` and `fireworks` publish their catalogues as Markdown documentation rather than as a JSON API, so they read the `.md` page instead (`collector/docs.py`) — still no key involved. `normalize()` receives the raw text and each collector decides which column is the context window and which one is the price.

`deepinfra`, `novita`, `ppio`, `featherless` and `sambanova` all publish the same OpenAI-compatible `GET /models` envelope, so they share one base class (`collector/openai_compatible.py`) and differ only in which keys hold the context and the prices. Two things that base class refuses to do, because getting either wrong silently corrupts the price:

- **A non-token price is never converted into a token price.** These catalogues bill per image, per character, per second of audio and per request as well; only the token keys are read.
- **A price is only read where the payload states its unit.** DeepInfra's `input_tokens` is a price *per 1M tokens* despite the key name, Novita's and PPIO's `price_per_m_decimal` is dollars per 1M while the flat `input_token_price_per_m` mirroring it is in units of 1e-4 $/1M, and Featherless quotes each figure twice — per-token under `prompt`/`completion` and per-million under `input`/`output`. Each collector's docstring records which reading it uses and why; a mirrored field in a different unit is ignored rather than rescaled by a guessed factor.

`huggingface` reads the Inference Providers router, which is the one collector whose payload describes *other* providers: it reports, per model, one slot per partner with that partner's context window and supported features. Those facts are recorded on the partner's own relationship entry, while the router's own entry records only the route. The router's price is deliberately **not** recorded anywhere, because it is set per partner and differs between them — any single figure would be invented, and a partner's own price is not the router's to state. Partner keys the registry does not know (`baseten`, `nscale`, `ovhcloud`, `scaleway`) are reported for manual review rather than guessed at.

Collectors only **update facts they can read from the source**. Anything else keeps its hand-verified value; ids that do not match a registered model are reported as *needs manual review* instead of being invented. A provider model id that *does* resolve to a registered model gets its relationship entry created (vendor prefix, letter case, Fireworks' `p` decimal escape, route variants such as `:free` / `:batch`, snapshot suffixes and the model's own `version` are the only rewrites applied) — but apart from `catalog` below, a collector never creates a model document. Run `validate.py` and `build.py` afterwards.

### Catalog import (`catalog`)

`catalog` is the one collector that **does** create model documents, and it does so only for models that do not exist yet. It reads the two large public aggregator catalogues (Vercel AI Gateway and OpenRouter) and registers everything in them that is still missing — currently 470 models across 58 model providers, most of them long-tail open-weight releases, embedding models, image/video generation models and community fine-tunes. A model that is already registered is left completely alone, so hand-verified specs are never overwritten by a catalogue.

Three rules keep it from turning the registry into a mirror of an upstream JSON blob:

- **No guessed vendors.** `collector/vendors.json` maps a catalogue vendor key onto a registered `model_provider` (`aliases`), lists vendors that are deliberately skipped (`ignored`), and holds the `providers` entries used to create a `model_provider` document for a vendor that is not registered yet. A vendor that appears in neither file is reported as *needs manual review* and **nothing is written** — the mapping is always a human decision, never a prefix heuristic. To add a vendor, add it to `vendors.json` with a `website` or `documentation_url` to cite, then re-run.
- **No invented facts.** `model_id` is the catalogue id without its vendor prefix, `name` comes from the catalogue (Vercel's is the clean product name; OpenRouter's `"Vendor: Model"` prefix is dropped because the vendor is already in `model_provider`). `family` and `version` stay unset because no payload states them. Prices are provider facts and therefore only ever land on the relationship entry — never on the model document.
- **Aggregator ≠ vendor.** A catalogue is a reseller's view, not the developer's own documentation, so model documents imported this way carry `sources[].type = "documentation"` and say so in the note. Hand-written model documents keep `type = "official"` and cite the vendor's own page.

Vercel wins wherever both catalogues report a field (its `owned_by` is the vendor's own identifier and it carries a real `released` timestamp); OpenRouter contributes `hugging_face_id` (open weights) and `expiration_date`. Imported models get `status: "active"` — being listed in a live provider catalogue — unless the catalogue announces a retirement, which downgrades them to `deprecated`. `release_date` is only set from Vercel's `released`; OpenRouter's `created` is when *it* listed the model, which is not a release date, so it is not used.

```bash
.venv/bin/python -m collector catalog            # dry run
.venv/bin/python -m collector catalog --write    # import
.venv/bin/python -m collector catalog --write    # no-op: already imported
```

Two things are deliberately **not** imported: OpenRouter's `~vendor/…` ids (routing variants that track a vendor's latest release) and `openrouter/auto`, `/free`, `/fusion` (routers that pick a model per request). Both are listed in `vendors.json` under `ignored` with the reason.

After an import, run the other collectors once more — they will attach their own relationship entries to the newly registered models. Their first run rewrites the `sources` note on the two aggregator entries the catalog wrote, so run each one twice to see a clean `unchanged` report.

### Adding data by hand

1. **Model**: create `data/models/{model_id}.json` (required: `model_id`, `name`, `model_provider`, `status`, `updated_at`).
2. **Provider**: create `data/providers/{provider_id}.json` (required: `id`, `name`, `types`, `status`, `updated_at`); put `base_url`, `api_style`, endpoints, and authentication under `api`.
3. **Relationship**: create `data/relationships/{model_id}.json` listing every provider that serves the model (with its provider-specific `model_id`).
4. Run `scripts/validate.py`, then `scripts/build.py`, then commit both `data/` and `v1/`.

### Publishing on GitHub Pages

Push the repository and enable GitHub Pages (serve from the branch root). `.nojekyll` is included; no Actions workflow is needed or wanted. Updates happen only when someone edits `data/`, runs the build, and commits.

## Non-goals

No auto-updates, no scraping schedules, no GitHub Actions, no update buttons, no admin panel, no database, no server-side API, no API key storage, no proxying, no rankings, no recommendations, no benchmarks, no usage metering.
