"""Small local Streamlit panel that talks exclusively to the REST API."""

import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


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
        copy = dict(row)
        for key, value in copy.items():
            if key.endswith(("_date", "_start", "_stop")) and isinstance(value, str):
                parts = value[:10].split("-")
                if len(parts) == 3:
                    copy[key] = f"{parts[2]}/{parts[1]}/{parts[0]}"
        rendered.append(copy)
    return rendered


def _request(
    client: httpx.Client, method: str, path: str, **kwargs: Any
) -> dict[str, Any] | None:
    try:
        response = client.request(method, f"{API_BASE_URL}{path}", timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def _filters(st: Any) -> dict[str, str]:
    today = date.today()
    with st.sidebar:
        st.header("Filtros")
        start = st.date_input("Início", today - timedelta(days=6))
        stop = st.date_input("Fim", today)
        brand = st.selectbox("Marca", ["", "RCTEC", "FECAF", "CURSO_COM_BOLSA", "NAO_CLASSIFICADA"])
        campaign_id = st.text_input("ID interno da campanha")
        course = st.text_input("Curso da campanha")
        effective_status = st.text_input("Status efetivo")
    result = {"date_start": start.isoformat(), "date_stop": stop.isoformat()}
    for key, value in (("brand", brand), ("campaign_id", campaign_id), ("course", course), ("effective_status", effective_status)):
        if value.strip():
            result[key] = value.strip()
    return result


def _campaign_params(filters: dict[str, str]) -> dict[str, str | int]:
    return {"limit": 100, **{key: value for key, value in filters.items() if key in {"brand", "campaign_id", "course", "effective_status"}}}


def _enrollment_params(filters: dict[str, str]) -> dict[str, str | int]:
    return {"limit": 100, **{key: value for key, value in filters.items() if key in {"date_start", "date_stop", "brand", "campaign_id"}}}


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


def _campaigns(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    st.subheader("Campanhas e comparação")
    campaigns = _request(client, "GET", "/api/campaigns", params=_campaign_params(filters))
    if campaigns is None:
        st.error("Não foi possível carregar campanhas.")
        return
    if not campaigns["items"]:
        st.info("Nenhuma campanha encontrada.")
        return
    st.dataframe(_display_rows(campaigns["items"]), hide_index=True, use_container_width=True)
    with st.form("classification"):
        campaign_id = st.number_input("ID da campanha", min_value=1, step=1)
        brand = st.selectbox("Nova marca", ["RCTEC", "FECAF", "CURSO_COM_BOLSA", "NAO_CLASSIFICADA"])
        course = st.text_input("Novo curso (opcional)")
        submitted = st.form_submit_button("Salvar classificação")
    if submitted:
        payload: dict[str, Any] = {"brand": brand}
        if course.strip():
            payload["course"] = course.strip()
        if _request(client, "PATCH", f"/api/campaigns/{campaign_id}/classification", json=payload):
            st.success("Classificação atualizada.")
        else:
            st.error("Não foi possível atualizar a classificação.")


def _enrollments(st: Any, client: httpx.Client, filters: dict[str, str]) -> None:
    st.subheader("Matrículas")
    records = _request(client, "GET", "/api/enrollments", params=_enrollment_params(filters))
    if records is None:
        st.error("Não foi possível carregar matrículas.")
        return
    scoped_campaigns = _request(client, "GET", "/api/campaigns", params=_campaign_params(filters))
    if scoped_campaigns is None:
        st.error("Não foi possível aplicar o recorte das campanhas.")
        return
    campaign_ids = {campaign["id"] for campaign in scoped_campaigns["items"]}
    scoped_records = [record for record in records["items"] if record["campaign_id"] in campaign_ids]
    st.dataframe(_display_rows(scoped_records), hide_index=True, use_container_width=True)
    with st.form("enrollment"):
        record_id = st.text_input("ID do registro para corrigir (vazio cria novo)")
        campaign_id = st.number_input("ID da campanha da matrícula", min_value=1, step=1)
        reference_date = st.date_input("Data de referência")
        course = st.text_input("Curso da matrícula")
        contracted = st.number_input("Contratadas", min_value=0, step=1)
        paying = st.number_input("Pagantes", min_value=0, step=1)
        cancellations = st.number_input("Cancelamentos", min_value=0, step=1)
        expected = st.text_input("Receita esperada", "0.00")
        received = st.text_input("Receita recebida", "0.00")
        saved = st.form_submit_button("Salvar matrícula")
    if saved:
        payload = {"campaign_id": campaign_id, "reference_date": reference_date.isoformat(), "course": course, "contracted_enrollments": contracted, "paying_enrollments": paying, "cancellations": cancellations, "expected_revenue": expected, "received_revenue": received, "contribution_margin": None, "notes": None}
        method, path = (("PUT", f"/api/enrollments/{record_id}") if record_id.strip() else ("POST", "/api/enrollments"))
        if _request(client, method, path, json=payload):
            st.success("Matrícula salva.")
        else:
            st.error("Não foi possível salvar a matrícula.")


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
    filters = _filters(st)
    with httpx.Client() as client:
        connection = _request(client, "GET", "/api/meta/connection")
        if connection and connection["mode"] == "demo":
            st.info("Modo demonstração: os dados exibidos são fictícios.")
        overview, campaigns, enrollments, sync = st.tabs(["Visão geral", "Campanhas", "Matrículas", "Sincronização"])
        with overview:
            _overview(st, client, filters)
        with campaigns:
            _campaigns(st, client, filters)
        with enrollments:
            _enrollments(st, client, filters)
        with sync:
            _sync(st, client, filters)


if __name__ == "__main__":
    main()
