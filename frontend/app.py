"""Small local Streamlit panel that talks exclusively to the REST API."""

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EFFECTIVE_STATUS_OPTIONS = ("", "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "DISABLED")
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


def _export(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    st.subheader("Exportar relatório")
    if not _export_is_current(st, filters):
        st.session_state.pop("report_export", None)
        st.session_state.pop("report_export_filters", None)
    if st.button("Preparar relatório XLSX"):
        try:
            response = client.get(
                f"{API_BASE_URL}/api/export",
                params={**filters, "format": "xlsx", "dataset": "performance"},
                timeout=10,
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            st.error("Não foi possível preparar o relatório.")
        else:
            st.session_state["report_export"] = response.content
            st.session_state["report_export_filters"] = dict(filters)
    if report := st.session_state.get("report_export"):
        st.download_button(
            "Baixar relatório XLSX",
            data=report,
            file_name="meta-kpi-report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _export_is_current(st: Any, filters: dict[str, str]) -> bool:
    return (
        "report_export" not in st.session_state
        or st.session_state.get("report_export_filters") == filters
    )


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Meta KPI Calculator", layout="wide")
    st.title("Meta KPI Calculator")
    with httpx.Client() as client:
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
        overview, campaigns, enrollments, sync, export = st.tabs(["Visão geral", "Campanhas", "Lançamentos diários", "Sincronização", "Exportar"])
        with overview:
            _overview(st, client, filters, selected_campaign)
        with campaigns:
            _campaigns(st, client, filters, selected_campaign)
        with enrollments:
            _enrollments(st, client, filters, selected_campaign)
        with sync:
            if notice := st.session_state.pop("sync_notice", None):
                st.info(notice)
            _sync(st, client, filters, sync_state)
        with export:
            _export(st, client, filters)


if __name__ == "__main__":
    main()
