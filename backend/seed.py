"""Jeu de démonstration : une base vide devient un back-office parlant.

Trois règles gouvernent ce module, dans cet ordre :

1. **Il ne touche jamais une ligne qu'il n'a pas créée.** Tout ce qu'il pose
   porte `demo = 1`, et la purge ne vise que ce marqueur. Un semis ne peut
   donc pas effacer une vraie réservation, quelle que soit la version.
2. **Il s'efface devant le réel.** Dès qu'une réservation non-démo existe, le
   semis est refusé et les données d'exemple sont retirées : une facture de
   démonstration au milieu de vraies factures est pire qu'un back-office vide.
3. **Il est versionné.** `SEED_VERSION` est un entier global : l'incrémenter
   suffit à forcer le rejeu au prochain démarrage. C'est le seul geste à
   faire après avoir enrichi les exemples.

Les adresses e-mail utilisées sont en `@example.com`, réservé par la RFC 2606 :
un « renvoyer les e-mails » cliqué sur une réservation de démonstration ne
peut pas écrire à quelqu'un.
"""

import json
import logging
from datetime import date, timedelta

from . import billing, config, db

log = logging.getLogger("chef.seed")

# Incrémenter à CHAQUE modification des exemples ci-dessous -- y compris
# quand une nouvelle fonctionnalité ajoute un champ que le jeu doit montrer.
SEED_VERSION = 4
_MARKER = "seed_version"


def _d(days: int) -> str:
    return (billing.today() + timedelta(days=days)).isoformat()


# Adresse de départ du chef, fictive elle aussi. Sans elle, le lien
# d'itinéraire ne s'affiche jamais et la fonction reste invisible dans le jeu.
DEMO_CHEF_ADDRESS = "12 rue des Olivettes, 44000 Nantes"


# --- Identité de démonstration ----------------------------------------
# Entièrement FICTIVE, et c'est le point : sans elle, toute facture de
# démonstration s'imprime avec les PLACEHOLDER de content/site.json et ne
# montre pas ce qu'elle est censée montrer. Le SIRET et l'IBAN sont
# volontairement des suites reconnaissables — personne ne doit pouvoir les
# prendre pour de vrais. Elle ne sert que quand SEED_DEMO est allumé.
DEMO_LEGAL = {
    "company_name": "Camille Rousseau",
    "status": "Micro-entreprise — chef à domicile",
    "address": "12 rue des Olivettes, 44000 Nantes",
    "siret": "12345678900019",
    "iban": "FR76 1234 5678 9012 3456 7890 189",
    "bic": "DEMOFRPPXXX",
    "payment_terms": "Paiement à réception. Pas d'escompte pour paiement anticipé. "
                     "Pénalités de retard : trois fois le taux d'intérêt légal, "
                     "indemnité forfaitaire de recouvrement de 40 €.",
}


# --- Le contenu du jeu -------------------------------------------------
# Chaque entrée existe pour rendre visible un état de l'application. Un jeu
# qui ne montrerait que le cas nominal laisserait la moitié de l'interface non
# vérifiée -- et le premier rendu d'un état se ferait en production, sur une
# vraie réservation. `tools/check-seed.py` vérifie que cette liste couvre bien
# tous les états connus ; l'enrichir sans y passer ne sert à rien.

FORMULAS = [
    # (slug, nom, description, tarification, prix en centimes, convives mini, active)
    ("decouverte", "Menu Découverte",
     "Entrée, plat, dessert. Produits du marché, de saison.",
     "per_guest", 4500, 4, 1),
    ("signature", "Menu Signature",
     "Cinq services, pain maison, accords mets-vins possibles.",
     "per_guest", 7800, 6, 1),
    ("reception", "Réception",
     "Buffet ou cocktail dînatoire, service compris, à partir de quinze convives.",
     "quote", 0, 15, 1),
    # Forfait, et jamais choisie : c'est la seule que le back-office propose de
    # supprimer, donc le seul moyen de voir ce bouton.
    ("atelier", "Atelier cuisine",
     "Deux heures de cuisine à quatre mains, puis on passe à table.",
     "fixed", 32000, 0, 1),
    # Réglée « par convive » sans montant : le site l'affiche « sur devis » et
    # le back-office doit le signaler comme un tarif oublié.
    ("brunch", "Brunch du dimanche",
     "Salé, sucré, viennoiseries maison.",
     "per_guest", 0, 4, 1),
    # Retirée du site mais citée par une réservation passée : elle prouve
    # qu'on désactive au lieu de supprimer, sans casser l'historique.
    ("hiver", "Menu d'hiver",
     "Gibier, racines, longues cuissons. Carte de l'an dernier.",
     "per_guest", 6500, 4, 0),
]

