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

from . import config, db, diets, menus, money

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


# --- Rappels et relances -----------------------------------------------
# Trois envois programmés, décidés par backend/reminders.py. Ils ne touchent
# PAS aux colonnes `mail_*` de la réservation : celles-ci décrivent la
# confirmation initiale, et les écraser effacerait la trace de ce qui s'est
# passé le jour de la réservation. Leur résultat vit sur la ligne de rappel.

def _menu_recap(booking: dict) -> str:
    """Le menu, repris dans le rappel — seulement s'il a été envoyé.

    Un menu encore en brouillon n'a pas à fuiter par ce chemin : le chef ne l'a
    pas validé, et le client le découvrirait dans un rappel au lieu du message
    qui le lui présente.
    """
    lines = booking.get("menu_lines") or []
    if not lines:
        return ""
    return "Pour mémoire, le menu convenu :\n\n" + menus.text_block(lines) + "\n\n"


def send_meal_reminder(booking: dict, site_name: str) -> tuple[str, str]:
    """Rappel au client, quelques jours avant le repas.

    Il redit les régimes déclarés : c'est le dernier moment utile pour qu'un
    client corrige « finalement on sera sept, et ma belle-sœur est coeliaque ».
    """
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    url = follow_url(booking)
    body = (
        f"Bonjour {booking['name']},\n\n"
        f"Petit rappel : je cuisine chez vous {_pretty_date(booking['date'])} "
        f"({service}).\n\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or 'à définir ensemble'}\n"
        f"{_diet_block(booking)}"
        f"  Lieu       : {_address(booking)}\n"
        f"  Référence  : {booking['ref']}\n\n"
        f"{_menu_recap(booking)}"
        f"Si quelque chose a changé — le nombre de convives, une allergie, "
        f"l'adresse — répondez à cet e-mail : il est encore temps, après il "
        f"sera trop tard pour les courses.\n\n"
        + (f"Votre page de suivi : {url}\n\n" if url else "")
        + f"À très vite,\n{site_name}\n"
    )
    return _send(booking["email"],
                 f"Rendez-vous {_short_date(booking['date'])} ({service})",
                 body, reply_to=config.MAIL_TO or "")


def send_invoice_reminder(invoice: dict, booking: dict, balance: int,
                          site_name: str) -> tuple[str, str]:
    """Relance d'impayé. Le ton reste celui d'un artisan, pas d'un huissier.

    Le montant relancé est le **solde restant**, pas le total : relancer sur
    le total un client qui a versé un acompte lui donne raison de discuter au
    lieu de payer.
    """
    due = f" (échéance du {_pretty_date(invoice['due_on'])})" if invoice.get("due_on") else ""
    url = follow_url(booking)
    body = (
        f"Bonjour {booking['name']},\n\n"
        f"Je me permets un rappel au sujet de la facture {invoice['number']}"
        f"{due}, pour le repas du {_pretty_date(booking['date'])}.\n\n"
        f"  Montant de la facture : {money.format_amount(int(invoice['total_cents']))}\n"
        f"  Reste à régler        : {money.format_amount(balance)}\n\n"
        f"Si le règlement est déjà parti, ce message n'a plus lieu d'être et "
        f"je vous prie de m'en excuser — les virements se croisent.\n\n"
        + (f"La facture et le détail : {url}\n\n" if url else "")
        + f"Merci beaucoup,\n{site_name}\n"
    )
    return _send(booking["email"],
                 f"Facture {invoice['number']} — {money.format_amount(balance)} à régler",
                 body, reply_to=config.MAIL_TO or "")


def send_to_invoice_reminder(booking: dict) -> tuple[str, str]:
    """Signal au chef : un repas servi et jamais facturé. De l'argent oublié."""
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    body = (
        f"Le repas du {_pretty_date(booking['date'])} ({service}) a été servi et "
        f"n'est toujours pas facturé.\n\n"
        f"  Client     : {booking['name']}\n"
        f"  Convives   : {booking['guests']}\n"
        f"  Formule    : {booking['formula'] or '—'}\n"
        f"  Référence  : {booking['ref']}\n\n"
        f"Le brouillon se crée en un clic depuis le dossier.\n\n"
        f"Back-office : {config.PUBLIC_URL}/admin\n"
    )
    return _send(config.MAIL_TO,
                 f"[À facturer] {_short_date(booking['date'])} {service} — {booking['name']}",
                 body, reply_to=booking["email"])


# --- Demandes de devis -------------------------------------------------

def _quote_when(quote: dict) -> str:
    """Ce que la personne a dit de la date. Jamais un blanc : « pas de date
    précise » est une réponse, et le chef doit la lire comme telle."""
    parts = []
    if quote.get("wanted_date"):
        parts.append(_pretty_date(quote["wanted_date"]))
    if quote.get("service"):
        parts.append(SERVICE_LABEL.get(quote["service"], quote["service"]))
    if quote.get("flexibility"):
        parts.append(f"« {quote['flexibility']} »")
    return " · ".join(parts) or "pas de date précise"


