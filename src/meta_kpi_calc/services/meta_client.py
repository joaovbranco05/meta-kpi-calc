"""Small, read-only client for the Meta Graph API."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from meta_kpi_calc.core.config import normalize_meta_ad_account_id
from meta_kpi_calc.core.logging import redact_data, safe_json

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_PAGES = 100
USAGE_HEADERS = (
    "x-app-usage",
    "x-ad-account-usage",
    "x-business-use-case-usage",
)

ACCOUNT_FIELDS = "id,name,currency,timezone_name,account_status"
CAMPAIGN_FIELDS = (
    "id,name,status,effective_status,objective,start_time,stop_time"
)
INSIGHT_FIELDS = (
    "account_id,account_name,campaign_id,campaign_name,date_start,date_stop,"
    "spend,reach,impressions,frequency,clicks,inline_link_clicks,ctr,cpc,cpm,"
    "actions,cost_per_action_type"
)


class MetaClientError(Exception):
    """Sanitized failure raised by the read-only Meta client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MetaAccount:
    account_id: str
    account_name: str
    currency: str
    timezone_name: str
    account_status: int | str


@dataclass(frozen=True)
class MetaCampaign:
    meta_campaign_id: str
    name: str
    status: str | None
    effective_status: str
    objective: str | None
    start_time: str | None
    stop_time: str | None


@dataclass(frozen=True)
class MetaInsight:
    account_id: str
    account_name: str
    meta_campaign_id: str
    campaign_name: str
    date_start: date
    date_stop: date
    spend: Decimal
    reach: int
    impressions: int
    clicks: int
    inline_link_clicks: int
    leads: int
    frequency: Decimal | None
    meta_ctr: Decimal | None
    meta_cpc: Decimal | None
    meta_cpm: Decimal | None
    raw_actions: list[dict[str, Any]]
    raw_cost_per_action_type: list[dict[str, Any]]
    raw_response: dict[str, Any]