SLOTS = [
    # (offset en jours, service, note) -- passé pour l'historique facturé,
    # futur pour le calendrier public.
    (-52, "soir", ""),
    (-45, "midi", ""),
    (-38, "soir", ""),
    (-31, "midi", ""),
    (-24, "soir", ""),
    (-17, "midi", ""),
    (-10, "soir", ""),
    (-3,  "soir", ""),
    (1,   "soir", ""),        # dans la fenêtre de préavis : « trop proche »
    (9,   "midi", ""),
    (9,   "soir", "Menu automne, gibier possible"),
    (16,  "soir", ""),
    (23,  "midi", ""),
    (23,  "soir", ""),
    (30,  "soir", "Dernière date avant les fêtes"),
    (44,  "soir", ""),
]

BOOKINGS = [
    # Repas passé, facturé, soldé : le cas nominal complet.
    {
        "key": "soldee", "slot": (-24, "soir"), "ref": "R-KH4T7A",
        "name": "Claire Berthier", "email": "claire.berthier@example.com",
        "phone": "06 24 81 09 55", "address": "14 rue des Halles, Nantes",
        "guests": 8, "formula": "signature",
        "message": "Un invité ne mange pas de crustacés.",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "issued", "issued": -23, "due": 7,
            "lines": [("Menu Signature — dîner du {date}", 8, 7800),
                      ("Accord mets-vins", 8, 1500)],
            "mail": "sent", "notes": "Merci de votre confiance.",
        },
        "payments": [
            ("acompte", 22000, "virement", -22, "Acompte 30 %"),
            ("solde", 52400, "virement", -22, ""),
        ],
    },
    # Repas passé, facturé, acompte seulement : le solde à relancer.
    {
        "key": "acompte", "slot": (-17, "midi"), "ref": "R-9WQMFE",
        "name": "Julien Pasquier", "email": "j.pasquier@example.com",
        "phone": "07 61 44 12 03", "address": "3 impasse du Verger, Rezé",
        "guests": 6, "formula": "decouverte",
        "message": "Repas d'anniversaire, gâteau prévu de notre côté.",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "issued", "issued": -16, "due": 14,
            "lines": [("Menu Découverte — déjeuner du {date}", 6, 4500)],
            "mail": "sent",
        },
        "payments": [("acompte", 9000, "cheque", -16, "Chèque remis sur place")],
    },
    # Facture émise puis annulée, remplacée par une seconde : le chemin de
    # correction. Une facture émise ne se réécrit pas, elle se remplace.
    {
        "key": "refacturee", "slot": (-10, "soir"), "ref": "R-3XKLPT",
        "name": "Sophie Ramanantsoa", "email": "sophie.r@example.com",
        "phone": "06 07 55 31 20", "address": "27 bd des Poilus, Saint-Herblain",
        "guests": 12, "formula": "reception",
        "message": "Cocktail dînatoire pour un départ en retraite.",
        "mail": ("sent", "sent", ""),
        "cancelled_invoice": {
            "issued": -9, "due": 21, "reason": "Nombre de convives erroné (10 au lieu de 12).",
            "lines": [("Réception — dîner du {date}, 10 convives", 1, 95000)],
        },
        "invoice": {
            "status": "issued", "issued": -8, "due": 22,
            "lines": [("Réception — dîner du {date}, 12 convives", 1, 114000),
                      ("Déplacement et service", 1, 8000)],
            "mail": "sent",
        },
        "payments": [("acompte", 60000, "virement", -8, "")],
    },
    # Facture émise, échue, RIEN reçu, et l'envoi lui-même a échoué : le pire
    # cas de suivi, celui qu'il ne faut surtout pas manquer dans une liste.
    {
        "key": "impayee", "slot": (-45, "midi"), "ref": "R-P4WXQ7",
        "name": "Bruno Delalande", "email": "bruno.delalande@example.com",
        "phone": "06 88 44 09 71", "address": "6 rue du Port, Trentemoult",
        "guests": 5, "formula": "hiver",
        "message": "",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "issued", "issued": -44, "due": -14,
            "lines": [("Menu d'hiver — déjeuner du {date}", 5, 6500)],
            "mail": "failed", "mail_error": "SMTPRecipientsRefused: 550 mailbox unavailable",
            "notes": "Deuxième relance envoyée par téléphone.",
        },
        "payments": [],
    },
    # Facture assujettie à la TVA : la seule qui exerce la ventilation HT/TVA
    # du rendu. Le taux est figé sur la facture, pas relu dans la config.
    {
        "key": "tva", "slot": (-38, "soir"), "ref": "R-J9CMR3",
        "name": "Atelier Lumen SARL", "email": "compta@example.com",
        "phone": "02 40 12 88 30", "address": "9 quai de la Fosse, 44000 Nantes",
        "guests": 14, "formula": "reception",
        "message": "Dîner d'entreprise, facture au nom de la société.",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "issued", "issued": -37, "due": -7, "vat_rate_bp": 2000,
            "lines": [("Réception — dîner du {date}, 14 convives", 1, 138000),
                      ("Personnel de service supplémentaire", 2, 12000)],
            "mail": "sent", "notes": "Bon de commande n° 2026-0417.",
        },
        "payments": [("solde", 162000, "autre", -30, "Virement société, bordereau 4417")],
    },
    # Client qui a arrondi au-dessus : trop-perçu, à rendre ou à déduire.
    {
        "key": "trop_percu", "slot": (-52, "soir"), "ref": "R-T6HKV2",
        "name": "Hélène Nguyen", "email": "helene.nguyen@example.com",
        "phone": "06 51 30 22 47", "address": "2 allée des Tanneurs, Nantes",
        "guests": 4, "formula": "decouverte", "message": "",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "issued", "issued": -51, "due": -21,
            "lines": [("Menu Découverte — dîner du {date}", 4, 4500)],
            "mail": "sent",
        },
        "payments": [("solde", 20000, "especes", -51, "A laissé 200 € en liquide")],
    },
    # Repas passé, pas encore facturé : ce que le back-office doit rappeler.
    {
        "key": "a_facturer", "slot": (-3, "soir"), "ref": "R-YT7CD4",
        "name": "Marc Lefeuvre", "email": "marc.lefeuvre@example.com",
        "phone": "06 12 90 44 78", "address": "8 chemin de la Loire, Couëron",
        "guests": 4, "formula": "decouverte", "message": "",
        "mail": ("sent", "sent", ""),
        "payments": [],
    },
    # Réservée sans choisir de formule, et confirmation jamais partie parce
    # que l'envoi était coupé : le brouillon part alors d'une ligne à zéro,
    # à chiffrer à la main.
    {
        "key": "sans_formule", "slot": (-31, "midi"), "ref": "R-D2VYN8",
        "name": "Farid Benali", "email": "farid.benali@example.com",
        "phone": "", "address": "Salle des fêtes, Bouguenais",
        "guests": 9, "formula": None,
        "message": "On verra le menu ensemble, plutôt méditerranéen.",
        "mail": ("disabled", "disabled", "SMTP_HOST non configuré"),
        "invoice": {
            "status": "draft", "due": 30,
            "lines": [("Prestation de chef à domicile — déjeuner du {date}, 9 convives", 1, 0)],
        },
        "payments": [],
    },
    # À venir, brouillon de facture en attente : éditable, sans numéro.
    {
        "key": "brouillon", "slot": (9, "soir"), "ref": "R-KMN3W7",
        "name": "Élodie Grangier", "email": "elodie.grangier@example.com",
        "phone": "07 88 21 65 40", "address": "5 rue Kervégan, Nantes",
        "guests": 10, "formula": "signature",
        "message": "Deux personnes végétariennes, une allergie aux fruits à coque.",
        "mail": ("sent", "sent", ""),
        "invoice": {
            "status": "draft", "due": 30,
            "lines": [("Menu Signature — dîner du {date}", 10, 7800)],
        },
        "payments": [("acompte", 23400, "virement", -1, "Acompte reçu avant facture")],
    },
    # À venir, e-mail de confirmation en échec : le cas que le chef doit voir.
    {
        "key": "mail_ko", "slot": (16, "soir"), "ref": "R-QF62DA",
        "name": "Antoine Vasseur", "email": "antoine.vasseur@example.com",
        # Ni téléphone ni adresse : le formulaire ne les exige pas, et le
        # back-office doit rester lisible quand le client s'en tient au
        # minimum — y compris le lien d'itinéraire, qui explique son absence.
        "phone": "", "address": "",
        "guests": 6, "formula": "decouverte", "message": "",
        "mail": ("failed", "sent", "SMTPRecipientsRefused: 550 mailbox unavailable"),
        "payments": [],
    },
    # Annulée par le chef, acompte remboursé : la somme des encaissements
    # retombe à zéro sans qu'aucune ligne ne soit effacée.
    {
        "key": "annulee", "slot": (23, "midi"), "ref": "R-LW8JCH",
        "name": "Nadia Bouchard", "email": "nadia.bouchard@example.com",
        "phone": "06 33 77 12 84", "address": "19 rue du Calvaire, Nantes",
        "guests": 5, "formula": "decouverte", "message": "",
        "status": "cancelled", "cancelled": -2,
        "mail": ("sent", "sent", ""),
        "payments": [
            ("acompte", 6750, "cb", -12, ""),
            ("remboursement", -6750, "virement", -2, "Annulation du chef, remboursement intégral"),
        ],
    },
]


