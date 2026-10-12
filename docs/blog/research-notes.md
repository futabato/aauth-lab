# 調査メモ

調査基準日：**2026-10-09**／文書整備日：**2026-10-10**／用語・RFC 6749第1節の追加確認：**2026-10-12**

提供された調査 Page の整理です。以下の「既存調査で確認した内容」は 2026-10-09 時点の記録を引き継いだものです。2026-10-12の追加確認は、Hellōの登録対象の説明とRFC 6749第1節の訂正事項に記し、調査全体の更新とは区別します。公開前に最新版・議論・issue の状態を再確認します。[記事構成](outline.md) と [原稿](draft.md) は別に管理します。

## 記事上の決定と現在の状態

- タイトルは「AAuthは何を再設計するのか――AIエージェントの認可における課題と設計」。硬派な技術記事として、背景の課題、歴史、設計変更の理由を説明します。
- 記事は6節構成です。第1・3・4節に6〜7割を置くのは分量配分の案です。本文全文は未執筆です。
- `aauth-lab` は選定済みで、文書 API と AP・PS・Resource、固定スクリプトの Agent が既存です。前の作業では `AGENTS.md` / `README.md` を追記しただけで、起動・動作確認・テストは未実施でした。2026-10-12の文書確認ではmypy・ruffと既存テスト11件が通りましたが、記事用の実験結果は未実測です。
- 古い「名前未決定・リポジトリ未作成・未実装」という現状説明は更新しました。実装の詳しい状態と簡略化は [ルート README](../../README.md) を参照し、コードの存在を検証成功の根拠にしません。
- 並行作業で追加された [仕様対応表](../conformance-11.md) とルート README は、protocol-11 に未準拠であることを明記しています。対応表はコード読解に基づく記録であり、今回その分類の再監査は行っていません。本人認証のない同意画面では agent が自分の要求を承認できるため、同意フローの動作と本人の判断の保護を区別します。

## 背景：HellōのMCPサーバー開発

### 既存調査で確認した内容

