#!/usr/bin/env python3
"""Vérifie que le jeu de démonstration couvre tous les états connus.

Le dépôt s'impose de ne jamais laisser les données d'exemple prendre du retard
sur les fonctions (cf. CLAUDE.md). Sans ce contrôle, cette règle est une phrase
que personne ne revérifie : un état ajouté au code et oublié dans le semis ne
se voit qu'en production, sur une vraie réservation.

Chaque attente ci-dessous correspond à quelque chose que l'interface sait
afficher. **Ajouter un état au code, c'est ajouter une ligne ici et un exemple
dans `backend/seed.py`, dans le même commit.**

    python3 tools/check-seed.py

Sort en code 1 dès qu'un état n'est pas représenté. N'écrit que dans un
répertoire temporaire : aucune base existante n'est touchée.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="chef-seed-check-")
os.environ.update(DATA_DIR=_TMP, SEED_DEMO="1", DEV="1", TZ="Europe/Paris")

from backend import billing, db, seed, settings  # noqa: E402  (l'env doit précéder l'import)


def _load() -> dict:
    db.init()
    seed.apply()
    with db.cursor() as conn:
        data = {
            "formulas": [dict(r) for r in conn.execute("SELECT * FROM formulas")],
            "slots": [dict(r) for r in conn.execute("SELECT * FROM slots")],
            "bookings": [dict(r) for r in conn.execute(
                "SELECT b.*, s.date, s.service FROM bookings b JOIN slots s ON s.id = b.slot_id")],
            "payments": [dict(r) for r in conn.execute("SELECT * FROM payments")],
            "invoices": [dict(r) for r in conn.execute("SELECT * FROM invoices")],
        }
        data["states"] = {}
        for booking in data["bookings"]:
            data["states"][booking["ref"]] = billing.booking_billing(conn, booking)
        data["lines"] = {
            inv["id"]: billing.lines_of(conn, inv["id"]) for inv in data["invoices"]
        }
    return data


def build_checks(d: dict) -> list[tuple[str, bool]]:
    formulas, slots, bookings = d["formulas"], d["slots"], d["bookings"]
    payments, invoices = d["payments"], d["invoices"]
    states = d["states"].values()
    today = billing.today().isoformat()
    used = {b["formula_id"] for b in bookings if b["formula_id"]}
    issued = [i for i in invoices if i["status"] == "issued"]

    def any_state(name):
        return any(s["state"] == name for s in states)

    return [
        # --- Formules
        ("formule tarifée par convive",
         any(f["pricing"] == "per_guest" and f["price_cents"] > 0 for f in formulas)),
        ("formule au forfait",
         any(f["pricing"] == "fixed" and f["price_cents"] > 0 for f in formulas)),
        ("formule sur devis", any(f["pricing"] == "quote" for f in formulas)),
        ("formule retirée du site (active = 0)", any(not f["active"] for f in formulas)),
        ("formule tarifée sans montant saisi (badge « tarif non renseigné »)",
         any(f["pricing"] != "quote" and f["price_cents"] <= 0 for f in formulas)),
        ("formule supprimable, citée par aucune réservation",
         any(f["id"] not in used for f in formulas)),
        ("formule inactive mais gardée dans l'historique",
         any(not f["active"] and f["id"] in used for f in formulas)),

        # --- Créneaux
        ("créneau libre à venir",
         any(s["date"] > today and not any(b["slot_id"] == s["id"] and b["status"] == "confirmed"
                                           for b in bookings) for s in slots)),
        ("créneau porteur d'une note", any(s["note"] for s in slots)),
        ("créneau passé (historique)", any(s["date"] < today for s in slots)),

        # --- Réservations
        ("réservation annulée", any(b["status"] == "cancelled" for b in bookings)),
        ("réservation sans formule choisie", any(b["formula_id"] is None for b in bookings)),
        ("confirmation client en échec", any(b["mail_client"] == "failed" for b in bookings)),
        ("envoi désactivé au moment de la réservation",
         any(b["mail_client"] == "disabled" for b in bookings)),
        ("repas passé non facturé",
         any(b["date"] < today and b["status"] == "confirmed"
             and not any(i["booking_id"] == b["id"] and i["status"] != "cancelled"
                         for i in invoices)
             for b in bookings)),

        # --- Encaissements
        *[(f"encaissement par {method}", any(p["method"] == method for p in payments))
          for method in billing.PAYMENT_METHODS],
        *[(f"encaissement de type {kind}", any(p["kind"] == kind for p in payments))
          for kind in billing.PAYMENT_KINDS],
        ("montant négatif (remboursement)", any(p["amount_cents"] < 0 for p in payments)),

        # --- Factures
        ("facture brouillon", any(i["status"] == "draft" for i in invoices)),
        ("facture émise", bool(issued)),
        ("facture annulée", any(i["status"] == "cancelled" for i in invoices)),
        ("facture annulée avec motif",
         any(i["status"] == "cancelled" and i["cancel_reason"] for i in invoices)),
        ("réservation refacturée après annulation",
         any(len([i for i in invoices if i["booking_id"] == b["id"]]) > 1 for b in bookings)),
        ("facture à plusieurs lignes", any(len(v) > 1 for v in d["lines"].values())),
        ("facture avec mention libre", any(i["notes"] for i in invoices)),
        ("facture assujettie à la TVA", any(i["vat_rate_bp"] > 0 for i in invoices)),
        ("facture en franchise (mention 293 B)", any(i["vat_rate_bp"] == 0 for i in invoices)),
        ("facture échue et impayée",
         any(i["due_on"] and i["due_on"] < today
             and billing.payment_state(i["total_cents"],
                                       sum(p["amount_cents"] for p in payments
                                           if p["booking_id"] == i["booking_id"])) != "paid"
             for i in issued)),
        ("envoi de facture réussi", any(i["mail_status"] == "sent" for i in issued)),
        ("envoi de facture en échec",
         any(i["mail_status"] == "failed" and i["mail_error"] for i in issued)),

        # --- États de paiement dérivés
        ("état : pas encore facturé", any_state("unbilled")),
        ("état : impayé", any_state("unpaid")),
        ("état : partiellement payé", any_state("partial")),
        ("état : soldé", any_state("paid")),
        ("état : trop-perçu", any_state("overpaid")),

        # --- Identité imprimée sur les factures
        ("identité vendeur de démonstration renseignée",
         all(billing.seller_identity().get(k) for k in
             ("name", "address", "siret", "iban", "payment_terms"))),
        ("adresse de départ du chef renseignée (lien d'itinéraire visible)",
         bool(settings.chef_address())),
        ("réservation avec adresse de repas, pour l'itinéraire",
         any(b["address"] for b in bookings)),
        ("réservation sans adresse de repas",
         any(not b["address"] for b in bookings)),
        ("réservation avec code postal et ville", any(b["city"] for b in bookings)),
        ("réservation sans ville (géocodage impossible)",
         any(b["address"] and not b["city"] for b in bookings)),
        ("trajet estimé", any(b["travel_seconds"] for b in bookings)),
        ("trajet en échec, avec son motif",
         any(b["travel_error"] and not b["travel_seconds"] for b in bookings)),
        ("trajet jamais demandé (bouton « Estimer »)",
         any(b["address"] and not b["travel_seconds"] and not b["travel_error"]
             for b in bookings)),
    ]


def main() -> int:
    checks = build_checks(_load())
    missing = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n{len(checks) - len(missing)}/{len(checks)} états représentés.")
    if missing:
        print("\nÉtats absents du jeu de démonstration :", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print("\nAjoute un exemple dans backend/seed.py et incrémente SEED_VERSION.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
