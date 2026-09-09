"""Concrete filters shared by the KPI summary and report data."""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from meta_kpi_calc.db.models import Campaign, CampaignBrand


@dataclass(frozen=True)
class ReportFilters:
    """The one inclusive campaign scope used by dashboard and exports."""

    date_start: date
    date_stop: date
    brand: CampaignBrand | None = None
    campaign_id: int | None = None
    course: str | None = None
    effective_status: str | None = None

    def campaign_predicates(self) -> tuple[ColumnElement[bool], ...]:
        predicates: list[ColumnElement[bool]] = []
        if self.campaign_id is not None:
            predicates.append(Campaign.id == self.campaign_id)
        if self.brand is not None:
            predicates.append(Campaign.brand == self.brand)
        if self.course is not None:
            predicates.append(Campaign.course == self.course)
        if self.effective_status is not None:
            predicates.append(Campaign.effective_status == self.effective_status)
        if self.date_start is not None and self.date_stop is not None:
            date_start_dt = datetime.combine(self.date_start, time.min, tzinfo=timezone.utc)
            date_stop_dt = datetime.combine(self.date_stop, time.max, tzinfo=timezone.utc)
            predicates.append(
                or_(
                    Campaign.start_time.is_(None),
                    Campaign.start_time <= date_stop_dt,
                )
            )
            predicates.append(
                or_(
                    Campaign.stop_time.is_(None),
                    Campaign.stop_time >= date_start_dt,
                )
            )
        return tuple(predicates)
