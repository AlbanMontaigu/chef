"""Formules, encaissements, factures : les règles, hors des routes HTTP.

Trois invariants tiennent ce module, et ils ne sont pas négociables :

1. **L'argent est un entier de centimes** (`money.py`). Aucun flottant.
2. **Ce qui est payé est la somme des encaissements**, jamais une colonne
   « payé » entretenue à côté. Un état dérivé ne peut pas diverger.
3. **Une facture émise est figée.** Le numéro est attribué à l'émission, dans
   la transaction qui la gèle, et la séquence est sans trou. Corriger une
   facture émise, c'est l'annuler et en émettre une autre -- jamais réécrire
   celle qui est déjà partie chez le client.
"""

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta

from . import config, content, money

log = logging.getLogger("chef.billing")

PRICING_KINDS = ("per_guest", "fixed", "quote")
PAYMENT_KINDS = ("acompte", "solde", "remboursement")
PAYMENT_METHODS = ("virement", "especes", "cheque", "cb", "autre")

PRICING_LABEL = {
    "per_guest": "par convive",
    "fixed": "forfait",
    "quote": "sur devis",
}
PAYMENT_METHOD_LABEL = {
    "virement": "virement", "especes": "espèces", "cheque": "chèque",
    "cb": "carte", "autre": "autre",
}


def now_iso() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def today() -> date:
    return datetime.now(config.TZ).date()


# --- Formules ----------------------------------------------------------