# --- Application -------------------------------------------------------

def _purge(conn) -> int:
    """Retire les lignes de démonstration, et elles seules.

    Les réservations partent les premières : leurs encaissements et leurs
    factures suivent en cascade (`ON DELETE CASCADE`, `PRAGMA foreign_keys =
    ON`). Les créneaux ne partent qu'ensuite, et **seulement s'ils sont
    vides** : un créneau de démonstration sur lequel une vraie réservation
    aurait atterri reste en place avec elle, plutôt que de l'emporter en
    cascade. Même chose pour une formule encore citée par une réservation
    survivante -- sans quoi son historique perdrait son tarif.
    """
    conn.execute("DELETE FROM bookings WHERE demo = 1")
    removed = conn.execute(
        "DELETE FROM slots WHERE demo = 1 AND id NOT IN (SELECT slot_id FROM bookings)"
    ).rowcount
    kept = conn.execute("SELECT COUNT(*) AS n FROM slots WHERE demo = 1").fetchone()["n"]
    if kept:
        log.warning("%d créneau(x) de démonstration conservés : une réservation réelle "
                    "s'y trouve", kept)
    conn.execute(
        "DELETE FROM formulas WHERE demo = 1 AND id NOT IN "
        "(SELECT formula_id FROM bookings WHERE formula_id IS NOT NULL)")
    return removed


