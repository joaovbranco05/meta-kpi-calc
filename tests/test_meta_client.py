import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from meta_kpi_calc.services.meta_client import (
    ACCOUNT_FIELDS,
    CAMPAIGN_FIELDS,
    INSIGHT_FIELDS,
    MAX_ATTEMPTS,
    MAX_PAGES,
    MetaClient,
    MetaClientError,
)

TOKEN = "sentinel-meta-token"
START = date(2026, 9, 1)
STOP = date(2026, 9, 2)


def account_payload() -> dict[str, Any]:
    return {
        "id": "act_123",
        "name": "Test account",
        "currency": "BRL",
        "timezone_name": "America/Sao_Paulo",
        "account_status": 1,
    }


def campaign_payload(
    campaign_id: str = "campaign-1", effective_status: str = "ACTIVE"
) -> dict[str, Any]:
    return {
        "id": campaign_id,
        "name": f"Campaign {campaign_id}",
        "status": "ACTIVE",
        "effective_status": effective_status,
        "objective": "OUTCOME_LEADS",
        "start_time": "2026-09-01T00:00:00-0300",
        "stop_time": None,
    }


def insight_payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "account_id": "123",
        "account_name": "Test account",
        "campaign_id": "campaign-1",
        "campaign_name": "Campaign 1",
        "date_start": "2026-09-01",
        "date_stop": "2026-09-01",
        "spend": "12.34",
        "reach": "100",
        "impressions": "120",
        "clicks": "11",
        "inline_link_clicks": "8",
        "frequency": "1.200000",
        "ctr": "6.666667",
        "cpc": "1.542500",
        "cpm": "102.833333",
        "actions": [
            {"action_type": "lead", "value": "2"},
            {"action_type": "chosen", "value": 3},
            {"action_type": "ignored", "value": "not-an-integer"},
        ],
        "cost_per_action_type": [{"action_type": "lead", "value": "6.17"}],
    }
    values.update(overrides)
    return values


def make_client(
    handler: Any,
    *,
    account_id: str = "123",
    token: str = TOKEN,
    api_version: str = "v26.0",
    lead_action_types: tuple[str, ...] = (" lead ", "chosen", "lead"),
    sleep: Any = lambda _seconds: None,
) -> tuple[MetaClient, httpx.Client]:
    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return (
        MetaClient(
            http_client,
            token=token,
            ad_account_id=account_id,
            api_version=api_version,
            lead_action_types=lead_action_types,
            sleep=sleep,
        ),
        http_client,
    )


def test_get_account_uses_fixed_get_endpoint_header_and_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=account_payload())

    client, http_client = make_client(handler, account_id="act_123")
    try:
        account = client.get_account()
    finally:
        http_client.close()

    assert account.account_id == "act_123"
    assert account.account_status == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v26.0/act_123"
    assert dict(request.url.params) == {"fields": ACCOUNT_FIELDS}
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)


def test_campaigns_filter_active_locally_and_preserve_all_on_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    campaign_payload("active", "ACTIVE"),
                    campaign_payload("paused", "PAUSED"),
                ]
            },
        )

    client, http_client = make_client(handler)
    try:
        active = client.list_campaigns()
        all_campaigns = client.list_campaigns(active_only=False)
    finally:
        http_client.close()

    assert [item.meta_campaign_id for item in active] == ["active"]
    assert [item.meta_campaign_id for item in all_campaigns] == ["active", "paused"]
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.path == "/v26.0/act_123/campaigns" for request in requests)
    assert all(
        dict(request.url.params) == {"fields": CAMPAIGN_FIELDS}
        for request in requests
    )