def _quote_chef_body(quote: dict) -> str:
    return (
        f"Demande de devis ({quote['ref']})\n\n"
        f"  Quand      : {_quote_when(quote)}\n"
        f"  Convives   : {quote['guests'] or 'non précisé'}\n"
        f"  Occasion   : {quote['occasion'] or '—'}\n"
        f"  Formule    : {quote['formula'] or 'aucune en tête'}\n"
        f"{_diet_block(quote)}\n"
        f"  Client     : {quote['name']}\n"
        f"  E-mail     : {quote['email']}\n"
        f"  Téléphone  : {quote['phone'] or '—'}\n"
        f"  Secteur    : {quote['city'] or '—'}\n\n"
        f"  Message    : {quote['message'] or '—'}\n\n"
        f"Répondez directement à cet e-mail : il part sur son adresse.\n"
        f"Back-office : {config.PUBLIC_URL}/admin\n"
    )


def _quote_ack_body(quote: dict, site_name: str) -> str:
    return (
        f"Bonjour {quote['name']},\n\n"
        f"J'ai bien reçu votre demande et je vous réponds personnellement, "
        f"sous deux jours ouvrés.\n\n"
        f"Ce que j'ai noté :\n\n"
        f"  Quand      : {_quote_when(quote)}\n"
        f"  Convives   : {quote['guests'] or 'à préciser'}\n"
        f"  Occasion   : {quote['occasion'] or 'à préciser'}\n"
        f"  Référence  : {quote['ref']}\n\n"
        f"Attention : **ceci n'est pas une réservation** — aucune date n'est "
        f"bloquée pour l'instant. Nous en fixons une ensemble une fois le "
        f"devis calé.\n\n"
        f"Si j'ai mal compris quelque chose, répondez simplement à cet e-mail.\n\n"
        f"À très vite,\n{site_name}\n"
    )


def send_quote_ack(quote: dict, site_name: str) -> tuple[str, str]:
    """Accusé de réception, envoyé avant la réponse HTTP.

    Il dit noir sur blanc que rien n'est réservé : une demande de devis qui
    ressemble à une confirmation fait attendre un chef qui ne viendra pas.
    """
    return _send(quote["email"], f"Votre demande — {quote['ref']}",
                 _quote_ack_body(quote, site_name), reply_to=config.MAIL_TO or "")


def send_quote_notification(quote: dict) -> tuple[str, str]:
    when = quote.get("wanted_date") and _short_date(quote["wanted_date"]) or "date libre"
    return _send(
        config.MAIL_TO,
        f"[Devis] {when} — {quote['name']}"
        + (f", {quote['guests']} couverts" if quote.get("guests") else ""),
        _quote_chef_body(quote),
        reply_to=quote["email"],
    )


def notify_chef_quote(quote: dict, ref: str, client_status: str, client_error: str) -> None:
    """Tâche de fond : la copie du chef, et l'issue des deux envois.

    Écrite sur la demande comme pour une réservation : un devis dont l'accusé
    n'est jamais parti est une personne qui attend une réponse qu'elle croit
    en route.
    """
    chef_status, chef_err = send_quote_notification(quote)
    error = " | ".join(dict.fromkeys(p for p in (client_error, chef_err) if p))
    with db.transaction() as conn:
        conn.execute(
            "UPDATE quotes SET mail_client = ?, mail_chef = ?, mail_error = ? WHERE ref = ?",
            (client_status, chef_status, error[:500], ref),
        )


# --- Menu --------------------------------------------------------------

def send_menu(booking: dict, menu: dict, site_name: str) -> None:
    """Envoie le menu composé pour ce repas, et inscrit le résultat.

    Le résultat vit sur le menu, pas sur la réservation : les colonnes `mail_*`
    de celle-ci décrivent la confirmation initiale. Un menu qu'on croit parti
    et un menu parti se distinguent sinon par rien -- et le client arriverait
    à table sans savoir ce qu'il mange.
    """
    service = SERVICE_LABEL.get(booking["service"], booking["service"])
    title = menu.get("title") or "Votre menu"
    note = f"\n{menu['note']}\n" if menu.get("note") else ""
    body = (
        f"Bonjour {booking['name']},\n\n"
        f"Voici ce que je vous propose pour le {_pretty_date(booking['date'])} "
        f"({service}), {booking['guests']} convives.\n\n"
        f"  {title}\n\n"
        f"{menus.text_block(menu['lines'])}\n"
        f"{note}\n"
        f"{_diet_block(booking)}"
        f"\nJ'ai construit ce menu sur les contraintes ci-dessus : si l'une "
        f"manque ou a changé, dites-le moi maintenant.\n\n"
        + (f"Votre page de suivi : {follow_url(booking)}\n\n" if follow_url(booking) else "")
        + f"À très vite,\n{site_name}\n"
    )
    status, err = _send(booking["email"],
                        f"Votre menu — {_short_date(booking['date'])} ({service})",
                        body, reply_to=config.MAIL_TO or "")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE menus SET mail_status = ?, mail_error = ? WHERE booking_id = ?",
            (status, err[:500], booking["id"]),
        )
