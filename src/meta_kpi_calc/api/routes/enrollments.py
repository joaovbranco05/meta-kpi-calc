"""Enrollment records and commercial closure endpoints."""

from datetime import date

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.schemas import (
    CommercialClosureResponse,
    CommercialClosureWrite,
    EnrollmentResponse,
    EnrollmentWrite,
    Page,
)
from meta_kpi_calc.db.models import Campaign, CampaignBrand, CommercialClosure, EnrollmentRecord
from meta_kpi_calc.api.routes._shared import (
    SessionDependency,
    Offset,
    Limit,
    _error,
    _enrollment_response,
    _commercial_closure_response,
    _validate_period,
)

router = APIRouter()


def _enrollment_duplicate(
    session,
    payload: EnrollmentWrite,
    *,
    excluding_id: int | None = None,
) -> int | None:
    query = select(EnrollmentRecord.id).where(
        EnrollmentRecord.campaign_id == payload.campaign_id,
        EnrollmentRecord.reference_date == payload.reference_date,
        EnrollmentRecord.course == payload.course,
    )
    if excluding_id is not None:
        query = query.where(EnrollmentRecord.id != excluding_id)
    return session.scalar(query)


def _apply_enrollment(enrollment: EnrollmentRecord, payload: EnrollmentWrite) -> None:
    for field, value in payload.model_dump().items():
        setattr(enrollment, field, value)


@router.post(
    "/enrollments", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED
)
def create_enrollment(
    payload: EnrollmentWrite, session: SessionDependency
) -> EnrollmentResponse:
    try:
        with session.begin():
            campaign = session.get(Campaign, payload.campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            duplicate_id = _enrollment_duplicate(session, payload)
            if duplicate_id is not None:
                _error(
                    409,
                    "duplicate_enrollment",
                    "Enrollment already exists; use PUT to update it.",
                    record_id=duplicate_id,
                )
            enrollment = EnrollmentRecord(**payload.model_dump())
            session.add(enrollment)
            session.flush()
            response = _enrollment_response(enrollment, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        _error(
            409,
            "duplicate_enrollment",
            "Enrollment already exists; use PUT to update it.",
        )


@router.get("/enrollments", response_model=Page[EnrollmentResponse])
def list_enrollments(
    session: SessionDependency,
    campaign_id: int | None = None,
    brand: CampaignBrand | None = None,
    course: str | None = None,
    effective_status: str | None = None,
    date_start: date | None = None,
    date_stop: date | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[EnrollmentResponse]:
    _validate_period(date_start, date_stop)
    if course is not None:
        course = course.strip()
        if not course:
            _error(422, "validation_error", "Request validation failed.")
    if effective_status is not None:
        effective_status = effective_status.strip()
        if not effective_status:
            _error(422, "validation_error", "Request validation failed.")
    filters = []
    if campaign_id is not None:
        filters.append(EnrollmentRecord.campaign_id == campaign_id)
    if brand is not None:
        filters.append(Campaign.brand == brand)
    if course is not None:
        filters.append(EnrollmentRecord.course == course)
    if effective_status is not None:
        filters.append(Campaign.effective_status == effective_status)
    if date_start is not None and date_stop is not None:
        filters.append(EnrollmentRecord.reference_date.between(date_start, date_stop))
    base = select(EnrollmentRecord, Campaign.meta_campaign_id).join(
        Campaign, Campaign.id == EnrollmentRecord.campaign_id
    ).where(*filters)
    total = session.scalar(
        select(func.count(EnrollmentRecord.id))
        .join(Campaign, Campaign.id == EnrollmentRecord.campaign_id)
        .where(*filters)
    ) or 0
    rows = session.execute(
        base.order_by(EnrollmentRecord.id).offset(offset).limit(limit)
    ).all()
    return Page(
        items=[_enrollment_response(item, meta_id) for item, meta_id in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.put(
    "/enrollments/{record_id}", response_model=EnrollmentResponse
)
def replace_enrollment(
    record_id: int,
    payload: EnrollmentWrite,
    session: SessionDependency,
) -> EnrollmentResponse:
    try:
        with session.begin():
            enrollment = session.get(EnrollmentRecord, record_id)
            if enrollment is None:
                _error(404, "enrollment_not_found", "Enrollment was not found.")
            campaign = session.get(Campaign, payload.campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            duplicate_id = _enrollment_duplicate(
                session, payload, excluding_id=record_id
            )
            if duplicate_id is not None:
                _error(
                    409,
                    "duplicate_enrollment",
                    "Enrollment already exists.",
                    record_id=duplicate_id,
                )
            _apply_enrollment(enrollment, payload)
            session.flush()
            response = _enrollment_response(enrollment, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        _error(409, "duplicate_enrollment", "Enrollment already exists.")


@router.put(
    "/commercial-closures/{campaign_id}/{reference_date}",
    response_model=CommercialClosureResponse,
)
def replace_commercial_closure(
    campaign_id: int,
    reference_date: date,
    payload: CommercialClosureWrite,
    session: SessionDependency,
) -> CommercialClosureResponse:
    try:
        with session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            closure = session.scalar(
                select(CommercialClosure).where(
                    CommercialClosure.campaign_id == campaign_id,
                    CommercialClosure.reference_date == reference_date,
                )
            )
            if closure is None:
                closure = CommercialClosure(
                    campaign_id=campaign_id,
                    reference_date=reference_date,
                    status=payload.status,
                )
                session.add(closure)
            else:
                closure.status = payload.status
            session.flush()
            response = _commercial_closure_response(closure, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        closure = session.scalar(
            select(CommercialClosure).where(
                CommercialClosure.campaign_id == campaign_id,
                CommercialClosure.reference_date == reference_date,
            )
        )
        if closure is None:
            raise
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise
        return _commercial_closure_response(closure, campaign.meta_campaign_id)
