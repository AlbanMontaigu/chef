"""Récapitulatif comptable : ce que le chef doit déclarer.

Les données étaient toutes là — `payments` et `invoices` — mais aucune vue ne
les additionnait. Un micro-entrepreneur déclare son chiffre d'affaires
trimestriellement, et il n'avait rien pour le sortir.

**La base déclarable, ce sont les ENCAISSEMENTS, pas les factures.** Le régime
micro est une comptabilité de trésorerie : on déclare ce qui est entré sur le
compte pendant le trimestre, pas ce qui a été facturé. Une facture émise en
mars et payée en avril appartient au deuxième trimestre. C'est pour cette
raison que tout ce module part de `payments.received_on` et jamais de
`invoices.issued_on` — les deux vues sont montrées côte à côte, mais la
première est nommée comme celle qui compte.

Un remboursement est une ligne négative, donc il se retranche du trimestre où
il a lieu : c'est exactement ce que veut une comptabilité de caisse.

Ce module ne conseille rien et ne déclare rien à la place de personne. Il
additionne, il nomme ce qu'il additionne, et il exporte.
"""

import csv
import io
import logging

from . import billing, config, money

log = logging.getLogger("chef.accounting")

QUARTERS = ((1, "T1", "janvier – mars"), (2, "T2", "avril – juin"),
            (3, "T3", "juillet – septembre"), (4, "T4", "octobre – décembre"))

MONTH_NAMES = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
               "août", "septembre", "octobre", "novembre", "décembre")


def available_years(conn) -> list[int]:
    """Années où quelque chose s'est passé. L'année en cours y figure toujours,
    même vide : une liste qui ne la propose pas donne l'impression que
    l'export ne marche pas encore."""
    rows = conn.execute(
        """SELECT DISTINCT substr(received_on, 1, 4) AS y FROM payments
           WHERE received_on <> ''
           UNION SELECT DISTINCT substr(issued_on, 1, 4) FROM invoices
           WHERE issued_on IS NOT NULL AND issued_on <> ''"""
    ).fetchall()
    years = {int(r["y"]) for r in rows if (r["y"] or "").isdigit()}
    years.add(billing.today().year)
    return sorted(years, reverse=True)


def _payments_of_year(conn, year: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT p.*, b.ref, b.name, s.date AS meal_date, s.service
           FROM payments p
           JOIN bookings b ON b.id = p.booking_id
           JOIN slots s ON s.id = b.slot_id
           WHERE substr(p.received_on, 1, 4) = ?
           ORDER BY p.received_on, p.id""",
        (str(year),),
    ).fetchall()]


def _invoices_of_year(conn, year: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT i.*, b.ref, b.name, s.date AS meal_date, s.service,
                  (SELECT COALESCE(SUM(p.amount_cents), 0) FROM payments p
                    WHERE p.booking_id = i.booking_id) AS paid_cents
           FROM invoices i
           JOIN bookings b ON b.id = i.booking_id
           JOIN slots s ON s.id = b.slot_id
           WHERE i.status = 'issued' AND substr(i.issued_on, 1, 4) = ?
           ORDER BY i.number""",
        (str(year),),
    ).fetchall()]


def _month(received_on: str) -> int:
    try:
        return int(received_on[5:7])
    except (ValueError, IndexError):
        return 0


