"""Authorization contracts using synthetic identities and disposable databases."""

import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.auth.dependencies import SESSION_COOKIE
from meta_kpi_calc.auth.models import AdminAudit, AppSession, AppUser
from meta_kpi_calc.crm.ingestion import LeadSubmission, ingest_lead
from meta_kpi_calc.crm.models import LeadActivity


def _account(session, role, subject):
    user = AppUser(role=role, issuer="https://issuer.invalid", subject=subject, active=True)
    session.add(user)
    session.flush()
    token = secrets.token_urlsafe(32)
    session.add(
        AppSession(
            user_id=user.id,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.flush()
    return user.id, token


def _login(client, account):
    client.cookies.set(SESSION_COOKIE, account[1])


def test_permissions_and_audit(migrated_database):
    settings, database = migrated_database
    with database.session_factory.begin() as session:
        admin = _account(session, "admin", "admin")
        operator = _account(session, "usuario", "operator")
        other = _account(session, "usuario", "other")
        ids = []
        for index, owner in enumerate((operator[0], other[0], None)):
            lead = ingest_lead(
                session, LeadSubmission(str(index + 100), {"full_name": "Synthetic"})
            ).lead
            lead.assigned_user_id = owner
            ids.append(lead.id)

    with TestClient(create_app(settings)) as client:
        crm = "/api/crm/leads"
        users = "/api/admin/users"
        forged = {"X-User-Id": str(admin[0]), "X-Role": "admin", "Authorization": "Bearer admin"}
        for path in (crm, users, "/api/campaigns", "/api/export"):
            assert client.get(path, headers=forged).status_code == 401
        assert client.get("/docs").status_code == 404

        _login(client, operator)
        listed = client.get(crm, params={"query": "Synthetic", "limit": 1}).json()
        assert listed["total"] == 1
        assert [row["id"] for row in listed["items"]] == ids[:1]
        assert client.get(crm, params={"query": "101"}).json()["total"] == 0
        assert client.get(crm, params={"offset": 1}).json()["total"] == 1
        assert client.get(crm, params={"unassigned": True}).status_code == 403

        for lead_id in ids[1:]:
            assert client.get(f"{crm}/{lead_id}").status_code == 404
            assert client.get(f"{crm}/{lead_id}/activities").status_code == 404
            assert (
                client.patch(
                    f"{crm}/{lead_id}/status", json={"commercial_status": "LOST"}
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"{crm}/{lead_id}/activities", json={"activity_type": "NOTE", "note": "Test"}
                ).status_code
                == 404
            )

        path = f"{crm}/{ids[0]}"
        assert (
            client.patch(f"{path}/assignment", json={"assigned_user_id": other[0]}).status_code
            == 403
        )
        for endpoint in (users, "/api/campaigns", "/api/enrollments", "/api/export"):
            assert client.get(endpoint, headers=forged).status_code == 403
        assert client.post("/api/meta/sync", json={}).status_code == 403
        assert (
            client.post(
                users, json={"issuer": "test", "subject": "forged", "role": "admin"}
            ).status_code
            == 403
        )

        status_body = {"commercial_status": "CONTACTED"}
        assert (
            client.patch(
                f"{path}/status", json=status_body | {"actor_id": str(admin[0])}
            ).status_code
            == 422
        )
        assert client.patch(f"{path}/status", json=status_body).status_code == 200
        note = {"activity_type": "NOTE", "note": "Synthetic note"}
        assert (
            client.post(f"{path}/activities", json=note | {"actor_user_id": admin[0]}).status_code
            == 422
        )
        assert client.post(f"{path}/activities", json=note).json()["actor_user_id"] == operator[0]
        history = client.get(f"{path}/activities").json()
        assert [row["actor_user_id"] for row in history] == [None, operator[0], operator[0]]

        _login(client, admin)
        assert client.get("/api/campaigns").status_code == 200
        assert client.get(crm).json()["total"] == 3
        assert client.get(crm, params={"unassigned": True}).json()["total"] == 1
        assert client.get(users).status_code == 200
        assert (
            client.patch(f"{path}/assignment", json={"assigned_user_id": other[0]}).status_code
            == 200
        )
        for change in ({"active": False, "role": "admin"}, {"active": True, "role": "usuario"}):
            assert client.put(f"{users}/{admin[0]}", json=change).status_code == 409
        created = {"issuer": "https://issuer.invalid", "subject": "new", "role": "usuario"}
        assert client.post(users, json=created).status_code == 201
        assert client.post(users, json=created).status_code == 409

        _login(client, operator)
        assert client.get(path).status_code == 404
        _login(client, admin)
        assert (
            client.put(
                f"{users}/{operator[0]}", json={"role": "usuario", "active": False}
            ).status_code
            == 200
        )
        _login(client, operator)
        assert client.get(crm).status_code == 401
        _login(client, admin)
        assert (
            client.put(
                f"{users}/{operator[0]}", json={"role": "usuario", "active": True}
            ).status_code
            == 200
        )
        _login(client, operator)
        assert client.get(crm).status_code == 401

    with database.session_factory() as session:
        assert session.scalars(select(AdminAudit.action).order_by(AdminAudit.id)).all() == [
            "lead_assigned",
            "user_created",
            "user_updated",
            "user_updated",
        ]
        assert session.scalar(select(func.count()).select_from(LeadActivity)) == 5


def test_expired_and_inactive_sessions(migrated_database):
    settings, database = migrated_database
    with database.session_factory.begin() as session:
        inactive = _account(session, "admin", "inactive")
        expired = _account(session, "admin", "expired")
        session.get(AppUser, inactive[0]).active = False
        digest = hashlib.sha256(expired[1].encode()).hexdigest()
        session.get(AppSession, digest).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with TestClient(create_app(settings)) as client:
        for account in (inactive, expired):
            _login(client, account)
            assert client.get("/api/crm/leads").status_code == 401


def test_concurrent_admin_deactivation_keeps_one_active(migrated_database):
    settings, database = migrated_database
    with database.session_factory.begin() as session:
        admins = [_account(session, "admin", str(index)) for index in range(2)]
    barrier = Barrier(2)

    def deactivate(account):
        with TestClient(create_app(settings)) as client:
            _login(client, account)
            barrier.wait(timeout=10)
            return client.put(
                f"/api/admin/users/{account[0]}", json={"role": "admin", "active": False}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(deactivate, admins)) == [200, 409]
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(AppUser).where(AppUser.active.is_(True))
            )
            == 1
        )


