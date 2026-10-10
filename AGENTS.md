# AGENTS.md

このリポジトリで作業するコーディングエージェント向けのガイドです。人間向けの説明は `README.md` にあります。Codex と Claude Code のどちらもこのガイドを適用し、作業前後に `git status` と対象ファイルの差分を確認してください。他の作業者の未コミット変更を上書き・取り消さないでください。

## 目的

IETF の AAuth ドラフトを**実装を通じて理解する**ための実験場です。プロダクトではありません。

- 優先するのは「仕様のどこに基づいて、誰が何を判断し、どこで止まるか」が**コードとタイムラインから読み取れること**です。性能や汎用性は二の次です。
- 現在のテーマは「実行途中で追加の許可が必要になったとき」です。ケース A（resource での step-up）は実装済みです。ケース B（`permission_endpoint`）とケース C（clarification と mission の更新）は未着手です。

記事作業は [docs/blog/README.md](docs/blog/README.md) から始め、構成・調査メモ・原稿と作業状態を確認してください。調査基準日と文書整備日を区別し、未実測の実験結果を補完しないでください。

## 仕様

- 基準は `docs/spec/draft-hardt-oauth-aauth-protocol-11.txt` です。**このファイルを一次情報として読んでください。** 記憶や Web 上の要約に頼らないでください。
- 検証の対象は 2026-10-09 に確認した `draft-hardt-oauth-aauth-protocol-11`（個人提出の Internet-Draft、標準化未完了）に固定します。他の版や editor's copy の記述を混ぜないでください。
- 新しいリビジョンに追従するときは、ファイルを追加し、差分を確認してから参照先を切り替えてください。既存のファイルは上書きしないでください。
- 仕様に基づく処理には、コメントや event の `spec=` に節番号（例: `§6.5.1`）を付けてください。
- 規範的要件への対応状況は `docs/conformance-11.md` で管理しています。挙動を変えたら、該当する行の状態・根拠（`file:line`）・テスト列を更新してください。
- 仕様が規定していない挙動を決めたときは、コードのコメントでそう明記し、README の「仕様が答えていないこと」または「仕様からの逸脱と簡略化」に追記してください。未確認事項は該当節とともに残し、仕様が保証する挙動として補完しないでください。

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

## 検証と証跡

- README の「検証計画と判定基準」に沿って、HTTP 応答だけでなく API の実行記録とリソースの前後差分で判定してください。陰性試験では削除の `EXECUTE` がなく、データが変わらないことを確認します。単体テストだけで API の副作用不変を検証済みとしないでください。
- 通信順序と method / path、関連する公開 token claims（存在する `iss` / `aud` / `sub` / `jti` / `iat` / `exp` / `scope` / `mission_s256` / `presented_jti`）、JOSE の `typ` / `kid`、公開鍵の thumbprint（`cnf.jwk` / `agent_jkt` との対応）、同意の状態遷移、判断主体と理由、データの前後差分を対応付けて残してください。現行 events だけで不足する項目は、未採取と明記してください。
- `docs.delete` を「特定の対象を一度だけ削除できる許可」と扱わないでください。署名後の改ざん、別対象への新しい正しい署名付き要求、deferred の再 poll は別々に検証します。所有者チェックや保護対象の拒否は Resource 側のポリシーです。対象・回数を限定するポリシーや R3 の per-call grant は後続検証に分けます。
- 架空のデータ・本人・テスト用鍵だけを使ってください。実データ・実アカウント・本物の認証情報は使わず、秘密鍵や本物の認証情報をログ・リポジトリに入れないでください。
- 暗号演算・JWT・HTTP 署名は信頼できるライブラリを使用し、暗号処理を独自実装しないでください。既存の JWT 組み立て・HTTP 署名処理にはラボ独自の部分があるため、ライブラリ利用方針を満たす検証済み実装と見なさず、README の残課題を保持してください。
- 削除の追加同意はこのラボで選ぶポリシーです。OAuth と拡張でも追加同意は実現できるため、デモの成功だけで AAuth の優位性・唯一解・標準化完了・プロンプトインジェクション防止を主張しないでください。
- 実行した検証と未実施事項を区別してください。未実装の機能の起動コマンド・出力・テスト通過を捏造しないでください。文書だけの変更でも Markdown と文書間の整合性を確認し、実行していない起動・テストは未実施と報告してください。

## 注意点

- Resource の文書 API は `/docs` です。FastAPI の Swagger UI は `/_swagger` に移してあります。
- サーバー識別子は、ラボに限り `http://localhost:<port>` を許可しています（`server_id(..., allow_loopback_http=True)`）。この例外を他の箇所に広げないでください。
- discovery はエグレス制御（`Topology.admits`）を通ります。ラボの3サーバー以外へは取得に行きません。
- サーバーを止めるときは、ポートで止めてください（`fuser -k 8001/tcp` など）。`pkill -f "aauth-lab up"` は、それを実行しているシェル自身も対象にしてしまいます。
- `/lab/*` のエンドポイントは、実験のための制御用です。仕様にはありません。仕様のエンドポイントとは区別しておいてください。
