"""Back-office : formules et tarifs, encaissements, factures.

Séparé de `admin.py` parce que c'est un autre métier -- ouvrir des dates et
facturer un repas n'ont ni les mêmes règles ni le même rythme -- et parce que
tout ce qui touche à l'argent gagne à être relisible d'une seule traite.

Le cycle d'une facture, qui est la seule chose non évidente ici :

```mermaid
stateDiagram-v2
    [*] --> brouillon : créée depuis une réservation
    brouillon --> brouillon : lignes, notes, échéance modifiables
    brouillon --> émise : numéro attribué, totaux gelés
    émise --> envoyée : e-mail au client (résultat inscrit sur la facture)
    émise --> annulée : erreur constatée après coup
    annulée --> [*] : une nouvelle facture peut être créée
```

Une facture émise ne revient jamais en brouillon : son numéro est parti chez
le client et la séquence doit rester sans trou.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from .. import (auth, billing, config, content, db, invoice_html, mailer, menus,
                money, settings, travel)

log = logging.getLogger("chef.billing.api")

router = APIRouter(prefix="/api/admin", tags=["billing"],
                   dependencies=[Depends(auth.require_admin)])


def _amount(value: str | int) -> int:
    try:
        return money.parse_amount(value)
    except ValueError as exc:
        raise HTTPException(422, f"Montant invalide : {value!r}.") from exc


# --- Formules ----------------------------------------------------------

class FormulaIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=600)
    pricing: str = Field(default="per_guest")
    price: str = Field(default="0")          # saisi en euros, stocké en centimes
    min_guests: int = Field(default=0, ge=0, le=500)
    active: bool = True
    position: int = Field(default=0, ge=0, le=999)

    @field_validator("pricing")
    @classmethod
    def _pricing(cls, value: str) -> str:
        if value not in billing.PRICING_KINDS:
            raise ValueError(f"tarification invalide (attendu {', '.join(billing.PRICING_KINDS)})")
        return value


def _slugify(name: str) -> str:
    import re
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return slug or "formule"


@router.get("/formulas")
def list_formulas() -> dict:
    with db.cursor() as conn:
        rows = billing.formula_rows(conn, include_inactive=True)
        used = {
            r["formula_id"]
            for r in conn.execute(
                "SELECT DISTINCT formula_id FROM bookings WHERE formula_id IS NOT NULL")
        }
    return {
        "formulas": [
            # `price_label` encode déjà le mode de tarification (« / personne »,
            # « (forfait) », « sur devis ») : un libellé de mode en plus était
            # redondant, et donnait « sur devis · sur devis ».
            {**row,
             "price_label": billing.price_label(row),
             # Une formule déjà choisie par un client ne se supprime pas : le
             # back-office doit le savoir avant de proposer le bouton.
             "in_use": row["id"] in used}
            for row in rows
        ],
        "pricing_kinds": [{"value": k, "label": billing.PRICING_LABEL[k]}
                          for k in billing.PRICING_KINDS],
    }


@router.post("/formulas", status_code=201)
def create_formula(payload: FormulaIn) -> dict:
    price = _amount(payload.price) if payload.pricing != "quote" else 0
    if price < 0:
        raise HTTPException(422, "Un tarif ne peut pas être négatif.")
    base = _slugify(payload.name)
    with db.transaction() as conn:
        slug, n = base, 1
        while conn.execute("SELECT 1 FROM formulas WHERE slug = ?", (slug,)).fetchone():
            n += 1
            slug = f"{base}-{n}"
        formula_id = conn.execute(
            """INSERT INTO formulas (slug, name, description, pricing, price_cents,
                                     min_guests, active, position, demo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (slug, payload.name, payload.description, payload.pricing, price,
             payload.min_guests, int(payload.active), payload.position, billing.now_iso()),
        ).lastrowid
    log.info("formule %r créée (%s)", payload.name, slug)
    return {"id": formula_id, "slug": slug}


