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

from . import config, db

log = logging.getLogger("chef.settings")

# Clé de `meta` -> valeur par défaut. Une clé absente vaut son défaut ; il n'y
# a pas d'état « non initialisé » à gérer ailleurs.
DEFAULTS = {
    "chef_address": "",
}


def all_settings() -> dict:
    values = dict(DEFAULTS)
    for key in DEFAULTS:
        values[key] = db.meta_get(f"setting:{key}", DEFAULTS[key])
    if config.SEED_DEMO and not values["chef_address"]:
        # Même raison que seed.DEMO_LEGAL : sans adresse de départ, le lien
        # d'itinéraire ne s'affiche jamais et la fonction reste invisible dans
        # le jeu de démonstration. Import local, seed.py importe ce module.
        from . import seed

        values["chef_address"] = seed.DEMO_CHEF_ADDRESS
    return values


def chef_address() -> str:
    return all_settings()["chef_address"]


def save(values: dict) -> None:
    with db.transaction() as conn:
        for key, value in values.items():
            if key not in DEFAULTS:
                raise KeyError(key)
            db.meta_set(conn, f"setting:{key}", value)
    log.info("réglages mis à jour : %s", ", ".join(sorted(values)))
