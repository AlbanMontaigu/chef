"""Single FastAPI app: the API and the static frontend, same origin.

One process, one container, no CORS -- same shape as flip7. `/admin` is
served as a separate page rather than a route of the public SPA so that a
visitor never downloads the back-office at all.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, content, db
from .routers import admin, public

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("chef")

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    site = content.load(force=True)
    log.info("started - site=%r mail=%s admin=%s",
             site.get("name"), config.mail_enabled(), bool(config.ADMIN_PASSWORD))
    # Both of these are survivable but leave the site half-functional, so they
    # are shouted at startup rather than discovered at the first booking.
    if not config.ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD unset - the back-office cannot be used")
    if not config.mail_enabled():
        log.warning("SMTP_HOST unset - booking confirmations will NOT be sent")
    yield


app = FastAPI(title="Chef a domicile", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.exception_handler(500)
def on_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Erreur interne."}, status_code=500)


app.include_router(public.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    """Liveness for Coolify and for the reverse-monitor: it touches the
    database, so a broken volume shows up here instead of at booking time."""
    with db.cursor() as conn:
        slots = conn.execute("SELECT COUNT(*) AS n FROM slots").fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE status = 'confirmed'"
        ).fetchone()["n"]
    return {
        "ok": True,
        "slots": slots,
        "bookings": pending,
        "mail_enabled": config.mail_enabled(),
        "admin_configured": bool(config.ADMIN_PASSWORD),
    }


@app.get("/build.txt", include_in_schema=False)
def build() -> FileResponse:
    path = os.path.join(FRONTEND, "build.txt")
    return FileResponse(path if os.path.exists(path) else os.devnull, media_type="text/plain")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND, "admin", "index.html"))


# Mounted last: it owns every path the API did not claim.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
