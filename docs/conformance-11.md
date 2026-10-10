# draft-hardt-oauth-aauth-protocol-11 対応表

この実装が -11 の規範的要件（MUST / SHOULD / REQUIRED / RECOMMENDED）をどこまで満たしているかの一覧です。**「仕様に準拠している」ことを示す文書ではありません。** 実装済みの部分が仕様の文言と合っているかをコードで確認した結果と、合っていない部分の記録です。

- 対象: `docs/spec/draft-hardt-oauth-aauth-protocol-11.txt`
- 基準のコード: commit `85af779`（2026-10-10）
- 方法: 原文から規範語を含む文を抽出し（387 文）、§15 IANA・§17 改版履歴・§19 参考文献を除いた全文を、実装のコードを読んで分類した。規範語を含まない検証手順（§5.3.3、§6.7.2、§6.7.3、§7.1.4、§9.4.3、§9.4.4、§11.3.4、§11.5.2 の番号付き手順）も対象に含めた。
- 限界: 分類はコードを読んで行った判断で、多くは自動テストで裏付けていない（「テスト」列）。参照先の仕様（I-D.hardt-httpbis-signature-key、RFC 9421）は読んでおらず、それらへの適合は確認していない。他の実装との相互運用も確認していない。

## 凡例

| 記号 | 意味 |
|---|---|
| ✅ 実装 | コードで要件を満たしている |
| 🟡 部分 | 一部だけ満たしている。不足を備考に書く |
| ⚠️ 逸脱 | ラボの都合で意図して満たしていない |
| ❌ 未実装 | 満たしていない（機能自体は実装している） |
| ➖ 対象外 | その機能・ロール自体を実装していない |
| ❓ 未確認 | 参照仕様を読んでいないなどの理由で判定できない |

テスト列: `T` = 自動テストで挙動を確認している、`—` = コードを読んで判断しただけ。

## 集計

表の行数で数えています（1行に複数の要件をまとめた行があるため、要件の数とは一致しません）。

| ✅ 実装 | 🟡 部分 | ⚠️ 逸脱 | ❌ 未実装 | ➖ 対象外 | ❓ 未確認 | 計 |
|---|---|---|---|---|---|---|
| 98 | 20 | 8 | 30 | 15 | 1 | 172 |

## まず知っておくべき不足

対応表のうち、ケース A の「誰が判断し、どこで止まるか」という結論に直接影響するものです。

1. **確認コードだけで承認できる（§11.6.3.1、§13.13、MUST）。** 同意画面は確認コードで開け、開いた画面のフォームから承認を送れます。本人の認証はありません。確認コードは agent が本人に伝えるので、**agent は自分の要求を自分で承認できます。** テスト用の「本人の代役」（`person.py`）は実際にこの経路で承認しています。このため、このラボでの「本人が判断した」は、「同意画面の操作が行われた」以上の意味を持ちません。
2. **確認コードの試行回数制限がない（§11.6.3.1、MUST）。** コードは 40 bit ですが、総当たりへの対策がありません。
3. **JWKS に未対応の鍵が混ざると検証全体が失敗する（§11.4、MUST）。** 例えば ES256 の鍵が1つでも JWKS にあると、Ed25519 の鍵も選べなくなります（実行して確認済み）。
4. **署名の失敗が正しいエラーコードで返らない（§11.3.4）。** `issuer_missing`、`issuer_mismatch`、`unknown_key`、`unsupported_algorithm`、`invalid_key` を区別せず、`invalid_jwt` にまとめています。メタデータや JWKS の取得に失敗した場合は、401 ではなく 500 になります。
5. **`parent_agent` を無視する（§10.2.2、MUST）。** サブエージェントの agent token で PS に token を要求しても拒否しません。ラボの AP はサブエージェントの token を発行しませんが、PS の検証としては不足です。
6. **person token の発行記録がない（§7.1、MUST）。** 失効の前提になる記録（jti、aud、exp）を残していません。

