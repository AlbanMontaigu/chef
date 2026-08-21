"""Le menu d'un repas : ce que le chef va réellement cuisiner.

Une formule est un cadre et un tarif — « Menu Signature, cinq services ». Le
menu, lui, est ce qui sera dans l'assiette ce soir-là, composé après avoir
parlé au client, selon la saison et le marché. Les deux ne se confondent pas,
et jusqu'ici seul le premier existait : le cœur du métier n'était nulle part.

Trois choix le tiennent :

1. **Un menu appartient à une réservation**, une seule, et n'est pas
   réutilisable. Un menu recyclé d'un client à l'autre serait un catalogue,
   pas un menu — et le chef le composerait ailleurs.
2. **Brouillon puis envoyé.** Tant qu'il est brouillon, il n'existe que pour
   le chef. Une fois envoyé, il apparaît sur la page du client et part par
   e-mail : c'est un engagement, il ne se modifie plus sans le redire.
3. **Les services sont libres.** « Entrée / Plat / Dessert » est une
   suggestion, pas un schéma : un chef qui fait sept services ou un plat
   unique en cocotte ne doit pas se battre contre le formulaire.
"""

import json
import logging

log = logging.getLogger("chef.menus")

# Proposés dans la saisie, jamais imposés. L'ordre est celui du repas : c'est
# lui qui sert de tri quand le chef ne s'occupe pas des positions.
COMMON_COURSES = (
    "Apéritif", "Amuse-bouche", "Entrée", "Poisson", "Plat",
    "Fromage", "Dessert", "Mignardises",
)

MAX_LINES = 30


def normalise(lines: list[dict]) -> list[dict]:
    """Valide et nettoie les lignes d'un menu : [{course, dish}].

    Une ligne sans plat est jetée en silence -- c'est une ligne que le chef a
    ajoutée puis n'a pas remplie, pas une information. Une ligne avec un plat
    et sans service reste : le service est facultatif, le plat est le menu.
    """
    out = []
    for line in lines[:MAX_LINES]:
        dish = str(line.get("dish", "")).strip()
        if not dish:
            continue
        out.append({
            "course": str(line.get("course", "")).strip()[:60],
            "dish": dish[:300],
        })
    return out


def dumps(lines: list[dict]) -> str:
    return json.dumps(lines, ensure_ascii=False)


def loads(raw: str | None) -> list[dict]:
    """Un menu illisible ne fait jamais tomber l'affichage d'une réservation :
    il est signalé et rendu vide, ce qui se lit « aucun menu »."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.error("colonne menu illisible : %r", raw)
        return []
    return data if isinstance(data, list) else []


def text_block(lines: list[dict], indent: str = "  ") -> str:
    """Rendu texte pour l'e-mail. Le service est en tête de ligne quand il
    existe, sinon le plat parle tout seul."""
    out = []
    for line in lines:
        out.append(f"{indent}{line['course']} — {line['dish']}" if line["course"]
                   else f"{indent}{line['dish']}")
    return "\n".join(out)
