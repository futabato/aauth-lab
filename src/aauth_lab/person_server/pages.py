"""The person's surfaces at the PS: consent page and dashboard.

§7.4: resource-asserted and agent-asserted content MUST be visually distinguished,
and agent-asserted content MUST be attributed to the agent and sanitized.
"""

from html import escape

from aauth_lab.core.ids import format_scope
from aauth_lab.person_server.state import (
    Mission,
    MissionProposal,
    Pending,
    TokenRequest,
)

_STYLE = """
:root { --fg:#1f2328; --muted:#59636e; --bg:#f6f8fa; --card:#fff; --line:#d1d9e0;
        --res:#0969da; --res-bg:#ddf4ff; --agent:#9a6700; --agent-bg:#fff8c5;
        --ok:#1a7f37; --ng:#cf222e; }
* { box-sizing: border-box; }
body { margin:0; font: 15px/1.6 system-ui, sans-serif; color:var(--fg); background:var(--bg); }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 24px 0 8px; }
.sub { color: var(--muted); margin: 0 0 20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:16px; margin: 12px 0; }
.src { font-size:12px; font-weight:600; letter-spacing:.02em; border-radius:4px;
       padding:2px 8px; display:inline-block; margin-bottom:8px; }
.resource { border-left:4px solid var(--res); }
.resource .src { background:var(--res-bg); color:var(--res); }
.agent { border-left:4px solid var(--agent); }
.agent .src { background:var(--agent-bg); color:var(--agent); }
.ps { border-left:4px solid var(--muted); }
.ps .src { background:var(--bg); color:var(--muted); }
pre { white-space: pre-wrap; margin:0; font: inherit; }
code { background: var(--bg); padding: 1px 6px; border-radius: 4px; }
label.scope { display:flex; gap:10px; align-items:flex-start; padding:6px 0; }
.actions { display:flex; gap:12px; margin-top:20px; flex-wrap: wrap; }
button { font: inherit; padding: 8px 18px; border-radius: 6px; border:1px solid var(--line);
         cursor:pointer; background: var(--card); }
button.approve { background: var(--ok); color:#fff; border-color: var(--ok); }
button.deny { color: var(--ng); }
table { width:100%; border-collapse: collapse; }
td, th { text-align:left; padding:6px 4px; border-bottom:1px solid var(--line); vertical-align: top; }
.state { font-size:12px; color:var(--muted); }
"""


def page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def _agent_box(title: str, text: str) -> str:
    # Agent-asserted: shown, attributed, escaped — but never the basis of the decision alone.
    return (
        f'<div class="card agent"><span class="src">エージェントの主張</span>'
        f"<div><strong>{escape(title)}</strong></div><pre>{escape(text)}</pre></div>"
    )


def consent_page(pending: Pending, person: str) -> str:
    match pending.subject:
        case MissionProposal() as proposal:
            return _mission_page(pending, proposal, person)
        case TokenRequest() as request:
            return _token_page(pending, request, person)


def _form(pending: Pending, inner: str) -> str:
    return (
        f'<form method="post" action="/interaction/{escape(pending.id)}/decision">'
        f'<input type="hidden" name="nonce" value="{escape(pending.decision_nonce)}">'
        f"{inner}"
        f'<div class="actions"><button class="approve" name="decision" value="approve">承認する</button>'
        f'<button class="deny" name="decision" value="deny">拒否する</button></div></form>'
    )


def _mission_page(pending: Pending, proposal: MissionProposal, person: str) -> str:
    resources = "".join(f"<li><code>{escape(r)}</code></li>" for r in proposal.resources)
    body = (
        f"<h1>新しい mission の承認</h1>"
        f'<p class="sub">{escape(person)} さん、<code>{escape(pending.agent)}</code> が'
        f" 次の作業を始めようとしています。</p>"
        + _agent_box("作業内容（mission の提案）", proposal.description)
        + f'<div class="card agent"><span class="src">エージェントの主張</span>'
        f"<div><strong>アクセス予定のリソース</strong></div><ul>{resources}</ul></div>"
        f'<div class="card ps"><span class="src">Person Server より</span>'
        f"<div>承認すると、上記リソースの低リスク操作（読み取り）は mission の範囲内で"
        f"確認なしに許可されます。それ以外の操作は都度あなたに確認します。</div></div>"
    )
    return page("mission の承認", body + _form(pending, ""))


