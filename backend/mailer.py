"""Transactional mail: the client's confirmation and the chef's notification.

A booking confirmation that quietly fails to send is worse than no email at
all -- the client believes they are expected and the chef never hears about
it. So sending never raises into the request path, but every outcome is
written back onto the booking row and surfaced in the back-office.
"""

import logging
import smtplib
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from . import config, db, diets, money

log = logging.getLogger("chef.mail")

SERVICE_LABEL = {"midi": "déjeuner", "soir": "dîner"}


def _send(to: str, subject: str, body: str, reply_to: str = "",
          attachment: tuple[str, str] | None = None) -> tuple[str, str]:
    """Returns (status, error). status is 'sent' | 'failed' | 'disabled'."""
    if not config.mail_enabled():
        log.warning("mail disabled (SMTP_HOST unset) -- not sending %r to %s", subject, to)
        return "disabled", "SMTP_HOST non configuré"
    if not to:
        return "failed", "destinataire vide"

    # max_line_length large : par défaut (78) un sujet accentué est découpé en
    # deux mots encodés, et Gmail rend alors une espace en trop au point de
    # coupure -- constaté sur un envoi réel. Un seul fragment supprime la cause.
    # Raccourcir le sujet ne suffisait pas : le découpage vient des accents.
    msg = EmailMessage(policy=policy.SMTP.clone(max_line_length=900))
    msg["From"] = formataddr((config.MAIL_FROM_NAME or None, config.MAIL_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if attachment:
        filename, html = attachment
        # Pièce jointe HTML plutôt qu'un PDF : le dépôt s'interdit une
        # bibliothèque de rendu, et le navigateur du client imprime la page en
        # PDF s'il en veut un. Le corps texte porte déjà le montant et
        # l'échéance, donc un client qui n'ouvre pas la pièce jointe sait quand
        # même ce qu'il doit.
        msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html",
                           filename=filename)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT) as smtp:
            if config.SMTP_STARTTLS:
                smtp.starttls()
                smtp.ehlo()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("mail to %s failed: %s", to, exc)
        return "failed", f"{type(exc).__name__}: {exc}"

    log.info("mail sent to %s (%s)", to, subject)
    return "sent", ""


def _short_date(iso_date: str) -> str:
    """Date courte pour les sujets. Un sujet long est replié par l'encodeur
    d'en-tête MIME, ce qui insère une espace parasite au point de coupure --
    et se lit mal dans une liste de messages sur téléphone."""
    from datetime import date

    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre"]
    d = date.fromisoformat(iso_date)
    return f"{d.day} {months[d.month - 1]}"


def _pretty_date(iso_date: str) -> str:
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre"]
    from datetime import date

    d = date.fromisoformat(iso_date)
    return f"{days[d.weekday()]} {d.day} {months[d.month - 1]} {d.year}"


def _diet_block(booking: dict, indent: str = "  ") -> str:
    """Bloc régimes, TOUJOURS présent — y compris vide.

    Un bloc qui disparaît quand il n'y a rien à dire est indistinguable d'un
    bloc oublié : le chef ne saurait pas s'il n'y a pas d'allergie ou si la
    question n'a pas été posée. Il est donc écrit dans les deux cas.
    """
    lines = diets.text_lines(booking.get("diets"))
    if not lines:
        return f"{indent}Régimes    : aucun signalé\n"
    body = f"\n{indent}             ".join(lines)
    return f"{indent}Régimes    : {body}\n"


def _client_body(booking: dict, site_name: str) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return (
        f"Bonjour {booking['name']},\n\n"
        f"Votre réservation est confirmée.\n\n"
        f"  Date       : {_pretty_date(booking['date'])} ({service})\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or 'à définir ensemble'}\n"
        f"{_diet_block(booking)}"
        f"  Référence  : {booking['ref']}\n\n"
        f"Je vous recontacte rapidement pour caler le menu et les derniers "
        f"détails (matériel sur place, horaire d'arrivée). Si la ligne "
        f"« Régimes » ci-dessus est incomplète ou fausse, dites-le moi : "
        f"c'est sur elle que je construis le menu.\n\n"
        f"{_follow_block(booking)}"
        f"À très bientôt,\n{site_name}\n"
    )