def test_insights_use_exact_params_types_and_configured_lead_actions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [insight_payload()]})

    client, http_client = make_client(handler)
    try:
        insights = client.get_insights(START, STOP)
    finally:
        http_client.close()

    assert len(insights) == 1
    insight = insights[0]
    assert insight.meta_campaign_id == "campaign-1"
    assert insight.date_start == START
    assert insight.spend == Decimal("12.34")
    assert insight.frequency == Decimal("1.200000")
    assert insight.leads == 5
    assert not hasattr(insight, "qualified_leads")
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v26.0/act_123/insights"
    assert request.url.params["fields"] == INSIGHT_FIELDS
    assert request.url.params["level"] == "campaign"
    assert request.url.params["time_increment"] == "1"
    assert request.url.params["time_range"] == (
        '{"since":"2026-09-01","until":"2026-09-02"}'
    )


def test_missing_actions_produce_zero_leads_and_optional_metrics() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    insight_payload(
                        actions=None,
                        cost_per_action_type=None,
                        frequency=None,
                        ctr=None,
                        cpc=None,
                        cpm=None,
                    )
                ]
            },
        )

    client, http_client = make_client(handler)
    try:
        insight = client.get_insights(START, STOP)[0]
    finally:
        http_client.close()

    assert insight.leads == 0
    assert insight.frequency is None
    assert insight.raw_actions == []
    assert insight.raw_cost_per_action_type == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("name", None),
        ("currency", 1),
        ("timezone_name", " "),
        ("account_status", True),
        ("account_status", ""),
    ],
)
def test_invalid_account_fields_are_rejected(field: str, value: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**account_payload(), field: value})

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError):
            client.get_account()
    finally:
        http_client.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("name", 1),
        ("effective_status", None),
        ("status", 1),
        ("objective", []),
        ("start_time", False),
        ("stop_time", {}),
    ],
)
def test_invalid_campaign_fields_are_rejected(field: str, value: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        row = {**campaign_payload(), field: value}
        return httpx.Response(200, json={"data": [row]})

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError):
            client.list_campaigns(active_only=False)
    finally:
        http_client.close()


def test_inverted_period_and_invalid_configuration_fail_before_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError, match="date range"):
            client.get_insights(STOP, START)
    finally:
        http_client.close()
    assert requests == []

    for overrides in (
        {"token": " "},
        {"account_id": "act_bad"},
        {"api_version": "26.0"},
        {"lead_action_types": ("lead", 1)},
        {"lead_action_types": "lead"},
        {"lead_action_types": None},
        {"lead_action_types": 1},
    ):
        with pytest.raises(MetaClientError):
            invalid, invalid_http = make_client(
                handler, **overrides  # type: ignore[arg-type]
            )
            invalid_http.close()
            del invalid
    assert requests == []


def test_pagination_reuses_fixed_endpoint_and_only_adds_after() -> None:
    requests: list[httpx.Request] = []
    untrusted_next = "https://graph.facebook.com/evil/path?access_token=do-not-use"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [campaign_payload("one")],
                    "paging": {
                        "cursors": {"after": "cursor-two"},
                        "next": untrusted_next,
                    },
                },
            )
        return httpx.Response(200, json={"data": [campaign_payload("two")]})

    client, http_client = make_client(handler)
    try:
        campaigns = client.list_campaigns()
    finally:
        http_client.close()

    assert [item.meta_campaign_id for item in campaigns] == ["one", "two"]
    assert len(requests) == 2
    assert all(request.url.path == "/v26.0/act_123/campaigns" for request in requests)
    assert dict(requests[0].url.params) == {"fields": CAMPAIGN_FIELDS}
    assert dict(requests[1].url.params) == {
        "fields": CAMPAIGN_FIELDS,
        "after": "cursor-two",
    }
    assert str(requests[1].url) != untrusted_next


@pytest.mark.parametrize(
    "paging",
    [
        {"cursors": {"after": "same"}},
        {"cursors": {"after": "same"}},
    ],
)
def test_repeated_cursor_stops_before_third_request(paging: dict[str, Any]) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"data": [], "paging": paging})

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError, match="repeated"):
            client.list_campaigns()
    finally:
        http_client.close()
    assert requests == 2


