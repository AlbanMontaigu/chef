"""Réglages opérationnels du chef, stockés en base.

Ce qui atterrit ici plutôt que dans `content/site.json` : tout ce qui est
**privé** ou que le chef doit pouvoir changer seul, sans redéploiement.
L'adresse de départ est les deux à la fois — c'est le plus souvent son
domicile, et le dépôt est public.

Ce module est le seul à lire ces clés, et rien de ce qu'il expose ne passe par
`/api/content` : le site public n'a aucune raison de connaître d'où part le
chef.
"""

import logging
import re

from . import config, db

log = logging.getLogger("chef.settings")

# Clé de `meta` -> valeur par défaut. Une clé absente vaut son défaut ; il n'y
# a pas d'état « non initialisé » à gérer ailleurs.
DEFAULTS = {
    "chef_address": "",
    # Préfixes de code postal acceptés à la réservation, séparés par des
    # virgules : « 44, 85, 49 ». VIDE = aucune restriction, ce qui est le
    # comportement d'avant et reste celui par défaut.
    "area_postcodes": "",
}


def all_settings() -> dict:
    values = dict(DEFAULTS)
    for key in DEFAULTS:
        values[key] = db.meta_get(f"setting:{key}", DEFAULTS[key])
    if config.SEED_DEMO:
        # Même raison que seed.DEMO_LEGAL : sans adresse de départ ni zone, le
        # lien d'itinéraire et le contrôle de zone ne s'affichent jamais, et
        # les deux fonctions passent pour absentes du jeu de démonstration.
        # L'import est local (seed.py importe ce module) et se fait ICI, une
        # fois, avant les deux replis. Il a d'abord vécu dans le premier `if`
        # et le second s'en servait : dès qu'une adresse était enregistrée
        # sans zone, `all_settings()` levait un UnboundLocalError -- donc une
        # 500 sur /api/content, c'est-à-dire le site public entier.
        from . import seed

        if not values["chef_address"]:
            values["chef_address"] = seed.DEMO_CHEF_ADDRESS
        if not values["area_postcodes"]:
            values["area_postcodes"] = seed.DEMO_AREA_POSTCODES
    return values


def chef_address() -> str:
    return all_settings()["chef_address"]


# --- Zone de déplacement -----------------------------------------------
# Le contrôle se fait sur le CODE POSTAL, pas sur une distance calculée. Un
# géocodage sur le chemin d'une réservation ajouterait un appel réseau à un
# service public sans garantie, avec sa latence et ses pannes, au moment
# précis où le client valide -- et un service lent ferait échouer des
# réservations parfaitement légitimes. Le préfixe est instantané, hors ligne,
# et le chef le comprend sans explication. L'estimation de trajet, elle, reste
# ce qu'elle a toujours été : une information a posteriori, dans le dossier.

_POSTCODE_RE = re.compile(r"\b(\d{5})\b")


def area_prefixes() -> tuple[str, ...]:
    raw = all_settings()["area_postcodes"]
    return tuple(p for p in (x.strip() for x in raw.split(",")) if p.isdigit())


def postcode_of(city: str) -> str:
    """Code postal lu dans « 44000 Nantes ». Vide si on n'en trouve pas."""
    match = _POSTCODE_RE.search(city or "")
    return match.group(1) if match else ""


def area_note() -> str:
    """Phrase affichée au client, dérivée de la liste QUI FAIT LOI.

    Elle n'est pas recopiée à la main dans le fichier éditorial : une zone
    annoncée qui diverge de la zone appliquée fait refuser une réservation à
    quelqu'un à qui on venait de dire oui.
    """
    prefixes = area_prefixes()
    if not prefixes:
        return ""
    listed = ", ".join(prefixes[:-1]) + f" et {prefixes[-1]}" if len(prefixes) > 1 else prefixes[0]
    return f"Je me déplace dans les départements {listed}."


def in_area(city: str) -> tuple[bool, str]:
    """(accepté, motif du refus).

    Deux cas passent toujours : aucune zone configurée, et aucun code postal
    lisible. L'adresse est facultative sur le formulaire ; refuser faute de
    code postal transformerait un champ optionnel en champ obligatoire, par
    un chemin que personne n'a choisi.
    """
    prefixes = area_prefixes()
    if not prefixes:
        return True, ""
    code = postcode_of(city)
    if not code:
        return True, ""
    if any(code.startswith(p) for p in prefixes):
        return True, ""
    return False, (f"Le code postal {code} est hors de ma zone de déplacement "
                   f"({', '.join(prefixes)}).")


def save(values: dict) -> None:
    with db.transaction() as conn:
        for key, value in values.items():
            if key not in DEFAULTS:
                raise KeyError(key)
            db.meta_set(conn, f"setting:{key}", value)
    log.info("réglages mis à jour : %s", ", ".join(sorted(values)))