def formula_rows(conn: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else "WHERE active = 1"
    rows = conn.execute(
        f"SELECT * FROM formulas {where} ORDER BY position, id"
    ).fetchall()
    return [dict(r) for r in rows]


def price_label(row: dict) -> str:
    """Ce que le site public affiche. Un tarif « sur devis » n'a pas de prix
    à montrer : afficher « 0,00 € » serait pire que la mention."""
    if row["pricing"] == "quote" or row["price_cents"] <= 0:
        return "sur devis"
    amount = money.format_amount(row["price_cents"])
    return f"{amount} / personne" if row["pricing"] == "per_guest" else f"{amount} (forfait)"


def public_formulas(conn: sqlite3.Connection) -> list[dict]:
    return [
        {
            "id": row["slug"],
            "name": row["name"],
            "description": row["description"],
            "price": price_label(row),
            "min_guests": row["min_guests"] or 0,
        }
        for row in formula_rows(conn)
    ]


def quote_cents(row: dict | None, guests: int) -> int | None:
    """Montant attendu pour cette formule et ce nombre de convives.

    `None` veut dire « pas chiffrable automatiquement » (formule sur devis, ou
    aucune formule choisie) : le chef pose le montant lui-même. Renvoyer 0
    laisserait croire à un repas gratuit.
    """
    if row is None or row["pricing"] == "quote" or row["price_cents"] <= 0:
        return None
    if row["pricing"] == "fixed":
        return int(row["price_cents"])
    return int(row["price_cents"]) * max(1, int(guests))


# --- Encaissements -----------------------------------------------------

def paid_cents(conn: sqlite3.Connection, booking_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payments WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()
    return int(row["total"])


def payments_of(conn: sqlite3.Connection, booking_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM payments WHERE booking_id = ? ORDER BY received_on, id",
        (booking_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def payment_state(due: int | None, paid: int) -> str:
    """'unbilled' | 'unpaid' | 'partial' | 'paid' | 'overpaid'."""
    if due is None:
        return "unbilled"
    if paid <= 0:
        return "unpaid"
    if paid < due:
        return "partial"
    return "paid" if paid == due else "overpaid"


# --- Factures ----------------------------------------------------------

def live_invoice(conn: sqlite3.Connection, booking_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM invoices WHERE booking_id = ? AND status <> 'cancelled'",
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None


def lines_of(conn: sqlite3.Connection, invoice_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY position, id",
        (invoice_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def lines_total(lines: list[dict]) -> int:
    return sum(int(l["quantity"]) * int(l["unit_cents"]) for l in lines)


def invoice_total(conn: sqlite3.Connection, invoice: dict) -> int:
    """Total d'une facture.

    Émise : le total gelé, celui qui est parti chez le client -- on ne le
    recalcule pas, même si une formule a changé de prix depuis. Brouillon :
    la somme vivante de ses lignes.
    """
    if invoice["status"] == "draft":
        return lines_total(lines_of(conn, invoice["id"]))
    return int(invoice["total_cents"])


def seller_identity() -> dict:
    """Identité du vendeur, telle qu'elle figurera sur la facture.

    Lue dans le fichier éditorial et **recopiée** dans la facture à
    l'émission : un SIRET ou une adresse qui change plus tard ne doit pas
    réécrire rétroactivement une facture déjà envoyée.
    """
    site = content.load()
    legal = site.get("legal") or {}
    contact = site.get("contact") or {}
    return {
        "name": legal.get("company_name") or site.get("name") or "",
        "address": legal.get("address") or "",
        "siret": legal.get("siret") or "",
        "status": legal.get("status") or "",
        "email": contact.get("email") or "",
        "phone": contact.get("phone") or "",
        # L'environnement prime sur le fichier : cf. config.INVOICE_IBAN.
        "iban": config.INVOICE_IBAN or legal.get("iban") or "",
        "bic": config.INVOICE_BIC or legal.get("bic") or "",
        "payment_terms": legal.get("payment_terms") or "",
    }


def client_identity(booking: dict) -> dict:
    return {
        "name": booking["name"],
        "email": booking["email"],
        "phone": booking.get("phone") or "",
        "address": booking.get("address") or "",
    }


def default_lines(conn: sqlite3.Connection, booking: dict) -> list[tuple[str, int, int]]:
    """Lignes proposées pour un nouveau brouillon : (libellé, quantité, PU).

    Toujours au moins une ligne, quitte à ce qu'elle soit à zéro -- un
    brouillon vide oblige le chef à tout retaper et invite à émettre une
    facture sans objet.
    """
    formula = None
    if booking.get("formula_id"):
        row = conn.execute("SELECT * FROM formulas WHERE id = ?", (booking["formula_id"],)).fetchone()
        formula = dict(row) if row else None
    guests = int(booking["guests"])
    label = (formula["name"] if formula else booking.get("formula")) or "Prestation de chef à domicile"
    if formula and formula["pricing"] == "per_guest" and formula["price_cents"] > 0:
        return [(f"{label} — {_service_label(booking['service'])} du {booking['date']}",
                 guests, int(formula["price_cents"]))]
    if formula and formula["pricing"] == "fixed" and formula["price_cents"] > 0:
        return [(f"{label} — {_service_label(booking['service'])} du {booking['date']}",
                 1, int(formula["price_cents"]))]
    return [(f"{label} — {_service_label(booking['service'])} du {booking['date']}, "
             f"{guests} convives", 1, 0)]


def _service_label(service: str) -> str:
    return {"midi": "déjeuner", "soir": "dîner"}.get(service, service)


def create_draft(conn: sqlite3.Connection, booking: dict) -> int:
    due = today() + timedelta(days=config.PAYMENT_TERMS_DAYS)
    cur = conn.execute(
        """INSERT INTO invoices (booking_id, status, due_on, vat_rate_bp, vat_note,
                                 seller_json, client_json, created_at)
           VALUES (?, 'draft', ?, ?, ?, ?, ?, ?)""",
        (booking["id"], due.isoformat(), config.VAT_RATE_BP, config.VAT_NOTE,
         json.dumps(seller_identity(), ensure_ascii=False),
         json.dumps(client_identity(booking), ensure_ascii=False), now_iso()),
    )
    invoice_id = cur.lastrowid
    for position, (label, quantity, unit) in enumerate(default_lines(conn, booking)):
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, label, quantity, unit_cents, position)"
            " VALUES (?, ?, ?, ?, ?)",
            (invoice_id, label, quantity, unit, position),
        )
    return invoice_id


def next_number(conn: sqlite3.Connection, on: date) -> str:
    """Numéro séquentiel par année : F2026-001, F2026-002…

    Attribué ici, dans la transaction d'émission, et nulle part ailleurs. Le
    maximum est relu à chaque fois plutôt que gardé dans un compteur : un
    compteur et des factures peuvent désynchroniser, `MAX` ne le peut pas.
    L'index unique sur `number` reste le garde-fou en cas de course.
    """
    prefix = f"{config.INVOICE_PREFIX}{on.year}-"
    row = conn.execute(
        "SELECT number FROM invoices WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    nxt = 1 if row is None else int(row["number"].rsplit("-", 1)[1]) + 1
    return f"{prefix}{nxt:03d}"


def issue(conn: sqlite3.Connection, invoice: dict, booking: dict) -> tuple[str, int]:
    """Gèle un brouillon : numéro, date, totaux, identités. Renvoie (numéro, total)."""
    lines = lines_of(conn, invoice["id"])
    total = lines_total(lines)
    on = today()
    number = next_number(conn, on)
    conn.execute(
        """UPDATE invoices
           SET number = ?, status = 'issued', issued_on = ?, issued_at = ?,
               total_cents = ?, seller_json = ?, client_json = ?
           WHERE id = ? AND status = 'draft'""",
        (number, on.isoformat(), now_iso(), total,
         json.dumps(seller_identity(), ensure_ascii=False),
         json.dumps(client_identity(booking), ensure_ascii=False), invoice["id"]),
    )
    return number, total


def booking_billing(conn: sqlite3.Connection, booking: dict) -> dict:
    """Vue facturation d'une réservation, telle que le back-office l'affiche."""
    invoice = live_invoice(conn, booking["id"])
    formula = None
    if booking.get("formula_id"):
        row = conn.execute("SELECT * FROM formulas WHERE id = ?", (booking["formula_id"],)).fetchone()
        formula = dict(row) if row else None
    estimate = quote_cents(formula, int(booking["guests"]))
    paid = paid_cents(conn, booking["id"])
    due = invoice_total(conn, invoice) if invoice and invoice["status"] == "issued" else None
    return {
        "estimate_cents": estimate,
        "paid_cents": paid,
        "due_cents": due,
        "balance_cents": None if due is None else due - paid,
        "state": payment_state(due, paid),
        "payments": payments_of(conn, booking["id"]),
        "invoice": _invoice_view(conn, invoice) if invoice else None,
    }


def _invoice_view(conn: sqlite3.Connection, invoice: dict) -> dict:
    lines = lines_of(conn, invoice["id"])
    total = invoice_total(conn, invoice)
    ht, vat = money.vat_split(total, int(invoice["vat_rate_bp"]))
    seller = json.loads(invoice["seller_json"] or "{}")
    client = json.loads(invoice["client_json"] or "{}")
    # Les deux colonnes JSON brutes ne ressortent pas : elles sont déjà là,
    # désérialisées, sous `seller` et `client`. Les laisser inviterait un jour
    # à lire la mauvaise des deux.
    rest = {k: v for k, v in invoice.items() if k not in ("seller_json", "client_json")}
    return {
        **rest,
        "lines": lines,
        "total_cents": total,
        "ht_cents": ht,
        "vat_cents": vat,
        "seller": seller,
        "client": client,
        "editable": invoice["status"] == "draft",
    }


def invoice_view(conn: sqlite3.Connection, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    return _invoice_view(conn, dict(row)) if row else None