## 共通: 識別子とメタデータ（§11.1、§11.2）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 11.1.1 | issuer は https | MUST | ⚠️ 逸脱 | `core/ids.py:25` | — | `http://localhost` / `127.0.0.1` を許可 |
| 11.1.1 | scheme と host のみ（ポート、パス、クエリ、フラグメントなし） | MUST | ⚠️ 逸脱 | `core/ids.py:25` | — | ポートを許可。パス、クエリ、フラグメントは拒否 |
| 11.1.1 | 末尾スラッシュなし、小文字 | MUST | ✅ | `core/ids.py:33` | — | |
| 11.1.1 | IDN は A-label | MUST | ➖ | — | — | IDN を扱わない |
| 11.1.1 | 識別子は完全一致で比較 | MUST | ✅ | — | — | 正規化せず `==` で比較 |
| 11.1.2 | 各 endpoint と jwks_uri は https、クエリ・フラグメントなし | MUST | ⚠️ 逸脱 | 各 `metadata()` | — | http を使用 |
| 11.2 | 取得したメタデータの issuer の存在と一致を確認 | MUST | ✅ | `core/discovery.py:77-80` | — | |
| 11.2 | 欠落は `issuer_missing`、不一致は `issuer_mismatch` で拒否 | MUST | 🟡 部分 | `core/server.py:111-122` | — | 内部では区別するが、応答では `invalid_jwt` になる |
| 11.2 | name や description（Markdown）は表示前に無害化 | MUST | ✅ | `person_server/pages.py` | — | `html.escape`。Markdown として描画しない |
| 11.2.1 | AP メタデータの issuer、jwks_uri | REQUIRED | ✅ | `agent_provider/app.py:35` | T | |
| 11.2.2 | PS メタデータの issuer、jwks_uri、auth_token_endpoint、person_token_endpoint | REQUIRED | ✅ | `person_server/app.py:270` | T | |
| 11.2.2 | revocation_endpoint、scopes_supported、claims_supported | RECOMMENDED | ❌ | — | — | |
| 11.2.4 | Resource メタデータの issuer、jwks_uri | REQUIRED | ✅ | `resource/app.py:417` | T | |
| 11.2.4 | access_mode が auth-token なら、最初の呼び出しで person token を提示 | MUST | 🟡 部分 | `agent/client.py:215` | T | mission で person token を得ていれば提示する。access_mode 自体は読まない |
| 11.2.4 | agent は additional_signature_components を署名に含める | MUST | 🟡 部分 | — | — | agent はこのフィールドを読まない。ラボの Resource は宣言しないので実害はない |
| 11.2.4 | revocation_endpoint | RECOMMENDED | ❌ | — | — | |
| 11.2.5 | リンク関係 `aauth-resource` | — | ➖ | — | — | |

