"""Small local Streamlit panel that talks exclusively to the REST API."""

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EFFECTIVE_STATUS_OPTIONS = ("", "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "DISABLED")


def _format_value(value: Any) -> str:
    if value is None:
        return "Não calculável"
    if isinstance(value, Decimal):
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


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


def _filters(st: Any) -> dict[str, str]:
    today = date.today()
    with st.sidebar:
        st.header("Filtros")
        start = st.date_input("Início", today - timedelta(days=6))
        stop = st.date_input("Fim", today)
        brand = st.selectbox("Marca", ["", "RCTEC", "FECAF", "CURSO_COM_BOLSA", "NAO_CLASSIFICADA"])
        effective_status = st.selectbox(
            "Status efetivo",
            EFFECTIVE_STATUS_OPTIONS,
            format_func=lambda value: "Todos" if value == "" else value,
        )
    result = {"date_start": start.isoformat(), "date_stop": stop.isoformat()}
    for key, value in (("brand", brand), ("effective_status", effective_status)):
        if value.strip():
            result[key] = value.strip()
    return result


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


def _overview(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    summary = _request(client, "GET", "/api/dashboard/summary", params=filters)
    if summary is None:
        st.error("A API está indisponível ou respondeu com erro.")
        return
    st.subheader("Visão geral")
    totals = summary["totals"]
    columns = st.columns(4)
    for column, (label, key) in zip(columns, (("Investimento", "spend"), ("Leads", "leads"), ("Contratadas", "contracted_enrollments"), ("Pagantes", "paying_enrollments"))):
        column.metric(label, _format_currency(totals[key]) if key == "spend" else _format_value(totals[key]))
    st.subheader("KPIs")
    st.dataframe([{"Indicador": key, "Valor": _format_value(value)} for key, value in summary["kpis"].items()], hide_index=True, use_container_width=True)
    if summary["warnings"]:
        st.warning("Há dados incompletos ou divergências para revisar.")
        st.dataframe(summary["warnings"], hide_index=True, use_container_width=True)
    coverage = summary["commercial_coverage"]
    labels = {"unknown": "não informado", "partial": "parcial", "complete": "fechado"}
    st.caption(
        "Cobertura comercial: "
        f"{labels[coverage['status']]} "
        f"({coverage['complete_units']} fechados, {coverage['partial_units']} parciais, "
        f"{coverage['unknown_units']} sem confirmação)."
    )


def _campaigns(
    st: Any,
    client: httpx.Client,
    filters: dict[str, str],
    selected_campaign: dict[str, Any] | None,
) -> None:
    st.subheader("Campanhas e comparação")
    campaigns = _request(
        client,
        "GET",
        "/api/campaigns",
        params={
            **_campaign_params(filters),
            "offset": int(st.session_state.get("campaign-table-page", 0)) * 50,
            "limit": 50,
        },
    )
    if campaigns is None:
        st.error("Não foi possível carregar campanhas.")
        return
    offset = _page_offset(st, "campaign-table-page", campaigns["total"])
    if offset != campaigns["offset"]:
        campaigns = _request(
            client,
            "GET",
            "/api/campaigns",
            params={**_campaign_params(filters), "offset": offset, "limit": 50},
        )
        if campaigns is None:
            return
    if not campaigns["items"]:
        st.info("Nenhuma campanha encontrada.")
        return
    st.dataframe(_display_rows(campaigns["items"]), hide_index=True, use_container_width=True)
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


def _sync(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    st.subheader("Sincronização e configurações")
    connection = _request(client, "GET", "/api/meta/connection")
    if connection is None:
        st.error("Não foi possível consultar a conexão.")
        return
    st.json({key: connection[key] for key in ("mode", "configured", "connected")})
    if st.button("Sincronizar período filtrado"):
        result = _request(client, "POST", "/api/meta/sync", json={"date_start": filters["date_start"], "date_stop": filters["date_stop"]})
        if result:
            st.success("Sincronização concluída.")
        else:
            st.error("A sincronização não está disponível ou falhou.")


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Meta KPI Calculator", layout="wide")
    st.title("Meta KPI Calculator")
    with httpx.Client() as client:
        filters = _campaign_selector(st, client, _filters(st))
        selected_campaign = None
        if "campaign_id" in filters:
            selected_campaign = _request(
                client, "GET", f"/api/campaigns/{filters['campaign_id']}"
            )
        connection = _request(client, "GET", "/api/meta/connection")
        if connection and connection["mode"] == "demo":
            st.info("Modo demonstração: os dados exibidos são fictícios.")
        overview, campaigns, enrollments, sync = st.tabs(["Visão geral", "Campanhas", "Lançamentos diários", "Sincronização"])
        with overview:
            _overview(st, client, filters)
        with campaigns:
            _campaigns(st, client, filters, selected_campaign)
        with enrollments:
            _enrollments(st, client, filters, selected_campaign)
        with sync:
            _sync(st, client, filters)


if __name__ == "__main__":
    main()