def test_profile_changes_revoke_all_existing_sessions(migrated_database):
    settings, database = migrated_database
    with database.session_factory.begin() as session:
        admin = _account(session, "admin", "admin")
        user = _account(session, "usuario", "target")

    def new_session():
        token = secrets.token_urlsafe(32)
        with database.session_factory.begin() as session:
            session.add(
                AppSession(
                    user_id=user[0],
                    token_digest=hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        return user[0], token

    previous_sessions = [user, new_session()]
    with TestClient(create_app(settings)) as client:
        endpoint = f"/api/admin/users/{user[0]}"
        for role, active, expected in (
            ("admin", True, 200),
            ("usuario", True, 403),
            ("usuario", False, 401),
            ("usuario", True, 403),
        ):
            _login(client, admin)
            assert client.put(endpoint, json={"role": role, "active": active}).status_code == 200
            for account in previous_sessions:
                _login(client, account)
                assert client.get("/api/campaigns").status_code == 401
            # A fresh cookie represents reauthentication; only the fixture issues it.
            if active:
                fresh = new_session()
                previous_sessions.append(fresh)
                _login(client, fresh)
                assert client.get("/api/campaigns").status_code == expected

    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AdminAudit)) == 4


def test_administrative_audit_failure_rolls_back(migrated_database):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    from meta_kpi_calc.crm.models import Lead

    settings, database = migrated_database
    with database.session_factory.begin() as session:
        admin = _account(session, "admin", "admin")
        target = _account(session, "usuario", "target")
        lead_id = ingest_lead(session, LeadSubmission("123", {})).lead.id

    def fail_audit(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic audit failure")

    event.listen(AdminAudit, "before_insert", fail_audit)
    try:
        with TestClient(create_app(settings)) as client:
            _login(client, admin)
            path = f"/api/crm/leads/{lead_id}/assignment"
            assert (
                client.patch(
                    path, json={"assigned_user_id": target[0], "actor_id": target[0]}
                ).status_code
                == 422
            )
            assert client.patch(path, json={"assigned_user_id": target[0]}).status_code == 503
            assert (
                client.put(
                    f"/api/admin/users/{target[0]}", json={"role": "admin", "active": False}
                ).status_code
                == 503
            )
            assert (
                client.post(
                    "/api/admin/users", json={"issuer": "test", "subject": "new", "role": "usuario"}
                ).status_code
                == 503
            )
            _login(client, target)
            assert client.get("/api/crm/leads").status_code == 200
    finally:
        event.remove(AdminAudit, "before_insert", fail_audit)
    with database.session_factory() as session:
        assert session.get(Lead, lead_id).assigned_user_id is None
        assert session.get(AppUser, target[0]).role == "usuario"
        assert session.scalar(select(func.count()).select_from(AppUser)) == 2
        assert session.scalar(select(func.count()).select_from(AdminAudit)) == 0
