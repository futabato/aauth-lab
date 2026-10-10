# aauth-lab

IETF で議論中の **AAuth**（[draft-hardt-oauth-aauth-protocol-11](https://datatracker.ietf.org/doc/html/draft-hardt-oauth-aauth-protocol-11), 2026-09-25）を、実装を通じて理解するための実験場です。仕様の原文は `docs/spec/draft-hardt-oauth-aauth-protocol-11.txt` に固定して置いています。2026-10-09 に確認したこの版を検証の基準とし、他の版や editor's copy と混ぜません。個人提出の Internet-Draft であり、標準化が完了した仕様ではありません。

最初のテーマは **「実行途中で追加の許可が必要になったとき、誰が何を判断し、どこで操作を止めるのか」** です（ケース A: リソースでの step-up）。

この実験は、追加同意の成否だけで AAuth の優位性を示すものではありません。OAuth とその拡張でも追加同意は実現できます。AAuth を唯一の解やプロンプトインジェクション防止策として扱わず、確認した認可の境界と実装上の選択を記事の根拠にします。

## 検証の前提

- 認可フローは固定スクリプトの Agent・PS・Resource の三者構成（§4.2.4）です。既存の AP はテスト用の署名付き agent token と metadata / JWKS を提供します。`/lab/enroll` は bootstrap の代替であり、bootstrap 自体は検証しません。独立した AS・LLM・多段呼び出しは今回の範囲に含めません。
- 対象は架空の文書 API と Alice です。実データ・実アカウントを使いません。状態とテスト用鍵は起動時に生成されるため、実行ごとの鍵・token・初期データを証跡に対応付けます。
- シナリオ A では、Alice への自動紐付けを行い、本人の代役による mission 承認の後に最初の person token を取得します。`person.py` の最初の mission 承認は既定で自動承認であり、`--person manual` もその後の追加同意を手動にする設定です。実際の本人確認や初回の代理行動への同意を検証したとは扱いません（§7.1、§13.8、§13.13、§13.14）。person token 自体も本人確認の保証水準を証明しません（§7.1.1、§13.9）。

## 動かし方

```sh
uv sync
uv run aauth-lab up            # AP :8001 / PS :8002 / Resource :8003 を起動
uv run aauth-lab demo          # 別ターミナルでシナリオ A を実行し、タイムラインを表示
```

実験ごとのオプション:

| コマンド | 何を見るか |
|---|---|
| `demo` | 202 deferred: resource が DELETE を保留し、承認後に実行。同じ token で再 poll しても再実行しない |
| `demo --delivery retry` | 401: resource は何も保持せず、agent が再送する |
| `demo --person deny` | 本人が拒否。PS は 403 denied、resource は拒否を知らないまま保留が残る |
| `demo --person narrow` | 本人が `docs.delete` を外して承認（権限の縮小）。resource は保留を終了 |
| `demo --revoke-mission` | 削除の直前に本人が mission を終了。PS が `mission_terminated` で拒否 |
| `demo --person manual` | 本人の判断をブラウザで行う（URL とコードが表示される） |

`http://localhost:8002/` は本人（Alice）のダッシュボードです。確認待ちの要求と mission の一覧があり、mission を途中で終了させることもできます。

```sh
uv run pytest     # 実サーバー3つを立てて上の実験をすべて検証
uv run mypy       # strict
```

## シナリオ A のタイムライン（`demo` の出力から抜粋）

```
   Agent → DELETE /docs/3                                         （手持ちの auth token は docs.read のみ）
Resource ⚑ step-up — docs.delete が足りない → 202 auth-token        [§6.5.1]
Resource ■ DELETE /docs/3 を resource が保留                         ← 操作が止まる場所 ①
   Agent → resource token を PS に持っていく（scope=docs.delete docs.read）
      PS ◆ Supervisor: 本人に確認 — docs.delete は本人の同意が必要      ← 判断 ①（エスカレーション）
      PS ■ token 要求を保留。本人の判断待ち                             ← 止まる場所 ②
  Person ◆ 本人: 承認（scope=docs.delete docs.read）                   ← 判断 ②（最終判断）
      PS 🔑 auth token を発行
   Agent → auth token を付けて pending URL を poll
Resource ▶ 保留していた DELETE /docs/3 を再開                        ← 判断 ③（強制）
Resource ✔ 「古い下書き (2019)」を削除
Resource · 同じ auth token で再 poll → 保存済みの結果を返す（再実行しない）
Resource ✖ 「雇用契約書」は保護対象。auth token があっても削除しない      ← 判断 ④（業務ルール）
```

## 分かったこと

### 誰が何を判断するか

AAuth には「唯一の判断者（PDP）」がいません（§4.4）。それぞれが自分の立場から別のことを判断します。

| 主体 | 判断すること | このラボでの実装 |
|---|---|---|
| **Resource** | この操作に何が必要か（resource token に入れる scope）。届いた token で足りるか | `DELETE` には `docs.delete` が必要。足りなければ step-up |
| **PS（Supervisor）** | token を発行してよいか。自分で決めるか、本人に聞くか | `RuleSupervisor`: 承認済みリソースの `docs.read` は自動で許可、`docs.admin` は常に拒否、それ以外は本人に聞く。同意は mission 内で記憶する |
| **Person** | 最終的な同意。要求より狭く許可することもできる | PS の同意画面でチェックを外すと scope が縮小される |
| **Resource（再び）** | token があっても、この対象に実行してよいか | 保護された文書は token に関係なく拒否 |
| **Agent** | 何も「許可」しない。判断するのは **401 のあとに再送するかどうか**だけ | — |

同意画面では、**resource が主張する内容**（何の権限が要るか）と、**agent が主張する内容**（なぜ要るか = justification）を見た目で区別しています（§7.4）。PS は agent の主張だけを根拠に判断してはいけません。

### どこで止まるか：401 と 202 の違い（§6.5.1）

| | 401（`--delivery retry`） | 202 deferred（既定） |
|---|---|---|
| 操作を保持するのは | **Agent**（意図だけ。resource は何も覚えていない） | **Resource**（呼び出しそのもの） |
| 承認後に実行させるのは | Agent が同じリクエストを再送する | Agent が auth token を付けて pending URL を poll すると、resource が実行する |
| 応答が失われたとき | 「実行されなかった」のか「実行されたが応答が消えた」のか区別できない | 同じ auth token の jti をキーに、保存済みの結果を返す（再実行しない） |
| 向いている操作 | 状態を持たない、冪等なもの（このラボでは GET） | 冪等でない操作（このラボでは DELETE） |

どちらを使うかは **resource が呼び出しごとに選びます**。Agent は両方に対応しなければなりません。

### scope と削除対象・回数の境界

`docs.delete` は「文書 A を一度だけ削除する許可」ではありません（§11.10）。削除の追加同意はこのラボの PS ポリシーで、AAuth がすべての削除に義務付けるものではありません。同意を mission 内で記憶するため、同じ resource / scope では再度聞かずに許可する場合があります。

署名済みの A への要求を B へ改ざんする試験と、承認後に B への新しい要求を正しく署名する試験は別です。後者は通常の `docs.delete` と Resource のポリシーが許せば実行でき、署名検証が止めるとは限りません。deferred の再 poll で同じ保留操作を再実行しないことも、token 全体を一回限りにする制御とは区別します。

対象・回数を限定する制御は、明示的なアプリポリシーか R3 の per-call grant を扱う後続検証に分けます。protocol-11 は R3 を companion specification として参照します（§6.7.1、§11.2.4）が、その詳細と対象版は今回未確認です。所有者チェックは Resource 側のポリシーです。現在の保護文書チェックは所有者チェックではなく、複数の所有者にまたがる認可は未検証です。

## 検証計画と判定基準

HTTP ステータスや画面だけで成否を決めず、API の実行記録（`EXECUTE`）と文書データの前後差分を照合します。各試験は初期状態を揃え、変える条件を一つにします。失敗時の「データ不変」は対象の残存だけでなく、文書一覧・内容に意図しない差分がないことまで確認します。

| 試験 | 判定すること |
|---|---|
| `docs.read` だけで DELETE | 追加許可なしでは削除を実行しない。step-up は許可取得の開始であり、削除成功ではない |
| 追加同意が pending / ignore | 承認前の状態を採取し、削除の実行記録がなくデータが変わらない |
| 追加同意を拒否・縮小 | PS の拒否または scope 不足により、削除の実行記録がなくデータが変わらない |
| 承認後の DELETE | 正しい鍵・audience・有効期限・`docs.delete` と Resource のポリシーを満たした場合だけ対象が削除される |
| token を別の鍵で使用 | 正しい token を別鍵で署名した要求に使い、鍵結合の検証で拒否され、データが変わらない |
| 期限切れ token | HTTP 署名の時刻は有効に保ち、token の `exp` だけを失敗条件にして拒否とデータ不変を確認する |
| 別 audience の token | 信頼するテスト発行元が署名した別 resource 向け token を提示し、拒否とデータ不変を確認する |
| 無効な token 署名 | JWT 署名だけを無効にし、HTTP 要求は改めて正しく署名して、拒否とデータ不変を確認する |
| HTTP リクエストの改ざん | 有効な token と HTTP 署名を作った後に署名対象を改ざんし、拒否とデータ不変を確認する。変更した method / path / header / body と実際の署名対象を記録する（§11.3.3.1、§11.2.4） |

既存の `tests/test_scenario.py` には承認・拒否・権限縮小、mission 終了、deferred 再実行抑止、削除後の ID に関する検査があります。HTTP 改ざんは `tests/test_core.py` の単体試験です。別鍵・期限切れ・別 audience・無効な JWT 署名の API 陰性試験、pending 中の状態採取、全データの前後比較は追加検証が必要です。2026-10-10 の文書レビューでは起動・pytest・mypy・ruff を実行していません。上表は検証計画であり、全項目の通過記録ではありません。

記事に使う証跡には、対象版、実行したコマンドと条件、通信順序、関連する公開 token claims と鍵 thumbprint、同意の状態遷移、判断主体と理由、データの前後差分を残します。現在の `var/events.jsonl` はその一部を記録する計測器で、未採取の項目は別途確認が必要です。秘密鍵や本物の認証情報はログ・リポジトリに入れません。

## 仕様が答えていないこと（実装して気づいた点）

- **PS での拒否は resource に伝わらない。** 202 で保留している DELETE は、PS が `denied` を返しても resource 側では保留のまま残り、期限切れ（408）になるまで消えません。PS から resource への通知経路は定義されていません。
- **本人が権限を縮小したとき、保留中の呼び出しをどうするか。** 縮小された token で poll された場合の resource の振る舞いは規定がありません。このラボでは `403 insufficient_scope` を返して保留を終了しています。
- **step-up の resource token に入れる scope。** 追加分だけにするのか、既存分との和集合にするのかは書かれていません。このラボでは和集合（`docs.read docs.delete`）にしています。新しい auth token が古い token を置き換えるためです。
- **step-up で得た token の有効期限は延びない。** 新しい auth token の `exp` は、提示した token の `exp` を超えられません（§9.4.1）。期限を延ばすには、上流の token から取り直す必要があります（§7.1.3）。

## 構成

```
src/aauth_lab/
  core/            仕様のプリミティブ（role に依存しない）
    httpsig.py       RFC 9421 署名と検証、Signature-Key、Content-Digest（§11.3）
    tokens.py        agent / person / resource / auth token と Ed25519 JWS（§11.5）
    requirement.py   AAuth-Requirement ヘッダ（§11.6）
    discovery.py     メタデータと JWKS の発見（§11.2, §11.4）
    server.py        署名付きリクエストの検証、202 deferred 応答、problem+json
    events.py        全ロールが書き込む共通タイムライン（ラボ用の計測器）
  agent_provider/  agent token の発行（§5）
  person_server/   person token・auth token・mission・同意画面（§7, §8）
    supervisor.py    判断ロジックを差し替え可能な Protocol として分離
  resource/        文書 API。step-up と保留した呼び出しの実行（§6）
  agent/client.py  401 と 202 の両方に対応するエージェントの状態機械
  person.py        本人の代役（自動テスト用）と手動モード
  scenario.py      シナリオ A
```

## 仕様からの逸脱と簡略化

| 項目 | 仕様 | このラボ |
|---|---|---|
| サーバー識別子 | https、ポートなし（§11.1.1） | `http://localhost:<port>` も許可（`allow_loopback_http`） |
| agent token の取得 | 範囲外（bootstrap 仕様） | `POST /lab/enroll`（認証なし） |
| agent と person の紐付け | 範囲外。1対1であることは必須（§13.14） | 最初の接触時に Alice に自動で紐付け |
| 承認画面での本人認証 | 外部到達可能な PS は必須。免除はループバック限定・外部到達不可・OS レベルのアクセス制御が条件（§13.13） | 認証なし（ループバック限定）。免除に必要な OS レベルのアクセス制御は未確認 |
| PS の interaction 中継 | SHOULD（§11.6.3.2） | 未実装。agent が URL とコードを直接表示 |
| PS が人に聞かずに拒否する場合 | token endpoint での直接拒否のコードは規定なし | `403 denied`（ポーリング用エラーコードを流用） |
| 署名アルゴリズム | Ed25519 は MUST、ES256 は SHOULD | Ed25519 のみ |
| 暗号・署名の実装 | JWT / HTTP 署名の各検証規則（§11.3、§11.5） | Ed25519 の暗号演算は `cryptography`、Structured Fields は `http-sfv`。JWT 組み立てと HTTP 署名の署名基底・検証手順はラボ独自。信頼できる JWT / HTTP 署名ライブラリの採用・適合性確認は残課題で、この実験だけで安全性や仕様適合を保証しない |
| 未実装 | — | clarification chat、permission / audit endpoint、mission の update と completion、失効（revocation）、リプレイキャッシュ、AS（4者モード） |
| mission の終了 | mission control endpoint（コンパニオン仕様は TBD） | `POST /lab/missions/{s256}/revoke` |
