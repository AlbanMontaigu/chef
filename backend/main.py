"""Single FastAPI app: the API and the static frontend, same origin.

One process, one container, no CORS -- same shape as flip7. `/admin` is
served as a separate page rather than a route of the public SPA so that a
visitor never downloads the back-office at all.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

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


class FrontendFiles(StaticFiles):
    """Static frontend with revalidation forced on code, caching kept on media.

    There is no build step here, so `admin.js` keeps its name from one version
    to the next and a browser has no way to know it changed. Left to default
    heuristics it serves the previous module happily -- which is how a deploy
    can land on the server and stay invisible in the browser, mixing a new
    stylesheet with old code. `no-cache` does not mean "never cache": the file
    is still stored, the browser just has to revalidate, and the ETag turns
    that into a cheap 304. Images keep a long cache: their content changes only
    by changing filename.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        if path.rsplit(".", 1)[-1].lower() in ("html", "js", "css", "json", "txt"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=604800"
        return response


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
def build() -> Response:
    """Build stamp. Absent in a dev checkout -- the image creates it -- so the
    missing case answers empty rather than erroring on a cosmetic file."""
    path = os.path.join(FRONTEND, "build.txt")
    headers = {"Cache-Control": "no-cache"}
    if not os.path.exists(path):
        return PlainTextResponse("", headers=headers)
    return FileResponse(path, media_type="text/plain", headers=headers)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(
        os.path.join(FRONTEND, "admin", "index.html"),
        headers={"Cache-Control": "no-cache"},
    )


# Mounted last: it owns every path the API did not claim.
app.mount("/", FrontendFiles(directory=FRONTEND, html=True), name="frontend")
