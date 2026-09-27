# Model Info

**Model Info** は、AIモデルと、それを提供するAPI Providerの情報をまとめた静的・オープンソースのJSONデータソースです。

1つの場所で2つの問いに答えます。

1. **このモデルの仕様は?**(コンテキストウィンドウ、モダリティ、機能、料金、状態)
2. **どのProvider経由で使えて、どう接続するか?**(ProviderごとのモデルID、Base URL、API形式、Endpoint、認証方式、Providerごとの料金)

Model Infoはモデルを**実行したり、APIをプロキシしたり、ランキングや推薦をしたりしません**。検証済みの事実をJSON Schemaで検証し、静的JSONとして配信するだけです。

English: [README.md](README.md)

## 基本概念

```text
Model            -> 1つのモデルの仕様(model provider が開発)
Provider         -> 1つのサービス(model provider / api_provider などの役割を持つ)
Model × Provider -> 「このモデルはこのProvider経由で利用できる」
```

**Model Provider ≠ API Provider。** DeepSeekのモデルはDeepSeek自身だけでなく、OpenRouterやOpenCode経由でも利用できます。そのため3つの概念を明確に分離しています。

- `data/models/*.json` — モデル本体(`model_provider` = 開発元)
- `data/providers/*.json` — 各サービス(`types` = 役割: `model_provider` / `api_provider` / `aggregator` / `gateway` / `runtime` / `platform`)
- `data/relationships/*.json` — Providerごとの提供情報(Provider固有のモデルIDと上書き)

**OpenCode Zen と OpenCode Go** は別サービス(Base URL・カタログ・料金が異なる)なので、`opencode` と `opencode-go` の2プロバイダとして登録します。**Vercel AI Gateway** (`vercel-ai-gateway`)も同じく集約型のアグリゲーターで、1つのOpenAI互換エンドポイントで多数の第三者モデル(OpenAI / Anthropic / Google 等)を `openai/gpt-5` `anthropic/claude-sonnet-4-5` のような vendor-prefixed id として提供します(BYOK or OIDC)。同一モデルのエイリアスや無料SKUのように1サービスが複数IDを持つ場合、同一プロバイダを関係ファイルに複数回(各エントリ異なる `model_id`)で列挙します。

Ollama・llama.cpp・vLLMなどのRuntime / PlatformはAPI Providerではありません。実行環境はモデル側の `runtime` マップに記録します。

## リポジトリ構成

```text
model-info/
├── data/                      # 信頼できるソース(手作業 / collector 出力)
│   ├── models/{model_id}.json
│   ├── providers/{provider_id}.json
│   └── relationships/{model_id}.json
├── schemas/v1/                # JSON Schema(draft 2020-12)
│   ├── model.schema.json
│   ├── provider.schema.json
│   └── model-provider.schema.json
├── v1/                        # 生成された静的API(GitHub Pagesで配信)
├── collector/                 # 手動実行のPython Collector(自動実行なし)
├── scripts/
│   ├── validate.py            # スキーマ + 整合性 + 秘密情報スキャン
│   └── build.py               # 検証 -> v1/ 生成
├── tests/                     # pytest
├── README.md / README.ja.md
└── .nojekyll
```

## API(静的ファイル)

論理エンドポイントごとに `….json` と `…/index.json` の2形式を生成します(GitHub Pagesは拡張子なしURLを配信できないため)。

| 論理リクエスト | 静的ファイル |
| --- | --- |
| `GET /v1/models` | `v1/models.json` または `v1/models/index.json` |
| `GET /v1/models/{model_id}` | `v1/models/{model_id}.json` または `v1/models/{model_id}/index.json` |
| `GET /v1/providers` | `v1/providers.json` または `v1/providers/index.json` |
| `GET /v1/providers/{provider_id}` | `v1/providers/{provider_id}.json` または `…/index.json` |
| `GET /v1/providers/{provider_id}/models` | `v1/providers/{provider_id}/models.json` または `…/models/index.json` |

GitHub Pages 上ではリポジトリルートから `https://<user>.github.io/<repo>/v1/models.json` のように取得できます。

モデル詳細レスポンスには接続に必要な情報をまとめて含めます。

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

### 上書きセマンティクス(Model × Provider)

関係エントリ内の任意キーは次の3値で表現します。

| 形式 | 意味 |
| --- | --- |
| キーなし | モデル定義の値を継承 |
| `null` | このProviderでは不明 |
| 値あり | 上書き |

`model.provider_pricing`(model側のショートカット、`provider_id` でキー付け)も同じ意味です。両方に同じProviderの料金が書かれている場合は一致必須で、検証が強制します。

