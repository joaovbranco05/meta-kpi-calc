"""Aggregate router for all Analytics REST endpoints.

Each domain is implemented in its own module:
- meta_sync.py  : /meta/connection, /meta/sync, /meta/sync/status
- campaigns.py  : /campaigns, /campaigns/{id}/classification, /campaigns/{id}/insights
- enrollments.py: /enrollments, /commercial-closures
- dashboard.py  : /dashboard/*, /export
"""

from fastapi import APIRouter

from meta_kpi_calc.api.routes.campaigns import router as _campaigns_router
from meta_kpi_calc.api.routes.dashboard import router as _dashboard_router
from meta_kpi_calc.api.routes.enrollments import router as _enrollments_router
from meta_kpi_calc.api.routes.meta_sync import router as _meta_sync_router

router = APIRouter(prefix="/api")
router.include_router(_meta_sync_router)
router.include_router(_campaigns_router)
router.include_router(_enrollments_router)
router.include_router(_dashboard_router)
