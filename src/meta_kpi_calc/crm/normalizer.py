"""Minimal Graph lead mapping. Unknown answers are counted, never retained."""

from dataclasses import dataclass
from datetime import datetime, timezone

from meta_kpi_calc.crm.ingestion import LeadSubmission
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, meta_id

FIELD_LIMITS = {"full_name": 255, "phone_number": 64, "email": 320, "city": 255, "state": 128}


@dataclass(frozen=True)
class NormalizedLead:
    submission: LeadSubmission
    unmapped_fields: int


def normalize_lead(payload: dict, *, page_id: str, form_id: str | None = None,
                   lead_id: str | None = None, ad_id: str | None = None) -> NormalizedLead:
    received_id = meta_id(payload.get("id"))
    if lead_id is not None and received_id != meta_id(lead_id):
        raise LeadAdsError("source_mismatch")
    if payload.get("page_id") is not None and meta_id(payload["page_id"]) != meta_id(page_id):
        raise LeadAdsError("source_mismatch")
    values: dict = {"source": "META_LEAD_ADS", "meta_page_id": meta_id(page_id)}
    raw_time = payload.get("created_time")
    try:
        if not isinstance(raw_time, str):
            raise ValueError
        created = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError
        values["meta_created_time"] = created.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise LeadAdsError("invalid_payload") from None
    for source, expected in (("form_id", form_id), ("ad_id", ad_id)):
        actual = payload.get(source)
        if actual is not None:
            actual = meta_id(actual)
            if expected is not None and actual != meta_id(expected):
                raise LeadAdsError("source_mismatch")
        if actual is not None or expected is not None:
            values[f"meta_{source}"] = actual if actual is not None else meta_id(expected)
    # Optional IDs already present in verified responses are retained, never inferred.
    for source in ("campaign_id", "adset_id"):
        if payload.get(source) is not None:
            values[f"meta_{source}"] = meta_id(payload[source])
    data = payload.get("field_data", [])
    if not isinstance(data, list) or len(data) > 100:
        raise LeadAdsError("invalid_payload")
    unmapped = 0
    for field in data:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not isinstance(field.get("values"), list):
            raise LeadAdsError("invalid_payload")
        name = field["name"]
        responses = field["values"]
        if name not in FIELD_LIMITS:
            unmapped += 1
            continue
        if not responses:
            continue
        if len(responses) != 1 or not isinstance(responses[0], str) or len(responses[0]) > FIELD_LIMITS[name]:
            raise LeadAdsError("invalid_payload")
        value = responses[0].strip()
        if not value:
            continue
        if name in values and values[name] != value:
            raise LeadAdsError("invalid_payload")
        values[name] = value
    return NormalizedLead(LeadSubmission(received_id, values), unmapped)
