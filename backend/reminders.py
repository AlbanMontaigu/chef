"""Rappels et relances : ce que personne ne regardait.

`invoices.due_on` était saisi, imprimé sur la facture, et **lu par personne**.
Aucun rappel avant un repas, aucune relance d'impayé, aucun signal au chef sur
un repas servi et jamais facturé. Ce module est ce qui regarde.

Il fonctionne en **deux temps séparés**, et c'est tout le dessin :

1. `plan()` inscrit ce qui *devra* partir, avec sa date. Un index unique sur
   (nature, cible, échéance) rend l'inscription idempotente : replanifier
   cent fois n'ajoute rien. C'est ce qui garantit qu'une relance ne part pas
   deux fois, même si le processus redémarre en boucle.
2. `flush()` envoie ce qui est dû. Chaque envoi **revérifie sa propre raison
   d'être** juste avant de partir : une réservation annulée entre-temps ne
   reçoit pas son rappel, une facture soldée hier ne reçoit pas sa relance.
   Sans ce contrôle, la file d'attente enverrait des vérités périmées — et
   relancer un client qui a déjà payé coûte plus cher que de se taire.

**Un rappel manqué est pire qu'un rappel en double.** Le compteur de
tentatives est incrémenté et commité *avant* l'envoi : si le processus meurt
entre le `250 OK` du serveur SMTP et l'écriture du résultat — une fenêtre de
quelques millisecondes — la relance repartira une fois. C'est le compromis
choisi, assumé, et borné à trois tentatives.

Rien n'est silencieux : chaque ligne garde son état, son destinataire, son
motif d'abandon ou son erreur, et le back-office les montre.
"""

import logging
from datetime import date, datetime, timedelta

from . import billing, config, content, db, mailer

log = logging.getLogger("chef.reminders")

# Natures de rappel. Le libellé sert au back-office ; l'identifiant est
# stocké en base et cité par l'index d'unicité : le renommer réenverrait
# tout l'historique.
KIND_LABEL = {
    "repas_proche": "Rappel au client, avant le repas",
    "facture_echue": "Relance d'impayé, au client",
    "a_facturer": "Repas servi non facturé, au chef",
}

STATUS_LABEL = {
    "pending": "en attente",
    "sent": "envoyé",
    "failed": "en échec",
    "skipped": "abandonné",
}


def _now() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def _target(kind_id: str, row_id: int) -> str:
    return f"{kind_id}:{int(row_id)}"