@pytest.mark.parametrize(
    "next_value",
    [
        "http://graph.facebook.com/path",
        "https://example.com/path",
        "not-a-url",
        "https://[",
        "https://[::1",
        None,
    ],
)
def test_untrusted_or_malformed_next_is_rejected(next_value: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [],
                "paging": {"cursors": {"after": "cursor"}, "next": next_value},
            },
        )

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError, match="pagination"):
            client.list_campaigns()
    finally:
        http_client.close()


def test_page_limit_allows_100_complete_pages_and_blocks_101st() -> None:
    completed_requests = 0

    def complete_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal completed_requests
        completed_requests += 1
        paging = (
            {"cursors": {"after": f"cursor-{completed_requests}"}}
            if completed_requests < MAX_PAGES
            else {}
        )
        return httpx.Response(200, json={"data": [], "paging": paging})

    client, http_client = make_client(complete_handler)
    try:
        assert client.list_campaigns() == []
    finally:
        http_client.close()
    assert completed_requests == MAX_PAGES

    excessive_requests = 0

    def excessive_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal excessive_requests
        excessive_requests += 1
        return httpx.Response(
            200,
            json={
                "data": [],
                "paging": {"cursors": {"after": f"cursor-{excessive_requests}"}},
            },
        )

    client, http_client = make_client(excessive_handler)
    try:
        with pytest.raises(MetaClientError, match="limit"):
            client.list_campaigns()
    finally:
        http_client.close()
    assert excessive_requests == MAX_PAGES


@pytest.mark.parametrize("failure", ["transport", "timeout", 429, 500, 599])
def test_transient_failures_can_succeed_on_third_attempt(failure: Any) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == MAX_ATTEMPTS:
            return httpx.Response(200, json=account_payload())
        if failure == "transport":
            raise httpx.ConnectError("private transport detail", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private timeout detail", request=request)
        return httpx.Response(failure)

    client, http_client = make_client(handler, sleep=sleeps.append)
    try:
        assert client.get_account().account_id == "act_123"
    finally:
        http_client.close()
    assert attempts == MAX_ATTEMPTS
    assert sleeps == [1.0, 2.0]


def test_transport_exhaustion_stops_after_three_without_final_sleep(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(
            f"private-{TOKEN}-https://secret.invalid/?after=cursor", request=request
        )

    caplog.set_level(logging.WARNING, logger="meta_kpi_calc.services.meta_client")
    client, http_client = make_client(handler, sleep=sleeps.append)
    try:
        with pytest.raises(MetaClientError) as captured:
            client.get_account()
    finally:
        http_client.close()

    assert attempts == MAX_ATTEMPTS
    assert sleeps == [1.0, 2.0]
    assert captured.value.status_code is None
    rendered = str(captured.value) + repr(captured.value) + caplog.text
    assert TOKEN not in rendered
    assert "secret.invalid" not in rendered
    assert "cursor" not in rendered


@pytest.mark.parametrize("status", [300, 301, 400, 401, 404, 499, 600])
def test_permanent_http_errors_are_not_retried(status: int) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text="private error body")

    client, http_client = make_client(handler, sleep=sleeps.append)
    try:
        with pytest.raises(MetaClientError) as captured:
            client.get_account()
    finally:
        http_client.close()
    assert captured.value.status_code == status
    assert attempts == 1
    assert sleeps == []
    assert "private error body" not in str(captured.value)


def test_redirect_is_never_followed_even_when_injected_client_enables_it() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host != "graph.facebook.com":
            return httpx.Response(200, json=account_payload())
        return httpx.Response(
            302,
            headers={"Location": "https://evil.invalid/redirect"},
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    client = MetaClient(
        http_client,
        token=TOKEN,
        ad_account_id="123",
        api_version="v26.0",
        lead_action_types=("lead",),
    )
    try:
        with pytest.raises(MetaClientError) as captured:
            client.get_account()
    finally:
        http_client.close()

    assert captured.value.status_code == 302
    assert len(requests) == 1
    assert requests[0].url.host == "graph.facebook.com"


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        ("0", [0.0, 0.0]),
        ("7", [7.0, 7.0]),
        ("-1", [1.0, 2.0]),
        ("1.5", [1.0, 2.0]),
        ("later", [1.0, 2.0]),
    ],
)
def test_retry_after_integer_or_progressive_fallback(
    retry_after: str, expected: list[float]
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": retry_after})

    client, http_client = make_client(handler, sleep=sleeps.append)
    try:
        with pytest.raises(MetaClientError) as captured:
            client.get_account()
    finally:
        http_client.close()
    assert captured.value.status_code == 429
    assert attempts == MAX_ATTEMPTS
    assert sleeps == expected


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"error": {"message": "private response"}},
        {"data": "not-a-list"},
        {"data": ["not-an-object"]},
        {"data": [], "paging": "not-an-object"},
        {"data": [], "paging": {"cursors": "not-an-object"}},
        {"data": [], "paging": {"cursors": {"after": ""}}},
        {"data": [], "paging": {"cursors": {"after": "   "}}},
    ],
)
def test_malformed_response_shapes_are_sanitized(payload: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError) as captured:
            client.list_campaigns()
    finally:
        http_client.close()
    assert "private response" not in str(captured.value)