@router.patch("/formulas/{formula_id}")
def update_formula(formula_id: int, payload: FormulaIn) -> dict:
    price = _amount(payload.price) if payload.pricing != "quote" else 0
    if price < 0:
        raise HTTPException(422, "Un tarif ne peut pas être négatif.")
    with db.transaction() as conn:
        cur = conn.execute(
            """UPDATE formulas SET name = ?, description = ?, pricing = ?, price_cents = ?,
                                   min_guests = ?, active = ?, position = ?
               WHERE id = ?""",
            (payload.name, payload.description, payload.pricing, price,
             payload.min_guests, int(payload.active), payload.position, formula_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Formule introuvable.")
    # Le changement de prix ne touche aucune facture déjà émise : leurs
    # montants sont gelés. Les brouillons, eux, gardent les lignes déjà
    # posées -- éditer un tarif ne réécrit pas un devis en cours.
    log.info("formule %d mise à jour", formula_id)
    return {"updated": formula_id}


@router.delete("/formulas/{formula_id}")
def delete_formula(formula_id: int) -> dict:
    with db.transaction() as conn:
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE formula_id = ?", (formula_id,)
        ).fetchone()["n"]
        if used:
            # Supprimer couperait le lien avec des réservations passées et
            # rendrait leur historique illisible. Désactiver la retire du site
            # sans rien perdre.
            raise HTTPException(
                409, f"{used} réservation(s) utilisent cette formule. "
                     "Désactive-la pour la retirer du site, elle reste dans l'historique.")
        cur = conn.execute("DELETE FROM formulas WHERE id = ?", (formula_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Formule introuvable.")
    return {"deleted": formula_id}


# --- Encaissements -----------------------------------------------------

class PaymentIn(BaseModel):
    amount: str
    kind: str = Field(default="acompte")
    method: str = Field(default="virement")
    received_on: str = ""
    note: str = Field(default="", max_length=300)

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in billing.PAYMENT_KINDS:
            raise ValueError("type d'encaissement invalide")
        return value

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        if value not in billing.PAYMENT_METHODS:
            raise ValueError("moyen de paiement invalide")
        return value


@router.post("/bookings/{booking_id}/payments", status_code=201)
def add_payment(booking_id: int, payload: PaymentIn) -> dict:
    amount = abs(_amount(payload.amount))
    if amount == 0:
        raise HTTPException(422, "Un encaissement de zéro n'a rien à enregistrer.")
    # Le signe vient du type, pas de la saisie : le chef tape « 90 » pour un
    # remboursement de 90 € comme pour un acompte de 90 €, et c'est le code
    # qui sait lequel diminue le solde.
    if payload.kind == "remboursement":
        amount = -amount
    received = payload.received_on or billing.today().isoformat()
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM bookings WHERE id = ?", (booking_id,)).fetchone():
            raise HTTPException(404, "Réservation introuvable.")
        payment_id = conn.execute(
            """INSERT INTO payments (booking_id, kind, amount_cents, method, received_on,
                                     note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (booking_id, payload.kind, amount, payload.method, received,
             payload.note, billing.now_iso()),
        ).lastrowid
    log.info("encaissement %s de %s sur la réservation %d",
             payload.kind, money.format_amount(amount), booking_id)
    return {"id": payment_id, "amount_cents": amount}


@router.delete("/payments/{payment_id}")
def delete_payment(payment_id: int) -> dict:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Encaissement introuvable.")
        conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
    log.info("encaissement %d supprimé (%s)", payment_id,
             money.format_amount(int(row["amount_cents"])))
    return {"deleted": payment_id}


# --- Factures ----------------------------------------------------------

class LineIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=9999)
    unit: str = Field(default="0")


class InvoiceIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=40)
    notes: str = Field(default="", max_length=1000)
    due_on: str = ""
    vat_rate_bp: int = Field(default=0, ge=0, le=10000)


def _booking_or_404(conn, booking_id: int) -> dict:
    row = conn.execute(
        "SELECT b.*, s.date, s.service FROM bookings b JOIN slots s ON s.id = b.slot_id"
        " WHERE b.id = ?", (booking_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Réservation introuvable.")
    return dict(row)


@router.get("/bookings/{booking_id}/billing")
def booking_billing(booking_id: int) -> dict:
    with db.cursor() as conn:
        booking = _booking_or_404(conn, booking_id)
        return billing.booking_billing(conn, booking)


@router.post("/bookings/{booking_id}/invoice", status_code=201)
def create_invoice(booking_id: int) -> dict:
    with db.transaction() as conn:
        booking = _booking_or_404(conn, booking_id)
        if billing.live_invoice(conn, booking_id):
            raise HTTPException(409, "Cette réservation a déjà une facture. "
                                     "Annule-la avant d'en créer une autre.")
        invoice_id = billing.create_draft(conn, booking)
    log.info("brouillon de facture créé pour %s", booking["ref"])
    return {"id": invoice_id}


@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: InvoiceIn) -> dict:
    lines = [(l.label, l.quantity, _amount(l.unit)) for l in payload.lines]
    if any(unit < 0 for _, _, unit in lines):
        raise HTTPException(422, "Une ligne de facture ne peut pas être négative. "
                                 "Pour une remise, ajoute une ligne « remise » à part.")
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Facture introuvable.")
        if row["status"] != "draft":
            # Le point dur de tout ce module : une facture émise porte un
            # numéro parti chez le client. La corriger sur place produirait
            # deux documents différents sous le même numéro.
            raise HTTPException(409, "Cette facture est émise : elle ne se modifie plus. "
                                     "Annule-la et émets-en une nouvelle.")
        conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
        for position, (label, quantity, unit) in enumerate(lines):
            conn.execute(
                "INSERT INTO invoice_lines (invoice_id, label, quantity, unit_cents, position)"
                " VALUES (?, ?, ?, ?, ?)",
                (invoice_id, label, quantity, unit, position),
            )
        conn.execute(
            "UPDATE invoices SET notes = ?, due_on = ?, vat_rate_bp = ? WHERE id = ?",
            (payload.notes, payload.due_on or None, payload.vat_rate_bp, invoice_id),
        )
    return {"updated": invoice_id,
            "total_cents": sum(q * u for _, q, u in lines)}


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(invoice_id: int) -> dict:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Facture introuvable.")
        if row["status"] != "draft":
            raise HTTPException(409, "Cette facture est déjà émise.")
        lines = billing.lines_of(conn, invoice_id)
        if billing.lines_total(lines) <= 0:
            raise HTTPException(422, "Une facture à zéro ne s'émet pas : "
                                     "renseigne les montants d'abord.")
        booking = _booking_or_404(conn, row["booking_id"])
        number, total = billing.issue(conn, dict(row), booking)
    log.info("facture %s émise (%s)", number, money.format_amount(total))
    return {"number": number, "total_cents": total}


class CancelInvoiceIn(BaseModel):
    reason: str = Field(default="", max_length=400)


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: int, payload: CancelInvoiceIn) -> dict:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Facture introuvable.")
        if row["status"] == "cancelled":
            raise HTTPException(409, "Cette facture est déjà annulée.")
        if row["status"] == "issued" and not payload.reason.strip():
            # Le numéro reste consommé et l'annulation reste dans l'historique :
            # sans motif, personne ne saura dans six mois pourquoi il manque.
            raise HTTPException(422, "Indique le motif d'annulation : il reste "
                                     "attaché à la facture.")
        conn.execute(
            "UPDATE invoices SET status = 'cancelled', cancelled_at = ?, cancel_reason = ?"
            " WHERE id = ?",
            (billing.now_iso(), payload.reason.strip(), invoice_id),
        )
    log.info("facture %s annulée : %s", row["number"] or f"brouillon #{invoice_id}",
             payload.reason or "—")
    return {"cancelled": invoice_id}


@router.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int, background: BackgroundTasks) -> dict:
    if not config.mail_enabled():
        raise HTTPException(503, "Envoi d'e-mails désactivé (SMTP_HOST non configuré).")
    with db.cursor() as conn:
        invoice = billing.invoice_view(conn, invoice_id)
        if invoice is None:
            raise HTTPException(404, "Facture introuvable.")
        if invoice["status"] != "issued":
            raise HTTPException(409, "Seule une facture émise s'envoie : "
                                     "un brouillon n'a pas de numéro.")
        payments = billing.payments_of(conn, invoice["booking_id"])
    if not invoice["client"].get("email"):
        raise HTTPException(422, "Aucune adresse e-mail sur cette facture.")
    html = invoice_html.render(invoice, payments)
    background.add_task(mailer.send_invoice, invoice, content.site_name(), html)
    return {"queued": invoice["number"]}


@router.get("/invoices/{invoice_id}/view", response_class=HTMLResponse)
def view_invoice(invoice_id: int) -> HTMLResponse:
    """Page imprimable. C'est aussi ce qui part en pièce jointe : un seul
    rendu, donc ce que le chef relit est exactement ce que le client reçoit."""
    with db.cursor() as conn:
        invoice = billing.invoice_view(conn, invoice_id)
        if invoice is None:
            raise HTTPException(404, "Facture introuvable.")
        payments = billing.payments_of(conn, invoice["booking_id"])
    return HTMLResponse(invoice_html.render(invoice, payments),
                        headers={"Cache-Control": "no-store"})


@router.get("/invoices")
def list_invoices(status: str = "all", limit: int = 200) -> dict:
    """Toutes les factures, avec leur solde. La vue « qui me doit combien »."""
    limit = max(1, min(limit, 500))
    where, params = "", []
    if status != "all":
        where = "WHERE i.status = ?"
        params.append(status)
    with db.cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT i.*, b.ref, b.name, b.guests, s.date, s.service,
                   (SELECT COALESCE(SUM(p.amount_cents), 0) FROM payments p
                     WHERE p.booking_id = i.booking_id) AS paid_cents
            FROM invoices i
            JOIN bookings b ON b.id = i.booking_id
            JOIN slots s ON s.id = b.slot_id
            {where}
            ORDER BY (i.issued_on IS NULL) DESC, i.issued_on DESC, i.id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        invoices = []
        for row in rows:
            item = dict(row)
            total = billing.invoice_total(conn, item)
            item["total_cents"] = total
            # Une facture annulée ne porte plus de créance : afficher un solde
            # dessus enverrait relancer un client sur un document qui n'existe
            # plus. Les encaissements, eux, restent visibles sur la réservation.
            issued = item["status"] == "issued"
            item["balance_cents"] = (total - int(item["paid_cents"])) if issued else None
            item["state"] = ("cancelled" if item["status"] == "cancelled"
                             else billing.payment_state(total if issued else None,
                                                        int(item["paid_cents"])))
            invoices.append(item)
    outstanding = sum(i["balance_cents"] for i in invoices
                      if i["status"] == "issued" and i["balance_cents"] > 0)
    return {"invoices": invoices, "outstanding_cents": outstanding}


# --- Adresse d'une réservation -----------------------------------------

class AddressIn(BaseModel):
    address: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)


@router.patch("/bookings/{booking_id}/address")
def update_address(booking_id: int, payload: AddressIn) -> dict:
    """Corrige l'adresse du repas.

    Le client saisit ce qu'il veut dans un formulaire libre, et une adresse
    incomplète condamne l'estimation de trajet à jamais. Le chef appelle,
    demande la rue exacte, et la corrige ici.

    Le changement **efface l'estimation conservée** : elle décrivait l'ancienne
    adresse, la garder afficherait une durée qui ne correspond plus à rien. Une
    facture déjà émise, elle, ne bouge pas — son adresse client a été recopiée
    à l'émission et ne doit pas se réécrire après coup.
    """
    with db.transaction() as conn:
        row = conn.execute("SELECT ref FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Réservation introuvable.")
        conn.execute(
            "UPDATE bookings SET address = ?, city = ?, travel_seconds = NULL,"
            " travel_meters = NULL, travel_error = '', travel_label = '', travel_at = NULL"
            " WHERE id = ?",
            (payload.address.strip(), payload.city.strip(), booking_id),
        )
    log.info("adresse corrigée sur %s", row["ref"])
    return {"updated": booking_id}


# --- Trajet ------------------------------------------------------------

@router.post("/bookings/{booking_id}/travel")
def compute_travel(booking_id: int) -> dict:
    """Estime le trajet et conserve le résultat sur la réservation.

    À la demande, et seulement ici : les services interrogés sont publics et
    sans garantie, ils n'ont rien à faire sur le chemin d'une réservation
    client. Un échec s'inscrit sur la ligne au lieu de disparaître, pour que
    le chef sache que le calcul a été tenté et pourquoi il n'a rien donné.
    """
    with db.cursor() as conn:
        booking = _booking_or_404(conn, booking_id)
    if not (booking.get("city") or "").strip():
        # Refus déterministe, avant tout appel réseau : une rue sans ville est
        # ambiguë dans toute la France, et le géocodeur tranchera au hasard
        # plutôt que d'échouer. Mieux vaut ne pas demander.
        result = {"seconds": None, "meters": None, "origin_label": "",
                  "destination_label": "", "approximate": False,
                  "error": "code postal et ville manquants sur cette réservation — "
                           "sans eux, l'adresse ne peut pas être localisée de façon sûre"}
    else:
        result = travel.estimate(settings.chef_address(), billing.full_address(booking),
                                 fallback=(booking.get("city") or "").strip())
    with db.transaction() as conn:
        conn.execute(
            "UPDATE bookings SET travel_seconds = ?, travel_meters = ?, travel_error = ?,"
            " travel_label = ?, travel_approx = ?, travel_at = ? WHERE id = ?",
            (result["seconds"], result["meters"], result["error"][:300],
             result["destination_label"][:200], int(result.get("approximate", False)),
             billing.now_iso(), booking_id),
        )
    if result["error"]:
        log.info("trajet non estimé pour %s : %s", booking["ref"], result["error"])
    return {
        **result,
        "label": travel.format_duration(result["seconds"]),
        "km": round(result["meters"] / 1000, 1) if result["meters"] else None,
    }


# --- Réglages ----------------------------------------------------------

class SettingsIn(BaseModel):
    chef_address: str = Field(default="", max_length=300)
    area_postcodes: str = Field(default="", max_length=200)

    @field_validator("area_postcodes")
    @classmethod
    def _postcodes(cls, value: str) -> str:
        """Normalise « 44 ,85, 49 » en « 44, 49, 85 ».

        Une entrée non numérique est refusée plutôt que silencieusement
        ignorée : un chef qui tape « Loire-Atlantique » croirait sa zone posée
        alors que `area_prefixes()` la jetterait, et le site laisserait passer
        la France entière sans que rien ne le dise.
        """
        parts = [p.strip() for p in value.split(",") if p.strip()]
        bad = [p for p in parts if not p.isdigit()]
        if bad:
            raise ValueError(
                "la zone attend des débuts de code postal, séparés par des virgules "
                f"(ex. « 44, 85 ») — reçu : {', '.join(bad)}")
        return ", ".join(sorted(set(parts)))


@router.get("/settings")
def read_settings() -> dict:
    return settings.all_settings()


@router.patch("/settings")
def write_settings(payload: SettingsIn) -> dict:
    """Enregistre TOUS les réglages déclarés par le modèle.

    Écrit ainsi, et pas champ par champ : la version précédente ne posait que
    `chef_address` et jetait la zone en silence, tout en répondant
    « updated: true ». Ajouter un réglage au modèle sans penser à l'écrire ici
    donnait un champ qui s'affiche, s'enregistre en apparence, et ne fait
    rien. `settings.save()` refuse une clé inconnue, donc le modèle et
    `DEFAULTS` ne peuvent pas diverger sans que ça se voie tout de suite.
    """
    values = {k: v.strip() if isinstance(v, str) else v
              for k, v in payload.model_dump().items()}
    settings.save(values)
    return {"updated": True, "settings": settings.all_settings()}


# --- Menus -------------------------------------------------------------

class MenuLineIn(BaseModel):
    course: str = Field(default="", max_length=60)
    dish: str = Field(default="", max_length=300)


class MenuIn(BaseModel):
    title: str = Field(default="", max_length=160)
    note: str = Field(default="", max_length=1000)
    lines: list[MenuLineIn] = Field(default_factory=list, max_length=menus.MAX_LINES)


def _menu_row(conn, booking_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM menus WHERE booking_id = ?", (booking_id,)).fetchone()
    return dict(row) if row else None


@router.put("/bookings/{booking_id}/menu")
def save_menu(booking_id: int, payload: MenuIn) -> dict:
    """Crée ou remplace le brouillon de menu d'une réservation.

    Un menu déjà envoyé se réécrit, mais retombe en brouillon : le client a
    reçu une version, la nouvelle ne vaut que si elle lui est renvoyée. Le
    laisser « envoyé » avec un contenu différent ferait croire au chef que son
    client connaît un menu qu'il n'a jamais vu.
    """
    lines = menus.normalise([line.model_dump() for line in payload.lines])
    now = billing.now_iso()
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM bookings WHERE id = ?", (booking_id,)).fetchone() is None:
            raise HTTPException(404, "Réservation introuvable.")
        conn.execute(
            """INSERT INTO menus (booking_id, title, lines, note, status, created_at)
               VALUES (?, ?, ?, ?, 'draft', ?)
               ON CONFLICT (booking_id) DO UPDATE SET
                   title = excluded.title, lines = excluded.lines,
                   note = excluded.note, status = 'draft'""",
            (booking_id, payload.title, menus.dumps(lines), payload.note, now),
        )
    return {"saved": True, "lines": len(lines)}


@router.post("/bookings/{booking_id}/menu/send")
def send_menu(booking_id: int, background: BackgroundTasks) -> dict:
    """Envoie le menu au client et le rend visible sur sa page.

    Un menu vide ne part pas : un e-mail intitulé « votre menu » sans un seul
    plat inquiète plus qu'il ne renseigne.
    """
    if not config.mail_enabled():
        raise HTTPException(503, "Envoi d'e-mails désactivé (SMTP_HOST non configuré).")
    now = billing.now_iso()
    with db.transaction() as conn:
        row = conn.execute(
            """SELECT b.*, s.date, s.service FROM bookings b
               JOIN slots s ON s.id = b.slot_id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Réservation introuvable.")
        if row["status"] != "confirmed":
            raise HTTPException(409, "Réservation annulée : le menu n'a plus de destinataire.")
        menu = _menu_row(conn, booking_id)
        if menu is None or not menus.loads(menu["lines"]):
            raise HTTPException(422, "Ce menu est vide : ajoutez au moins un plat.")
        conn.execute(
            "UPDATE menus SET status = 'sent', sent_at = ? WHERE booking_id = ?",
            (now, booking_id),
        )
    menu = {**menu, "lines": menus.loads(menu["lines"])}
    background.add_task(mailer.send_menu, dict(row), menu, content.site_name())
    return {"queued": row["ref"]}
