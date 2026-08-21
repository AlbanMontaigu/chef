"""Régimes et allergies déclarés à la réservation.

Jusqu'ici tout passait par le champ libre « message ». Un chef qui découvre
une allergie aux fruits à coque au milieu d'un paragraphe, le jour du repas,
c'est un incident — pas un oubli de lecture. Ces contraintes deviennent donc
une donnée à part, comptée et affichée comme telle.

Deux choix structurent ce module :

1. **Un régime porte un nombre de convives**, pas un booléen. « Il y a des
   végétariens » ne se cuisine pas ; « deux végétariens sur dix » se cuisine.
2. **Une allergie n'est pas une préférence.** Les deux vivent dans la même
   liste parce que le client les déclare au même endroit, mais le drapeau
   `allergy` les sépare partout où elles s'affichent : une préférence
   contrariée déçoit, une allergie manquée envoie quelqu'un à l'hôpital.

Le catalogue est fermé et servi au front par `/api/content` : le formulaire,
le back-office et les e-mails nomment ainsi les mêmes choses. Ce que le client
veut dire en plus reste dans le message libre, qui n'a pas disparu.
"""

import json
import logging

log = logging.getLogger("chef.diets")

# (identifiant stable, libellé, est-ce une allergie)
# L'identifiant est cité par les réservations enregistrées : le renommer
# casserait l'historique, le libellé se réécrit librement.
CATALOGUE = (
    ("sans-gluten", "Sans gluten", True),
    ("sans-lactose", "Sans lactose", True),
    ("sans-fruits-a-coque", "Sans fruits à coque", True),
    ("sans-arachide", "Sans arachide", True),
    ("sans-crustaces", "Sans crustacés ni fruits de mer", True),
    ("sans-oeuf", "Sans œuf", True),
    ("vegetarien", "Végétarien", False),
    ("vegan", "Végétalien", False),
    ("sans-porc", "Sans porc", False),
    ("sans-alcool", "Sans alcool", False),
)

BY_ID = {row[0]: row for row in CATALOGUE}


def catalogue() -> list[dict]:
    """Ce que le formulaire public affiche, dans l'ordre : allergies d'abord."""
    return [{"id": i, "label": label, "allergy": allergy}
            for i, label, allergy in CATALOGUE]


def normalise(entries: list[dict], guests: int) -> list[dict]:
    """Valide une saisie et la range dans l'ordre du catalogue.

    Un identifiant inconnu est refusé plutôt qu'ignoré : il ne peut venir que
    d'un formulaire trafiqué ou d'un catalogue désynchronisé, et l'avaler en
    silence ferait disparaître une contrainte que le client croit avoir dite.
    Le nombre est borné au nombre de convives — « douze végétariens » sur une
    table de six est une faute de frappe, pas une information.
    """
    seen: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("id", "")).strip()
        if key not in BY_ID:
            raise ValueError(f"régime inconnu : {key!r}")
        count = int(entry.get("count") or 1)
        seen[key] = max(1, min(count, max(1, int(guests))))
    return [{"id": i, "count": seen[i]} for i, _, _ in CATALOGUE if i in seen]


def dumps(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False)


def loads(raw: str | None) -> list[dict]:
    """Relit la colonne. Un contenu illisible n'est jamais une raison de faire
    tomber l'affichage d'une réservation : on le signale et on rend une liste
    vide, ce qui se voit dans le back-office comme « aucun régime signalé »."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.error("colonne diets illisible : %r", raw)
        return []
    return data if isinstance(data, list) else []


def describe(raw: str | None) -> list[dict]:
    """Colonne brute -> [{id, label, count, allergy}], prêt à afficher.

    Une entrée dont l'identifiant a disparu du catalogue garde son
    identifiant comme libellé : mieux vaut un intitulé moche qu'une contrainte
    escamotée parce qu'on a renommé une constante.
    """
    out = []
    for entry in loads(raw):
        key = str(entry.get("id", ""))
        row = BY_ID.get(key)
        out.append({
            "id": key,
            "label": row[1] if row else key,
            "allergy": bool(row[2]) if row else True,
            "count": int(entry.get("count") or 1),
        })
    return out


def text_lines(raw: str | None) -> list[str]:
    """Rendu texte pour les e-mails : « 2 × Sans gluten (allergie) »."""
    return [f"{d['count']} × {d['label']}" + (" (allergie)" if d["allergy"] else "")
            for d in describe(raw)]


def has_allergy(raw: str | None) -> bool:
    return any(d["allergy"] for d in describe(raw))
