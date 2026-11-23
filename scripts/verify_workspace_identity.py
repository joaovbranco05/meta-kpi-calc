"""One-shot identity receipt on a private socket, separate from the CRM API."""

import argparse
import json
import os
import stat
from getpass import getpass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.engine import make_url

from meta_kpi_calc.auth.dependencies import SessionDependency
from meta_kpi_calc.auth.routes import PRIVATE_HEADERS, login, verify_callback
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import Database


def create_verifier(settings, email, receipt, *, transport=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.state.settings = settings
    app.state.database = Database(settings)
    app.state.oidc_transport = transport
    app.add_api_route("/auth/login", login, methods=["GET"])

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers.update(PRIVATE_HEADERS)
        return response

    @app.get("/auth/callback")
    def callback(request: Request, session: SessionDependency):
        if receipt.exists():
            raise HTTPException(409, "Verification already completed")
        _, issuer, subject, _, _ = verify_callback(request, session, expected_email=email)
        try:
            fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise HTTPException(409, "Verification already completed") from None
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"iss": issuer, "sub": subject}, output)
            output.write("\n")
        session.commit()
        return PlainTextResponse("Identity verified. Close this tab.")

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Private rctec-4c1 sandbox")
    parser.add_argument("receipt", choices=("admin", "usuario"))
    args = parser.parse_args()
    directory = args.directory.resolve()
    if (
        directory.parent != Path("/tmp").resolve()
        or not directory.name.startswith("rctec-4c1.")
        or directory.stat().st_uid != os.getuid()
        or stat.S_IMODE(directory.stat().st_mode) != 0o700
    ):
        parser.error("Private homologation directory required")
    try:
        settings = Settings(_env_file=directory / "settings.env")
        url = make_url(settings.active_database_url)
        if (
            url.get_backend_name() != "postgresql"
            or url.database != "rctec_hml"
            or url.username != "rctec_hml_runtime"
            or Path(url.query.get("host", "")).resolve() != directory
            or url.query.get("port") != "55489"
            or str(settings.oidc_public_origin) != "https://localhost:18501/"
        ):
            parser.error("Only the homologation database and exact HTTPS origin are allowed")
    except (TypeError, ValueError):
        parser.error("Invalid homologation settings")
    email = getpass("Expected Workspace address (not echoed): ").strip()
    if "@" not in email:
        parser.error("Workspace address required")
    app = create_verifier(settings, email, directory / f"identity-{args.receipt}.json")
    uvicorn.run(app, uds=str(directory / "verifier.sock"), access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