def _insert(conn, kind: str, target: str, due_on: str, recipient: str) -> bool:
    """Inscrit un rappel s'il n'existe pas déjà. Renvoie True s'il est neuf.

    `INSERT OR IGNORE` sur l'index unique (kind, target, due_on) : c'est là,
    et nulle part dans du Python, que se joue le « une seule fois ».
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO reminders (kind, target, due_on, recipient, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (kind, target, due_on, recipient, _now()),
    )
    return cur.rowcount > 0


# --- Planification -----------------------------------------------------

def plan(conn, today: date) -> int:
    """Inscrit tout ce qui devra partir. Idempotent, appelé à chaque tick."""
    created = 0
    created += _plan_meals(conn, today)
    created += _plan_overdue_invoices(conn, today)
    created += _plan_to_invoice(conn, today)
    if created:
        log.info("%d rappel(s) planifié(s)", created)
    return created


def _plan_meals(conn, today: date) -> int:
    """Rappel au client, quelques jours avant le repas.

    Planifié seulement pour les repas encore à venir : inscrire un rappel dont
    la date est déjà passée le ferait partir immédiatement, après le repas.
    """
    rows = conn.execute(
        """SELECT b.id, b.email, s.date FROM bookings b JOIN slots s ON s.id = b.slot_id
           WHERE b.status = 'confirmed' AND s.date >= ? AND b.email <> ''""",
        (today.isoformat(),),
    ).fetchall()
    created = 0
    for row in rows:
        due = date.fromisoformat(row["date"]) - timedelta(days=config.REMINDER_MEAL_DAYS)
        if due < today:
            continue
        created += _insert(conn, "repas_proche", _target("booking", row["id"]),
                           due.isoformat(), row["email"])
    return created


def _plan_overdue_invoices(conn, today: date) -> int:
    """Relances d'impayé. Plusieurs échéances, donc plusieurs lignes.

    Chaque occurrence porte sa propre date et devient donc une ligne distincte
    au regard de l'index : deux relances espacées, jamais deux fois la même.
    Elles ne sont inscrites que si la facture est réellement impayée au moment
    de la planification, et revérifiées à l'envoi.
    """
    rows = conn.execute(
        """SELECT i.id, i.booking_id, i.due_on, i.total_cents,
                  (SELECT COALESCE(SUM(p.amount_cents), 0) FROM payments p
                    WHERE p.booking_id = i.booking_id) AS paid
           FROM invoices i
           WHERE i.status = 'issued' AND i.due_on IS NOT NULL AND i.due_on <> ''""",
    ).fetchall()
    created = 0
    for row in rows:
        if int(row["paid"]) >= int(row["total_cents"]):
            continue
        booking = conn.execute(
            "SELECT email FROM bookings WHERE id = ?", (row["booking_id"],)
        ).fetchone()
        if booking is None or not booking["email"]:
            continue
        base = date.fromisoformat(row["due_on"])
        for offset in config.REMINDER_INVOICE_DAYS:
            created += _insert(conn, "facture_echue", _target("invoice", row["id"]),
                               (base + timedelta(days=offset)).isoformat(),
                               booking["email"])
    return created


def _plan_to_invoice(conn, today: date) -> int:
    """Signal au chef : un repas servi, aucune facture. De l'argent oublié.

    Une seule occurrence, quelques jours après le repas -- au-delà, c'est un
    harcèlement de sa propre boîte mail, et le back-office l'affiche déjà en
    permanence dans son résumé.
    """
    if not config.MAIL_TO:
        return 0
    rows = conn.execute(
        """SELECT b.id, s.date FROM bookings b JOIN slots s ON s.id = b.slot_id
           WHERE b.status = 'confirmed' AND s.date < ?
             AND NOT EXISTS (SELECT 1 FROM invoices i
                             WHERE i.booking_id = b.id AND i.status <> 'cancelled')""",
        (today.isoformat(),),
    ).fetchall()
    created = 0
    for row in rows:
        due = date.fromisoformat(row["date"]) + timedelta(days=config.REMINDER_INVOICE_LAG)
        created += _insert(conn, "a_facturer", _target("booking", row["id"]),
                           due.isoformat(), config.MAIL_TO)
    return created


# --- Pertinence, revérifiée juste avant l'envoi ------------------------

def _context(conn, kind: str, target: str) -> tuple[dict | None, str]:
    """(données de l'envoi, motif d'abandon).

    Un motif non vide veut dire « ne pas envoyer, et dire pourquoi ». La
    raison d'être du rappel est recalculée depuis la base, jamais relue depuis
    la ligne de rappel : c'est le monde qui a pu changer, pas l'intention.
    """
    what, _, raw_id = target.partition(":")
    row_id = int(raw_id)

    if kind in ("repas_proche", "a_facturer"):
        row = conn.execute(
            """SELECT b.*, s.date, s.service FROM bookings b
               JOIN slots s ON s.id = b.slot_id WHERE b.id = ?""",
            (row_id,),
        ).fetchone()
        if row is None:
            return None, "réservation supprimée"
        booking = dict(row)
        if booking["status"] != "confirmed":
            return None, "réservation annulée depuis"
        if kind == "repas_proche":
            if booking["date"] < billing.today().isoformat():
                return None, "le repas a déjà eu lieu"
            return {"booking": booking}, ""
        # a_facturer : le chef a pu facturer entre-temps.
        live = billing.live_invoice(conn, booking["id"])
        if live is not None:
            return None, "facture créée depuis"
        return {"booking": booking}, ""

    if kind == "facture_echue":
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None, "facture supprimée"
        invoice = dict(row)
        if invoice["status"] != "issued":
            return None, f"facture {invoice['status']} depuis"
        paid = billing.paid_cents(conn, invoice["booking_id"])
        balance = int(invoice["total_cents"]) - paid
        if balance <= 0:
            return None, "facture soldée depuis"
        booking = conn.execute(
            """SELECT b.*, s.date, s.service FROM bookings b
               JOIN slots s ON s.id = b.slot_id WHERE b.id = ?""",
            (invoice["booking_id"],),
        ).fetchone()
        if booking is None:
            return None, "réservation supprimée"
        return {"invoice": invoice, "booking": dict(booking), "balance": balance}, ""

    return None, f"nature inconnue ({kind})"


def _deliver(kind: str, ctx: dict) -> tuple[str, str]:
    site = content.site_name()
    if kind == "repas_proche":
        return mailer.send_meal_reminder(ctx["booking"], site)
    if kind == "a_facturer":
        return mailer.send_to_invoice_reminder(ctx["booking"])
    if kind == "facture_echue":
        return mailer.send_invoice_reminder(ctx["invoice"], ctx["booking"],
                                            ctx["balance"], site)
    return "failed", f"nature inconnue ({kind})"


# --- Envoi -------------------------------------------------------------

def flush(today: date) -> dict:
    """Envoie ce qui est dû. Renvoie un compte par issue."""
    tally = {"sent": 0, "failed": 0, "skipped": 0}
    with db.cursor() as conn:
        due = [dict(r) for r in conn.execute(
            """SELECT * FROM reminders WHERE status = 'pending' AND due_on <= ?
               ORDER BY due_on, id LIMIT 200""",
            (today.isoformat(),),
        ).fetchall()]

    for row in due:
        with db.cursor() as conn:
            ctx, giveup = _context(conn, row["kind"], row["target"])
        if giveup:
            _record(row["id"], "skipped", giveup)
            tally["skipped"] += 1
            log.info("rappel %s %s abandonné : %s", row["kind"], row["target"], giveup)
            continue

        # Le compteur monte AVANT l'envoi et il est commité : c'est ce qui borne
        # les dégâts si le processus meurt pendant l'envoi. Cf. l'en-tête du
        # module -- on préfère un doublon possible à un rappel perdu.
        attempts = int(row["attempts"]) + 1
        with db.transaction() as conn:
            conn.execute("UPDATE reminders SET attempts = ? WHERE id = ?", (attempts, row["id"]))

        status, error = _deliver(row["kind"], ctx)
        if status == "sent":
            _record(row["id"], "sent", "")
            tally["sent"] += 1
        elif attempts >= config.REMINDER_MAX_ATTEMPTS:
            # À court de tentatives : la ligne s'arrête sur 'failed' et reste
            # visible dans le back-office. Elle ne repartira pas toute seule.
            _record(row["id"], "failed", error)
            tally["failed"] += 1
            log.error("rappel %s %s abandonné après %d tentatives : %s",
                      row["kind"], row["target"], attempts, error)
        else:
            # Reste 'pending' : le prochain tick réessaiera. L'erreur est
            # conservée pour qu'un échec transitoire se distingue d'une attente.
            _record(row["id"], "pending", error)
            log.warning("rappel %s %s en échec (tentative %d) : %s",
                        row["kind"], row["target"], attempts, error)
    if any(tally.values()):
        log.info("relances : %s", tally)
    return tally


def _record(reminder_id: int, status: str, error: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE reminders SET status = ?, error = ?, sent_at = ? WHERE id = ?",
            (status, error[:500],
             _now() if status == "sent" else None, reminder_id),
        )


def run_once() -> dict:
    """Un tour complet : planifier puis envoyer. C'est le seul point d'entrée."""
    today = billing.today()
    with db.transaction() as conn:
        planned = plan(conn, today)
    tally = flush(today)
    return {"planned": planned, **tally}


# --- Vue back-office ---------------------------------------------------

def overview(conn, limit: int = 60) -> dict:
    """Ce que le back-office affiche : à venir, parti, en échec.

    Les échecs remontent en premier et sans limite d'âge : c'est la seule
    catégorie sur laquelle le chef a quelque chose à faire.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT r.*, b.ref, b.name, s.date, s.service
           FROM reminders r
           LEFT JOIN bookings b ON b.id = CASE
               WHEN r.target LIKE 'booking:%' THEN CAST(substr(r.target, 9) AS INTEGER)
               ELSE (SELECT booking_id FROM invoices
                      WHERE id = CAST(substr(r.target, 9) AS INTEGER)) END
           LEFT JOIN slots s ON s.id = b.slot_id
           ORDER BY r.due_on DESC, r.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()]
    for row in rows:
        row["kind_label"] = KIND_LABEL.get(row["kind"], row["kind"])
        row["status_label"] = STATUS_LABEL.get(row["status"], row["status"])
    return {
        "reminders": rows,
        "failed": sum(1 for r in rows if r["status"] == "failed"),
        "pending": sum(1 for r in rows if r["status"] == "pending"),
        "enabled": config.REMINDERS_ENABLED,
        "mail_enabled": config.mail_enabled(),
        "tick_minutes": config.REMINDER_TICK_MINUTES,
    }


def health() -> dict:
    """Compteurs pour /health : une file qui gonfle doit se voir de l'extérieur."""
    with db.cursor() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM reminders GROUP BY status"
        ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "enabled": config.REMINDERS_ENABLED,
        "pending": counts.get("pending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
    }
