#!/usr/bin/env python3
"""Vide la base et rejoue le jeu de démonstration. **Destructif.**

Pourquoi cet outil existe : le semis refuse de rejouer dès qu'une réservation
non-démo apparaît, et il a raison — mélanger des exemples à de vraies
réservations fabriquerait une facture de démonstration indiscernable d'une
vraie. Mais sur une instance qui sert de bac à sable, ces « vraies »
réservations sont des essais, et il faut pouvoir repartir de zéro.

    python3 tools/reset-db.py                 # inventaire seul, ne touche à rien
    SEED_DEMO=1 python3 tools/reset-db.py --yes   # détruit et re-sème

Sur une instance déployée, le script n'est pas dans l'image : il s'injecte.

    cat tools/reset-db.py | docker exec -i <conteneur> python3 -        # inventaire
    cat tools/reset-db.py | docker exec -i <conteneur> python3 - --yes  # destruction

Trois refus, dans cet ordre :

1. Sans `--yes`, l'outil ne fait qu'inventorier. Une commande destructive ne
   doit pas pouvoir partir d'une faute de frappe.
2. Sans `SEED_DEMO`, il refuse : vider une base qui ne sera pas re-semée ne
   laisse qu'un site vide, ce qui n'est jamais l'intention.
3. Il imprime ce qu'il détruit AVANT de le faire — réservations nominatives,
   factures émises avec leur numéro, encaissements — parce qu'une facture émise
   effacée n'est pas rattrapable et que la séquence, elle, est censée être sans
   trou.
"""

import os
import sys
from pathlib import Path

# Cet outil n'est PAS copié dans l'image Docker, à dessein : un script qui vide
# la base n'a rien à faire à demeure dans le conteneur qui sert de vraies
# réservations. Il s'injecte au coup par coup —
#     cat tools/reset-db.py | docker exec -i <conteneur> python3 - --yes
# — d'où le repli sur le répertoire courant : lu depuis l'entrée standard, le
# script n'a pas de `__file__`.
try:
    ROOT = Path(__file__).resolve().parent.parent
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from backend import config, db, seed  # noqa: E402


def inventory() -> dict:
    with db.cursor() as conn:
        counts = {}
        for table in ("slots", "bookings", "formulas", "payments", "invoices",
                      "invoice_lines", "geocache", "meta"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            except Exception:
                counts[table] = 0
        real = [dict(r) for r in conn.execute(
            "SELECT ref, name, demo FROM bookings WHERE demo = 0 ORDER BY ref")]
        issued = [dict(r) for r in conn.execute(
            "SELECT number, status, total_cents FROM invoices"
            " WHERE status = 'issued' ORDER BY number")]
    return {"counts": counts, "real": real, "issued": issued}


def main() -> int:
    confirmed = "--yes" in sys.argv
    print(f"Base : {config.DB_PATH}")
    if not Path(config.DB_PATH).exists():
        print("  (elle n'existe pas encore — rien à vider)")

    db.init()
    state = inventory()
    print("\nContenu actuel :")
    for table, n in state["counts"].items():
        print(f"  {table:14} {n}")

    if state["real"]:
        print(f"\n  ⚠ {len(state['real'])} réservation(s) NON marquées démonstration :")
        for r in state["real"]:
            print(f"      {r['ref']}  {r['name']}")
    if state["issued"]:
        print(f"\n  ⚠ {len(state['issued'])} facture(s) ÉMISES, dont les numéros disparaîtront :")
        for i in state["issued"]:
            print(f"      {i['number']}  {i['total_cents'] / 100:.2f} €")

    if not confirmed:
        print("\nRien n'a été touché. Relance avec --yes pour vider et re-semer.")
        return 0
    if not config.SEED_DEMO:
        print("\nRefusé : SEED_DEMO est éteint, la base resterait vide.", file=sys.stderr)
        print("Relance avec SEED_DEMO=1.", file=sys.stderr)
        return 1

    for suffix in ("", "-wal", "-shm"):
        path = Path(str(config.DB_PATH) + suffix)
        if path.exists():
            path.unlink()
            print(f"\n  supprimé : {path.name}")

    db.init()
    seed.apply()
    after = inventory()
    print("\nAprès re-semis :")
    for table, n in after["counts"].items():
        print(f"  {table:14} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