## 共通: 鍵、JWT、HTTP 署名（§11.3〜§11.5）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 11.3.1 | Ed25519 をサポート | MUST | ✅ | `core/keys.py` | T | 暗号演算は `cryptography` |
| 11.3.1 | ES256 をサポート | SHOULD | ❌ | — | — | |
| 11.3.1 | JWK の alg は必須かつ完全指定。欠落は拒否 | MUST | ✅ | `core/keys.py:22-31` | — | `Literal["Ed25519"]`。ただしエラーコードは `invalid_jwt`（`unsupported_algorithm` ではない） |
| 11.3.1 | EdDSA、none、対称鍵は使わない・受け付けない | MUST | ✅ | `core/tokens.py`（JoseHeader）、`core/keys.py` | — | 型で Ed25519 以外を拒否 |
| 11.3.1 | kty / crv と alg の不一致は拒否 | MUST | 🟡 部分 | `core/keys.py` | — | 拒否はするが、エラーコードが `invalid_key` ではない |
| 11.3.2 | agent は jwt スキームを使い、jwks_uri / hwk は使わない | MUST | ✅ | `core/httpsig.py:92`、`:174-176` | T | |
| 11.3.2 | サーバーとして署名する要求は jwks_uri スキーム | MUST | ➖ | — | — | サーバーから署名して送る要求（PS→AS、失効）がない |
| 11.3.3.1 | @method、@authority、@path、signature-key を署名対象に含める | MUST | ✅ | `core/httpsig.py:18`、`:109` | T | |
| 11.3.3.1 | 本文付きの PS 向け要求は content-digest、content-type も含める | MUST | ✅ | `core/httpsig.py:19`、`:157-163` | T | 本文があれば宛先を問わず要求する |
| 11.3.3.2 | created を含め、現在時刻にする | MUST | ✅ | `core/httpsig.py:109` | T | |
| 11.3.3.2 | agent は alg パラメータを付けない。検証側は無視する | MUST | ✅ | — | — | アルゴリズムは鍵から決めている |
| 11.3.3.2 | keyid を付けない。付いていても鍵は Signature-Key から取る | SHOULD NOT / MUST | ✅ | — | — | |
| 11.3.4 | 検証手順 1〜7 を実行し、失敗は 401 と Signature-Error | MUST | 🟡 部分 | `core/server.py:125`、`core/httpsig.py:135` | T | 手順は実装済み。エラーコードの区別が不足（上の「まず知っておくべき不足」4） |
| 11.3.4 | invalid_input では required_input を返す | — | ❓ | `core/httpsig.py:51` | T | ヘッダの構文を signature-key ドラフトで確認していない |
| 11.3.4 | created の有効期間はデフォルト 60 秒。古いと invalid_signature、未来なら clock_skew | MUST | ✅ | `core/httpsig.py:165-172` | — | |
| 11.3.4 | 未知のスキームは unsupported_scheme と Accept-Signature-Scheme | MUST | ✅ | `core/httpsig.py:174`、`core/server.py:58` | — | |
| 11.3.4 | 403 には Signature-Error などを付けない | MUST | ✅ | `core/server.py:44` | — | |
| 11.3.4 | NTP で時刻を同期 | SHOULD | ➖ | — | — | 1台で動かすので同じ時計 |
| 11.3.4.2 | expires パラメータがあれば守り、過去なら拒否 | MUST | ❌ | — | — | expires を読まない |
| 11.3.4.2 | リプレイキャッシュ | MAY | ➖ | — | — | |
| 11.4 | 公開する鍵は alg を持つ | MUST | ✅ | `core/keys.py:65` | — | |
| 11.4 | kid で鍵を選び、選ばない鍵が未対応でも失敗しない | MUST | ❌ | `core/keys.py`（Jwks） | — | 1つでも未対応の鍵があると JWKS 全体の読み込みが失敗する（実行して確認） |
| 11.4 | JWKS をキャッシュし、1分に1回より多く取得しない | MUST | ✅ | `core/discovery.py:15`、`:52-62` | — | |
| 11.4 | HTTP のキャッシュヘッダを尊重 | SHOULD | ❌ | — | — | |
| 11.4 | 未知の kid では再取得 | SHOULD | ✅ | `core/discovery.py:52-58` | — | |
| 11.4 | 取得に失敗したらキャッシュを使い、指数バックオフ | SHOULD | ❌ | `core/discovery.py:62` | — | 例外がそのまま伝わり 500 になる |
| 11.4 | 24 時間でキャッシュを破棄 | SHOULD | ✅ | `core/discovery.py:16` | — | |
| 11.4 | 署名検証に失敗したら一度だけ再取得 | SHOULD | ❌ | — | — | |
| 11.4 | メタデータや JWKS の取得前にエグレス制御 | MUST | 🟡 部分 | `core/discovery.py:70`、`config.py` | — | ラボの3サーバーだけを許可。signature-key ドラフトの定義と一致するかは未確認 |
| 11.5.1 | alg は完全指定、typ を確認してから扱う | MUST | ✅ | `core/tokens.py:148-159` | T | |
| 11.5.1 | cnf.jwk は alg を持つ | MUST | ✅ | `core/keys.py` | — | |
| 11.5.2 | 手順 1: typ を確認 | — | ✅ | `core/tokens.py:154` | T | |
| 11.5.2 | 手順 2: dwk を確認し、`{iss}/.well-known/{dwk}` から鍵を発見して署名を検証 | — | ✅ | `core/discovery.py:107-121` | T | dwk はモデルの Literal で確認 |
| 11.5.2 | 手順 3: exp を自分の時計で確認（猶予なし） | — | ✅ | `core/discovery.py:122` | — | |
| 11.5.2 | 手順 4: iss が有効なサーバー識別子 | — | ❌ | — | — | 受け取った iss を検証しない。エグレス制御で許可外の発行者には到達しない |
| 11.5.2 | exp − iat は 1 時間以下（発行側） | MUST | ✅ | 各 `lifetime()` 呼び出し | T | |