def test_invalid_json_is_sanitized() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"sentinel invalid json")

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError, match="invalid JSON") as captured:
            client.get_account()
    finally:
        http_client.close()
    assert "sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", ""),
        ("date_start", "bad-date"),
        ("date_stop", "2026-08-31"),
        ("spend", -1),
        ("spend", "NaN"),
        ("frequency", "Infinity"),
        ("reach", True),
        ("impressions", 1.5),
        ("clicks", "-1"),
        ("inline_link_clicks", None),
        ("actions", ["not-an-object"]),
        ("cost_per_action_type", {}),
    ],
)
def test_invalid_insight_fields_are_rejected(field: str, value: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [insight_payload(**{field: value})]})

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError):
            client.get_insights(START, STOP)
    finally:
        http_client.close()


@pytest.mark.parametrize("value", [True, 1.5, "-1", "1.0", "NaN"])
def test_invalid_configured_lead_value_is_rejected(value: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    insight_payload(actions=[{"action_type": "lead", "value": value}])
                ]
            },
        )

    client, http_client = make_client(handler)
    try:
        with pytest.raises(MetaClientError):
            client.get_insights(START, STOP)
    finally:
        http_client.close()


def test_raw_response_and_usage_logs_are_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    next_url = "https://graph.facebook.com/path?after=private-cursor"

    def handler(_request: httpx.Request) -> httpx.Response:
        row = insight_payload(
            actions=[
                {"action_type": "lead", "value": "1", "access_token": TOKEN}
            ],
            Authorization=f"Bearer {TOKEN}",
            echoed=TOKEN,
        )
        row[TOKEN] = "external-key"
        return httpx.Response(
            200,
            headers={
                "x-app-usage": json.dumps(
                    {
                        "access_token": TOKEN,
                        "echo": TOKEN,
                        TOKEN: 1,
                        "calls": 1,
                    }
                ),
                "x-ad-account-usage": f"malformed-{TOKEN}",
            },
            json={"data": [row], "paging": {"next": next_url}},
        )

    caplog.set_level(logging.INFO, logger="meta_kpi_calc.services.meta_client")
    client, http_client = make_client(handler)
    try:
        insight = client.get_insights(START, STOP)[0]
    finally:
        http_client.close()

    rendered = repr(insight.raw_response) + caplog.text
    assert TOKEN not in rendered
    assert "private-cursor" not in caplog.text
    assert next_url not in caplog.text
    assert "malformed-sentinel" not in caplog.text
    assert "[REDACTED]" in rendered
    assert "malformed" in caplog.text