def summary(conn, year: int) -> dict:
    payments = _payments_of_year(conn, year)
    invoices = _invoices_of_year(conn, year)

    by_month = [0] * 13  # index 1..12 ; l'index 0 recueille les dates illisibles
    for p in payments:
        by_month[_month(p["received_on"])] += int(p["amount_cents"])

    quarters = []
    for number, label, months in QUARTERS:
        total = sum(by_month[m] for m in range(3 * number - 2, 3 * number + 1))
        quarters.append({"number": number, "label": label, "months": months,
                         "cents": total, "amount": money.format_amount(total)})

    cashed = sum(int(p["amount_cents"]) for p in payments)
    invoiced = sum(int(i["total_cents"]) for i in invoices)
    # L'encours est calculé sur les factures de l'année, mais avec TOUS les
    # encaissements de la réservation : un acompte versé en décembre solde une
    # facture de janvier, et l'ignorer inventerait un impayé.
    outstanding = sum(max(0, int(i["total_cents"]) - int(i["paid_cents"])) for i in invoices)

    by_method: dict[str, int] = {}
    for p in payments:
        by_method[p["method"]] = by_method.get(p["method"], 0) + int(p["amount_cents"])

    vat_collected = 0
    for i in invoices:
        if int(i["vat_rate_bp"]) > 0:
            _, vat = money.vat_split(int(i["total_cents"]), int(i["vat_rate_bp"]))
            vat_collected += vat

    return {
        "year": year,
        "years": available_years(conn),
        # Nommé « encaissé » et pas « chiffre d'affaires » : c'est la même
        # chose au régime micro, et un intitulé ambigu inviterait à déclarer
        # le montant facturé, qui est faux.
        "cashed_cents": cashed,
        "cashed": money.format_amount(cashed),
        "invoiced_cents": invoiced,
        "invoiced": money.format_amount(invoiced),
        "outstanding_cents": outstanding,
        "outstanding": money.format_amount(outstanding),
        "quarters": quarters,
        "months": [{"number": m, "label": MONTH_NAMES[m - 1], "cents": by_month[m],
                    "amount": money.format_amount(by_month[m])}
                   for m in range(1, 13)],
        # Un encaissement daté n'importe comment fausserait un trimestre en
        # silence : il est compté à part et affiché comme tel.
        "undated_cents": by_month[0],
        "by_method": [{"method": k, "label": billing.PAYMENT_METHOD_LABEL.get(k, k),
                       "cents": v, "amount": money.format_amount(v)}
                      for k, v in sorted(by_method.items(), key=lambda kv: -kv[1])],
        "payments": len(payments),
        "invoices": len(invoices),
        "vat_rate_bp": config.VAT_RATE_BP,
        "vat_collected_cents": vat_collected,
        "vat_collected": money.format_amount(vat_collected),
        "vat_note": config.VAT_NOTE,
    }


# --- Export ------------------------------------------------------------

def _safe(value) -> str:
    """Neutralise une cellule que le tableur prendrait pour une formule.

    Un nom de client commençant par « = », « + », « - » ou « @ » est
    interprété comme une formule à l'ouverture du fichier. C'est une vraie
    voie d'attaque, et ici le contenu vient d'un formulaire public : il n'y a
    aucune raison de faire confiance à un nom saisi par un inconnu.
    """
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _euros(cents) -> str:
    """Montant en euros avec une virgule décimale : c'est ce qu'attend un
    tableur en locale française, et un point y produirait du texte."""
    return f"{int(cents) / 100:.2f}".replace(".", ",")


def _csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    # Point-virgule : le séparateur qu'attend un tableur en locale française,
    # où la virgule est le séparateur décimal. Avec une virgule, tout le
    # fichier atterrit dans une seule colonne.
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                        lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM : sans lui, Excel lit l'UTF-8 comme du latin-1 et tous les accents
    # des noms de clients ressortent en mojibake.
    return "﻿" + buffer.getvalue()


def payments_csv(conn, year: int) -> str:
    rows = [
        [p["received_on"], _euros(p["amount_cents"]),
         billing.PAYMENT_KIND_LABEL.get(p["kind"], p["kind"]),
         billing.PAYMENT_METHOD_LABEL.get(p["method"], p["method"]),
         _safe(p["name"]), p["ref"], p["meal_date"],
         billing.service_label(p["service"]), _safe(p["note"])]
        for p in _payments_of_year(conn, year)
    ]
    return _csv(["Date d'encaissement", "Montant (EUR)", "Type", "Moyen", "Client",
                 "Reference reservation", "Date du repas", "Service", "Note"], rows)


def invoices_csv(conn, year: int) -> str:
    rows = []
    for i in _invoices_of_year(conn, year):
        ht, vat = money.vat_split(int(i["total_cents"]), int(i["vat_rate_bp"]))
        rows.append([
            i["number"], i["issued_on"], i["due_on"] or "", _safe(i["name"]), i["ref"],
            i["meal_date"], _euros(i["total_cents"]), _euros(ht), _euros(vat),
            money.format_rate(int(i["vat_rate_bp"])) if int(i["vat_rate_bp"]) else "0 %",
            _euros(i["paid_cents"]),
            _euros(max(0, int(i["total_cents"]) - int(i["paid_cents"]))),
        ])
    return _csv(["Numero", "Date de facture", "Echeance", "Client", "Reference reservation",
                 "Date du repas", "Total TTC (EUR)", "Total HT (EUR)", "TVA (EUR)",
                 "Taux TVA", "Encaisse (EUR)", "Reste du (EUR)"], rows)
