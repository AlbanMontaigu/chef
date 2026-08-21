"""Back-office API. Everything below /api/admin requires the session cookie."""

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .. import auth, billing, config, content, db, diets, mailer

log = logging.getLogger("chef.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

SERVICES = ("midi", "soir")


# Partagée avec le routeur de facturation, définie dans auth.py.
require_admin = auth.require_admin


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.get("/session")
def session_state(request: Request) -> dict:
    return {
        "authenticated": auth.is_authenticated(request),
        "configured": auth.configured(),
        "mail_enabled": config.mail_enabled(),
    }


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    ip = auth.client_ip(request)
    if not auth.configured():
        # Refusing is the only safe answer: an unset password must never mean
        # "no password", or the back-office would be open to the internet.
        log.error("login attempt but ADMIN_PASSWORD is unset")
        raise HTTPException(503, "Back-office non configuré (ADMIN_PASSWORD manquant).")

    remaining = auth.locked_out(ip)
    if remaining:
        raise HTTPException(429, f"Trop de tentatives. Réessaie dans {remaining // 60 + 1} min.")

    if not auth.check_password(payload.password):
        auth.record_failure(ip)
        log.warning("failed admin login from %s", ip)
        raise HTTPException(401, "Mot de passe incorrect.")

    auth.clear_failures(ip)
    response.set_cookie(
        config.SESSION_COOKIE,
        auth.issue_token(),
        max_age=config.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=auth.secure_cookies(),
        path="/",
    )
    log.info("admin login from %s", ip)
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"authenticated": False}


# --- Slots -------------------------------------------------------------

class SlotIn(BaseModel):
    date: str
    service: str
    note: str = Field(default="", max_length=200)

    @field_validator("date")
    @classmethod
    def _date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("date invalide (attendu YYYY-MM-DD)")
        return value

    @field_validator("service")
    @classmethod
    def _service(cls, value: str) -> str:
        if value not in SERVICES:
            raise ValueError(f"service invalide (attendu {' ou '.join(SERVICES)})")
        return value


class SlotsIn(BaseModel):
    items: list[SlotIn] = Field(min_length=1, max_length=200)