[Dick Hardt の2025-08-04の実装記事](https://blog.hello.coop/posts/say-hello-to-ai) は、VS Code、Cursor、Claude などから既存の Hellō 管理 API を利用する MCP サーバーの開発経験です。MCP プロトコル自体の開発経験として紹介しません。[SEP 1299 の実装背景](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1299) も参照します。

管理対象となるサービスを Hellō の OIDC クライアントとして登録する操作と、管理 API を呼び出す MCP クライアントを OAuth クライアントとして登録する DCR は別の処理です。サービスの登録情報には名前・ロゴ・戻り先などがあり、その Client ID はログイン設定に使います。[Getting Started](https://www.hello.dev/docs/getting-started/)

DCR で得る `client_id` は本人の ID、アクセス許可、client への信頼そのものではありません。

### 著者の懸念と実装上の選択

Hardt は登録レコードの増加とライフサイクルを懸念し、MCP 向け登録エンドポイントが共通の `client_id` を返し、任意の `redirect_uri` を許す構成を選びました。一般に推奨する構成として扱いません。

権限は quickstart が作成中心、console が破壊的操作を含む管理、mcp が読み取り・作成・追加的更新で、mcp から削除を除外しました。refresh token も発行せず、必要時に再認可させています。これは token 漏洩の実事故ではなく、漏洩への懸念に基づく判断です。Web UI の DELETE 入力は削除操作の確認であり、操作範囲を表す scope と同じ安全策ではありません。

## OAuthとMCPを説明するときの訂正事項

| 論点 | 既存調査の結論と注意点 | 一次資料 |
|---|---|---|
| パスワード共有の問題 | RFC 6749 第1節は、外部のソフトウェアが資格情報を保存する必要と、ユーザがアクセス期間や対象を一部に限定できないことを挙げる。原稿では二つの箇条書きの冒頭を合計22語で引用し、平文パスワードなど省いた内容は日本語で説明する。同じサービスのパスワードを複数の外部ソフトウェアへ渡す場合、特定相手のアクセス取り消しのためのパスワード変更がほかの相手のアクセスも止める、という第4の箇条書きも日本語で説明する。ここには原文を重複掲載しない。2026-10-12に原文を照合 | [RFC 6749 §1](https://www.rfc-editor.org/rfc/rfc6749.html#section-1) |
| MCP の DCR | 2025-06-18 版では MUST ではなく SHOULD。静的 `client_id`・手動登録の代替がある。Hardt の「必要だった」という認識と要求水準を分ける | [MCP Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) |
| DCR の運用 | 共有 `client_id`、ステートレスな登録管理、software statement、濫用対策の余地がある。「無制限にレコードを保持するしかない」と書かない | [RFC 7591](https://www.rfc-editor.org/rfc/rfc7591) |
| 操作の確認 | 当時の Elicitation にも accept・decline・cancel がある。「確認機構が一切なかった」と一般化しない | [MCP Elicitation](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation) |
| token の鍵結合 | OAuth は Bearer token に限定されない。DPoP は鍵所持に token を結び付ける拡張で、client 認証そのものとは別 | [RFC 9449](https://www.rfc-editor.org/rfc/rfc9449) |
| 詳細な認可要求 | RAR は詳細な認可要求を表せる。操作承認を含む構成も検討できる | [RFC 9396](https://www.rfc-editor.org/rfc/rfc9396) |

Hellō が Elicitation を採用しなかった理由と、当時の各 client の対応状況は未確認です。追加同意は OAuth と拡張でも可能なので、このラボのデモ成功だけで AAuth の優位性は証明できません。

## 歴史とSEP 1299の位置付け

### 既存調査で確認した時系列

| 時期 | 資料 | 記事での扱い |
|---|---|---|
| 2012年 | [OAuth 2.0 / RFC 6749](https://www.rfc-editor.org/rfc/rfc6749) | 委譲モデルの出発点 |
| 2015年 | [DCR / RFC 7591](https://www.rfc-editor.org/rfc/rfc7591) | client 登録の拡張 |
| 2020年 | [Token Exchange / RFC 8693](https://www.rfc-editor.org/rfc/rfc8693) | token の交換・委譲を扱う拡張 |
| 2023年 | [RAR / RFC 9396](https://www.rfc-editor.org/rfc/rfc9396)、[DPoP / RFC 9449](https://www.rfc-editor.org/rfc/rfc9449) | 詳細な認可要求と鍵所持証明 |
| 2024年 | [GNAP / RFC 9635](https://www.rfc-editor.org/rfc/rfc9635) | 別の再設計の試み。OAuth→GNAP→AAuth の一本道にはしない |
| 2025-08-04 | [SEP 1299](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1299) | 認可処理の責任分担を移す提案 |
| 2026-04-02 | [draft-hardt-aauth-protocol-00](https://datatracker.ietf.org/doc/html/draft-hardt-aauth-protocol-00) | 最初の IETF Internet-Draft。構想の誕生日とは断定しない |
| 2026-09-25 | [draft-hardt-oauth-aauth-protocol-11](https://datatracker.ietf.org/doc/html/draft-hardt-oauth-aauth-protocol-11) | 2026-10-09 調査と再現実験の対象版 |

### 提案の内容と解釈

SEP 1299 は client 側の discovery・registration・token 管理の負担を server 側へ移し、HTTP 署名で client instance の鍵と結び付け、利用者への直接の interaction を設ける提案です。背後の既存 API との OAuth は維持できます。認可をなくすことではなく、誰が認可処理を担うかが論点です。

初期案の歴史資料と protocol-11 の検証根拠は分けます。protocol-11 は個人提出の草案であり、WG採用済み仕様や RFC として紹介しません。

## AAuthの設計と境界

根拠は [protocol-11 本文と設計理由](https://datatracker.ietf.org/doc/html/draft-hardt-oauth-aauth-protocol-11)、実験で読む原文は [固定仕様ファイル](../spec/draft-hardt-oauth-aauth-protocol-11.txt) です。

### 既存調査で確認した設計

- AP（Agent Provider）は agent の識別子と instance の鍵を結び付けます（§5）。agent は署名付き要求を送り、PS（Person Server）は本人側の同意・監督を担います（§7）。
- AS（Access Server）がある場合はリソース側の認可ポリシーを判断します。Resource 自身のポリシー適用も必要です。常に独立した4者を置く設計ではなく、5つのアクセスモードと役割の同居を扱います（§4.2、§4.4）。ラボは独立 AS を含みません。
- Mission は人の意図を表します。自然言語の目的だけで API の金額・対象・回数を機械的に強制するものではありません（§8）。`approved_tools` は事前許可の記録であり、protocol 自体がローカルなツール実行を禁止する仕組みではありません。プロンプトインジェクション防止の保証として紹介しません。
- PS と AS の信頼確立には §9.3.1 の手順があり、受け入れ条件は各実装のポリシーに依存します。「信頼確立は仕様の範囲外」と一括りにしません。
- 失効エンドポイントへの対応は SHOULD で、未対応先では token の `exp` まで効力が残り得ます（§11.12）。

### 探索的R3と未確認の範囲

[公式サイト](https://aauth.dev/) の R3 は探索的な提案として区別します。呼び出し単位の grant を扱うため、「操作単位の承認は不可能」とは断言しません。成熟度・対象版・強制範囲は protocol-11 本文と分けて評価し、R3 の詳細な仕様とラボでの実装・動作は今回未確認です。

## OAuth拡張と独立プロトコルをめぐる議論

### 参加者の主張と記録の位置付け

2026-10-05 OAuth interim の [公開メモ](https://notes.ietf.org/notes-ietf-interim-2026-oauth-06-oauth) と [チャット記録](https://datatracker.ietf.org/doc/chatlog-interim-2026-oauth-06-202610051300/) を参照します。既存調査では、Aaron らの OAuth 拡張へ取り込む方向と、Dick の異なる基礎を持つ protocol の方向が議論されました。

議長はメーリングリストで何を問うかを検討する形で締めており、進路が合意済みとは書きません。公開メモを正式議事録とは呼びません。protocol-11 の付録 C.4.5「Why Not Extend OAuth」にある強い一般化も著者の主張として扱い、OAuth 全般の確定事実に置き換えません。

その後の議論と結論は、公開前の再確認事項です。

## 未解決事項：2026-10-09時点の記録

issue の存在は脆弱性の実証や欠陥認定ではありません。以下の状態を現在も継続中と断定せず、公開前に確認します。

| 論点 | 既存調査の記録 | 次の確認 |
|---|---|---|
| [Issue 108](https://github.com/dickhardt/AAuth/issues/108) | 長時間の承認待ちにおける grant、鍵更新、関連証跡の寿命。調査時点では -12 へ持ち越す論点 | 議論と解決状態。後続版の情報を -11 の実験に混ぜない |
| [Issue 222](https://github.com/dickhardt/AAuth/issues/222) | 秒単位の `created` と同条件の要求が replay cache で正当な再要求と衝突し得る。任意 nonce の案 | 仕様の採用状態。protocol-11 で nonce 必須とは書かない |
| [Issue 221](https://github.com/dickhardt/AAuth/issues/221) | 中継主体が別人の有効な upstream token を取り違えた場合の検知境界の質問 | 質問・未解決状態と攻撃実証を区別する |
| [Issue 208](https://github.com/dickhardt/AAuth/issues/208) | AP の self-host を認める本文と、独立 AP を前提にした設計理由の整合 | 文書修正の状態。WG 全体の方針対立に広げない |

記事終盤では、意図の解釈を誰に任せるか、業務 API の制約をどこで強制するか、AP・PS の信頼と鍵管理、PS への集中、非同期承認後の再試行・二重実行、失効反映、既存 OAuth との共存・移行を詰めます。送信元や要求の署名検証と、業務処理を一度だけ実行することは別の問題です。

## 検証を記事へ結び付けるメモ

**状態：検証待ち。実験結果は未実測です。** 条件と判定基準は [ルート README](../../README.md) に置き、ここでは記事で何を説明するかを管理します。

| 観測すること | 記事へ残す証拠 | 解釈の境界 |
|---|---|---|
| 読み取り権限から削除への追加同意 | 通信順序、要求 scope、同意の状態遷移、判断主体・理由 | 追加同意はラボが選ぶポリシー。OAuth でも実現可能 |
| pending・拒否・権限縮小で副作用がないこと | API の実行記録と文書一覧・内容の前後差分 | HTTP ステータスや画面だけで判断しない |
| 承認後の削除 | 有効な鍵・audience・期限・scope と Resource の判断、実行記録、状態差分 | 成功だけで AAuth の優位性や仕様適合は証明しない |
| 別鍵・期限切れ・別 audience・無効な token 署名・HTTP 改ざん | 公開 claims、鍵 thumbprint、失敗条件、判断主体・理由、データ不変 | 条件を個別に変える。署名後の改ざんと新しい正しい署名を分ける |
| 別文書 B への新しい正しい署名付き要求 | 対象、同意した scope、Resource のポリシー、前後状態 | `docs.delete` は文書 A・一度限りの許可ではない。B へ通っても直ちに脆弱性とは扱わない |

対象・回数を限定する制御は、Resource 側の明示的な業務ポリシーまたは探索的 R3 の後続検証に分けます。所有者チェックは Resource 側のポリシーであり、現在の保護文書チェックと同じではありません。deferred 再 poll の再実行抑止も、token 全体を一回限りにする制御とは別です。

AP の bootstrap、Alice の自動紐付け、本人の代役による初回 mission 承認、loopback の認証省略、JWT / HTTP 署名のラボ独自部分など、既存の簡略化・残課題を実験結果の限定条件として残します。実データ・実アカウントは使わず、秘密鍵や本物の認証情報を記録しません。

## スライドの進捗と図の候補

以下は提供された調査 Page の進捗記録です。最初は背景説明8枚、その後 MCP 実装の課題に絞った6枚の PowerPoint / PDF を 2026-10-09 に納品し、情報密度を増やす改稿も完了しています。ファイル名は「MCP実装で表面化した認可の課題_6枚図解_完成版」。会話に添付済みとされていますが、今回は添付ファイル・所在・内容を確認していません。

6枚の構成：

1. client 登録→本人のログイン・同意→token 発行→API 実行の全体像
2. MCP クライアントの DCR と、管理対象となるサービスの OIDC クライアント登録の違い
3. 登録運用の懸念と共通 `client_id` という実装選択
4. scope の範囲と削除操作の確認・除外
5. Bearer token と refresh token をめぐる判断
6. SEP 1299 が提案する認可処理の責任分担

図は明快にし、1枚あたりの情報量は多くて構いません。本文だけでも条件と根拠が読め、図で主体・流れ・判断点が分かる構成にします。重要な説明を発表者ノートだけに置きません。

## 再開地点と公開前の確認

- [ ] 改稿済み6枚を確認し、第1節の説明順・図を固めて本文を書く。
- [ ] 第2節に向けて OAuth 拡張との対応関係を整理する。
- [ ] ラボの実験を実測し、公開可能な証跡と限定条件を揃える。未実測のまま結果を補完しない。
- [ ] 最新仕様・標準化状態・公開議論・各 issue の解決状態を再確認し、確認日を更新する。
- [ ] R3 を扱う場合は対象版・成熟度・強制範囲を確認する。protocol-11 固定実験と混ぜない。
- [ ] 著者・参加者の主張と事実を再点検し、出典・図・原稿・実験の条件を確認する。外部公開はまだ行っていない。