## 共通: AAuth-Requirement、deferred、エラー（§11.6〜§11.10）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 11.6.1 | requirement メンバーを含む Dictionary。未知のパラメータは無視 | MUST | ✅ | `core/requirement.py` | T | |
| 11.6.2 | 未知の requirement を満たせるものとして扱わない | MUST | ✅ | `core/requirement.py:42`、`agent/client.py` | T | |
| 11.6.3 | interaction は url（https）と code、Location、Retry-After を含む | MUST | 🟡 部分 | `person_server/app.py:259` | T | url が http（識別子と同じ逸脱） |
| 11.6.3.1 | Crockford base32、40 bit 以上、8 文字以上、暗号論的乱数 | MUST | ✅ | `person_server/state.py:126` | — | ちょうど 40 bit |
| 11.6.3.1 | ハイフン除去、大文字小文字を区別しない、I/L→1、O→0 | MUST | ✅ | `person_server/state.py:132` | — | |
| 11.6.3.1 | 承認・拒否は認証された経路で記録し、コードだけで承認させない | MUST | ❌ | `person_server/app.py:495-535` | T | 上の「まず知っておくべき不足」1 |
| 11.6.3.1 | コードは1回限り。再提示は invalid_code | MUST | ✅ | `person_server/state.py:162` | — | 画面上のメッセージで返す |
| 11.6.3.1 | 試行回数を制限し、失敗が続いたら終端扱い | MUST | ❌ | — | — | |
| 11.6.3.1 | コードの期限は保留中の要求より長くしない。期限後は expired | MUST | 🟡 部分 | `person_server/app.py:503` | — | 期限切れの要求は開けないが、`expired` のエラーコードではなく画面メッセージ |
| 11.6.3.2 | PS の interaction_endpoint で中継する | SHOULD | ❌ | — | — | agent が URL とコードを直接見せる |
| 11.6.4 | approval では Location と Retry-After | MUST | ➖ | — | — | approval を出す経路がない |
| 11.7 | agent は resource への要求に AAuth-Capabilities を付ける | SHOULD | ❌ | — | — | |
| 11.7 | ヘッダがなければ能力を仮定しない | MUST | ✅ | — | — | Resource は能力を使わない。PS は本文の capabilities を見て user_unreachable を返す |
| 11.8 | agent は 202 を常に処理する | MUST | 🟡 部分 | `agent/client.py:215` | T | resource の 202 は auth-token のときだけ処理し、それ以外はエラーにする |
| 11.8.2 | 202 に Location（同一オリジン）、Retry-After、Cache-Control: no-store、status | REQUIRED | ✅ | `core/server.py:147` | T | |
| 11.8.2 | 未知の status は pending として扱う | MUST | ✅ | `agent/client.py:370` | — | status を見ず、202 なら待ち続ける |
| 11.8.3 | Retry-After を守る。なければ 5 秒 | MUST | ✅ | `agent/client.py:281`、`:401` | T | |
| 11.8.3 | 429 なら間隔を 5 秒延ばす | MUST | ❌ | — | — | |
| 11.8.4 | 410 なら再試行しない | MUST | ✅ | `agent/client.py` | — | 202 以外は終端として扱う |
| 11.9.1 | 署名エラーはヘッダで判断し、本文に依存しない | MUST | ✅ | `agent/client.py` | — | |
| 11.9.1 | unsupported_algorithm に Accept-Signature-Alg | SHOULD | ❌ | — | — | このコード自体を返さない |
| 11.9.2 | problem+json の error で判断し、type に依存しない | MUST | ✅ | `core/server.py:44`、`agent/client.py` | T | |
| 11.10 | resource token の scope は scope_descriptions にあるものだけ | MUST | ✅ | `resource/app.py:45`、`person_server/app.py:384` | T | PS 側でも確認している |
| 11.10 | auth token の scope は resource token より広くしない | MUST | ✅ | `person_server/app.py:568` | T | 本人が狭めた場合も確認 |
| 11.12 | 失効エンドポイントと連鎖失効 | SHOULD ほか | ➖ | — | — | 未実装 |