@router.get("/slots", dependencies=[Depends(require_admin)])
def list_slots(start: str = "", end: str = "") -> dict:
    """Every slot in the window, with its booking if it has one."""
    today = datetime.now(config.TZ).date()
    start = start or today.replace(day=1).isoformat()
    end = end or (today + timedelta(days=120)).isoformat()
    with db.cursor() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.date, s.service, s.note,
                   b.id AS booking_id, b.ref, b.name, b.guests
            FROM slots s
            LEFT JOIN bookings b ON b.slot_id = s.id AND b.status = 'confirmed'
            WHERE s.date >= ? AND s.date <= ?
            ORDER BY s.date, s.service
            """,
            (start, end),
        ).fetchall()
    lead = int(content.load()["booking"].get("lead_days", 3))
    return {
        "start": start,
        "end": end,
        # Anything before this date is open but unbookable: the public
        # calendar filters it out, so the back-office has to flag it.
        "first_bookable": (today + timedelta(days=lead)).isoformat(),
        "slots": [dict(r) for r in rows],
    }


@router.post("/slots", dependencies=[Depends(require_admin)], status_code=201)
def open_slots(payload: SlotsIn) -> dict:
    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    created = 0
    with db.transaction() as conn:
        for item in payload.items:
            cur = conn.execute(
                """
                INSERT INTO slots (date, service, note, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (date, service) DO NOTHING
                """,
                (item.date, item.service, item.note, now),
            )
            created += cur.rowcount
    log.info("opened %d slot(s)", created)
    return {"created": created, "requested": len(payload.items)}


@router.delete("/slots/{slot_id}", dependencies=[Depends(require_admin)])
def close_slot(slot_id: int) -> dict:
    """Close an unbooked slot. A booked one must be cancelled first --
    deleting it here would cascade the booking away without telling anyone."""
    with db.transaction() as conn:
        booked = conn.execute(
            "SELECT ref FROM bookings WHERE slot_id = ? AND status = 'confirmed'", (slot_id,)
        ).fetchone()
        if booked:
            raise HTTPException(
                409, f"Créneau réservé ({booked['ref']}). Annule la réservation d'abord."
            )
        cur = conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Créneau introuvable.")
    return {"closed": slot_id}


# --- Bookings ----------------------------------------------------------

@router.get("/bookings", dependencies=[Depends(require_admin)])
def list_bookings(status: str = "confirmed", limit: int = 200) -> dict:
    limit = max(1, min(limit, 500))
    where, params = "", []
    if status != "all":
        where = "WHERE b.status = ?"
        params.append(status)
    with db.cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT b.*, s.date, s.service,
                   (SELECT COALESCE(SUM(p.amount_cents), 0) FROM payments p
                     WHERE p.booking_id = b.id) AS paid_cents,
                   i.id AS invoice_id, i.number AS invoice_number,
                   i.status AS invoice_status, i.total_cents AS invoice_total_cents,
                   i.mail_status AS invoice_mail_status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN invoices i ON i.booking_id = b.id AND i.status <> 'cancelled'
            {where}
            ORDER BY s.date ASC, s.service ASC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        bookings = [_with_billing(conn, dict(r)) for r in rows]
    # Les régimes sont dépliés ici plutôt que dans le front : le libellé et le
    # caractère « allergie » viennent du catalogue serveur, qui fait foi.
    for booking in bookings:
        booking["diets_detail"] = diets.describe(booking.get("diets"))
    # Anything whose mail did not go out is an open loop the chef must know
    # about: the client may be expecting a confirmation that never arrived.
    issues = [b for b in bookings if "failed" in (b["mail_client"], b["mail_chef"])
              or "disabled" in (b["mail_client"], b["mail_chef"])]
    return {"bookings": bookings, "mail_issues": len(issues)}


@router.get("/formula-options", dependencies=[Depends(require_admin)])
def formula_options() -> dict:
    """Formules actives, pour les listes déroulantes du back-office."""
    with db.cursor() as conn:
        return {"formulas": [
            {"id": r["id"], "slug": r["slug"], "name": r["name"],
             "pricing": r["pricing"], "price_cents": r["price_cents"]}
            for r in billing.formula_rows(conn)
        ]}


def _with_billing(conn, booking: dict) -> dict:
    """Ajoute l'état de facturation à une réservation listée.

    Le montant dû n'existe qu'à partir d'une facture émise : un brouillon est
    une intention, pas une créance, et l'afficher comme un impayé enverrait le
    chef relancer un client qui n'a rien reçu.
    """
    paid = int(booking.pop("paid_cents", 0) or 0)
    status = booking.get("invoice_status")
    total = None
    if status == "draft":
        total = billing.lines_total(billing.lines_of(conn, booking["invoice_id"]))
    elif status == "issued":
        total = int(booking["invoice_total_cents"] or 0)
    due = total if status == "issued" else None
    booking["invoice_total_cents"] = total
    booking["billing"] = {
        "paid_cents": paid,
        "due_cents": due,
        "balance_cents": None if due is None else due - paid,
        "state": billing.payment_state(due, paid),
    }
    return booking


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/bookings/{booking_id}/cancel", dependencies=[Depends(require_admin)])
def cancel_booking(booking_id: int, payload: CancelIn, background: BackgroundTasks) -> dict:
    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    with db.transaction() as conn:
        row = conn.execute(
            """
            SELECT b.*, s.date, s.service FROM bookings b
            JOIN slots s ON s.id = b.slot_id WHERE b.id = ?
            """,
            (booking_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Réservation introuvable.")
        if row["status"] != "confirmed":
            raise HTTPException(409, "Cette réservation est déjà annulée.")
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (now, booking_id),
        )
    booking = dict(row)
    log.info("booking %s cancelled", booking["ref"])
    # Cancelling frees the slot: it goes back on the public calendar.
    background.add_task(mailer.send_cancellation_mail, booking, content.site_name(), payload.reason)
    return {"cancelled": booking["ref"]}


@router.post("/bookings/{booking_id}/resend", dependencies=[Depends(require_admin)])
def resend_mails(booking_id: int, background: BackgroundTasks) -> dict:
    """Retry the confirmation pair after a mail failure was fixed."""
    if not config.mail_enabled():
        raise HTTPException(503, "Envoi d'e-mails désactivé (SMTP_HOST non configuré).")
    with db.cursor() as conn:
        row = conn.execute(
            """
            SELECT b.*, s.date, s.service FROM bookings b
            JOIN slots s ON s.id = b.slot_id WHERE b.id = ?
            """,
            (booking_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Réservation introuvable.")
    if row["status"] != "confirmed":
        # Resending here would mail a confirmation for a booking that no
        # longer exists -- the client would show up.
        raise HTTPException(409, "Réservation annulée : rien à renvoyer.")
    background.add_task(mailer.send_booking_mails, dict(row), content.site_name())
    return {"queued": row["ref"]}
