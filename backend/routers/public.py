"""Public API: site copy, open slots, and creating a booking."""

import logging
import re
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from .. import billing, config, content, db, diets, mailer, settings

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
    city: str = Field(default="", max_length=120)
    guests: int = Field(ge=1, le=100)
    # Identifiant de formule (slug), pas son libellé : le nom peut être
    # réécrit dans le back-office, la référence choisie ce jour-là ne doit pas
    # bouger avec lui. Le libellé est figé côté serveur au moment de l'écriture.
    formula: str = Field(default="", max_length=120)
    # [{"id": "sans-gluten", "count": 2}] -- cf. backend/diets.py. Le champ
    # libre `message` reste : il dit ce qu'un catalogue fermé ne dira jamais.
    diets: list[dict] = Field(default_factory=list, max_length=20)
    message: str = Field(default="", max_length=2000)

    @field_validator("name", "phone", "address", "city", "formula", "message")
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
    site["diets"] = diets.catalogue()
    # La zone annoncée au client est DÉRIVÉE de la liste qui fait loi, jamais
    # recopiée dans le fichier éditorial : une zone affichée qui diverge de la
    # zone appliquée fait refuser quelqu'un à qui on venait de dire oui.
    site["booking"] = {**site["booking"], "area_note": settings.area_note()}
    site["occasions"] = [{"id": i, "label": label} for i, label in OCCASIONS]
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


def _new_ref(prefix: str = "R") -> str:
    return f"{prefix}-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))


# Types d'événement proposés. Un menu fermé plutôt qu'un champ libre : le chef
# ne cuisine pas pareil un dîner à deux et un buffet de baptême, et c'est la
# première chose qu'il veut lire. « Autre » existe pour ne rien exclure.
OCCASIONS = (
    ("repas-famille", "Repas de famille"),
    ("diner-amis", "Dîner entre amis"),
    ("anniversaire", "Anniversaire"),
    ("mariage", "Mariage, baptême, communion"),
    ("professionnel", "Repas professionnel, séminaire"),
    ("cours", "Cours ou atelier de cuisine"),
    ("autre", "Autre"),
)
OCCASION_LABEL = dict(OCCASIONS)