def _has_real_bookings(conn) -> bool:
    return conn.execute("SELECT 1 FROM bookings WHERE demo = 0 LIMIT 1").fetchone() is not None


def _insert(conn) -> None:
    now = billing.now_iso()

    formula_ids = {}
    formula_names = {}
    for position, (slug, name, description, pricing, price, min_guests, active) in enumerate(FORMULAS):
        cur = conn.execute(
            """INSERT INTO formulas (slug, name, description, pricing, price_cents,
                                     min_guests, active, position, demo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (slug, name, description, pricing, price, min_guests, active, position, now),
        )
        formula_ids[slug] = cur.lastrowid
        formula_names[slug] = name

    slot_ids = {}
    for offset, service, note in SLOTS:
        cur = conn.execute(
            "INSERT INTO slots (date, service, note, created_at, demo) VALUES (?, ?, ?, ?, 1)",
            (_d(offset), service, note, now),
        )
        slot_ids[(offset, service)] = cur.lastrowid

    for spec in BOOKINGS:
        slot_key = tuple(spec["slot"])
        slot_date = _d(slot_key[0])
        mail_client, mail_chef, mail_error = spec["mail"]
        # Une réservation peut n'avoir aucune formule : le client verra plus
        # tard avec le chef. Le libellé reste vide et la facture part d'une
        # ligne à chiffrer.
        slug = spec["formula"]
        cur = conn.execute(
            """INSERT INTO bookings (ref, slot_id, name, email, phone, address, guests,
                                     formula, formula_id, message, status, created_at,
                                     cancelled_at, mail_client, mail_chef, mail_error, demo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (spec["ref"], slot_ids[slot_key], spec["name"], spec["email"], spec["phone"],
             spec["address"], spec["guests"],
             formula_names.get(slug, "") if slug else "",
             formula_ids.get(slug) if slug else None, spec["message"],
             spec.get("status", "confirmed"), _d(slot_key[0] - 30),
             _d(spec["cancelled"]) if spec.get("cancelled") is not None else None,
             mail_client, mail_chef, mail_error),
        )
        booking_id = cur.lastrowid

        for kind, amount, method, offset, note in spec.get("payments", []):
            conn.execute(
                """INSERT INTO payments (booking_id, kind, amount_cents, method,
                                         received_on, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (booking_id, kind, amount, method, _d(offset), note, now),
            )

        booking = {
            "id": booking_id, "name": spec["name"], "email": spec["email"],
            "phone": spec["phone"], "address": spec["address"],
        }
        if spec.get("cancelled_invoice"):
            _insert_invoice(conn, booking, slot_date, spec["cancelled_invoice"],
                            status="cancelled", now=now)
        if spec.get("invoice"):
            _insert_invoice(conn, booking, slot_date, spec["invoice"],
                            status=spec["invoice"]["status"], now=now)


def _insert_invoice(conn, booking: dict, slot_date: str, spec: dict, status: str, now: str) -> None:
    lines = [(label.format(date=slot_date), qty, unit) for label, qty, unit in spec["lines"]]
    # Le taux est figé sur la facture, jamais relu dans la config : une facture
    # émise sous un régime ne doit pas changer quand le régime change.
    vat = int(spec.get("vat_rate_bp", config.VAT_RATE_BP))
    total = sum(qty * unit for _, qty, unit in lines)
    issued_on = _d(spec["issued"]) if spec.get("issued") is not None else None
    # Numéro pris sur l'année de la date de facture, comme en vrai : un
    # semis joué début janvier ne doit pas dater ses exemples de l'an neuf.
    number = None
    if status != "draft":
        number = billing.next_number(conn, date.fromisoformat(issued_on or _d(0)))
    cur = conn.execute(
        """INSERT INTO invoices (booking_id, number, status, issued_on, due_on,
                                 vat_rate_bp, vat_note, seller_json, client_json,
                                 notes, total_cents, created_at, issued_at,
                                 cancelled_at, cancel_reason, mail_status, mail_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (booking["id"], number, status, issued_on,
         _d(spec["due"]) if spec.get("due") is not None else None,
         vat, config.VAT_NOTE,
         json.dumps(billing.seller_identity(), ensure_ascii=False),
         json.dumps(billing.client_identity(booking), ensure_ascii=False),
         spec.get("notes", ""),
         0 if status == "draft" else total, now,
         issued_on, _d(0) if status == "cancelled" else None,
         spec.get("reason", ""), spec.get("mail", "pending"),
         spec.get("mail_error", "")),
    )
    invoice_id = cur.lastrowid
    for position, (label, qty, unit) in enumerate(lines):
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, label, quantity, unit_cents, position)"
            " VALUES (?, ?, ?, ?, ?)",
            (invoice_id, label, qty, unit, position),
        )


