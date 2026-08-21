"""Public API: site copy, open slots, and creating a booking."""

import logging
import re
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from .. import billing, config, content, db, mailer

log = logging.getLogger("chef.public")

router = APIRouter(prefix="/api", tags=["public"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
REF_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY3479"  # no look-alikes: read over the phone


def today() -> date:
    return datetime.now(config.TZ).date()


class BookingIn(BaseModel):
    slot_id: int
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=160)
    phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=300)
    guests: int = Field(ge=1, le=100)
    # Identifiant de formule (slug), pas son libellé : le nom peut être
    # réécrit dans le back-office, la référence choisie ce jour-là ne doit pas
    # bouger avec lui. Le libellé est figé côté serveur au moment de l'écriture.
    formula: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=2000)

    @field_validator("name", "phone", "address", "formula", "message")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("adresse e-mail invalide")
        return value


@router.get("/content")
def get_content() -> dict:
    """Éditorial du fichier JSON + formules et tarifs venus de la base.

    Les deux sources sont assemblées ici et nulle part ailleurs : le front n'a
    qu'un seul document à lire, et un tarif affiché sur le site est toujours
    celui qui servira de base à la facture."""
    site = dict(content.load())
    with db.cursor() as conn:
        site["formulas"] = billing.public_formulas(conn)
    return site


@router.get("/availability")
def availability() -> dict:
    """Slots the chef has opened, that nobody has booked, still in the future.

    `lead_days` from the content file keeps the chef from being booked for
    tomorrow evening: shopping and prep need a runway.
    """
    cfg = content.load()["booking"]
    first = today() + timedelta(days=int(cfg.get("lead_days", 3)))
    horizon = today() + timedelta(days=int(cfg.get("horizon_days", 365)))
    with db.cursor() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.date, s.service, s.note
            FROM slots s
            LEFT JOIN bookings b ON b.slot_id = s.id AND b.status = 'confirmed'
            WHERE b.id IS NULL AND s.date >= ? AND s.date <= ?
            ORDER BY s.date, s.service
            """,
            (first.isoformat(), horizon.isoformat()),
        ).fetchall()
    return {
        "first_bookable": first.isoformat(),
        "slots": [dict(row) for row in rows],
    }


def _new_ref() -> str:
    return "R-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))


@router.post("/bookings", status_code=201)
def create_booking(payload: BookingIn, background: BackgroundTasks) -> dict:
    cfg = content.load()["booking"]
    min_guests = int(cfg.get("min_guests", 1))
    max_guests = int(cfg.get("max_guests", 100))
    if not (min_guests <= payload.guests <= max_guests):
        raise HTTPException(
            422, f"Le nombre de convives doit être compris entre {min_guests} et {max_guests}."
        )

    first = today() + timedelta(days=int(cfg.get("lead_days", 3)))
    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    formula_id, formula_label = None, ""

    # One transaction decides availability and takes the slot. The partial
    # unique index on bookings is the real guard -- two clients hitting the
    # last slot at once cannot both come out with a confirmation.
    with db.transaction() as conn:
        slot = conn.execute(
            "SELECT id, date, service FROM slots WHERE id = ?", (payload.slot_id,)
        ).fetchone()
        if slot is None:
            raise HTTPException(404, "Ce créneau n'existe plus.")
        if slot["date"] < first.isoformat():
            raise HTTPException(409, "Ce créneau est trop proche pour être réservé.")
        taken = conn.execute(
            "SELECT 1 FROM bookings WHERE slot_id = ? AND status = 'confirmed'",
            (payload.slot_id,),
        ).fetchone()
        if taken:
            raise HTTPException(409, "Ce créneau vient d'être réservé. Choisissez-en un autre.")

        if payload.formula:
            row = conn.execute(
                "SELECT id, name, min_guests FROM formulas WHERE slug = ? AND active = 1",
                (payload.formula,),
            ).fetchone()
            # Une formule inconnue ou retirée n'est pas une erreur bloquante :
            # la date compte plus que la formule, qui se recale de toute façon
            # au téléphone. On enregistre alors « à définir » plutôt que de
            # refuser une réservation pour un menu.
            if row is not None:
                formula_id, formula_label = row["id"], row["name"]
                if row["min_guests"] and payload.guests < row["min_guests"]:
                    raise HTTPException(
                        422,
                        f"La formule « {row['name']} » démarre à {row['min_guests']} convives.")
            else:
                log.warning("formule inconnue %r sur une réservation", payload.formula)

        ref = _new_ref()
        cur = conn.execute(
            """
            INSERT INTO bookings
                (ref, slot_id, name, email, phone, address, guests, formula, formula_id,
                 message, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (ref, payload.slot_id, payload.name, payload.email, payload.phone,
             payload.address, payload.guests, formula_label, formula_id,
             payload.message, now),
        )
        booking_id = cur.lastrowid

    booking = {
        "id": booking_id, "ref": ref, "date": slot["date"], "service": slot["service"],
        "name": payload.name, "email": payload.email, "phone": payload.phone,
        "address": payload.address, "guests": payload.guests,
        "formula": formula_label, "message": payload.message,
    }
    log.info("booking %s created for %s %s", ref, slot["date"], slot["service"])

    # The client's confirmation goes out inline so the page can state what
    # actually happened; the chef's copy (and the recording of both outcomes)
    # follows in the background.
    client_status, client_err = mailer.send_client_confirmation(booking, content.site_name())
    background.add_task(mailer.notify_chef, booking, client_status, client_err)

    return {
        "ref": ref,
        "date": slot["date"],
        "service": slot["service"],
        "mail_sent": client_status == "sent",
    }
