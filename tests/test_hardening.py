import logging

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import Campaign, CampaignInsight, SyncRun
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.services.demo_seed import DEMO_START_DATE, seed_demo

TOKEN = "stage-eight-token-sentinel"


def _real_settings(base: Settings) -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=False,
        database_url=base.demo_database_url,
        demo_database_url=base.database_url,
        meta_access_token=SecretStr(TOKEN),
        meta_ad_account_id="123",
    )


def test_mocked_external_token_never_reaches_public_or_persisted_outputs(
    migrated_database: tuple[Settings, Database],
    caplog,
) -> None:
    base, database = migrated_database

    def meta_response(request: httpx.Request) -> httpx.Response:
        headers = {"x-business-use-case-usage": f'{{"secret":"{TOKEN}"}}'}
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "data": [
                        {
                            "id": "stage-8-campaign",
                            "name": "Stage 8 campaign",
                            "status": "ACTIVE",
                            "effective_status": "ACTIVE",
                            TOKEN: TOKEN,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers=headers,
            json={
                "data": [
                    {
                        "account_id": "123",
                        "account_name": "Test account",
                        "campaign_id": "stage-8-campaign",
                        "campaign_name": "Stage 8 campaign",
                        "date_start": "2026-09-01",
                        "date_stop": "2026-09-01",
                        "spend": "10.00",
                        "reach": "100",
                        "impressions": "120",
                        "clicks": "10",
                        "inline_link_clicks": "8",
                        "actions": [
                            {
                                "action_type": "lead",
                                "value": "2",
                                "private": TOKEN,
                            }
                        ],
                        TOKEN: TOKEN,
                    }
                ]
            },
        )

    external = httpx.Client(transport=httpx.MockTransport(meta_response))
    try:
        caplog.set_level(logging.INFO)
        app = create_app(_real_settings(base), http_client=external)
        with TestClient(app) as client:
            synced = client.post(
                "/api/meta/sync",
                json={"date_start": "2026-09-01", "date_stop": "2026-09-01"},
            )
            campaigns = client.get("/api/campaigns")
            exported = client.get(
                "/api/export",
                params={
                    "date_start": "2026-09-01",
                    "date_stop": "2026-09-01",
                    "format": "csv",
                    "dataset": "performance",
                },
            )
    finally:
        external.close()

    assert synced.status_code == 200
    assert campaigns.status_code == 200
    assert exported.status_code == 200
    assert TOKEN not in synced.text
    assert TOKEN not in campaigns.text
    assert TOKEN.encode() not in exported.content
    assert TOKEN not in caplog.text
    with database.session_factory() as session:
        campaign = session.scalar(select(Campaign))
        insight = session.scalar(select(CampaignInsight))
        sync_run = session.scalar(select(SyncRun))
        persisted = (
            campaign.meta_campaign_id,
            campaign.name,
            insight.raw_actions,
            insight.raw_cost_per_action_type,
            insight.raw_response,
            sync_run.error_message,
        )
    assert TOKEN not in repr(persisted)


def test_demo_smoke_covers_api_and_export_without_credentials(
    migrated_database: tuple[Settings, Database],
) -> None:
    settings, _database = migrated_database
    assert settings.meta_access_token is None
    assert seed_demo(settings) == {
        "campaigns": 3,
        "insights": 21,
        "enrollments": 3,
    }
    day = DEMO_START_DATE.isoformat()

    with TestClient(create_app(settings)) as client:
        responses = [
            client.get("/health"),
            client.get("/api/meta/connection"),
            client.get("/api/campaigns"),
            client.get(
                "/api/dashboard/summary",
                params={"date_start": day, "date_stop": day},
            ),
            client.get(
                "/api/export",
                params={
                    "date_start": day,
                    "date_stop": day,
                    "format": "csv",
                    "dataset": "performance",
                },
            ),
        ]

    assert [response.status_code for response in responses] == [200] * 5
    assert responses[0].json()["mode"] == "demo"
    assert responses[1].json() == {
        "mode": "demo",
        "configured": False,
        "connected": False,
        "account": None,
    }
    assert responses[2].json()["total"] == 3
    assert responses[3].json()["totals"]["spend"] != "0.00"
    assert responses[4].content.startswith(b"\xef\xbb\xbf")
