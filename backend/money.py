"""Montants.

Tout l'argent de ce dépôt est un **entier de centimes**. Aucun flottant ne
touche un prix : `0.1 + 0.2` ne fait pas `0.3`, et une facture dont le total
diffère d'un centime de la somme de ses lignes est une facture fausse. La
seule conversion vers du décimal se fait à l'affichage, ici.
"""

import re

_AMOUNT_RE = re.compile(r"^-?\d+(?:[.,]\d{1,2})?$")


def parse_amount(value: str | int | float) -> int:
    """Saisie humaine (« 45 », « 45,50 », « 1 200.00 ») -> centimes.

    Accepte un entier de centimes tel quel n'est PAS possible ici : un nombre
    nu est un montant en euros, comme le chef l'a tapé. Lever plutôt que
    deviner -- un montant mal interprété se retrouve sur une vraie facture.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value * 100
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    text = text.replace("€", "")
    if not _AMOUNT_RE.match(text):
        raise ValueError(f"montant invalide : {value!r}")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("-").replace(",", ".")
    if "." in text:
        whole, frac = text.split(".")
        frac = (frac + "00")[:2]
    else:
        whole, frac = text, "00"
    return sign * (int(whole) * 100 + int(frac))


def format_amount(cents: int) -> str:
    """Centimes -> « 1 234,50 € », espace fine insécable comprise."""
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    whole, frac = divmod(cents, 100)
    groups = f"{whole:,}".replace(",", " ")
    return f"{sign}{groups},{frac:02d} €"


def vat_split(total_ttc_cents: int, rate_bp: int) -> tuple[int, int]:
    """(HT, TVA) à partir d'un TTC et d'un taux en points de base.

    Les tarifs annoncés au client sont TTC : c'est ce qu'il paye. La ventilation
    est donc une extraction, pas une addition. L'arrondi va sur la TVA pour que
    HT + TVA redonne exactement le TTC facturé -- jamais un centime d'écart.
    """
    if rate_bp <= 0:
        return total_ttc_cents, 0
    ht = round(total_ttc_cents * 10000 / (10000 + rate_bp))
    return ht, total_ttc_cents - ht


def format_rate(rate_bp: int) -> str:
    whole, frac = divmod(rate_bp, 100)
    return f"{whole} %" if frac == 0 else f"{whole},{frac:02d} %".rstrip("0").rstrip(",")
