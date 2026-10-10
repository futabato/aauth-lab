# 記事構成

**AAuthは何を再設計するのか――AIエージェントの認可における課題と設計**

調査基準日：2026-10-09／文書整備日：2026-10-10

6節の順序は合意済みです。第1・3・4節に全体の6〜7割を置くのは配分案で、原稿量は未確定です。根拠の詳細・注意点は [調査メモ](research-notes.md)、執筆は [draft.md](draft.md)、進捗は [入口](README.md) に置きます。

## 1. MCPサーバー開発で表面化した認可課題

- **問い**：既存の Hellō 管理 API を MCP 経由で利用するとき、クライアント登録の運用、破壊的操作の確認、token 保管で何が問題になったか。
- **根拠**：[Hardt の実装記事](https://blog.hello.coop/posts/say-hello-to-ai)、[SEP 1299 の実装背景](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1299)。管理対象の app 登録と OAuth client の DCR を分ける。
- **説明する境界**：MCP プロトコルの開発経験ではなく、MCP サーバーの開発経験。共通 `client_id` と任意 `redirect_uri` は個別の実装選択。漏洩への懸念は漏洩事故の実証ではない。
- **図案**：client 登録→本人のログイン・同意→token 発行→API 実行の流れ。app 登録は別の処理として描き、削除の操作確認と scope を区別する。
- **状態**：執筆待ち。既存6枚のレビューと第1節の説明順・図の決定待ち。

## 2. OAuthが解決してきた問題と拡張

- **問い**：OAuth の委譲モデルと既存拡張は、登録・委譲・詳細な認可要求・鍵結合をどこまで扱えるか。
- **根拠**：[RFC 6749](https://www.rfc-editor.org/rfc/rfc6749)、[DCR / RFC 7591](https://www.rfc-editor.org/rfc/rfc7591)、[Token Exchange / RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)、[RAR / RFC 9396](https://www.rfc-editor.org/rfc/rfc9396)、[DPoP / RFC 9449](https://www.rfc-editor.org/rfc/rfc9449)。MCP は [2025-06-18 版 Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) と [Elicitation](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation) を使う。
- **説明する境界**：DCR は SHOULD で代替がある。DPoP は client 認証そのものではない。OAuth を Bearer token だけに限定せず、追加同意・操作承認が可能な構成を正当に扱う。
- **図案**：課題と拡張の対応表。委譲、登録、要求の詳細化、鍵所持証明、操作確認を別の列に置く。
- **状態**：執筆待ち。拡張との対応関係の整理待ち。当時の Elicitation の client 対応と Hellō が採用しなかった理由は未確認。

## 3. SEP 1299からAAuthへの経緯

- **問い**：クライアントの discovery・registration・token 管理をサーバー側へ移す提案は、どの設計変更を求めていたか。
- **根拠**：[SEP 1299](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1299)（2025-08-04）、[最初の Internet-Draft -00](https://datatracker.ietf.org/doc/html/draft-hardt-aauth-protocol-00)（2026-04-02）、[protocol-11](https://datatracker.ietf.org/doc/html/draft-hardt-oauth-aauth-protocol-11)（2026-09-25）。比較の補助に [GNAP / RFC 9635](https://www.rfc-editor.org/rfc/rfc9635) を使う。
- **説明する境界**：既存 API との OAuth は維持できる。認可をなくす提案ではなく、処理を誰が担うかの提案。初稿公開日は構想の誕生日とは断定しない。OAuth→GNAP→AAuth という必然的な進化にはしない。
- **図案**：SEP の前後で認可処理を担う主体を比較する図と、提案・初稿・対象版を示す時系列。
- **状態**：執筆待ち。歴史の根拠は既存調査に基づき、公開前の再確認待ち。歴史資料の -00 を -11 の実装根拠に混ぜない。

## 4. AAuthによる認可の役割分担の再設計

- **問い**：AP、Agent、PS、Resource、必要に応じた AS は、それぞれ何を識別・判断・強制するか。
- **根拠**：[固定仕様 protocol-11](../spec/draft-hardt-oauth-aauth-protocol-11.txt) のアクセスモード・判断点（§4.2、§4.4）、person token（§7.1）、同意表示（§7.4）、Mission（§8）、信頼確立（§9.3.1）、HTTP 署名と scope（§11.3、§11.10）。実験条件は [ルート README](../../README.md)。
- **説明する境界**：常に独立4者を置く構成ではない。Resource のポリシー適用も必要。自然言語の Mission や `approved_tools` が対象・回数・ローカルなツール実行を自動で強制するとは書かない。
- **図案**：5アクセスモードの役割配置図と、ラボの三者認可フロー。通信順序、同意の判断点、保留、実行、前後状態を対応付ける。
- **状態**：執筆待ち・検証待ち。追加同意、拒否・pending 時の副作用不変、鍵結合を観測してから結果を書く。scope と文書 ID・回数、HTTP 改ざんと別対象への新規署名、再 poll と一度限りの grant を分ける。ラボの本人認証不足と未準拠の限定は [仕様対応表](../conformance-11.md) とルート README に従う。

## 5. OAuth拡張か別プロトコルかという意見対立

- **問い**：既存の OAuth 拡張へ取り込む案と、基礎から設計する案は、何を共有し何で対立するか。
- **根拠**：2026-10-05 OAuth interim の [公開メモ](https://notes.ietf.org/notes-ietf-interim-2026-oauth-06-oauth)、[チャット記録](https://datatracker.ietf.org/doc/chatlog-interim-2026-oauth-06-202610051300/)、protocol-11 の設計理由（付録 C.4.5）。
- **説明する境界**：参加者の提案と合意を分ける。公開メモを正式議事録とは呼ばず、著者の「Why Not Extend OAuth」を OAuth 全般の確定事実にしない。
- **図案**：両案の設計単位、既存資産との関係、責任分担を比較する表。優劣を先に決めない。
- **状態**：執筆待ち。議論の結論・その後の進路は公開前の再確認待ち。

## 6. 現在地と残る課題

- **問い**：標準化・実装・運用で何が決まっておらず、何を追加で確かめる必要があるか。
- **根拠**：[protocol-11](https://datatracker.ietf.org/doc/html/draft-hardt-oauth-aauth-protocol-11)、[Issue 108](https://github.com/dickhardt/AAuth/issues/108)、[222](https://github.com/dickhardt/AAuth/issues/222)、[221](https://github.com/dickhardt/AAuth/issues/221)、[208](https://github.com/dickhardt/AAuth/issues/208)、[公式サイトの探索的 R3](https://aauth.dev/)。論点は [調査メモ](research-notes.md) を参照する。
- **説明する境界**：個人提出の Internet-Draft で、WG採用済み仕様や RFC として扱わない。issue の存在と脆弱性の実証は別。R3 の成熟度・対象版・強制範囲は本文仕様と分けて評価する。
- **図案**：仕様で確認すること、Resource の業務ポリシー、運用で決めること、未解決事項の対応表。
- **状態**：執筆待ち・最新情報の再確認待ち。AP・PS の信頼、鍵管理、非同期承認と二重実行、失効、既存 OAuth との共存・移行を詰める。ラボの結果は未実測のまま残す。
