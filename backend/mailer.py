"""Transactional mail: the client's confirmation and the chef's notification.

A booking confirmation that quietly fails to send is worse than no email at
all -- the client believes they are expected and the chef never hears about
it. So sending never raises into the request path, but every outcome is
written back onto the booking row and surfaced in the back-office.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from . import config, db

log = logging.getLogger("chef.mail")

SERVICE_LABEL = {"midi": "déjeuner", "soir": "dîner"}


def _send(to: str, subject: str, body: str, reply_to: str = "") -> tuple[str, str]:
    """Returns (status, error). status is 'sent' | 'failed' | 'disabled'."""
    if not config.mail_enabled():
        log.warning("mail disabled (SMTP_HOST unset) -- not sending %r to %s", subject, to)
        return "disabled", "SMTP_HOST non configuré"
    if not to:
        return "failed", "destinataire vide"

    msg = EmailMessage()
    msg["From"] = formataddr((config.MAIL_FROM_NAME or None, config.MAIL_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

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


def _pretty_date(iso_date: str) -> str:
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre"]
    from datetime import date

    d = date.fromisoformat(iso_date)
    return f"{days[d.weekday()]} {d.day} {months[d.month - 1]} {d.year}"


def _client_body(booking: dict, site_name: str) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return (
        f"Bonjour {booking['name']},\n\n"
        f"Votre réservation est confirmée.\n\n"
        f"  Date       : {_pretty_date(booking['date'])} ({service})\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or 'à définir ensemble'}\n"
        f"  Référence  : {booking['ref']}\n\n"
        f"Je vous recontacte rapidement pour caler le menu et les derniers "
        f"détails (allergies, matériel sur place, horaire d'arrivée).\n\n"
        f"Pour annuler ou modifier, répondez simplement à cet e-mail.\n\n"
        f"À très bientôt,\n{site_name}\n"
    )


def _chef_body(booking: dict) -> str:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return (
        f"Nouvelle réservation ({booking['ref']})\n\n"
        f"  Date       : {_pretty_date(booking['date'])} ({service})\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or '—'}\n\n"
        f"  Client     : {booking['name']}\n"
        f"  E-mail     : {booking['email']}\n"
        f"  Téléphone  : {booking['phone'] or '—'}\n"
        f"  Adresse    : {booking['address'] or '—'}\n\n"
        f"  Message    : {booking['message'] or '—'}\n\n"
        f"Back-office : {config.PUBLIC_URL}/admin\n"
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
        f"Réservation confirmée — {_pretty_date(booking['date'])} ({service})",
        _client_body(booking, site_name),
        reply_to=config.MAIL_TO or "",
    )


def send_chef_notification(booking: dict) -> tuple[str, str]:
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    return _send(
        config.MAIL_TO,
        f"[Réservation] {booking['name']} — {booking['date']} {service} — {booking['guests']} couverts",
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
