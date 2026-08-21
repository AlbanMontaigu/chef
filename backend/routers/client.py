"""Page de suivi du client : ce qu'il peut voir et faire avec sa réservation.

Jusqu'ici le client repartait avec une référence `R-XXXXXX` et rien pour s'en
servir : toute question, toute annulation passait par un e-mail ou un coup de
fil au chef. Ce routeur lui donne une page.

**Le jeton, pas la référence.** La référence est faite pour être dictée au
téléphone -- six caractères, alphabet sans sosies -- donc devinable. Elle ne
peut pas ouvrir un dossier. Chaque réservation porte donc un jeton séparé de
128 bits, qui n'apparaît que dans le lien envoyé au client.

**Le serveur décide seul si l'annulation est possible.** La page affiche le
bouton d'après ce que dit `/api/r/{token}`, mais c'est `POST .../cancel` qui
refait le contrôle : un bouton affiché n'est pas une autorisation.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse

from .. import billing, config, content, db, diets, invoice_html, mailer, money

log = logging.getLogger("chef.client")

router = APIRouter(prefix="/api/r", tags=["client"])

SERVICE_LABEL = {"midi": "déjeuner", "soir": "dîner"}


def _load(token: str) -> dict:
    """Réservation désignée par son jeton, ou 404.

    Un jeton vide ne cherche rien : sans ce garde, une base contenant encore
    des lignes sans jeton (le temps d'une migration) rendrait `/r/` équivalent
    à « la première réservation venue ».
    """
    if not token or len(token) < 16:
        raise HTTPException(404, "Lien inconnu.")
    with db.cursor() as conn:
        row = conn.execute(
            """SELECT b.*, s.date, s.service, s.note FROM bookings b
               JOIN slots s ON s.id = b.slot_id WHERE b.token = ?""",
            (token,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Ce lien ne correspond à aucune réservation.")
    return dict(row)


def _cancellation(conn, booking: dict) -> dict:
    """Peut-il annuler lui-même, et sinon pourquoi.

    Le motif est TOUJOURS renvoyé, même quand c'est possible : la page dit au
    client jusqu'à quand il peut le faire, plutôt que de lui laisser découvrir
    la fermeture du guichet le jour où il en a besoin.
    """
    days = int(content.load()["booking"].get("cancel_days", 7))
    limit = (billing.today() + timedelta(days=days)).isoformat()
    if booking["status"] != "confirmed":
        return {"allowed": False, "days": days, "limit": limit,
                "reason": "Cette réservation est déjà annulée."}
    if booking["date"] < billing.today().isoformat():
        return {"allowed": False, "days": days, "limit": limit,
                "reason": "Ce repas a déjà eu lieu."}
    invoice = billing.live_invoice(conn, booking["id"])
    if invoice and invoice["status"] == "issued":
        # Une facture émise est un document parti chez le client ; l'annuler
        # est un geste comptable, pas un clic. Le chef s'en charge.
        return {"allowed": False, "days": days, "limit": limit,
                "reason": "Une facture a déjà été émise pour ce repas : "
                          "écrivez-moi, je m'en occupe avec vous."}
    if booking["date"] < limit:
        return {"allowed": False, "days": days, "limit": limit,
                "reason": f"L'annulation en ligne ferme {days} jours avant le repas — "
                          f"les courses sont engagées. Écrivez-moi, on trouvera une solution."}
    return {"allowed": True, "days": days, "limit": limit,
            "reason": f"Vous pouvez annuler vous-même jusqu'à {days} jours avant le repas."}


def _view(booking: dict) -> dict:
    with db.cursor() as conn:
        invoice = billing.live_invoice(conn, booking["id"])
        paid = billing.paid_cents(conn, booking["id"])
        cancellation = _cancellation(conn, booking)
        invoice_view = None
        if invoice and invoice["status"] == "issued":
            total = int(invoice["total_cents"])
            invoice_view = {
                "number": invoice["number"],
                "issued_on": invoice["issued_on"],
                "due_on": invoice["due_on"],
                "total_cents": total,
                "total": money.format_amount(total),
                "paid_cents": paid,
                "paid": money.format_amount(paid),
                "balance_cents": total - paid,
                "balance": money.format_amount(total - paid),
                "state": billing.payment_state(total, paid),
            }
    site = content.load()
    return {
        "site": site.get("name") or "",
        "ref": booking["ref"],
        "status": booking["status"],
        "date": booking["date"],
        "service": booking["service"],
        "guests": booking["guests"],
        "formula": booking["formula"],
        "address": booking["address"],
        "city": booking["city"],
        "message": booking["message"],
        "diets": diets.describe(booking["diets"]),
        # Montré même sans facture : un acompte encaissé avant facturation
        # existe, et le client doit le retrouver.
        "paid_cents": paid,
        "paid": money.format_amount(paid),
        "invoice": invoice_view,
        "cancellation": cancellation,
        "contact": site.get("contact") or {},
        "cancelled_at": booking["cancelled_at"],
    }


@router.get("/{token}")
def read(token: str) -> dict:
    return _view(_load(token))


@router.post("/{token}/cancel")
def cancel(token: str, background: BackgroundTasks) -> dict:
    booking = _load(token)
    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    with db.transaction() as conn:
        # Le droit d'annuler est recontrôlé ici, dans la transaction qui écrit :
        # l'état affiché à la page peut dater de plusieurs minutes, et le
        # bouton n'est qu'un affichage.
        verdict = _cancellation(conn, booking)
        if not verdict["allowed"]:
            raise HTTPException(409, verdict["reason"])
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (now, booking["id"]),
        )
        paid = billing.paid_cents(conn, booking["id"])
    booking["cancelled_at"] = now
    booking["status"] = "cancelled"
    log.info("booking %s cancelled by the client", booking["ref"])
    # Le créneau redevient libre tout seul : l'index partiel ne compte que les
    # réservations confirmées. Le chef, lui, doit l'apprendre — et savoir tout
    # de suite si de l'argent est à rendre.
    background.add_task(mailer.notify_chef_client_cancelled, dict(booking), paid)
    background.add_task(mailer.send_client_cancellation_ack, dict(booking),
                        content.site_name(), paid)
    return _view(_load(token))


@router.get("/{token}/invoice", response_class=HTMLResponse)
def view_invoice(token: str) -> HTMLResponse:
    """La facture du client, telle qu'elle lui a été envoyée.

    Seulement émise : un brouillon est une intention du chef, pas un document,
    et le montrer ferait discuter un client sur un chiffre qui va changer.
    """
    booking = _load(token)
    with db.cursor() as conn:
        invoice = billing.live_invoice(conn, booking["id"])
        if invoice is None or invoice["status"] != "issued":
            raise HTTPException(404, "Aucune facture émise pour cette réservation.")
        view = billing.invoice_view(conn, invoice["id"])
        payments = billing.payments_of(conn, booking["id"])
    # Même rendu que celui envoyé au client et relu par le chef : un seul
    # document, donc aucun écart possible entre les trois.
    return HTMLResponse(invoice_html.render(view, payments),
                        headers={"Cache-Control": "no-store"})