def _token_page(pending: Pending, request: TokenRequest, person: str) -> str:
    rt = request.resource_token
    scopes = "".join(
        f'<label class="scope"><input type="checkbox" name="scope" value="{escape(s)}" checked>'
        f"<span><code>{escape(s)}</code><br>{escape(request.scope_descriptions.get(s, ''))}</span>"
        f"</label>"
        for s in sorted(request.requested)
    )
    resource_box = (
        f'<div class="card resource"><span class="src">リソースの主張（resource token）</span>'
        f"<div><strong>{escape(request.resource_name)}</strong> "
        f"<code>{escape(rt.iss)}</code> が次の権限を求めています。</div>{scopes}"
        f'<div class="state">チェックを外すと、その scope を除いて許可します（権限の縮小）。</div></div>'
    )
    justification = (
        _agent_box("理由（justification）", request.justification) if request.justification else ""
    )
    ps_box = (
        f'<div class="card ps"><span class="src">Person Server の判断</span>'
        f"<div>{escape(request.supervisor_reason)}</div></div>"
    )
    title = "追加の権限の確認" if request.step_up else "権限の確認"
    body = (
        f"<h1>{title}</h1>"
        f'<p class="sub">{escape(person)} さん、<code>{escape(pending.agent)}</code> の'
        f"操作が途中で止まっています。続行するにはあなたの判断が必要です。</p>"
        + ps_box
        + resource_box
        + justification
    )
    return page(title, body + _form(pending, ""))


def code_entry_page(error: str | None = None) -> str:
    err = f'<p style="color:var(--ng)">{escape(error)}</p>' if error else ""
    return page(
        "コードの入力",
        f"<h1>確認コードを入力</h1>{err}"
        f'<form method="get" action="/interaction"><input name="code" autofocus '
        f'placeholder="XXXX-XXXX"> <button>開く</button></form>',
    )


def done_page(approved: bool) -> str:
    msg = (
        "承認しました。エージェントは処理を再開します。"
        if approved
        else "拒否しました。エージェントには拒否が伝わります。"
    )
    return page(
        "完了",
        f"<h1>{'承認' if approved else '拒否'}しました</h1><p>{msg}</p>"
        f'<p><a href="/">ダッシュボードへ</a></p>',
    )


def dashboard(person: str, open_requests: list[Pending], missions: list[Mission]) -> str:
    rows = (
        "".join(
            f"<tr><td><code>{escape(p.agent)}</code><br><span class='state'>{escape(p.state)}</span></td>"
            f"<td>{escape(_summary(p))}</td>"
            f"<td><a href='/interaction?code={escape(p.code)}'>{escape(p.code)}</a></td></tr>"
            for p in open_requests
        )
        or "<tr><td colspan=3 class='state'>待っている確認はありません</td></tr>"
    )
    mission_rows = (
        "".join(
            f"<tr><td><code>{escape(m.s256[:12])}…</code><br>"
            f"<span class='state'>{'active' if m.active else escape(str(m.terminated))}</span></td>"
            f"<td><pre>{escape(m.blob.description)}</pre>"
            f"<div class='state'>同意済み: {escape(_consents(m))}</div></td>"
            f"<td>{_terminate_button(m)}</td></tr>"
            for m in missions
        )
        or "<tr><td colspan=3 class='state'>mission はありません</td></tr>"
    )
    body = (
        f"<h1>{escape(person)} の Person Server</h1>"
        f'<p class="sub">あなたの代わりに動くエージェントへの確認と、mission の管理。</p>'
        f"<h2>確認待ち</h2><div class='card'><table>{rows}</table></div>"
        f"<h2>Mission</h2><div class='card'><table>{mission_rows}</table></div>"
        f"<script>setTimeout(() => location.reload(), 3000)</script>"
    )
    return page("Person Server", body)


def _summary(p: Pending) -> str:
    match p.subject:
        case MissionProposal():
            return "mission の承認"
        case TokenRequest(requested=requested, resource_token=rt):
            return f"{rt.iss} に {format_scope(requested)}"


def _consents(m: Mission) -> str:
    return ", ".join(f"{r}: {format_scope(s)}" for r, s in m.consents.items()) or "なし"


def _terminate_button(m: Mission) -> str:
    if not m.active:
        return ""
    return (
        f"<form method='post' action='/lab/missions/{escape(m.s256)}/revoke'>"
        f"<button class='deny'>終了させる</button></form>"
    )
