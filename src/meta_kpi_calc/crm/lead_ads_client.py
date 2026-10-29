"""GET-only Lead Ads HTTP boundary; retries belong to the durable inbox."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib.parse import urlsplit

import httpx

FIELDS = "id,created_time,ad_id,form_id,field_data"
TIMEOUT = httpx.Timeout(connect=5, read=10, write=10, pool=5)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class LeadAdsError(Exception):
    """Only fixed codes cross the HTTP boundary; never attach external values."""

    def __init__(self, code: str, *, transient: bool = False, retry_after: int = 0):
        super().__init__(code)
        self.code = code
        self.transient = transient
        self.retry_after = min(max(retry_after, 0), 3600)


def meta_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,64}", value) is None:
        raise LeadAdsError("invalid_payload")
    return value


class MetaLeadAdsClient:
    def __init__(self, http_client: httpx.Client, *, token: str, api_version: str,
                 max_pages: int = 100, page_size: int = 100):
        if not token.strip() or re.fullmatch(r"v[0-9]+\.[0-9]+", api_version) is None:
            raise LeadAdsError("configuration_invalid")
        if not 1 <= max_pages <= 1000 or not 1 <= page_size <= 1000:
            raise LeadAdsError("configuration_invalid")
        self._http = http_client
        self._token = token
        self._base = f"https://graph.facebook.com/{api_version}"
        self._max_pages = max_pages
        self._page_size = page_size

    def _get(self, path: str, params: dict[str, str | int]) -> dict:
        try:
            with self._http.stream("GET", self._base + path, params=params,
                                   headers={"Authorization": f"Bearer {self._token}"},
                                   follow_redirects=False, timeout=TIMEOUT) as response:
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    raw_delay = response.headers.get("Retry-After", "")
                    delay = int(raw_delay) if re.fullmatch(r"[0-9]{1,8}", raw_delay) else 0
                    raise LeadAdsError("graph_temporary", transient=True, retry_after=delay)
                if response.status_code in {401, 403}:
                    raise LeadAdsError("graph_access_denied")
                if response.status_code == 404:
                    raise LeadAdsError("graph_not_found")
                if response.status_code != 200:
                    raise LeadAdsError("graph_rejected")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise LeadAdsError("invalid_payload")
                    body.extend(chunk)
        except httpx.TransportError:
            raise LeadAdsError("graph_transport", transient=True) from None
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise LeadAdsError("invalid_payload") from None
        if not isinstance(payload, dict):
            raise LeadAdsError("invalid_payload")
        if "error" in payload:
            raise LeadAdsError("graph_rejected")
        return payload

    def get_lead(self, lead_id: str) -> dict:
        expected = meta_id(lead_id)
        result = self._get(f"/{expected}", {"fields": FIELDS})
        if meta_id(result.get("id")) != expected:
            raise LeadAdsError("source_mismatch")
        return result

    def iter_form_lead_pages(self, form_id: str) -> Iterator[list[dict]]:
        path = f"/{meta_id(form_id)}/leads"
        params: dict[str, str | int] = {"fields": FIELDS, "limit": self._page_size}
        seen: set[str] = set()
        for _ in range(self._max_pages):
            payload = self._get(path, params)
            rows = payload.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise LeadAdsError("invalid_payload")
            paging = payload.get("paging", {})
            if not isinstance(paging, dict):
                raise LeadAdsError("invalid_pagination")
            next_url = paging.get("next")
            if next_url is None:
                yield rows
                return
            if not isinstance(next_url, str):
                raise LeadAdsError("invalid_pagination")
            try:
                url = urlsplit(next_url)
                trusted = (url.scheme == "https" and url.hostname == "graph.facebook.com"
                           and url.port in (None, 443) and url.username is None
                           and url.password is None and not url.fragment
                           and url.path == urlsplit(self._base + path).path)
            except ValueError:
                trusted = False
            cursors = paging.get("cursors", {})
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not trusted or not isinstance(after, str) or not after or len(after) > 4096:
                raise LeadAdsError("invalid_pagination")
            if after in seen:
                raise LeadAdsError("invalid_pagination")
            seen.add(after)
            yield rows
            params["after"] = after
        raise LeadAdsError("page_limit")