def _follow_block(booking: dict) -> str:
    """Le lien de suivi remplace « répondez à cet e-mail » quand il existe.

    Les deux ensemble diraient au client de choisir entre une page et une
    boîte mail pour le même geste ; l'e-mail reste nommé comme le recours,
    puisque la page ferme l'annulation quelques jours avant le repas.
    """
    url = follow_url(booking)
    if not url:
        return "Pour annuler ou modifier, répondez simplement à cet e-mail.\n\n"
    return (f"Le détail de votre réservation, votre facture et l'annulation "
            f"sont ici, ce lien est le vôtre :\n\n  {url}\n\n"
            f"Pour tout le reste, répondez simplement à cet e-mail.\n\n")


def follow_url(booking: dict) -> str:
    """Lien de la page de suivi. Vide si la réservation n'a pas de jeton --
    on préfère une phrase en moins qu'un lien qui tombe sur une 404."""
    token = booking.get("token") or ""
    return f"{config.PUBLIC_URL}/r/{token}" if token else ""


def _address(booking: dict) -> str:
    parts = [(booking.get("address") or "").strip(), (booking.get("city") or "").strip()]
    return ", ".join(p for p in parts if p) or "—"


def _chef_body(booking: dict) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return (
        f"Nouvelle réservation ({booking['ref']})\n\n"
        f"  Date       : {_pretty_date(booking['date'])} ({service})\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or '—'}\n"
        f"{_diet_block(booking)}\n"
        f"  Client     : {booking['name']}\n"
        f"  E-mail     : {booking['email']}\n"
        f"  Téléphone  : {booking['phone'] or '—'}\n"
        f"  Adresse    : {_address(booking)}\n\n"
        f"  Message    : {booking['message'] or '—'}\n\n"
        f"Back-office : {config.PUBLIC_URL}/admin\n"
        + (f"Page du client : {follow_url(booking)}\n" if follow_url(booking) else "")
    )


def _client_cancelled_chef_body(booking: dict, paid: int) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    # Le solde encaissé est écrit en toutes lettres, y compris à zéro : c'est
    # la seule ligne qui engage de l'argent, et « rien à rembourser » doit se
    # lire aussi clairement que le contraire.
    money_line = (f"  ⚠ ARGENT   : {money.format_amount(paid)} déjà encaissé — à rembourser.\n"
                  if paid > 0 else "  Argent     : rien encaissé, rien à rembourser.\n")
    return (
        f"Le client a annulé lui-même ({booking['ref']}).\n\n"
        f"  Date       : {_pretty_date(booking['date'])} ({service})\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Client     : {booking['name']}\n"
        f"  E-mail     : {booking['email']}\n"
        f"  Téléphone  : {booking['phone'] or '—'}\n"
        f"{money_line}"
        f"\nLe créneau est de nouveau libre sur le site.\n\n"
        f"Back-office : {config.PUBLIC_URL}/admin\n"
    )


def _client_cancelled_ack_body(booking: dict, site_name: str, paid: int) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    money_line = (f"\nVous aviez versé {money.format_amount(paid)} : je vous recontacte "
                  f"très vite pour le remboursement.\n" if paid > 0 else "")
    return (
        f"Bonjour {booking['name']},\n\n"
        f"Votre annulation est enregistrée : le repas du "
        f"{_pretty_date(booking['date'])} ({service}), référence {booking['ref']}, "
        f"n'aura pas lieu.\n"
        f"{money_line}\n"
        f"Si vous souhaitez reporter plutôt qu'annuler, répondez à cet e-mail : "
        f"je vous garde une date.\n\n"
        f"À une prochaine fois,\n{site_name}\n"
    )


def notify_chef_client_cancelled(booking: dict, paid: int) -> None:
    """Tâche de fond : prévenir le chef qu'un client s'est désisté.

    Le résultat n'est pas écrit sur la réservation : les colonnes `mail_*`
    décrivent la confirmation initiale, et les écraser effacerait la trace de
    ce qui s'est passé au moment de la réservation.
    """
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    _send(
        config.MAIL_TO,
        f"[Annulation client] {_short_date(booking['date'])} {service} — {booking['name']}"
        + (" 💶 acompte à rendre" if paid > 0 else ""),
        _client_cancelled_chef_body(booking, paid),
        reply_to=booking["email"],
    )


