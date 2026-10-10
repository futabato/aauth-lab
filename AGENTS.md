# AGENTS.md

このリポジトリで作業するコーディングエージェント向けのガイドです。人間向けの説明は `README.md` にあります。

## 目的

IETF の AAuth ドラフトを**実装を通じて理解する**ための実験場です。プロダクトではありません。

- 優先するのは「仕様のどこに基づいて、誰が何を判断し、どこで止まるか」が**コードとタイムラインから読み取れること**です。性能や汎用性は二の次です。
- 現在のテーマは「実行途中で追加の許可が必要になったとき」です。ケース A（resource での step-up）は実装済みです。ケース B（`permission_endpoint`）とケース C（clarification と mission の更新）は未着手です。

## 仕様

- 基準は `docs/spec/draft-hardt-oauth-aauth-protocol-11.txt` です。**このファイルを一次情報として読んでください。** 記憶や Web 上の要約に頼らないでください。
- 新しいリビジョンに追従するときは、ファイルを追加し、差分を確認してから参照先を切り替えてください。既存のファイルは上書きしないでください。
- 仕様に基づく処理には、コメントや event の `spec=` に節番号（例: `§6.5.1`）を付けてください。
- 仕様が規定していない挙動を決めたときは、コードのコメントでそう明記し、README の「仕様が答えていないこと」または「仕様からの逸脱と簡略化」に追記してください。

## コマンド

```sh
uv sync
uv run aauth-lab up                  # AP :8001 / PS :8002 / Resource :8003
uv run aauth-lab demo [--delivery retry|deferred] [--person approve|deny|narrow|ignore|manual] [--revoke-mission]
uv run aauth-lab timeline            # var/events.jsonl を表示
uv run pytest                        # 実サーバーをスレッドで立てる統合テストを含む（空きポートを使う）
uv run mypy                          # strict。src と tests の両方が対象
uv run ruff check --fix && uv run ruff format
```

変更後は **mypy・ruff・pytest がすべて通る**状態にしてください。挙動を変えた場合は、`aauth-lab demo` のタイムラインも確認してください。

## 構成

- `src/aauth_lab/core/`：ロールに依存しない仕様のプリミティブ（署名、トークン、AAuth-Requirement、discovery、サーバー共通処理、events）。ロール固有の判断はここに書かないでください。
- `agent_provider/`、`person_server/`、`resource/`：各ロールです。`create_app(topology)` で FastAPI アプリを作ります。状態はインメモリで、再起動すると消えます。
- `person_server/supervisor.py`：PS の判断ロジックです。`Supervisor` Protocol の実装を差し替えて比較する想定です。
- `agent/client.py`：エージェントの状態機械です。401 と 202 の両方に対応する必要があります（§6.5.1）。
- `person.py`：テストやデモで本人の役を代行する処理と、手動モードです。
- `scenario.py`：シナリオです。新しいケースはここに追加し、`cli.py` から呼べるようにしてください。

## コーディング規約

- **型から書いてください。** `mypy --strict` を前提とします。`Any` と `cast` は使わないでください。やむを得ず `# type: ignore[...]` を書くときは理由を添えてください。
- 状態の分岐は `Literal`、`StrEnum`、dataclass の union と `match` で表現してください（例: `Requirement`、`Presented`、`Verdict`、`Outcome`）。
- JSON は `JsonValue` と `JsonObject`、もしくは pydantic モデルで扱ってください。`response.json()` の戻り値をそのまま使わないでください。
- トークンの種類は JOSE の `typ` と、モデルの `Literal` で固定した `dwk` で区別します。トークン型を追加するときも同じ方式にしてください（§13.11）。
- FastAPI では `Annotated` を使ってください。PS の状態を変えるハンドラは `async def` にしてください。`asyncio.Event` をスレッドプールから触らないためです。
- エラーは、署名の失敗なら `SignatureFailure`（401 と `Signature-Error` ヘッダ）、それ以外は `ProblemError`（problem+json）で返してください。
- コード上の識別子は英語です。ユーザーに見える文言（event のタイトル、同意画面）は日本語です。

## タイムライン（events）の書き方

全ロールが `var/events.jsonl` に追記します。これはラボの計測器で、プロトコルの一部ではありません。

- `Kind.DECISION`：誰かが判断したとき。理由を必ず含めてください。
- `Kind.HOLD`：操作が止まったとき。`detail["where"]` に、止めているのは誰か（`resource` / `person_server` / `agent`）を必ず入れてください。テストがこの値を見ています。
- `Kind.EXECUTE`：副作用が実際に起きたとき。
- 新しい振る舞いを追加したら、それがタイムライン上で読めるように event を出してください。

## 注意点

- Resource の文書 API は `/docs` です。FastAPI の Swagger UI は `/_swagger` に移してあります。
- サーバー識別子は、ラボに限り `http://localhost:<port>` を許可しています（`server_id(..., allow_loopback_http=True)`）。この例外を他の箇所に広げないでください。
- discovery はエグレス制御（`Topology.admits`）を通ります。ラボの3サーバー以外へは取得に行きません。
- サーバーを止めるときは、ポートで止めてください（`fuser -k 8001/tcp` など）。`pkill -f "aauth-lab up"` は、それを実行しているシェル自身も対象にしてしまいます。
- `/lab/*` のエンドポイントは、実験のための制御用です。仕様にはありません。仕様のエンドポイントとは区別しておいてください。
