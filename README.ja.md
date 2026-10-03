# Model Info

**Model Info** は、AIモデルと、それを提供するAPI Providerの情報をまとめた静的・オープンソースのJSONデータソースです。

1つの場所で2つの問いに答えます。

1. **このモデルの仕様は?**(コンテキストウィンドウ、モダリティ、機能、料金、状態)
2. **どのProvider経由で使えて、どう接続するか?**(ProviderごとのモデルID、Base URL、API形式、Endpoint、認証方式、Providerごとの料金)

Model Infoはモデルを**実行したり、APIをプロキシしたり、ランキングや推薦をしたりしません**。検証済みの事実をJSON Schemaで検証し、静的JSONとして配信するだけです。

同じリポジトリルート(`index.html` + `web/`)にデータの静的検索サイトがあり、同一のファイルを2つの静的ホスト(**Cloudflare Pages** https://model-info.ta26.top/ と **GitHub Pages** https://taitai2661.github.io/model-info/)で配信しています。ブラウザでリポジトリルートを開くと、キーワード検索、機能/モダリティ/ステータスでのフィルタ、プロバイダー別接続情報の閲覧ができます。ビルド工程・フレームワークなし — バニラHTML/CSS/JSがコミット済みの `v1/` JSONを実行時にfetchします。`v1/` ファイルの解説ページは `api.html` です(日英対応)。

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

**すべての事実は手作業で記入します。** Collector・スクレイパー・取込ジョブはありません。人が一次情報を読んでJSONを書きます。手順は[手動でのデータ追加](#手動でのデータ追加)を参照してください。

## リポジトリ構成

```text
model-info/
├── data/                      # 信頼できるソース(すべて手編集)
│   ├── models/{model_id}.json
│   ├── providers/{provider_id}.json
│   └── relationships/{model_id}.json
├── schemas/v1/                # JSON Schema(draft 2020-12)
│   ├── model.schema.json
│   ├── provider.schema.json
│   └── model-provider.schema.json
├── v1/                        # 生成された静的API(Cloudflare Pages と GitHub Pages で配信)
├── scripts/
│   ├── new.py                 # model / provider / relationship のひな形を作成
│   ├── validate.py            # スキーマ + 整合性 + 秘密情報スキャン
│   ├── build.py               # 検証 -> v1/ 生成
│   └── make_icons.py          # favicon.svg からPNGアイコンを再生成
├── web/                       # 検索サイト(HTML/CSS/JS)+ api.html
├── favicon.svg / icon-*.png   # サイトアイコン一式
├── tests/                     # pytest
├── README.md / README.ja.md
└── .nojekyll
```

## API(静的ファイル)

論理エンドポイントごとに `….json` と `…/index.json` の2形式を生成します(静的ホスティングは拡張子なしURLを配信できないため)。

| 論理リクエスト | 静的ファイル |
| --- | --- |
| `GET /v1/models` | `v1/models.json` または `v1/models/index.json` |
| `GET /v1/models/{model_id}` | `v1/models/{model_id}.json` または `v1/models/{model_id}/index.json` |
| `GET /v1/providers` | `v1/providers.json` または `v1/providers/index.json` |
| `GET /v1/providers/{provider_id}` | `v1/providers/{provider_id}.json` または `…/index.json` |
| `GET /v1/providers/{provider_id}/models` | `v1/providers/{provider_id}/models.json` または `…/models/index.json` |

どちらのホストも配信ルートから同一のファイルを返します。例えば `https://model-info.ta26.top/v1/models.json` と `https://taitai2661.github.io/model-info/v1/models.json` は同じ内容です。

このセクションは `api.html` でブラウザから読める形にしています(エンドポイント表、コピー可能なリクエスト例、JSON Schema へのリンク付き)。

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

推論モードと推論レベルは別々の設定です。`model.reasoning` に `reasoning.mode` (`standard` / `pro`) と `reasoning.effort` の選択肢を記録し、`model.service_tier` に `fast` などの処理ティアを記録します。`providers[].api_variant` は、同じベースモデルを保ったまま、提供元の別名が特定のモードやティアを選ぶことを表します。

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

プロバイダー固有の別名は `providers[].api_variant` に選択される設定を記録し、プロバイダー側のモデル ID を保持します。推論モードと推論レベル、処理ティアやスループット別名は別々に扱います。

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

### 上書きセマンティクス(Model × Provider)

関係エントリ内の任意キーは次の3値で表現します。

| 形式 | 意味 |
| --- | --- |
| キーなし | モデル定義の値を継承 |
| `null` | このProviderでは不明 |
| 値あり | 上書き |

`model.provider_pricing`(model側のショートカット、`provider_id` でキー付け)も同じ意味です。両方に同じProviderの料金が書かれている場合は一致必須で、検証が強制します。

関係エントリ内のネストオブジェクト(`pricing` / `context` / `modalities` / `capabilities` / `reasoning` / `service_tier` / `api_variant` / `api_capabilities`)はモデル本体のオブジェクトを**丸ごと置き換えます**。置換後オブジェクト内で省略されたフィールドは「そのProviderでは不明」であって、継承ではありません。

## データのルール

- **推測しない。** 不明なコンテキスト長・料金・機能は `null`(またはキー自体を省略)。`0` にしない、憶測しない。`0` が意味を持つのは料金(明示的に無料な tier)のみで、コンテキスト長の `0` は `validate.py` が拒否します。上流では「該当なし」(画像・動画・embedding モデルにはトークン上限がない)を意味するからです。
- **出典を必ず記録。** `sources[]` に `type`(`official` / `documentation` / `community` / `manual`)、`url`、`retrieved_at` を保持。`official` は開発者本人のページ、`documentation` は第三者が開発者のモデルについて説明したものです。
- **秘密情報は絶対に保存しない。** APIキーは一切書き込みません。検証は全データファイルを資格情報らしき文字列で走査し、検出したらビルドを失敗させます。
- **enum**: `status` = `active | preview | experimental | deprecated | retired | unknown`、`api_style` = `openai_compatible | anthropic | google_generative_ai | custom`、`authentication.type` = `bearer | api_key | oauth | none | custom`、モダリティ = `text | image | audio | video | file`。
- 日時は `YYYY-MM-DD`。料金は `currency` + `unit`(既定 `1M_tokens`)単位。

全フィールドの定義は `schemas/v1/*.schema.json` が契約です。

## ワークフロー

自動化は一切しません。GitHub Actions・cron・自動更新・スクレイパー・管理画面は作りません。

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/new.py ...     # ドキュメントのひな形を作成(推奨)
.venv/bin/python scripts/validate.py    # data/ をスキーマ+ルールで検証
.venv/bin/python scripts/build.py       # v1/ を再生成(エラー時は生成しない)
.venv/bin/python -m pytest              # テスト
```

`data/` の変更は生成済み `v1/` と一緒にコミットします。

## 手動でのデータ追加

データを追加する唯一の方法です。1つの事実につき3つのドキュメントを、この順に書きます。数値には必ず出典を付けます。

### 1. Provider — `data/providers/{provider_id}.json`

必須: `id`, `name`, `types`, `status`, `updated_at`。1つのサービスが複数の役割を持つので、当てはまるものをすべて列挙します。

| type | 意味 |
| --- | --- |
| `model_provider` | モデルを開発する |
| `api_provider` | 自身(または他社)のモデルのAPIアクセスを販売する |
| `aggregator` / `gateway` | 1つのエンドポイントで多数の第三者モデルを再販売する |
| `runtime` / `platform` | モデルを実行する(Ollama、vLLM 等)。API Providerではない |

接続情報は `api` 配下に置きます。`base_url`(APIルートのみ。パス・クエリ・フラグメントは含めない)、`api_style`(`openai_compatible` / `anthropic` / `google_generative_ai` / `custom`)、`authentication.type`、そして `endpoints` には**パス**を書きます(例: `"chat_completions": "/chat/completions"`。URLではなくパス)。

### 2. Model — `data/models/{model_id}.json`

必須: `model_id`, `name`, `model_provider`, `status`, `updated_at`。`model_provider` は `model_provider` タイプを持つ登録済みProviderである必要があります。`model_id` はファイル名と一致し、`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` に従います。

任意ですが有用: `context`(`window` / `max_output_tokens` / `max_input_tokens` / `reasoning_tokens` など)、`modalities`、`capabilities`、`reasoning`、`service_tier`、`pricing`、`runtime`、`availability`、`release_date`、`family`、`version`、`provider_pricing`。

### 3. Relationship — `data/relationships/{model_id}.json`

必須: `model_id`, `providers[]`(1件以上)。各エントリは `provider_id` と、そのProvider側での `model_id`、そしてProvider固有の上書き([上書きセマンティクス](#上書きセマンティクスmodel--provider)参照)を持ちます。エイリアスや無料SKUは、同じProviderを `model_id` 違いで複数回列挙します。

vendor接頭辞を持つID(例: OpenRouter の `deepseek/deepseek-v4-pro`)はそのままここに記録します。正規のモデルドキュメントは1つのままです。

### JSONを手で書かずにひな形を作る

`scripts/new.py` がスキーマ準拠のひな形を正しい場所に作成し、その場で検証まで走らせます。

```bash
# Provider(役割が複数なら --type を繰り返す)
.venv/bin/python scripts/new.py provider acme \
  --name "Acme AI" --type model_provider --type api_provider \
  --website https://acme.example --base-url https://api.acme.example/v1 \
  --api-style openai_compatible --auth bearer \
  --source https://acme.example/docs

# そのProviderが開発するモデル
.venv/bin/python scripts/new.py model acme-1 \
  --name "Acme One" --provider acme --context 200000 --modalities text,image \
  --source https://acme.example/models/acme-1

# 提供元(provider[:provider_model_id])。複数指定可
.venv/bin/python scripts/new.py relationship acme-1 \
  --entry acme:acme-1-2026 --entry openrouter:acme/acme-1 \
  --source https://acme.example/docs

.venv/bin/python scripts/new.py list     # 登録済みProvider・モデルの一覧
```

`new.py` は既存ドキュメントを `--force` なしでは上書きせず、未登録の model_provider を勝手に作ることもありません。`relationship` を再実行すると、指定した新規Providerを既存ファイルに**追記**します。ひな形を作ったあと、出典から分かる事実を埋めてから:

```bash
.venv/bin/python scripts/validate.py    # スキーマ・整合性の誤りを検出
.venv/bin/python scripts/build.py       # v1/ を再生成
```

### 公開

同じコミット済みファイル群を、同一内容で配信する**2つの静的ホスト**で公開しています。

- **Cloudflare Pages** — https://model-info.ta26.top/(リポジトリをPagesプロジェクトに接続し、ビルドコマンドなし・出力ディレクトリをリポジトリルートに設定)
- **GitHub Pages** — https://taitai2661.github.io/model-info/(ブランチルートから配信)

すべて静的ファイルなのでコンパイルは不要です(`.nojekyll` はGitHub Pages用に同梱)。Actionsは不要(作りません)。更新は `data/` を編集し、ビルドしてコミットしたときだけ起き、両ホストが再デプロイされます。

## サイトアイコン

アイコンの原本は `favicon.svg` で、ブラウザはこれを直接利用します。`scripts/make_icons.py` が同じデザインを `apple-touch-icon.png` / `icon-192.png` / `icon-512.png`(`site.webmanifest` が参照)へ書き出します。外部依存はありません。

```bash
python3 scripts/make_icons.py
```

## 実装しないもの

Collector、自動更新、定期スクレイピング、GitHub Actions、更新ボタン、管理画面、Web上でのデータ編集、DB、サーバーサイドAPI、cron、AIによる情報収集・推測、モデル実行、APIプロキシ、APIキー管理、ランキング、推薦、自動ベンチマーク、使用量計測。