## Agent と Agent Provider（§4.5、§5、§6.5、§6.7.3、§7.1、§7.9、§9.4.4）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 4.5 | PS を持つ agent の agent token は ps を含む | MUST | ✅ | `agent_provider/app.py:48` | T | |
| 5.1 | 参加前に AP から agent token を取得 | MUST | ⚠️ 逸脱 | `agent_provider/app.py:48` | T | 取得方法は範囲外。`/lab/enroll` に認証がない |
| 5.1 / 5.3.1 | agent token は 24 時間以内 | SHOULD | ✅ | `agent_provider/app.py:17` | — | 1 時間 |
| 5.2 | agent 識別子の文字種と長さ、+ の扱い、大文字小文字を区別した比較 | MUST | 🟡 部分 | `core/ids.py:18`、`:48` | — | 構文は確認するが、トップレベルで `+` を禁止していない |
| 5.3.1 | PS は未知のクレームを無視 | MUST | ✅ | `core/tokens.py`（extra="ignore"） | — | |
| 5.3.3 | 手順 1: cnf.jwk が要求の署名鍵と一致 | — | ✅ | `core/server.py:143` | T | cnf.jwk で HTTP 署名を検証する |
| 5.3.3 | 手順 2: ps が有効な https URL | — | ❌ | — | — | |
| 5.3.3 / 10.2.2 | parent_agent があればサブエージェントとして扱い、PS は直接の要求を拒否 | MUST | ❌ | — | — | 上の「まず知っておくべき不足」5 |
| 6.5 | agent は resource token を取り出して検証してから PS へ渡す | MUST | ✅ | `agent/client.py:306` | T | |
| 6.5 | step-up にいつでも対応 | MUST | ✅ | `agent/client.py:215` | T | |
| 6.5.1 | 401 と 202 の両方に対応 | MUST | ✅ | `agent/client.py:215` | T | |
| 6.7.3 | 手順 1〜7（iss、agent_jkt、ps、sub、presented_jti、exp を確認してから PS へ） | — | ✅ | `agent/client.py:306-329` | T | |
| 6.7.1 | 期限切れの resource token は取り直して再要求 | MUST | ❌ | — | — | `expired_resource_token` を受けたらそのまま失敗する |
| 6.7.1 | login_hint は変えずに渡す | MUST | ➖ | — | — | login_hint を使わない |
| 7.1 | person token を期限までキャッシュ | SHOULD | ✅ | `agent/client.py:290` | T | |
| 7.2.1 | platform、device の制約 | MUST | ➖ | — | — | 送らない |
| 7.9 | 鍵をローテーションしたら再認可 | MUST | ➖ | — | — | ローテーションしない |
| 7.9.1 | 残り 5 分未満で更新し、その間は提示しない | SHOULD | ❌ | — | — | |
| 8.2 | mission の s256 を検証 | SHOULD | ✅ | `agent/client.py:187` | T | |
| 8.8 | mission_terminated なら、その mission での行動をやめる | MUST | 🟡 部分 | — | T | エラーとして呼び出し元に返す。agent 側で mission を無効にする状態は持たない |
| 9.1.3 / 9.4.4 | auth token の aud と cnf が自分のものか確認 | MUST | ✅ | `agent/client.py:359` | T | |
| 9.4.4 | auth token の署名を検証 | SHOULD / RECOMMENDED | ❌ | — | — | 解析するだけ |
| 9.4.4 | iss が resource token の aud、sub が提示した token と一致 | — | ❌ | — | — | |

