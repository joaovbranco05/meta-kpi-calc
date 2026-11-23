"""Local presentation assets for the public login and logout pages."""

import hashlib
from base64 import b64encode
from functools import cache
from html import escape
from importlib.resources import files

STYLE = """
*{box-sizing:border-box}
body{margin:0;min-height:100svh;display:grid;place-items:center;padding:24px;
background:#f8fafc;color:#0f172a;font:16px/1.5 system-ui,sans-serif}
main{width:min(100%,420px);padding:clamp(24px,6vw,40px);background:#fff;
border:1px solid #e2e8f0;border-radius:12px}
img{display:block;width:164px;max-width:100%;height:auto;margin-bottom:28px}
h1{margin:0 0 8px;font-size:clamp(23px,6vw,28px);letter-spacing:-.025em;line-height:1.2}
p{margin:0 0 24px;color:#475569;font-size:14px}
.action{display:block;width:100%;padding:11px 12px;border:0;border-radius:6px;
background:#2e4c6c;color:#fff;text-align:center;font:600 14px/1.5 system-ui,sans-serif;
text-decoration:none;cursor:pointer}
.action:hover{background:#233e5a}
a:focus-visible,button:focus-visible{outline:2px solid #2e4c6c;outline-offset:3px}
.cancel{display:block;margin-top:14px;text-align:center;color:#2e4c6c;font-size:14px}
"""

STYLE_HASH = b64encode(hashlib.sha256(STYLE.encode()).digest()).decode("ascii")
ENTRY_CSP = (
    f"default-src 'none'; img-src data:; style-src 'sha256-{STYLE_HASH}'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


@cache
def logo_data_uri() -> str:
    asset = files("meta_kpi_calc.auth").joinpath("assets", "logo_rctec_transparente.png")
    return "data:image/png;base64," + b64encode(asset.read_bytes()).decode("ascii")


def entry_page(*, logout_token: str | None = None) -> str:
    if logout_token is None:
        title = "Portal Comercial"
        detail = "Acesso restrito à equipe autorizada da RCTEC."
        action = '<a class="action" href="/auth/login">Entrar com Google Workspace</a>'
    else:
        title = "Sair do Portal Comercial"
        detail = "Confirme para encerrar sua sessão neste navegador."
        action = (
            '<form method="post" action="/auth/logout">'
            f'<input type="hidden" name="csrf" value="{escape(logout_token, quote=True)}">'
            '<button class="action" type="submit">Confirmar saída</button></form>'
            '<a class="cancel" href="/">Voltar ao portal</a>'
        )
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} | RCTEC</title><style>{STYLE}</style></head>'
        f'<body><main><img src="{logo_data_uri()}" alt="Escola Técnica RCTEC">'
        f'<h1>{title}</h1><p>{detail}</p>{action}</main></body></html>'
    )
