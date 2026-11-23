"""Small local Streamlit panel that talks exclusively to the REST API."""

import hashlib
import os
import re
from base64 import b64encode
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from meta_kpi_calc.auth.dependencies import BROWSER_COOKIE, SESSION_COOKIE

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EFFECTIVE_STATUS_OPTIONS = ("", "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "DISABLED")
ASSETS = Path(__file__).with_name("assets")
LOGO_PATH = ASSETS / "logo_rctec_transparente.png"
LEAD_STATUS_COLORS = ("#BBD4E8", "#BDE0E7", "#C9E1D2", "#B9DEC7", "#F1DBA8", "#E9C9CF")
LEAD_STATUS_LABELS = {
    "NEW": "Novo",
    "CONTACTED": "Contatado",
    "INTERESTED": "Interessado",
    "ENROLLED": "Matriculado",
    "NO_RESPONSE": "Sem resposta",
    "LOST": "Perdido",
}
PERIOD_OPTIONS = ("Este mês", "Mês anterior", "Últimos 7 dias", "Personalizado")

KPI_CATALOG = (
    ("calculated_ctr", "CTR calculado", "Mídia", "percent", "Cliques no link ÷ impressões.", "Indica a proporção de impressões que gerou clique no link."),
    ("calculated_cpc", "CPC calculado", "Mídia", "currency", "Investimento ÷ cliques no link.", "Mostra o custo médio de um clique no link."),
    ("calculated_cpm", "CPM calculado", "Mídia", "currency", "Investimento ÷ impressões × 1.000.", "Mostra o custo para mil impressões."),
    ("cpl", "CPL", "Mídia", "currency", "Investimento ÷ leads.", "Mostra o custo médio de um lead."),
    ("qualification_rate", "Qualificação dos leads", "Comercial", "percent", "Leads qualificados ÷ leads.", "Usa leads qualificados registrados; não é uma coorte."),
    ("cpql", "CPQL", "Comercial", "currency", "Investimento ÷ leads qualificados.", "Mostra o custo por lead qualificado registrado."),
    ("contractual_conversion", "Conversão contratada", "Comercial", "percent", "Contratadas ÷ leads.", "É uma razão entre totais do período, não uma coorte."),
    ("financial_conversion", "Conversão pagante", "Comercial", "percent", "Pagantes ÷ leads.", "É uma razão entre totais do período, não uma coorte."),
    ("net_enrollments", "Matrículas líquidas", "Comercial", "integer", "Contratadas − cancelamentos.", "Mostra o saldo registrado no período."),
    ("contract_to_paying_conversion", "Contratadas para pagantes", "Comercial", "percent", "Pagantes ÷ contratadas.", "É uma razão entre totais do período, não uma coorte."),
    ("cancellation_rate", "Taxa de cancelamento", "Comercial", "percent", "Cancelamentos ÷ contratadas.", "Pode exceder 100% quando os eventos pertencem a contratos de outros períodos."),
    ("net_cac", "CAC líquido", "Financeiro", "currency", "Investimento ÷ (contratadas − cancelamentos).", "Fica indisponível sem matrículas líquidas positivas."),
    ("contractual_cac", "CAC contratual", "Financeiro", "currency", "Investimento ÷ contratadas.", "Mostra o custo de mídia por matrícula contratada registrada."),
    ("financial_cac", "CAC financeiro", "Financeiro", "currency", "Investimento ÷ pagantes.", "Mostra o custo de mídia por matrícula pagante registrada."),
    ("expected_roas", "ROAS esperado", "Financeiro", "multiple", "Receita esperada ÷ investimento.", "Compara receita esperada com investimento em mídia."),
    ("received_roas", "ROAS recebido", "Financeiro", "multiple", "Receita recebida ÷ investimento.", "Compara receita recebida com investimento em mídia."),
    ("received_advertising_roi", "ROI de mídia recebido", "Financeiro", "percent", "(Receita recebida − investimento) ÷ investimento.", "Considera apenas investimento em mídia; não representa lucro total."),
    ("expected_revenue_per_paying_enrollment", "Receita esperada por pagante", "Financeiro", "currency", "Receita esperada ÷ pagantes.", "Mostra a receita esperada média por pagante registrado."),
    ("received_revenue_per_paying_enrollment", "Receita recebida por pagante", "Financeiro", "currency", "Receita recebida ÷ pagantes.", "Mostra a receita recebida média por pagante registrado."),
)

WARNING_MESSAGES = {
    "NON_ADDITIVE_METRICS_OMITTED": "Alcance, frequência e CTR/CPC/CPM informados pela Meta não são somados neste recorte.",
    "QUALIFIED_LEADS_INCOMPLETE": "Há dias sem medição de leads qualificados; taxa de qualificação e CPQL podem ficar indisponíveis.",
    "COURSE_MISMATCH": "O curso do lançamento difere da classificação da campanha.",
    "QUALIFIED_LEADS_EXCEED_LEADS": "Leads qualificados superam os leads no registro.",
    "CANCELLATIONS_EXCEED_CONTRACTED": "Cancelamentos superam as contratadas no lançamento.",
    "PAYING_EXCEEDS_CONTRACTED": "Pagantes superam as contratadas no lançamento.",
}

COMMERCIAL_COVERAGE_LABELS = {
    "unknown": "Não informada",
    "partial": "Parcial",
    "complete": "Fechada",
}


def _format_value(value: Any) -> str:
    if value is None:
        return "Não calculável"
    if isinstance(value, Decimal):
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def _format_metric(value: Any, unit: str) -> str:
    if value is None:
        return "Não calculável neste recorte"
    if unit == "currency":
        return _format_currency(value)
    if unit == "percent":
        return f"{Decimal(str(value)):,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    if unit == "multiple":
        return f"{Decimal(str(value)):,.2f}x".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def _format_date(value: str | None) -> str:
    if value is None:
        return "não confirmada"
    parsed = date.fromisoformat(value[:10])
    return parsed.strftime("%d/%m/%Y")


def _format_currency(value: Any) -> str:
    if value is None:
        return "Não calculável"
    amount = Decimal(str(value))
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for row in rows:
        copy = {
            key: value
            for key, value in row.items()
            if key not in {"id", "campaign_id", "meta_campaign_id"}
        }
        for key, value in copy.items():
            if key.endswith(("_date", "_start", "_stop")) and isinstance(value, str):
                parts = value[:10].split("-")
                if len(parts) == 3:
                    copy[key] = f"{parts[2]}/{parts[1]}/{parts[0]}"
        rendered.append(copy)
    return rendered


def _launch_result_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "Data": record["reference_date"],
        "Curso": record["course"],
        "Contratadas": record["contracted_enrollments"],
        "Pagantes": record["paying_enrollments"],
        "Cancelamentos": record["cancellations"],
        "Receita esperada": _format_currency(record["expected_revenue"]),
        "Receita recebida": _format_currency(record["received_revenue"]),
        "Margem de contribuição": _format_currency(record["contribution_margin"]),
        "Observações": record["notes"] or "—",
    }