## Resource（§6、§7.1.1、§7.1.4、§9.4.3、§13.7）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 6.2 / 6.3 / 6.6 | resource 独自の同意、session token、authorization endpoint | — | ➖ | — | — | |
| 6.4 | person token がなければ requirement=person-token | MUST | ✅ | `resource/app.py:178-189` | T | |
| 6.5 | auth token が要るときは requirement=auth-token と resource-token パラメータ | MUST | ✅ | `resource/app.py:228` | T | |
| 6.5 | 保持済みの auth token で足りなければ新しい resource token で step-up | MAY | ✅ | `resource/app.py:208-226` | T | scope は既存分と追加分の和集合（仕様に規定なし） |
| 6.5.1 | 結果を少なくとも auth token の exp まで保持し、同じ token の再提示には保存済みの結果を返す | MUST | ✅ | `resource/app.py:359-391` | T | メモリ上に無期限で保持 |
| 6.5.1 | 記録は auth token の jti をキーにする | — | ✅ | `resource/app.py:391` | T | |
| 6.5.1 | resource token が切れていたら後の poll で新しいものを渡す | MAY | ✅ | `resource/app.py:397-407` | — | |
| 6.7 | resource token を出す前に person token か auth token を検証。どちらもなければ person-token | MUST | ✅ | `resource/app.py:172` | T | |
| 6.7.1 | aud（三者構成では person token の iss）、ps、sub、presented_jti、agent_jkt | REQUIRED | ✅ | `resource/app.py:145-168` | T | |
| 6.7.1 | mission_s256 を変えずにコピー | REQUIRED | ✅ | `resource/app.py:202`、`:222` | T | |
| 6.7.1 | 5 分以内 | SHOULD | ✅ | `resource/app.py:43` | — | |
| 6.7.1 | 受け取った auth token のクレームを要求内容と照合 | MUST | ✅ | `resource/app.py:212-214`、`:370` | T | scope を照合 |
| 7.1.1 / 13.11 | person token を auth token の代わりに受け付けない | MUST | ✅ | `resource/app.py:190` | T | person token では常に challenge を返す |
| 7.1.1 / 13.9 | person token を本人確認の証拠として扱わない | MUST | ✅ | — | — | 扱っていない |
| 7.1.4 | person token の aud が自分、cnf.jwk が署名鍵 | — | 🟡 部分 | `resource/app.py:192` | — | 確認はするが、失敗は Signature-Error ではなく problem+json の 401 |
| 7.1.4 / 9.4.3.2 | (iss, sub) を識別子とし、記録と照合 | MUST | ❌ | — | — | 利用者の記録を持たない |
| 9.4.3.2 | auth token の aud が自分、cnf.jwk が必須で署名鍵と一致 | — | ✅ | `resource/app.py:210`、`core/server.py:143` | T | |
| 13.2 | pending URL は推測不能で期限付き。poll ごとに agent を確認 | MUST | ✅ | `resource/app.py:265`、`:352` | T | 鍵の thumbprint で確認 |
| 13.2 | 終端の応答の後は 410（保持期間中の再提示は除く） | MUST | 🟡 部分 | `resource/app.py:368`、`:396` | T | 別の token なら 410。期限切れは何度でも 408 を返す |
| 13.7 | PS が発行した auth token を bearer として扱わず、自分のポリシーを適用 | MUST | ✅ | `resource/app.py:310` | T | 保護された文書は拒否 |