関係エントリ内のネストオブジェクト(`pricing` / `context` / `modalities` / `capabilities` / `api_capabilities`)はモデル本体のオブジェクトを**丸ごと置き換えます**。置換後オブジェクト内で省略されたフィールドは「そのProviderでは不明」であって、継承ではありません。

## データのルール

- **推測しない。** 不明なコンテキスト長・料金・機能は `null`(またはキー自体を省略)。`0` にしない、憶測しない。
- **出典を必ず記録。** `sources[]` に `type`(`official` / `documentation` / `community` / `manual`)、`url`、`retrieved_at` を保持。
- **秘密情報は絶対に保存しない。** APIキーは一切書き込みません。検証は全データファイルを資格情報らしき文字列で走査し、検出したらビルドを失敗させます。
- **enum**: `status` = `active | preview | experimental | deprecated | retired | unknown`、`api_style` = `openai_compatible | anthropic | google_generative_ai | custom`、`authentication.type` = `bearer | api_key | oauth | none | custom`、モダリティ = `text | image | audio | video | file`。
- 日時は `YYYY-MM-DD`。料金は `currency` + `unit`(既定 `1M_tokens`)単位。

全フィールドの定義は `schemas/v1/*.schema.json` が契約です。

## ワークフロー

自動化は一切しません。GitHub Actions・cron・自動更新・更新ボタン・管理画面は作りません。

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/validate.py    # data/ をスキーマ+ルールで検証
.venv/bin/python scripts/build.py       # v1/ を再生成(エラー時は生成しない)
.venv/bin/python -m pytest              # テスト
```

`data/` の変更は生成済み `v1/` と一緒にコミットします。

### Collector(手動)

Collectorは公式エンドポイントから取得 → 正規化 → `data/` へマージまでを行います。コミットはせず、APIキーも保存しません(環境変数のみ参照)。

```bash
.venv/bin/python -m collector --list
.venv/bin/python -m collector openrouter          # dry run(キー不要)
.venv/bin/python -m collector openrouter --write  # 適用
export OPENAI_API_KEY=...                         # キーはシェルにのみ存在
.venv/bin/python -m collector openai --write
```

利用可能: `openai` / `anthropic` / `google` / `deepseek` / `mistral` / `openrouter`(公開・キー不要) / `opencode`(公開・キー不要) / `opencode-go`(公開・キー不要) / `groq`(公開・キー不要) / `together`(公開・キー不要) / `fireworks`(公開・キー不要) / `nvidia`(公開・キー不要) / `vercel-ai-gateway`(公開・キー不要)。

`groq` / `together` / `fireworks` はJSON APIではなくMarkdownのドキュメントでカタログを公開しているため、`.md` ページを直接読みます(`collector/docs.py`)。APIキーは引き続き不要で、どの列がコンテキスト長・料金なのかは各Collectorが判定します。

Collectorはソースから読み取れる情報**だけ**を更新します。読み取れない項目は手検証済みの値を保持します。Provider側のモデルIDが登録済みモデルに解決できる場合は relationship エントリを新規作成します(適用されるのは vendor 接頭辞・大文字小文字・Fireworks の `p` 表記・スナップショット接尾辞・モデル自身の `version` のみ)。モデルドキュメント自体をCollectorが作ることはありません。解決できないIDは従来通り「要手動確認」として報告されます。実行後は `validate.py` と `build.py` を走らせてください。

### 手動でのデータ追加

1. **Model**: `data/models/{model_id}.json` を作成(必須: `model_id`, `name`, `model_provider`, `status`, `updated_at`)。
2. **Provider**: `data/providers/{provider_id}.json` を作成(必須: `id`, `name`, `types`, `status`, `updated_at`)。`base_url`・`api_style`・Endpoint・認証は `api` 配下。
3. **Relationship**: `data/relationships/{model_id}.json` に、そのモデルを提供する全Provider(Provider固有の `model_id` 含む)を記載。
4. `scripts/validate.py` → `scripts/build.py` → `data/` と `v1/` をコミット。

### GitHub Pagesでの公開

ブランチルートからPagesを有効化するだけです。`.nojekyll` 同梱、Actionsは不要(作りません)。更新は `data/` を編集し、ビルドしてコミットしたときだけ起きます。

## 実装しないもの

自動更新、定期スクレイピング、GitHub Actions、更新ボタン、管理画面、Web上でのデータ編集、DB、サーバーサイドAPI、cron、AIによる情報収集・推測、モデル実行、APIプロキシ、APIキー管理、ランキング、推薦、自動ベンチマーク、使用量計測。