def _request(
    client: httpx.Client, method: str, path: str, **kwargs: Any
) -> dict[str, Any] | None:
    result, _ = _request_result(client, method, path, **kwargs)
    return result


def _request_result(
    client: httpx.Client, method: str, path: str, **kwargs: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | str | None]:
    try:
        response = client.request(method, f"{API_BASE_URL}{path}", timeout=10, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, dict):
                return None, {"status": str(response.status_code), **detail}
            return None, str(response.status_code)
        return response.json(), None
    except httpx.TimeoutException:
        return None, "timeout"
    except (httpx.HTTPError, ValueError):
        return None, "request"


def _error_message(error: dict[str, Any] | str | None) -> str:
    error_code = error.get("status") if isinstance(error, dict) else error
    messages = {
        "404": "O registro ou a campanha não foi encontrado.",
        "409": "Já existe um lançamento para esse recorte. Abra-o para editar.",
        "422": "Revise os campos informados e tente novamente.",
        "502": "O serviço externo não respondeu. Tente novamente mais tarde.",
        "timeout": "A operação demorou mais do que o esperado. Confira o resultado antes de repetir.",
    }
    return messages.get(error_code, "Não foi possível concluir a operação.")


def _parse_brl_money(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Informe um valor ou use 0.")
    if re.fullmatch(r"\d+", normalized):
        return normalized
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", normalized):
        return normalized.replace(".", "").replace(",", ".")
    if re.fullmatch(r"\d+,\d{1,2}", normalized):
        return normalized.replace(",", ".")
    if re.fullmatch(r"\d+\.\d{1,2}", normalized):
        return normalized
    raise ValueError("Use 1.234,56, 1234,56, 1234.56 ou 0, com no máximo duas casas.")


def _period_dates(period: str, today: date) -> tuple[date, date]:
    if period == "Este mês":
        return today.replace(day=1), today
    if period == "Mês anterior":
        current_month = today.replace(day=1)
        previous_stop = current_month - timedelta(days=1)
        return previous_stop.replace(day=1), previous_stop
    return today - timedelta(days=6), today


def _filters(st: Any, default_period: dict[str, Any] | None = None) -> dict[str, str]:
    today = date.today()
    if "applied_filters" not in st.session_state:
        default_start = default_period.get("date_start") if default_period else None
        default_stop = default_period.get("date_stop") if default_period else None
        if default_start and default_stop:
            st.session_state["applied_filters"] = {
                "date_start": default_start,
                "date_stop": default_stop,
            }
            default_selection = "Personalizado"
        else:
            start, stop = _period_dates("Últimos 7 dias", today)
            st.session_state["applied_filters"] = {
                "date_start": start.isoformat(),
                "date_stop": stop.isoformat(),
            }
            default_selection = "Últimos 7 dias"
        st.session_state.setdefault("period_selection", default_selection)
    applied = st.session_state["applied_filters"]
    brand_options = ["", "RCTEC", "FECAF", "CURSO_COM_BOLSA", "NAO_CLASSIFICADA"]
    with st.sidebar:
        st.header("Filtros")
        with st.form("report-filters"):
            period = st.radio(
                "Período",
                PERIOD_OPTIONS,
                index=PERIOD_OPTIONS.index(st.session_state["period_selection"]),
            )
            start = st.date_input(
                "Início",
                date.fromisoformat(applied["date_start"]),
                disabled=period != "Personalizado",
            )
            stop = st.date_input(
                "Fim",
                date.fromisoformat(applied["date_stop"]),
                disabled=period != "Personalizado",
            )
            brand = st.selectbox(
                "Marca",
                brand_options,
                index=brand_options.index(applied.get("brand", "")),
            )
            effective_status = st.selectbox(
                "Status efetivo",
                EFFECTIVE_STATUS_OPTIONS,
                index=EFFECTIVE_STATUS_OPTIONS.index(applied.get("effective_status", "")),
                format_func=lambda value: "Todos" if value == "" else value,
            )
            submitted = st.form_submit_button("Aplicar filtros")
    if submitted:
        if period != "Personalizado":
            start, stop = _period_dates(period, today)
        result = {"date_start": start.isoformat(), "date_stop": stop.isoformat()}
        for key, value in (("brand", brand), ("effective_status", effective_status)):
            if value.strip():
                result[key] = value.strip()
        st.session_state["applied_filters"] = result
        st.session_state["period_selection"] = period
        return result
    return applied


def _campaign_params(filters: dict[str, str]) -> dict[str, str | int]:
    return {
        "limit": 100,
        **{
            key: value
            for key, value in filters.items()
            if key in {"date_start", "date_stop", "brand", "campaign_id", "course", "effective_status"}
        },
    }


def _enrollment_params(filters: dict[str, str]) -> dict[str, str | int]:
    return {
        "limit": 50,
        **{
            key: value
            for key, value in filters.items()
            if key in {"date_start", "date_stop", "brand", "campaign_id", "effective_status"}
        },
    }


def _campaign_label(campaign: dict[str, Any], duplicate_names: set[str]) -> str:
    label = " — ".join(
        (
            campaign["name"],
            campaign["brand"],
            campaign["effective_status"] or "SEM STATUS",
        )
    )
    if campaign["name"] in duplicate_names:
        return f"{label} — {campaign['meta_campaign_id']}"
    return label


def _page_offset(st: Any, key: str, total: int) -> int:
    page_count = max(1, (total + 49) // 50)
    current = int(st.session_state.get(key, 0))
    current = min(max(current, 0), page_count - 1)
    previous, label, following = st.columns(3)
    if previous.button("Anterior", key=f"{key}-previous", disabled=current == 0):
        current -= 1
    label.caption(f"Página {current + 1} de {page_count} · {total} registros")
    if following.button("Próxima", key=f"{key}-next", disabled=current >= page_count - 1):
        current += 1
    st.session_state[key] = current
    return current * 50


def _campaign_selector(
    st: Any, client: httpx.Client, filters: dict[str, str]
) -> dict[str, str]:
    page = _request(client, "GET", "/api/campaigns", params={**_campaign_params(filters), "offset": int(st.session_state.get("campaign-page", 0)) * 50, "limit": 50})
    if page is None:
        st.sidebar.error("Não foi possível carregar campanhas.")
        return filters
    with st.sidebar:
        offset = _page_offset(st, "campaign-page", page["total"])
    if offset != page["offset"]:
        page = _request(client, "GET", "/api/campaigns", params={**_campaign_params(filters), "offset": offset, "limit": 50})
        if page is None:
            return filters
    items = page["items"]
    if not items:
        st.sidebar.info("Nenhuma campanha encontrada neste recorte.")
        return filters
    duplicate_names = {
        item["name"] for item in items if sum(row["name"] == item["name"] for row in items) > 1
    }
    options = [None, *items]
    chosen = st.sidebar.selectbox(
        "Campanha",
        options,
        format_func=lambda item: "Todas as campanhas" if item is None else _campaign_label(item, duplicate_names),
    )
    if chosen is None:
        return filters
    return {**filters, "campaign_id": str(chosen["id"])}


def _overview(
    st: Any,
    client: httpx.Client,
    filters: dict[str, str],
    selected_campaign: dict[str, Any] | None,
) -> None:
    st.markdown(
        """
        <style>
        [data-testid="stMetricLabel"] p {
            font-size: 0.75rem;
        }
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] > div {
            font-size: 1.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    summary = _request(client, "GET", "/api/dashboard/summary", params=filters)
    if summary is None:
        st.error("A API está indisponível ou respondeu com erro.")
        return
    totals = summary["totals"]
    campaign_name = selected_campaign["name"] if selected_campaign else "todas"
    scope = [
        f"Período: {_format_date(filters['date_start'])} a {_format_date(filters['date_stop'])}",
        f"Marca: {filters.get('brand', 'todas')}",
        f"Campanha: {campaign_name}",
    ]
    if filters.get("effective_status"):
        scope.append(f"Status: {filters['effective_status']}")
    if filters.get("course"):
        scope.append(f"Curso: {filters['course']}")
    st.caption(" · ".join(scope))
    last_sync = summary.get("last_media_sync_at")
    st.caption(f"Última atualização de mídia: {_format_date(last_sync)}")
    st.subheader("Mídia")
    media = st.columns(2)
    media[0].metric("Investimento", _format_currency(totals["spend"]))
    media[1].metric("Leads", _format_metric(totals["leads"], "integer"))
    st.subheader("Comercial")
    commercial = st.columns(3)
    commercial[0].metric("Contratadas", _format_metric(totals["contracted_enrollments"], "integer"))
    commercial[1].metric("Pagantes", _format_metric(totals["paying_enrollments"], "integer"))
    commercial[2].metric("Qualificação dos leads", _format_metric(summary["kpis"]["qualification_rate"], "percent"))
    st.subheader("Financeiro")
    financial = st.columns(3)
    financial[0].metric("CAC financeiro", _format_metric(summary["kpis"]["financial_cac"], "currency"))
    financial[1].metric("Receita recebida", _format_currency(totals["received_revenue"]))
    financial[2].metric("ROAS recebido", _format_metric(summary["kpis"]["received_roas"], "multiple"))
    coverage = summary["commercial_coverage"]
    _coverage_notice(st, coverage)
    _warning_sections(st, summary["warnings"])
    st.subheader("Catálogo de indicadores")
    st.dataframe(
        [
            {
                "Grupo": group,
                "Indicador": label,
                "Valor": _format_metric(summary["kpis"][key], unit),
                "Fórmula": formula,
                "Interpretação": interpretation,
            }
            for key, label, group, unit, formula, interpretation in KPI_CATALOG
        ],
        hide_index=True,
        use_container_width=True,
    )


def _coverage_notice(st: Any, coverage: dict[str, Any]) -> None:
    status = coverage["status"]
    if status == "complete":
        st.info("Cobertura comercial fechada.")
    elif status == "partial":
        st.warning("Há dias com fechamento parcial; revise antes de decidir.")
    elif coverage["expected_units"]:
        st.warning("Há dias sem confirmação comercial; os totais comerciais podem estar incompletos.")
    else:
        st.warning("Não há dias com dado operacional no recorte; cobertura comercial não confirmada.")


def _warning_sections(st: Any, warnings: list[dict[str, Any]]) -> None:
    groups = {"Informações": [], "Pendências": [], "Inconsistências": []}
    for warning in warnings:
        code = warning["code"]
        row = {"Mensagem": WARNING_MESSAGES.get(code, warning["message"])}
        if code == "NON_ADDITIVE_METRICS_OMITTED":
            groups["Informações"].append(row)
        elif code == "QUALIFIED_LEADS_INCOMPLETE":
            groups["Pendências"].append(row)
        else:
            groups["Inconsistências"].append(row)
    for title, rows in groups.items():
        if rows:
            st.subheader(title)
            st.dataframe(rows, hide_index=True, use_container_width=True)


def _campaigns(
    st: Any,
    client: httpx.Client,
    filters: dict[str, str],
    selected_campaign: dict[str, Any] | None,
) -> None:
    st.subheader("Campanhas e comparação")
    comparison = _request(
        client, "GET", "/api/dashboard/campaign-comparison", params=filters
    )
    if comparison is None:
        st.error("Não foi possível carregar a comparação por campanha.")
        return
    if not comparison:
        st.info("Nenhuma campanha encontrada.")
        return
    st.dataframe(
        [
            {
                "Campanha": row["name"],
                "Marca": row["brand"],
                "Curso": row["course"] or "—",
                "Status": row["effective_status"] or "—",
                "Investimento": _format_currency(row["spend"]),
                "Leads": row["leads"],
                "Contratadas": row["contracted_enrollments"],
                "Pagantes": row["paying_enrollments"],
                "CAC financeiro": _format_metric(row["financial_cac"], "currency"),
                "Receita recebida": _format_currency(row["received_revenue"]),
                "Cobertura comercial": COMMERCIAL_COVERAGE_LABELS[
                    row["commercial_coverage"]["status"]
                ],
            }
            for row in comparison
        ],
        hide_index=True,
        use_container_width=True,
    )
    if selected_campaign is None:
        st.info("Selecione uma campanha na barra lateral para alterar a classificação.")
        return
    with st.form("classification"):
        brand = st.selectbox("Nova marca", ["RCTEC", "FECAF", "CURSO_COM_BOLSA", "NAO_CLASSIFICADA"])
        course = st.text_input("Novo curso (opcional)")
        submitted = st.form_submit_button("Salvar classificação")
    if submitted:
        payload: dict[str, Any] = {"brand": brand}
        if course.strip():
            payload["course"] = course.strip()
        if _request(client, "PATCH", f"/api/campaigns/{selected_campaign['id']}/classification", json=payload):
            st.success("Classificação atualizada.")
        else:
            st.error("Não foi possível atualizar a classificação.")


COMPARISON_TOTAL_CATALOG = (
    ("Mídia", "Investimento", "spend", "currency"),
    ("Mídia", "Alcance", "reach", "integer"),
    ("Mídia", "Impressões", "impressions", "integer"),
    ("Mídia", "Cliques", "clicks", "integer"),
    ("Mídia", "Cliques no link", "inline_link_clicks", "integer"),
    ("Mídia", "Leads", "leads", "integer"),
    ("Mídia", "Leads qualificados", "qualified_leads", "integer"),
    ("Mídia", "CTR informado pela Meta", "meta_ctr", "percent"),
    ("Mídia", "CPC informado pela Meta", "meta_cpc", "currency"),
    ("Mídia", "CPM informado pela Meta", "meta_cpm", "currency"),
    ("Mídia", "Frequência", "frequency", "multiple"),
    ("Mídia", "Insights", "insight_count", "integer"),
    ("Comercial", "Contratadas", "contracted_enrollments", "integer"),
    ("Comercial", "Pagantes", "paying_enrollments", "integer"),
    ("Comercial", "Cancelamentos", "cancellations", "integer"),
    ("Comercial", "Receita esperada", "expected_revenue", "currency"),
    ("Comercial", "Receita recebida", "received_revenue", "currency"),
    ("Comercial", "Margem de contribuição", "contribution_margin", "unavailable"),
)


def _comparison_params(
    filters: dict[str, str], campaign_ids: list[int]
) -> dict[str, object]:
    return {
        **{key: value for key, value in filters.items() if key != "campaign_id"},
        "campaign_ids": campaign_ids,
    }


def _comparison_missing_value(
    campaign: dict[str, Any], source: str, key: str, value: Any
) -> str:
    insight_count = campaign.get("totals", {}).get("insight_count", 0)
    if source == "totals" and key in {
        "spend",
        "reach",
        "impressions",
        "clicks",
        "inline_link_clicks",
        "leads",
        "qualified_leads",
        "meta_ctr",
        "meta_cpc",
        "meta_cpm",
        "frequency",
        "insight_count",
    } and insight_count == 0:
        return "Dado ausente: sem insight no recorte"
    if value is not None:
        return ""
    if source == "unavailable":
        return "Não agregada neste recorte"
    warning_codes = {warning["code"] for warning in campaign.get("warnings", [])}
    if key in {"reach", "frequency", "meta_ctr", "meta_cpc", "meta_cpm"} and "NON_ADDITIVE_METRICS_OMITTED" in warning_codes:
        return "Não calculável: métrica não aditiva"
    if key in {"qualified_leads", "qualification_rate", "cpql"} and "QUALIFIED_LEADS_INCOMPLETE" in warning_codes:
        return "Não calculável: qualificados incompletos"
    return "Não calculável: denominador zero"


def _comparison_matrix_rows(
    campaigns: list[dict[str, Any]],
) -> list[dict[str, str]]:
    definitions = [
        (group, label, "totals", key, unit)
        for group, label, key, unit in COMPARISON_TOTAL_CATALOG
    ] + [
        (group, label, "kpis", key, unit)
        for key, label, group, unit, _formula, _interpretation in KPI_CATALOG
    ]
    rows: list[dict[str, str]] = []
    for group, label, source, key, unit in definitions:
        row = {"Grupo": group, "Indicador": label}
        for campaign in campaigns:
            value = None if source == "unavailable" else campaign[source][key]
            missing = _comparison_missing_value(campaign, source, key, value)
            row[campaign["name"] + " — " + campaign["meta_campaign_id"]] = (
                missing
                if missing
                else _format_metric(value, unit)
            )
        rows.append(row)
    return rows


def _comparison_campaigns(
    client: httpx.Client, filters: dict[str, str]
) -> list[dict[str, Any]] | None:
    """Load every campaign in the filtered scope for the multiselect."""
    params = {**_campaign_params(filters), "offset": 0, "limit": 100}
    page = _request(client, "GET", "/api/campaigns", params=params)
    if page is None:
        return None

    items = list(page["items"])
    total = int(page["total"])
    while len(items) < total:
        next_page = _request(
            client,
            "GET",
            "/api/campaigns",
            params={**params, "offset": len(items)},
        )
        if next_page is None or not next_page["items"]:
            return None
        items.extend(next_page["items"])
    return items if len(items) >= total else None


def _compare_campaigns(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    """Render the detailed, multi-campaign comparison without external calls."""
    st.subheader("Comparar campanhas")
    scope_filters = {key: value for key, value in filters.items() if key != "campaign_id"}
    scope_key = tuple(sorted(scope_filters.items()))
    if st.session_state.get("comparison_scope") != scope_key:
        st.session_state["comparison_scope"] = scope_key
        st.session_state["comparison_campaign_ids"] = []
        st.session_state.pop("comparison_export", None)
        st.session_state.pop("comparison_export_scope", None)

    items = _comparison_campaigns(client, scope_filters)
    if items is None:
        st.error("Não foi possível carregar campanhas para comparação.")
        return
    if len(items) < 2:
        st.info("É necessário ter pelo menos duas campanhas no escopo.")
        return
    duplicate_names = {
        item["name"]
        for item in items
        if sum(row["name"] == item["name"] for row in items) > 1
    }
    labels = {
        item["id"]: _campaign_label(item, duplicate_names) for item in items
    }
    options = [item["id"] for item in items]
    previous = [
        campaign_id
        for campaign_id in st.session_state.get("comparison_campaign_ids", [])
        if campaign_id in options
    ]
    selected_ids = st.multiselect(
        "Campanhas (selecione duas ou mais)",
        options,
        default=previous,
        format_func=lambda campaign_id: labels[campaign_id],
    )
    st.session_state["comparison_campaign_ids"] = selected_ids
    if len(selected_ids) < 2:
        st.info("Selecione duas ou mais campanhas para comparar.")
        return
    comparison = _request(
        client,
        "GET",
        "/api/dashboard/campaign-comparison/detail",
        params=_comparison_params(scope_filters, selected_ids),
    )
    if comparison is None:
        st.error("Não foi possível carregar a comparação detalhada.")
        return
    st.caption("Os indicadores mostram totais do recorte selecionado; não representam uma coorte.")
    st.dataframe(_comparison_matrix_rows(comparison), hide_index=True, use_container_width=True)
    st.subheader("Cobertura e pendências")
    st.dataframe(
        [
            {
                "Campanha": labels.get(item["id"], item["name"]),
                "Cobertura comercial": COMMERCIAL_COVERAGE_LABELS[item["commercial_coverage"]["status"]],
                "Dias esperados": item["commercial_coverage"]["expected_units"],
                "Dias sem confirmação": item["commercial_coverage"]["unknown_units"],
                "Dias parciais": item["commercial_coverage"]["partial_units"],
                "Dias fechados": item["commercial_coverage"]["complete_units"],
                "Última atualização de mídia": _format_date(item["last_media_sync_at"]),
                "Pendências": len(item["warnings"]),
            }
            for item in comparison
        ],
        hide_index=True,
        use_container_width=True,
    )
    warning_rows = [
        {
            "Campanha": labels.get(item["id"], item["name"]),
            "Código": warning["code"],
            "Motivo": WARNING_MESSAGES.get(warning["code"], warning["message"]),
        }
        for item in comparison
        for warning in item["warnings"]
    ]
    if warning_rows:
        st.dataframe(warning_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("Nenhuma pendência ou inconsistência registrada para as campanhas selecionadas.")
    _download_link(
        st, "comparison", "Baixar comparação XLSX", _comparison_params(scope_filters, selected_ids)
    )


def _set_enrollment_form_values(st: Any, record: dict[str, Any] | None, campaign: dict[str, Any]) -> None:
    st.session_state.update(
        {
            "launch_reference_date": date.fromisoformat(record["reference_date"]) if record else date.today(),
            "launch_course": record["course"] if record else campaign.get("course") or "",
            "launch_contracted": record["contracted_enrollments"] if record else 0,
            "launch_paying": record["paying_enrollments"] if record else 0,
            "launch_cancellations": record["cancellations"] if record else 0,
            "launch_expected": record["expected_revenue"] if record else "0",
            "launch_received": record["received_revenue"] if record else "0",
            "launch_margin": record["contribution_margin"] if record and record["contribution_margin"] is not None else "",
            "launch_notes": record["notes"] if record and record["notes"] is not None else "",
            "launch_closure": "UNCHANGED" if record else "PARTIAL",
        }
    )


def _find_duplicate(
    client: httpx.Client, campaign_id: int, reference_date: date, course: str
) -> dict[str, Any] | None:
    page = _request(
        client,
        "GET",
        "/api/enrollments",
        params={
            "campaign_id": campaign_id,
            "date_start": reference_date.isoformat(),
            "date_stop": reference_date.isoformat(),
            "course": course,
            "limit": 1,
        },
    )
    if page is None:
        return None
    return next((item for item in page["items"] if item["course"] == course), None)


def _has_daily_launches(
    client: httpx.Client, campaign_id: int, reference_date: date
) -> tuple[bool | None, dict[str, Any] | str | None]:
    page, error = _request_result(
        client,
        "GET",
        "/api/enrollments",
        params={
            "campaign_id": campaign_id,
            "date_start": reference_date.isoformat(),
            "date_stop": reference_date.isoformat(),
            "limit": 1,
        },
    )
    if page is None:
        return None, error
    return page["total"] > 0, None


def _editable_records(
    records: list[dict[str, Any]], campaign_id: int, editing_record: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Keep the selected duplicate available when it is outside the visible page."""
    candidates = [item for item in records if item["campaign_id"] == campaign_id]
    if (
        editing_record is not None
        and editing_record.get("campaign_id") == campaign_id
        and all(item["id"] != editing_record.get("id") for item in candidates)
    ):
        candidates.append(editing_record)
    return candidates


def _enrollments(
    st: Any,
    client: httpx.Client,
    filters: dict[str, str],
    selected_campaign: dict[str, Any] | None,
) -> None:
    st.subheader("Lançamentos diários")
    records = _request(
        client,
        "GET",
        "/api/enrollments",
        params={
            **_enrollment_params(filters),
            "offset": int(st.session_state.get("enrollment-page", 0)) * 50,
        },
    )
    if records is None:
        st.error("Não foi possível carregar lançamentos.")
        return
    offset = _page_offset(st, "enrollment-page", records["total"])
    if offset != records["offset"]:
        records = _request(client, "GET", "/api/enrollments", params={**_enrollment_params(filters), "offset": offset})
        if records is None:
            return
    st.dataframe(_display_rows(records["items"]), hide_index=True, use_container_width=True)
    notice = st.session_state.pop("launch_notice", None)
    if notice is not None:
        st.success("Lançamento salvo. Se ele não aparecer no recorte atual, ajuste os filtros.")
        launch = notice.get("lançamento") if "lançamento" in notice else None
        closure = notice.get("fechamento") if "fechamento" in notice else notice
        if launch is not None:
            st.dataframe([_launch_result_row(launch)], hide_index=True, use_container_width=True)
        if closure.get("status") == "COMPLETE":
            st.caption("Fechamento comercial: fechado.")
        elif closure.get("status") == "PARTIAL":
            st.caption("Fechamento comercial: parcial.")
    if selected_campaign is None:
        st.info("Selecione uma campanha na barra lateral para criar ou editar um lançamento.")
        return

    editing_id = st.session_state.get("launch_editing_id")
    editing_record = st.session_state.get("launch_editing_record")
    editable_records = _editable_records(
        records["items"],
        selected_campaign["id"],
        editing_record if isinstance(editing_record, dict) else None,
    )
    mode = st.radio(
        "Ação",
        ("Novo lançamento", "Editar lançamento"),
        horizontal=True,
        key="launch_mode",
    )
    selected_record: dict[str, Any] | None = None
    if mode == "Editar lançamento":
        if not editable_records:
            st.info("Não há lançamentos desta campanha nesta página.")
            return
        selected_index = next(
            (
                index
                for index, item in enumerate(editable_records)
                if item["id"] == editing_id
            ),
            None,
        )
        if editing_id is not None and selected_index is None:
            st.warning("O lançamento solicitado não está disponível para edição.")
            return
        selected_record = st.selectbox(
            "Lançamento para editar",
            editable_records,
            index=selected_index if selected_index is not None else 0,
            format_func=lambda item: f"{item['reference_date']} — {item['course']}",
        )
    current_marker = selected_record["id"] if selected_record else "new"
    if st.session_state.get("launch_loaded_marker") != current_marker:
        _set_enrollment_form_values(st, selected_record, selected_campaign)
        st.session_state["launch_loaded_marker"] = current_marker

    with st.form("daily-launch"):
        reference_date = st.date_input("Data de referência", key="launch_reference_date")
        course = st.text_input("Curso", key="launch_course")
        contracted = st.number_input("Contratadas", min_value=0, step=1, key="launch_contracted")
        paying = st.number_input("Pagantes", min_value=0, step=1, key="launch_paying")
        cancellations = st.number_input("Cancelamentos", min_value=0, step=1, key="launch_cancellations")
        expected = st.text_input("Receita esperada", key="launch_expected")
        received = st.text_input("Receita recebida", key="launch_received")
        margin = st.text_input("Margem de contribuição (opcional)", key="launch_margin")
        notes = st.text_area("Observações", key="launch_notes")
        closure_options = (
            ("UNCHANGED", "PARTIAL", "COMPLETE")
            if selected_record is not None
            else ("PARTIAL", "COMPLETE")
        )
        closure_status = st.selectbox(
            "Fechamento comercial",
            closure_options,
            format_func=lambda value: {
                "UNCHANGED": "Não alterar fechamento",
                "PARTIAL": "Parcial",
                "COMPLETE": "Fechado",
            }[value],
            key="launch_closure",
        )
        saved = st.form_submit_button("Salvar lançamento")
        confirmed_zero = (
            st.form_submit_button("Confirmar zero para o dia")
            if selected_record is None
            else False
        )

    if confirmed_zero:
        has_launches, lookup_error = _has_daily_launches(
            client, selected_campaign["id"], reference_date
        )
        if has_launches is None:
            st.error(_error_message(lookup_error))
            return
        if has_launches:
            st.warning("Há lançamentos neste dia. Use o fechamento comercial do formulário.")
            return
        result, error = _request_result(
            client,
            "PUT",
            f"/api/commercial-closures/{selected_campaign['id']}/{reference_date.isoformat()}",
            json={"status": "COMPLETE"},
        )
        if result is None:
            st.error(_error_message(error))
        else:
            st.session_state["launch_notice"] = result
            st.rerun()
    if not saved:
        return
    try:
        expected_value = _parse_brl_money(expected)
        received_value = _parse_brl_money(received)
        margin_value = _parse_brl_money(margin) if margin.strip() else None
    except ValueError as exc:
        st.error(str(exc))
        return
    if not course.strip():
        st.error("Informe o curso.")
        return
    if selected_record is None:
        duplicate = _find_duplicate(client, selected_campaign["id"], reference_date, course.strip())
        if duplicate is not None:
            st.warning("Já existe um lançamento para esta campanha, data e curso.")
            if st.button("Abrir lançamento existente"):
                st.session_state["launch_editing_id"] = duplicate["id"]
                st.session_state["launch_editing_record"] = duplicate
                st.session_state["launch_loaded_marker"] = None
                st.session_state["launch_mode"] = "Editar lançamento"
                st.rerun()
            return
    payload = {
        "campaign_id": selected_campaign["id"],
        "reference_date": reference_date.isoformat(),
        "course": course.strip(),
        "contracted_enrollments": contracted,
        "paying_enrollments": paying,
        "cancellations": cancellations,
        "expected_revenue": expected_value,
        "received_revenue": received_value,
        "contribution_margin": margin_value,
        "notes": notes or None,
    }
    method, path = (
        ("PUT", f"/api/enrollments/{selected_record['id']}")
        if selected_record is not None
        else ("POST", "/api/enrollments")
    )
    result, error = _request_result(client, method, path, json=payload)
    if result is None:
        if (
            isinstance(error, dict)
            and error.get("code") == "duplicate_enrollment"
            and isinstance(error.get("record_id"), int)
        ):
            duplicate = _find_duplicate(
                client, selected_campaign["id"], reference_date, course.strip()
            )
            st.session_state["launch_editing_id"] = error["record_id"]
            if duplicate is not None and duplicate["id"] == error["record_id"]:
                st.session_state["launch_editing_record"] = duplicate
            st.session_state["launch_loaded_marker"] = None
            st.session_state["launch_mode"] = "Editar lançamento"
            st.rerun()
            return
        st.error(_error_message(error))
        return
    if closure_status == "UNCHANGED":
        st.session_state["launch_notice"] = {"lançamento": result}
        st.rerun()
        return
    closure, closure_error = _request_result(
        client,
        "PUT",
        f"/api/commercial-closures/{selected_campaign['id']}/{reference_date.isoformat()}",
        json={"status": closure_status},
    )
    if closure is None:
        st.error(f"Lançamento salvo, mas o fechamento não foi atualizado: {_error_message(closure_error)}")
        return
    st.session_state["launch_notice"] = {"lançamento": result, "fechamento": closure}
    st.rerun()


def _sync(st: Any, client: httpx.Client, filters: dict[str, str], sync_state: dict[str, Any] | None) -> None:
    st.subheader("Sincronização e configurações")
    if sync_state is None:
        st.warning("Não foi possível consultar o estado local da sincronização.")
    else:
        labels = {
            "running": "Em execução",
            "completed": "Concluída",
            "failed": "Falhou",
            "not_confirmed": "Não confirmada",
        }
        st.info(f"Estado local: {labels[sync_state['state']]}")
        if sync_state["date_start"]:
            st.caption(
                f"Último período: {_format_date(sync_state['date_start'])} a "
                f"{_format_date(sync_state['date_stop'])}"
            )
    if st.button("Testar conexão Meta"):
        connection, error = _request_result(client, "GET", "/api/meta/connection")
        if connection is None:
            st.error(_error_message(error))
        elif connection["connected"]:
            st.success("Conexão Meta confirmada.")
        else:
            st.info("A conexão Meta não está configurada neste ambiente.")
    if st.button("Sincronizar período filtrado"):
        result, error = _request_result(
            client,
            "POST",
            "/api/meta/sync",
            json={"date_start": filters["date_start"], "date_stop": filters["date_stop"]},
        )
        if result is not None:
            st.session_state["sync_notice"] = "Sincronização concluída."
        else:
            st.session_state["sync_notice"] = _error_message(error)
        st.rerun()


def _export(st: Any, filters: dict[str, str]) -> None:
    st.subheader("Exportar relatório")
    _download_link(st, "report", "Baixar relatório XLSX", {
        **filters, "format": "xlsx", "dataset": "performance",
    })


def _download_link(st: Any, endpoint: str, label: str, parameters: dict) -> None:
    params = urlencode({**parameters, "binding": st.session_state["download_binding"]}, doseq=True)
    href = escape(f"/downloads/{endpoint}?{params}", quote=True)
    st.html(f'<a href="{href}">{escape(label)}</a>')


def _login_screen(st: Any) -> None:
    st.session_state.clear()
    st.html('<a href="/auth/login" target="_self">Entrar com Google Workspace</a>')


def _api_client(**kwargs) -> httpx.Client:
    socket = os.getenv("CRM_API_SOCKET")
    transport = httpx.HTTPTransport(uds=socket, trust_env=False) if socket else None
    return httpx.Client(transport=transport, trust_env=False, **kwargs)


def _auth_headers(token: str, browser: str) -> dict[str, str]:
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{43}", value) for value in (token, browser)):
        return {}
    return {"Cookie": f"{SESSION_COOKIE}={token}; {BROWSER_COOKIE}={browser}"}


def _lead_query_controls(st: Any, *, is_admin: bool) -> dict[str, str | bool]:
    applied = st.session_state.get("crm_lead_filters", {})
    with st.form("crm_lead_filters_form"):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            query = st.text_input(
                "Buscar lead", value=applied.get("query", ""), max_chars=128,
                placeholder="Nome, e-mail ou telefone",
            )
            status = st.selectbox(
                "Status", ("", *LEAD_STATUS_LABELS),
                index=("", *LEAD_STATUS_LABELS).index(applied.get("commercial_status", "")),
                format_func=lambda code: LEAD_STATUS_LABELS.get(code, "Todos os status"),
            )
            unassigned = False
            if is_admin:
                unassigned = st.selectbox(
                    "Responsável", (False, True), index=int(applied.get("unassigned", False)),
                    format_func=lambda value: "Sem responsável" if value else "Todos",
                )
            submitted = st.form_submit_button("Aplicar", type="primary")
        if submitted:
            filters = {
                "query": query.strip(), "commercial_status": status, "unassigned": unassigned,
            }
            if filters != applied:
                st.session_state["crm_lead_filters"] = filters
                st.session_state["crm_leads_offset"] = 0
            return filters
    return applied


def _lead_request_error(st: Any, error: dict | str | None, *, detail: bool = False) -> None:
    code = error.get("status") if isinstance(error, dict) else error
    if detail and code == "404":
        st.warning("Este lead não está disponível.")
    elif code == "403":
        st.warning("Seu perfil não tem permissão para esta consulta.")
    else:
        st.error("Não foi possível carregar o lead." if detail else "Não foi possível carregar os leads.")
        st.button("Tentar novamente")


def _responsible_label(lead: dict[str, Any]) -> str:
    if lead.get("assigned_user_id") is None:
        return "Sem responsável"
    label = lead.get("assigned_user_display_name")
    return label.strip() if isinstance(label, str) and label.strip() else "Nome não definido"


def _assignee_names(st: Any, client: httpx.Client) -> None:
    with st.expander("Configurar nome de exibição"):
        with st.form("crm_display_name"):
            st.caption("Use o ID interno registrado no provisionamento da conta.")
            account_id = st.number_input("ID interno da conta", min_value=1, step=1, value=None)
            name = st.text_input("Nome de exibição", max_chars=64)
            submitted = st.form_submit_button("Salvar nome")
        if submitted:
            if account_id is None:
                st.warning("Informe o ID interno da conta.")
                return
            result, error = _request_result(
                client, "PATCH", f"/api/admin/users/{account_id}/display-name",
                json={"display_name": name.strip() or None},
            )
            if result is None:
                st.error(_error_message(error))
                return
            st.success("Nome de exibição atualizado.")


def _lead_assignment(st: Any, client: httpx.Client, lead: dict[str, Any]) -> None:
    st.subheader("Distribuição")
    current = lead["assigned_user_id"]
    st.text(_responsible_label(lead))
    candidates, error = _request_result(client, "GET", "/api/admin/users/assignees")
    if candidates is None:
        st.error(_error_message(error))
        return
    labels = {
        item["id"]: item["display_name"] + (" (administrador)" if item["role"] == "admin" else "")
        for item in candidates if item["display_name"]
    }
    names = list(labels.values())
    if len(names) != len(set(names)) or len(labels) < len(candidates):
        st.caption("Configure nomes distintos para disponibilizar as contas no seletor.")
    choices = [
        account_id for account_id, name in labels.items()
        if account_id != current and names.count(name) == 1
    ]
    with st.form(f"crm_assignment_{lead['id']}_{current}"):
        choice = st.selectbox(
            "Novo responsável", choices, index=None,
            format_func=labels.__getitem__,
        )
        remove = st.checkbox("Retirar responsável") if current is not None else False
        confirmed = st.checkbox("Confirmo a alteração do responsável atual") if current is not None else True
        submitted = st.form_submit_button("Salvar atribuição", type="primary")
    if not submitted:
        return
    if not confirmed or (choice is not None and remove) or (choice is None and not remove):
        st.warning("Escolha uma única alteração e confirme quando houver responsável atual.")
        return
    _, error = _request_result(
        client, "PATCH", f"/api/crm/leads/{lead['id']}/assignment",
        json={"assigned_user_id": choice, "expected_assigned_user_id": current},
    )
    code = error.get("status") if isinstance(error, dict) else error
    if code == "409":
        st.session_state["crm_assignment_notice"] = ("warning", "A atribuição mudou. Revise o responsável atual.")
        st.rerun()
    if error is not None:
        st.error("Não foi possível salvar a atribuição. Confira o responsável atual antes de repetir.")
        return
    st.session_state["crm_assignment_notice"] = ("success", "Atribuição atualizada.")
    st.rerun()


def _lead_detail(st: Any, client: httpx.Client, lead_id: int, *, is_admin: bool) -> None:
    if st.button("Voltar à lista", icon=":material/arrow_back:", type="tertiary"):
        del st.session_state["crm_open_lead_id"]
        st.rerun()

    lead, error = _request_result(client, "GET", f"/api/crm/leads/{lead_id}")
    if lead is None:
        _lead_request_error(st, error, detail=True)
        return

    if notice := st.session_state.pop("crm_assignment_notice", None):
        level, message = notice
        if level == "success":
            st.success(message)
        else:
            st.warning(message)
    name = escape(lead.get("full_name") or "Lead sem nome")
    status = lead["commercial_status"]
    label = escape(LEAD_STATUS_LABELS.get(status, status))
    st.html(f'<header class="crm-heading"><h1>{name}</h1><p>{label}</p></header>')

    with st.container(horizontal=True, gap="medium"):
        with st.container(width=320):
            st.subheader("Contato")
            st.caption("E-mail")
            st.text(lead.get("email") or "—", width="stretch")
            st.caption("Telefone")
            st.text(lead.get("phone_number") or "—", width="stretch")

        with st.container(width=320):
            st.subheader("Interesse e origem")
            st.caption("Curso")
            st.text(lead.get("course") or "—", width="stretch")
            if lead.get("source"):
                st.caption("Origem")
                st.text(lead["source"], width="stretch")
            if lead.get("meta_campaign_name"):
                st.caption("Campanha")
                st.text(lead["meta_campaign_name"], width="stretch")
            if not is_admin and lead.get("assigned_user_display_name"):
                st.caption("Responsável")
                st.text(_responsible_label(lead), width="stretch")

    if is_admin:
        _lead_assignment(st, client, lead)


def _lead_list(st: Any, client: httpx.Client, title: str, *, is_admin: bool) -> None:
    if (lead_id := st.session_state.get("crm_open_lead_id")) is not None:
        _lead_detail(st, client, lead_id, is_admin=is_admin)
        return

    st.html(
        f'<header class="crm-heading"><h1>{title}</h1><p>'
        f'{"Carteira comercial da RCTEC" if is_admin else "Sua carteira de atendimento"}'
        '</p></header>'
    )
    if is_admin:
        _assignee_names(st, client)
    filters = _lead_query_controls(st, is_admin=is_admin)
    limit = 25
    offset = st.session_state.get("crm_leads_offset", 0)
    params = {"offset": offset, "limit": limit, **{k: v for k, v in filters.items() if v}}
    result, error = _request_result(client, "GET", "/api/crm/leads", params=params)
    if result is None:
        _lead_request_error(st, error)
        return
    total = result["total"]
    if offset and offset >= total:
        st.session_state["crm_leads_offset"] = max(total - 1, 0) // limit * limit
        st.rerun()
    if not total:
        if any(filters.values()):
            st.info("Nenhum lead corresponde aos filtros.")
        else:
            st.info("Nenhum lead cadastrado." if is_admin else "Nenhum lead atribuído a você.")
        return

    lead_ids = tuple(item["id"] for item in result["items"])
    # A positional selection belongs only to the exact ordered API result.
    table_signature = hashlib.sha256(repr((params, lead_ids)).encode()).hexdigest()
    rows = []
    for item in result["items"]:
        status = item["commercial_status"]
        row = {
            "Lead": item["full_name"] or "Lead sem nome",
            "Status": [LEAD_STATUS_LABELS.get(status, status)],
            "Curso": item.get("course") or "—",
        }
        if is_admin:
            row["Responsável"] = _responsible_label(item)
        rows.append(row)
    selection = st.dataframe(
        rows,
        hide_index=True,
        key=f"crm_leads_{table_signature}",
        on_select="rerun",
        selection_mode="single-row",
        row_height=37,
        width="stretch",
        column_config={
            "Lead": st.column_config.TextColumn(width=160),
            "Status": st.column_config.MultiselectColumn(
                width=112, options=tuple(LEAD_STATUS_LABELS.values()), color=LEAD_STATUS_COLORS,
            ),
            "Responsável": st.column_config.TextColumn(width=145),
        },
    )
    selected = selection.selection.rows
    with st.container(key="crm-pagination", horizontal=True, horizontal_alignment="distribute"):
        st.caption(f"{offset + 1}–{offset + len(rows)} de {total} leads")
        if total > limit:
            with st.container(horizontal=True):
                if st.button("Anterior", disabled=offset == 0):
                    st.session_state["crm_leads_offset"] = offset - limit
                    st.rerun()
                if st.button("Próxima", disabled=offset + limit >= total):
                    st.session_state["crm_leads_offset"] = offset + limit
                    st.rerun()
        valid_selection = bool(selected) and 0 <= selected[0] < len(lead_ids)
        if st.button("Abrir ficha", disabled=not valid_selection, type="primary"):
            st.session_state["crm_open_lead_id"] = lead_ids[selected[0]]
            st.rerun()


def _commercial_navigation(st: Any, *, is_admin: bool) -> str:
    options = (
        (("Leads", ":material/group:"), ("Analytics", ":material/monitoring:"))
        if is_admin else (("Meus leads", ":material/group:"),)
    )
    active = st.session_state.get("crm_section", options[0][0])
    with st.sidebar:
        logo = b64encode(LOGO_PATH.read_bytes()).decode("ascii")
        st.html(
            f'<img class="crm-logo" src="data:image/png;base64,{logo}" '
            'alt="Escola Técnica RCTEC">'
        )
        with st.container(key="crm-nav", gap="xxsmall"):
            for index, (label, icon) in enumerate(options):
                selected = active == label
                if st.button(
                    label,
                    key=f"crm-nav-{'active' if selected else 'idle'}-{index}",
                    icon=icon,
                    type="tertiary",
                    width="content",
                ) and not selected:
                    st.session_state["crm_section"] = label
                    st.rerun()
        st.html(
            '<nav class="crm-account" aria-label="Conta">'
            '<a href="/auth/login" target="_self">Trocar conta</a>'
            '<a href="/auth/logout" target="_self">Sair</a>'
            '</nav>'
        )
    return active


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Mini-CRM RCTEC", layout="wide")
    token = st.context.cookies.get(SESSION_COOKIE, "")
    headers = _auth_headers(token, st.context.cookies.get(BROWSER_COOKIE, ""))
    if not headers:
        _login_screen(st)
        return

    session_fingerprint = hashlib.sha256(token.encode()).hexdigest()

    @st.fragment(run_every="15s")
    def check_session():
        current_token = st.context.cookies.get(SESSION_COOKIE, "")
        current_headers = _auth_headers(current_token, st.context.cookies.get(BROWSER_COOKIE, ""))
        if current_headers != headers:
            st.session_state.clear()
            st.rerun()
        with _api_client(headers=current_headers) as checker:
            active = _request(checker, "GET", "/auth/session")
        if not active or (active["id"], active["role"], session_fingerprint) != st.session_state.get("identity"):
            st.session_state.clear()
            st.rerun()

    def on_response(response):
        if response.status_code == 401 and response.request.url.path != "/auth/session":
            st.session_state.clear()
            st.rerun()

    with _api_client(headers=headers, event_hooks={"response": [on_response]}) as client:
        identity = _request(client, "GET", "/auth/session")
        if not identity:
            _login_screen(st)
            return
        fingerprint = (identity["id"], identity["role"], session_fingerprint)
        if st.session_state.get("identity") != fingerprint:
            st.session_state.clear()
            st.session_state["identity"] = fingerprint
        st.session_state["download_binding"] = identity["binding"]
        client.headers["X-CSRF-Token"] = identity["csrf"]
        check_session()
        is_admin = identity["role"] == "admin"
        st.html(ASSETS / "crm.css")
        section = _commercial_navigation(st, is_admin=is_admin)
        if section != "Analytics":
            _lead_list(st, client, section, is_admin=is_admin)
            return

        st.title("Analytics")
        health = _request(client, "GET", "/health")
        if health and health.get("mode") == "demo":
            st.info("Modo demonstração: os dados exibidos são fictícios.")
        default_period = _request(client, "GET", "/api/dashboard/default-period")
        filters = _campaign_selector(st, client, _filters(st, default_period))
        selected_campaign = None
        if "campaign_id" in filters:
            selected_campaign = _request(
                client, "GET", f"/api/campaigns/{filters['campaign_id']}"
            )
        sync_state = _request(client, "GET", "/api/meta/sync/status")
        overview, campaigns, comparison, enrollments, sync, export = st.tabs(["Visão geral", "Campanhas", "Comparar campanhas", "Lançamentos diários", "Sincronização", "Exportar"])
        with overview:
            _overview(st, client, filters, selected_campaign)
        with campaigns:
            _campaigns(st, client, filters, selected_campaign)
        with comparison:
            _compare_campaigns(st, client, filters)
        with enrollments:
            _enrollments(st, client, filters, selected_campaign)
        with sync:
            if notice := st.session_state.pop("sync_notice", None):
                st.info(notice)
            _sync(st, client, filters, sync_state)
        with export:
            _export(st, filters)


if __name__ == "__main__":
    main()