class QuoteIn(BaseModel):
    """Une demande de devis exige beaucoup moins qu'une réservation.

    Elle ne prend pas de créneau, donc elle n'a besoin ni d'une date, ni d'une
    adresse, ni d'un nombre de convives exact : le nom, un moyen de rappeler,
    et ce que la personne cherche. Chaque champ obligatoire de plus est une
    demande qui n'arrive jamais.
    """

    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=160)
    phone: str = Field(default="", max_length=40)
    city: str = Field(default="", max_length=120)
    # Volontairement plus large que les 10 caractères d'une date ISO : la borne
    # de Pydantic s'applique AVANT le validateur, et un `max_length=10` faisait
    # refuser la demande entière au lieu de laisser `_wanted` blanchir un champ
    # facultatif. Constaté en test sur « pas-une-date ».
    wanted_date: str = Field(default="", max_length=40)
    service: str = Field(default="", max_length=10)
    flexibility: str = Field(default="", max_length=200)
    guests: int = Field(default=0, ge=0, le=500)
    occasion: str = Field(default="", max_length=40)
    formula: str = Field(default="", max_length=120)
    diets: list[dict] = Field(default_factory=list, max_length=20)
    message: str = Field(default="", max_length=2000)

    @field_validator("name", "phone", "city", "flexibility", "formula", "message")
    @classmethod
    def _strip_quote(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def _quote_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("adresse e-mail invalide")
        return value

    @field_validator("wanted_date")
    @classmethod
    def _wanted(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        try:
            date.fromisoformat(value)
        except ValueError:
            # Une date illisible est effacée plutôt que refusée : elle vaut
            # « pas de date précise », et perdre la demande entière pour ce
            # champ facultatif serait le pire des deux.
            log.warning("date souhaitée illisible sur un devis : %r", value)
            return ""
        return value

    @field_validator("service")
    @classmethod
    def _service(cls, value: str) -> str:
        value = value.strip()
        return value if value in ("midi", "soir") else ""

    @field_validator("occasion")
    @classmethod
    def _occasion(cls, value: str) -> str:
        value = value.strip()
        return value if value in OCCASION_LABEL else ""


@router.post("/quotes", status_code=201)
def create_quote(payload: QuoteIn, background: BackgroundTasks) -> dict:
    """Demande de devis : un message structuré, pas une réservation.

    Rien n'est bloqué, aucune date n'est prise. La réponse du chef se fait à
    la main -- c'est justement ce qui distingue une demande sur mesure d'un
    créneau au calendrier.
    """
    try:
        declared = diets.normalise(payload.diets, payload.guests or 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"Régime alimentaire non reconnu ({exc}).")

    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    formula_id, formula_label = None, ""
    with db.transaction() as conn:
        if payload.formula:
            row = conn.execute(
                "SELECT id, name FROM formulas WHERE slug = ? AND active = 1",
                (payload.formula,),
            ).fetchone()
            if row is not None:
                formula_id, formula_label = row["id"], row["name"]
        ref = _new_ref("Q")
        conn.execute(
            """INSERT INTO quotes (ref, name, email, phone, city, wanted_date, service,
                                   flexibility, guests, occasion, formula, formula_id,
                                   diets, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ref, payload.name, payload.email, payload.phone, payload.city,
             payload.wanted_date, payload.service, payload.flexibility, payload.guests,
             payload.occasion, formula_label, formula_id, diets.dumps(declared),
             payload.message, now),
        )

    quote = {
        "ref": ref, "name": payload.name, "email": payload.email, "phone": payload.phone,
        "city": payload.city, "wanted_date": payload.wanted_date, "service": payload.service,
        "flexibility": payload.flexibility, "guests": payload.guests,
        "occasion": OCCASION_LABEL.get(payload.occasion, ""), "formula": formula_label,
        "diets": diets.dumps(declared), "message": payload.message,
    }
    log.info("devis %s demandé par %s", ref, payload.email)

    # Même règle que pour une réservation : l'accusé de réception part AVANT la
    # réponse HTTP, puisque la page affirme qu'il est parti. La notification au
    # chef suit en tâche de fond.
    client_status, client_err = mailer.send_quote_ack(quote, content.site_name())
    background.add_task(mailer.notify_chef_quote, quote, ref, client_status, client_err)

    return {"ref": ref, "mail_sent": client_status == "sent"}


@router.post("/bookings", status_code=201)
def create_booking(payload: BookingIn, background: BackgroundTasks) -> dict:
    cfg = content.load()["booking"]
    min_guests = int(cfg.get("min_guests", 1))
    max_guests = int(cfg.get("max_guests", 100))
    if not (min_guests <= payload.guests <= max_guests):
        raise HTTPException(
            422, f"Le nombre de convives doit être compris entre {min_guests} et {max_guests}."
        )

    accepted, why = settings.in_area(payload.city)
    if not accepted:
        # Un refus qui ne propose rien fait perdre un client qui, souvent,
        # aurait payé le déplacement. Le devis est exactement le chemin pour
        # cette conversation-là.
        raise HTTPException(
            422, f"{why} Faites-moi une demande sur mesure : je regarde si c'est jouable.")

    try:
        declared = diets.normalise(payload.diets, payload.guests)
    except (TypeError, ValueError) as exc:
        # Refuser, pas ignorer : le client croit avoir signalé une allergie.
        raise HTTPException(422, f"Régime alimentaire non reconnu ({exc}).")

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
        token = db.new_token()
        cur = conn.execute(
            """
            INSERT INTO bookings
                (ref, token, slot_id, name, email, phone, address, city, guests, formula,
                 formula_id, message, diets, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (ref, token, payload.slot_id, payload.name, payload.email, payload.phone,
             payload.address, payload.city, payload.guests, formula_label, formula_id,
             payload.message, diets.dumps(declared), now),
        )
        booking_id = cur.lastrowid

    booking = {
        "id": booking_id, "ref": ref, "date": slot["date"], "service": slot["service"],
        "name": payload.name, "email": payload.email, "phone": payload.phone,
        "address": payload.address, "city": payload.city, "guests": payload.guests,
        "formula": formula_label, "message": payload.message,
        "diets": diets.dumps(declared), "token": token,
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
        # Le lien de suivi est rendu à la page de confirmation : un client qui
        # ne reçoit pas l'e-mail (ou le perd) repart quand même avec.
        "link": f"/r/{token}",
    }