## Person Server（§7、§8、§9.4.1）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 7 | すべての PS エンドポイントは agent token の HTTP 署名で認証 | — | ✅ | `person_server/app.py:147` | T | |
| 7.1 | person_token_endpoint を公開し、そこで person token を発行 | MUST | ✅ | `person_server/app.py:308` | T | |
| 7.1 | resource パラメータをサーバー識別子の規則で検証 | MUST | ❌ | `person_server/app.py:315` | — | 検証せずに aud にしている |
| 7.1 | mission_s256 の存在、有効性、所有者を確認 | MUST | ✅ | `person_server/app.py:236` | T | |
| 7.1 | 初めての resource では、メタデータを取得して名前などを提示 | SHOULD | ❌ | — | — | |
| 7.1 | 発行した person token の jti、aud、exp を記録 | MUST | ❌ | — | — | 上の「まず知っておくべき不足」6 |
| 7.1 | agent ごとに resource の数を制限 | SHOULD | ❌ | — | — | |
| 7.1 / 13.8 | 初めての resource 向けの person token は本人の承認を要する | SHOULD | 🟡 部分 | `person_server/app.py:538-566` | T | mission の承認時に列挙された resource は承認済み。`/person` は聞かずに発行する |
| 7.1.2 | person token は 1 時間以内で、agent token より長生きしない | MUST | ✅ | `person_server/app.py:173` | — | |
| 7.1.2 | mission の expires_at より長生きしない | MUST | 🟡 部分 | — | — | expires_at を設定しないので発生しない。確認処理もない |
| 7.1.2 | scope、account を含まない | MUST | ✅ | `core/tokens.py:62` | T | |
| 7.2.1 | resource_token、presented_token は必須 | REQUIRED | ✅ | `person_server/app.py`（AuthTokenRequest） | — | |
| 7.2.1 | justification は agent の主張として表示し、無害化 | MUST | ✅ | `person_server/pages.py` | — | |
| 6.7.2 | 手順 1: aud が自分 | — | ✅ | `person_server/app.py:331` | T | |
| 6.7.2 | 手順 2: agent_jkt が署名鍵の thumbprint | — | ✅ | `person_server/app.py:333` | T | |
| 6.7.2 | 手順 3: presented token を typ で検証（aud は resource token の iss、cnf は agent_jkt） | MUST | ✅ | `person_server/app.py:337-361` | T | 自分が発行した token だけを受け付ける |
| 6.7.2 | 手順 3: jti、sub、mission_s256、tenant の一致。不一致は invalid_resource_token | — | ✅ | `person_server/app.py:353-360` | — | |
| 6.7.2 | 不一致を運用者に通知 | SHOULD | ❌ | — | — | event に記録しない |
| 6.7.2 | ps が自分 | MUST | ✅ | `person_server/app.py:331` | — | |
| 6.7.2 | 手順 4: mission が有効で expires_at 前 | MUST | 🟡 部分 | `person_server/app.py:370` | T | 有効性は確認する。expires_at は確認しない |
| 6.7.1 | mission 内で同意を記憶し、聞き直さない | SHOULD | ✅ | `person_server/app.py:586`、`supervisor.py` | T | |
| 7.2.2 | 並行する要求を独立に扱う | MUST | ✅ | `person_server/state.py:146` | — | |
| 7.3 / 7.3.1 / 7.2.3 | callback、resource 起点の interaction | — | ➖ | — | — | |
| 7.4 | resource の主張と agent の主張を見た目で区別し、agent の主張は agent のものと明示 | MUST | ✅ | `person_server/pages.py` | — | |
| 7.4 / 13.4 | agent の主張だけで判断しない | MUST NOT | ✅ | `person_server/supervisor.py` | — | Supervisor は justification を判断に使わない |
| 7.5〜7.8 | clarification、interaction、permission、audit の各エンドポイント | — | ➖ | — | — | |
| 7.9 / 9.4.1 | auth token は 1 時間以内で、agent token と presented token より長生きしない | MUST | ✅ | `person_server/app.py:386`、`:195` | T | step-up で期限が延びないことをテストで確認 |
| 9.4.1 | mission の expires_at より長生きしない | MUST | 🟡 部分 | — | — | 7.1.2 と同じ |
| 9.4.1 / 14.1 | sub はリソースごとの仮名で、agent や鍵によって変わらない | SHOULD / MUST | ✅ | `person_server/app.py:166` | — | (PS, person, resource) から導出 |
| 8 | mission 自身の URL への action（update、completion） | — | ➖ | — | — | |
| 8.1 | mission の提案は agent token の署名付き POST | MUST | ✅ | `person_server/app.py:287` | T | |
| 8.2 | 応答の s256、mission、blob の agent、approved_at、description | REQUIRED | ✅ | `person_server/app.py:538-566` | T | |
| 8.2 | mission を扱うすべての判断で expires_at を確認 | MUST | ❌ | — | — | フィールドはあるが確認しない（設定もしない） |
| 8.2.1 | 保存したバイト列に対して s256 を計算し、同じバイト列を返す | MUST | ✅ | `person_server/state.py:51-53` | T | |
| 8.2.1 | 監査で公開するときも同じバイト列を返す | MUST | ➖ | — | — | 監査用の公開経路がない |
| 8.6 | 終了した mission での要求は mission_terminated。active には戻さない | MUST | ✅ | `person_server/app.py:236-257` | T | |
| 8.7 | mission が存在しない場合と他人の場合で同じ応答を返し、認可前に何も明かさない | MUST | 🟡 部分 | `person_server/app.py:240` | — | 応答は同じ。応答時間の差は測っていない |
| 8.8 | 403 と mission_status、termination_reason | MUST | ✅ | `person_server/app.py:249` | T | |