def send_client_cancellation_ack(booking: dict, site_name: str, paid: int) -> None:
    """Tâche de fond : accuser réception au client qui vient d'annuler."""
    _send(
        booking["email"],
        f"Annulation enregistrée — réservation {booking['ref']}",
        _client_cancelled_ack_body(booking, site_name, paid),
        reply_to=config.MAIL_TO or "",
    )


def _cancel_body(booking: dict, site_name: str, reason: str) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    tail = f"\nMotif : {reason}\n" if reason else ""
    return (
        f"Bonjour {booking['name']},\n\n"
        f"Votre réservation du {_pretty_date(booking['date'])} ({service}), "
        f"référence {booking['ref']}, a dû être annulée.\n{tail}\n"
        f"Je suis désolé pour ce contretemps — répondez à cet e-mail et nous "
        f"trouverons une autre date.\n\n"
        f"{site_name}\n"
    )


def _record(booking_id: int, client: str, chef: str, error: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE bookings SET mail_client = ?, mail_chef = ?, mail_error = ? WHERE id = ?",
            (client, chef, error[:500], booking_id),
        )


def send_client_confirmation(booking: dict, site_name: str) -> tuple[str, str]:
    """Sent inline, before the HTTP response.

    The confirmation page tells the visitor whether the mail left; that claim
    has to be true, and it cannot be if the send happens after the response.
    """
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return _send(
        booking["email"],
        f"Réservation confirmée — {_short_date(booking['date'])} ({service})",
        _client_body(booking, site_name),
        reply_to=config.MAIL_TO or "",
    )


def send_chef_notification(booking: dict) -> tuple[str, str]:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return _send(
        config.MAIL_TO,
        f"[Réservation] {_short_date(booking['date'])} {service} — {booking['name']}, "
        f"{booking['guests']} couverts"
        + (" ⚠ allergie" if diets.has_allergy(booking.get("diets")) else ""),
        _chef_body(booking),
        reply_to=booking["email"],
    )


def notify_chef(booking: dict, client_status: str, client_error: str) -> None:
    """Background task: the chef's copy, plus the recorded outcome of both."""
    chef_status, chef_err = send_chef_notification(booking)
    error = " | ".join(dict.fromkeys(p for p in (client_error, chef_err) if p))
    _record(booking["id"], client_status, chef_status, error)


def send_booking_mails(booking: dict, site_name: str) -> None:
    """Full pair, used by the back-office "renvoyer" action."""
    client_status, client_err = send_client_confirmation(booking, site_name)
    notify_chef(booking, client_status, client_err)


def send_cancellation_mail(booking: dict, site_name: str, reason: str) -> None:
    """Background task: tell the client the chef cancelled."""
    status, err = _send(
        booking["email"],
        f"Annulation — réservation {booking['ref']}",
        _cancel_body(booking, site_name, reason),
        reply_to=config.MAIL_TO or "",
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE bookings SET mail_client = ?, mail_error = ? WHERE id = ?",
            (status, err[:500], booking["id"]),
        )


def send_invoice(invoice: dict, site_name: str, html: str) -> tuple[str, str]:
    """Envoie une facture émise au client et inscrit le résultat sur la facture.

    Le résultat est écrit sur la ligne, comme pour les confirmations : une
    facture partie et une facture qu'on croit partie ne se distinguent
    autrement par rien, et c'est le chef qui court après le paiement.
    """
    status, err = _send(
        invoice["client"].get("email", ""),
        f"Facture {invoice['number']} — {site_name}",
        _invoice_body(invoice, site_name),
        reply_to=config.MAIL_TO or "",
        attachment=(f"facture-{invoice['number']}.html", html),
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE invoices SET mail_status = ?, mail_error = ?, mail_sent_at = ? WHERE id = ?",
            (status, err[:500],
             datetime.now(config.TZ).isoformat(timespec="seconds") if status == "sent" else None,
             invoice["id"]),
        )
    return status, err


def _invoice_body(invoice: dict, site_name: str) -> str:
    from . import invoice_html

    return invoice_html.text_summary(invoice, site_name)