def apply() -> None:
    """Appelé au démarrage, après `db.init()`."""
    stored = db.meta_get(_MARKER, "")

    if not config.SEED_DEMO:
        if stored:
            with db.transaction() as conn:
                removed = _purge(conn)
                conn.execute("DELETE FROM meta WHERE key = ?", (_MARKER,))
            log.info("SEED_DEMO off - %d créneau(x) de démonstration retirés", removed)
        return

    with db.transaction() as conn:
        if _has_real_bookings(conn):
            # De vraies réservations sont arrivées : les exemples s'effacent et
            # ne reviennent pas. Mélanger les deux fabriquerait une facture de
            # démonstration indiscernable d'une vraie.
            removed = _purge(conn)
            conn.execute("DELETE FROM meta WHERE key = ?", (_MARKER,))
            if removed or stored:
                log.warning("réservations réelles présentes - jeu de démonstration retiré "
                            "(%d créneau(x)) et non rejoué", removed)
            return

        if stored == str(SEED_VERSION):
            return

        removed = _purge(conn)
        _insert(conn)
        db.meta_set(conn, _MARKER, str(SEED_VERSION))

    log.info("jeu de démonstration v%s posé (%d créneau(x) remplacé(s), version stockée %r)",
             SEED_VERSION, removed, stored or "aucune")