class MetaClient:
    def __init__(
        self,
        http_client: httpx.Client,
        *,
        token: str,
        ad_account_id: str,
        api_version: str,
        lead_action_types: Sequence[str],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise MetaClientError("Meta access token is not configured.")
        if (
            not isinstance(api_version, str)
            or re.fullmatch(r"v\d+\.\d+", api_version) is None
        ):
            raise MetaClientError("Meta API version is invalid.")
        try:
            normalized_account_id = normalize_meta_ad_account_id(ad_account_id)
        except (AttributeError, ValueError):
            raise MetaClientError("Meta ad account ID is invalid.") from None
        if not isinstance(lead_action_types, Sequence) or isinstance(
            lead_action_types, (str, bytes)
        ) or any(
            not isinstance(item, str) for item in lead_action_types
        ):
            raise MetaClientError("Meta lead action types are invalid.")

        self._http_client = http_client
        self._token = token.strip()
        self._account_id = normalized_account_id
        self._base_url = f"https://graph.facebook.com/{api_version}"
        self._lead_action_types = frozenset(
            item.strip() for item in lead_action_types if item.strip()
        )
        self._sleep = sleep

    def get_account(self) -> MetaAccount:
        payload = self._request_json(
            "account",
            f"/{self._account_id}",
            {"fields": ACCOUNT_FIELDS},
        )
        return MetaAccount(
            account_id=_required_string(payload, "id"),
            account_name=_required_string(payload, "name"),
            currency=_required_string(payload, "currency"),
            timezone_name=_required_string(payload, "timezone_name"),
            account_status=_account_status(payload),
        )

    def list_campaigns(self, *, active_only: bool = True) -> list[MetaCampaign]:
        rows = self._get_pages(
            "campaigns",
            f"/{self._account_id}/campaigns",
            {"fields": CAMPAIGN_FIELDS},
        )
        campaigns = [
            MetaCampaign(
                meta_campaign_id=_required_string(row, "id"),
                name=_required_string(row, "name"),
                status=_optional_string(row, "status"),
                effective_status=_required_string(row, "effective_status"),
                objective=_optional_string(row, "objective"),
                start_time=_optional_string(row, "start_time"),
                stop_time=_optional_string(row, "stop_time"),
            )
            for row in rows
        ]
        if active_only:
            return [
                campaign
                for campaign in campaigns
                if campaign.effective_status == "ACTIVE"
            ]
        return campaigns

    def get_insights(self, date_start: date, date_stop: date) -> list[MetaInsight]:
        if date_start > date_stop:
            raise MetaClientError("Meta insight date range is invalid.")
        rows = self._get_pages(
            "insights",
            f"/{self._account_id}/insights",
            {
                "fields": INSIGHT_FIELDS,
                "level": "campaign",
                "time_increment": "1",
                "time_range": json.dumps(
                    {"since": date_start.isoformat(), "until": date_stop.isoformat()},
                    separators=(",", ":"),
                ),
            },
        )
        return [self._parse_insight(row) for row in rows]

    def _get_pages(
        self, operation: str, path: str, params: Mapping[str, str]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        page_params = dict(params)

        for page_number in range(1, MAX_PAGES + 1):
            payload = self._request_json(operation, path, page_params)
            data = payload.get("data")
            if not isinstance(data, list) or any(
                not isinstance(row, dict) for row in data
            ):
                raise MetaClientError("Meta page response is malformed.")
            rows.extend(data)

            cursor = _next_cursor(payload)
            if cursor is None:
                return rows
            if cursor in seen_cursors:
                raise MetaClientError("Meta pagination cursor was repeated.")
            if page_number == MAX_PAGES:
                raise MetaClientError("Meta pagination limit was exceeded.")
            seen_cursors.add(cursor)
            page_params = {**params, "after": cursor}

        raise MetaClientError("Meta pagination limit was exceeded.")

    def _request_json(
        self, operation: str, path: str, params: Mapping[str, str]
    ) -> dict[str, Any]:
        response = self._get_with_retries(operation, path, params)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            raise MetaClientError(
                "Meta response contains invalid JSON.", status_code=response.status_code
            ) from None
        if not isinstance(payload, dict):
            raise MetaClientError(
                "Meta response is malformed.", status_code=response.status_code
            )
        if "error" in payload:
            raise MetaClientError(
                "Meta API returned an error response.",
                status_code=response.status_code,
            )
        return payload

    def _get_with_retries(
        self, operation: str, path: str, params: Mapping[str, str]
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._http_client.get(
                    url,
                    params=params,
                    headers=headers,
                    follow_redirects=False,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                logger.warning(
                    "Meta transport failure operation=%s attempt=%d",
                    operation,
                    attempt,
                )
                if attempt == MAX_ATTEMPTS:
                    raise MetaClientError("Meta API request failed.") from None
                self._sleep(float(attempt))
                continue

            _log_response(operation, response, attempt, (self._token,))
            if 200 <= response.status_code < 300:
                return response

            is_transient = response.status_code == 429 or (
                500 <= response.status_code <= 599
            )
            if not is_transient or attempt == MAX_ATTEMPTS:
                raise MetaClientError(
                    "Meta API request failed.", status_code=response.status_code
                )
            self._sleep(_retry_delay(response, attempt))

        raise MetaClientError("Meta API request failed.")

    def _parse_insight(self, row: dict[str, Any]) -> MetaInsight:
        date_start = _required_date(row, "date_start")
        date_stop = _required_date(row, "date_stop")
        if date_start > date_stop:
            raise MetaClientError("Meta insight row is malformed.")

        actions = _object_list(row, "actions")
        cost_per_action_type = _object_list(row, "cost_per_action_type")
        leads = 0
        for action in actions:
            action_type = action.get("action_type")
            if (
                isinstance(action_type, str)
                and action_type.strip() in self._lead_action_types
            ):
                leads += _nonnegative_int(action, "value")

        sanitized_actions = redact_data(actions, (self._token,))
        sanitized_costs = redact_data(cost_per_action_type, (self._token,))
        sanitized_row = redact_data(row, (self._token,))
        return MetaInsight(
            account_id=_required_string(row, "account_id"),
            account_name=_required_string(row, "account_name"),
            meta_campaign_id=_required_string(row, "campaign_id"),
            campaign_name=_required_string(row, "campaign_name"),
            date_start=date_start,
            date_stop=date_stop,
            spend=_nonnegative_decimal(row, "spend"),
            reach=_nonnegative_int(row, "reach"),
            impressions=_nonnegative_int(row, "impressions"),
            clicks=_nonnegative_int(row, "clicks"),
            inline_link_clicks=_nonnegative_int(row, "inline_link_clicks"),
            leads=leads,
            frequency=_optional_nonnegative_decimal(row, "frequency"),
            meta_ctr=_optional_nonnegative_decimal(row, "ctr"),
            meta_cpc=_optional_nonnegative_decimal(row, "cpc"),
            meta_cpm=_optional_nonnegative_decimal(row, "cpm"),
            raw_actions=sanitized_actions,
            raw_cost_per_action_type=sanitized_costs,
            raw_response=sanitized_row,
        )


def _required_string(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MetaClientError("Meta response contains an invalid required field.")
    return value


def _optional_string(values: Mapping[str, Any], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    return _required_string(values, key)


def _account_status(values: Mapping[str, Any]) -> int | str:
    value = values.get("account_status")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise MetaClientError("Meta response contains an invalid account status.")
    if isinstance(value, str) and not value.strip():
        raise MetaClientError("Meta response contains an invalid account status.")
    return value


def _required_date(values: Mapping[str, Any], key: str) -> date:
    value = _required_string(values, key)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise MetaClientError("Meta response contains an invalid date.") from None


def _nonnegative_decimal(values: Mapping[str, Any], key: str) -> Decimal:
    value = values.get(key)
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise MetaClientError("Meta response contains an invalid decimal field.")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise MetaClientError(
            "Meta response contains an invalid decimal field."
        ) from None
    if not number.is_finite() or number < 0:
        raise MetaClientError("Meta response contains an invalid decimal field.")
    return number


def _optional_nonnegative_decimal(
    values: Mapping[str, Any], key: str
) -> Decimal | None:
    if values.get(key) is None:
        return None
    return _nonnegative_decimal(values, key)


def _nonnegative_int(values: Mapping[str, Any], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool):
        raise MetaClientError("Meta response contains an invalid integer field.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"\d+", value):
        number = int(value)
    else:
        raise MetaClientError("Meta response contains an invalid integer field.")
    if number < 0:
        raise MetaClientError("Meta response contains an invalid integer field.")
    return number


def _object_list(values: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = values.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MetaClientError("Meta response contains an invalid action list.")
    return value


def _next_cursor(payload: Mapping[str, Any]) -> str | None:
    if "paging" not in payload:
        return None
    paging = payload["paging"]
    if not isinstance(paging, dict):
        raise MetaClientError("Meta pagination response is malformed.")

    if "next" in paging:
        next_url = paging["next"]
        if not isinstance(next_url, str):
            raise MetaClientError("Meta pagination response is malformed.")
        try:
            parsed = urlparse(next_url)
            hostname = parsed.hostname
        except ValueError:
            raise MetaClientError("Meta pagination response is malformed.") from None
        if parsed.scheme != "https" or hostname != "graph.facebook.com":
            raise MetaClientError("Meta pagination host is invalid.")

    cursors = paging.get("cursors")
    if cursors is None:
        return None
    if not isinstance(cursors, dict):
        raise MetaClientError("Meta pagination response is malformed.")
    cursor = cursors.get("after")
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor.strip():
        raise MetaClientError("Meta pagination cursor is malformed.")
    return cursor


def _retry_delay(response: httpx.Response, fallback: int) -> float:
    value = response.headers.get("Retry-After")
    if value is not None and re.fullmatch(r"\d+", value):
        return float(int(value))
    return float(fallback)


def _log_response(
    operation: str,
    response: httpx.Response,
    attempt: int,
    secrets: Sequence[str],
) -> None:
    usage: dict[str, Any] = {}
    for header in USAGE_HEADERS:
        value = response.headers.get(header)
        if value is None:
            continue
        try:
            usage[header] = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            usage[header] = "malformed"
    logger.info(
        "Meta response operation=%s status=%d attempt=%d usage=%s",
        operation,
        response.status_code,
        attempt,
        safe_json(usage, secrets),
    )