## セキュリティとプライバシー（§13、§14）

| 節 | 要件 | 強度 | 状態 | 根拠 | テスト | 備考 |
|---|---|---|---|---|---|---|
| 3 / 13.3 | 表示前に値を無害化し、処理前に検証 | MUST | 🟡 部分 | `person_server/pages.py`、pydantic モデル | — | 表示は escape する。PS の `resource` パラメータなど、検証していない入力がある |
| 13.2 | PS の pending URL: 推測不能、期限付き、poll ごとに agent を確認、終端の後は 410 | MUST | ✅ | `person_server/state.py:150`、`person_server/app.py:454-484` | T | |
| 13.7 | PS の署名鍵を適切に保護 | MUST | ⚠️ 逸脱 | — | — | 起動ごとにメモリ上で生成し、保護していない |
| 13.10 | tenant を person の識別子の一部にしない | MUST | ✅ | — | — | tenant を使わない |
| 13.11 | typ を確認し、auth token が要る場所で person token を拒否 | MUST | ✅ | `core/tokens.py:154`、`resource/app.py:190` | T | |
| 13.12 | 追加の同意を求めるときは全体像を見せる | SHOULD | ❌ | — | — | 同意画面に mission の本文やこれまでの同意を出さない |
| 13.13 | 外部から到達できる承認画面では本人を認証 | MUST | ⚠️ 逸脱 | `person_server/app.py:495` | — | ループバックでのみ起動。OS レベルのアクセス制御による免除条件は確認していない |
| 13.14 | agent ごとに person は 1 人 | MUST | ✅ | `person_server/app.py:154` | — | 人が Alice だけ |
| 13.14 | agent を (iss, sub) で識別 | — | 🟡 部分 | `person_server/state.py:140` | — | sub（agent 識別子）だけで識別 |
| 13.14 | 新しい agent の登録を同意画面で明示 | SHOULD | ❌ | — | — | 自動で紐付ける |
| 13.15 / 14.2 | アクセス制御、監査ログ、データ保持方針 | MUST | ⚠️ 逸脱 | `core/events.py` | — | events は計測用で、アクセス制御はない |
| 13.16 | TLS 1.2 以上 | MUST | ⚠️ 逸脱 | — | — | http |
| 14.1 | sub は発行者内で一意で、person token、resource token、auth token で同じ値 | MUST | ✅ | `person_server/app.py:166`、`resource/app.py:145` | T | |

## 機能ごと実装していない節

| 節 | 内容 |
|---|---|
| §4.2.1〜4.2.3、§4.2.5 | 三者構成（§4.2.4）以外のアクセスモード |
| §6.2、§6.3、§6.6 | resource 独自の同意と session token、authorization endpoint |
| §7.2.3、§7.3（callback）、§7.3.1 | resource 起点の interaction、callback とそのエラー |
| §7.5 | clarification chat |
| §7.6〜§7.8 | interaction、permission、audit の各エンドポイント |
| §8.3〜§8.5 | mission log の公開、update、completion |
| §9.1〜§9.3、§11.2.3 | Access Server との連携（四者構成） |
| §9.4.5、§10 | upstream token、呼び出しの連鎖、サブエージェント |
| §11.2.5 | リンク関係 |
| §11.12 | 失効 |
| §12 | 段階的な導入（R3 の語彙など） |

## 参照仕様で未確認のもの

| 参照先 | このラボで影響する箇所 |
|---|---|
| I-D.hardt-httpbis-signature-key | Signature-Key ヘッダの形式、Signature-Error の構文（特に required_input）、エグレス制御の定義、`issuer_missing` などのエラーの扱い。AAuth 本文の例から推測して実装した |
| RFC 9421 | 署名基底の組み立て、@authority や @path の正規化、Signature-Input の再シリアライズ。テストベクタと照合していない |
| RFC 9530 | Content-Digest。sha-256 だけを実装 |
| RFC 7638 | JWK thumbprint。OKP の必須メンバー（crv、kty、x）で計算している |
