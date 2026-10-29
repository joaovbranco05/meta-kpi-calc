"""Signed Lead Ads ingress: validate first, persist minimal metadata, then ACK."""

import hashlib
import hmac
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from meta_kpi_calc.crm.inbox import EventInput, enqueue_events
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, meta_id

router = APIRouter(prefix="/webhooks/meta/lead-ads", tags=["Lead Ads webhook"])


def reject(status: int, code: str) -> None:
    raise HTTPException(status, detail={"code": code, "message": "Lead Ads request rejected."})


def _ready(request: Request):
    settings = request.app.state.settings
    if not settings.lead_ads_ingress_ready:
        reject(503, "lead_ads_disabled")
    return settings


@router.get("", response_class=PlainTextResponse)
def verify_webhook(request: Request) -> PlainTextResponse:
    settings = _ready(request)
    query = request.query_params
    challenge = query.get("hub.challenge", "")
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token", "")
    if mode != "subscribe" or not challenge or len(challenge) > 1024 or len(token) > 4096:
        reject(400, "invalid_verification")
    if not hmac.compare_digest(token.encode(), settings.lead_ads_verify_token.get_secret_value().encode()):
        reject(403, "invalid_verification")
    return PlainTextResponse(challenge)


def parse_events(payload: object, allowed_pages: list[str]) -> list[EventInput]:
    if not isinstance(payload, dict) or payload.get("object") != "page":
        raise LeadAdsError("invalid_payload")
    entries = payload.get("entry")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise LeadAdsError("invalid_payload")
    result: list[EventInput] = []
    changes_count = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list):
            raise LeadAdsError("invalid_payload")
        page_id = meta_id(entry.get("id"))
        if page_id not in allowed_pages:
            raise LeadAdsError("page_not_allowed")
        for change in entry["changes"]:
            changes_count += 1
            if changes_count > 1000 or not isinstance(change, dict) or not isinstance(change.get("field"), str):
                raise LeadAdsError("invalid_payload")
            if change["field"] != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                raise LeadAdsError("invalid_payload")
            if value.get("page_id") is not None and meta_id(value["page_id"]) != page_id:
                raise LeadAdsError("source_mismatch")
            lead = meta_id(value.get("leadgen_id"))
            form = meta_id(value["form_id"]) if value.get("form_id") is not None else None
            ad = meta_id(value["ad_id"]) if value.get("ad_id") is not None else None
            result.append(EventInput(lead, page_id, form, ad))
    return result


def _persist(factory, events: list[EventInput]) -> None:
    # No ACK until __exit__ successfully commits all events.
    with factory.begin() as session:
        enqueue_events(session, events)


@router.post("")
async def receive_webhook(request: Request) -> dict[str, str]:
    settings = _ready(request)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > settings.lead_ads_body_max_bytes:
            reject(413, "body_too_large")
        body.extend(chunk)
    signature = request.headers.get("x-hub-signature-256", "")
    if re.fullmatch(r"sha256=[0-9a-fA-F]{64}", signature) is None:
        reject(403, "invalid_signature")
    expected = hmac.new(settings.lead_ads_app_secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[7:].lower(), expected):
        reject(403, "invalid_signature")
    try:
        payload = json.loads(body)
        events = parse_events(payload, settings.lead_ads_allowed_page_ids)
    except LeadAdsError as error:
        reject(403 if error.code == "page_not_allowed" else 400, error.code)
    except (ValueError, UnicodeError, RecursionError):
        reject(400, "invalid_payload")
    await run_in_threadpool(_persist, request.app.state.database.session_factory, events)
    return {"status": "accepted"}
