"""Estimation du temps de trajet entre le chef et le lieu du repas.

Deux services publics, appelés depuis le serveur et jamais depuis la page :
**Nominatim** transforme une adresse en coordonnées, **OSRM** calcule la route.
Aucune bibliothèque ajoutée — `urllib` de la bibliothèque standard suffit,
donc la contrainte de dépendances minimales du dépôt tient.

Ce que ces services sont, et les règles qui en découlent :

- **Ce sont des serveurs publics de démonstration, sans garantie.** Ils peuvent
  être lents, indisponibles, ou disparaître. Donc : jamais sur le chemin d'une
  réservation client, uniquement à la demande depuis le back-office, avec un
  délai d'attente court, et un échec qui s'affiche en clair au lieu d'un blanc.
- **Leur politique d'usage demande de mettre les résultats en cache** plutôt
  que de redemander la même chose. Les géocodages vont donc dans la table
  `geocache`, et l'estimation est conservée sur la réservation : une adresse ne
  bouge pas.
- **Nominatim exige un agent identifiant l'application** et une requête par
  seconde au plus. Les deux sont respectés ici.

Le résultat est une estimation de conduite sans trafic. C'est dit tel quel dans
l'interface : annoncer « 34 min » comme une promesse serait faux.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, db

log = logging.getLogger("chef.travel")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://router.project-osrm.org/route/v1/driving"
TIMEOUT = 8          # court : personne n'attend derrière, mais personne n'attend longtemps
COUNTRY = "fr"       # le chef se déplace autour de chez lui, pas à l'étranger

# Nominatim : une requête par seconde au plus, toutes origines confondues.
# Le verrou sérialise les appels concurrents plutôt que de les laisser partir
# ensemble et se faire refuser tous les deux.
_nominatim_lock = threading.Lock()
_last_call = 0.0


def _user_agent() -> str:
    """Nominatim refuse un agent générique : il veut pouvoir identifier
    l'application et joindre quelqu'un en cas d'abus."""
    return f"chef-a-domicile/1.0 ({config.PUBLIC_URL}; {config.MAIL_FROM})"


def _fetch(url: str) -> tuple[dict | list | None, str]:
    request = urllib.request.Request(url, headers={
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except urllib.error.HTTPError as exc:
        return None, f"service indisponible ({exc.code})"
    except urllib.error.URLError as exc:
        return None, f"service injoignable ({exc.reason})"
    except (TimeoutError, json.JSONDecodeError, OSError) as exc:
        return None, f"réponse illisible ({type(exc).__name__})"


def geocode(address: str) -> tuple[tuple[float, float] | None, str, str]:
    """Adresse -> ((lat, lon), libellé reconnu, erreur).

    Le libellé reconnu est renvoyé pour être montré au chef : c'est le seul
    moyen qu'il repère qu'une adresse incomplète a été comprise de travers.
    """
    query = " ".join(address.split()).strip()
    if not query:
        return None, "", "adresse vide"

    with db.cursor() as conn:
        row = conn.execute("SELECT * FROM geocache WHERE query = ?", (query.lower(),)).fetchone()
    if row is not None:
        if row["lat"] is None:
            return None, "", "adresse non localisée"
        return (row["lat"], row["lon"]), row["label"], ""

    url = f"{NOMINATIM}?" + urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "limit": 1, "countrycodes": COUNTRY,
    })
    global _last_call
    with _nominatim_lock:
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        payload, error = _fetch(url)
        _last_call = time.monotonic()

    if error:
        # Un service momentanément absent ne se met pas en cache : ce serait
        # graver une panne passagère en « adresse introuvable ».
        return None, "", error

    found = payload[0] if payload else None
    now = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO geocache (query, lat, lon, label, created_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (query) DO UPDATE SET lat = excluded.lat, lon = excluded.lon,"
            " label = excluded.label",
            (query.lower(),
             float(found["lat"]) if found else None,
             float(found["lon"]) if found else None,
             found.get("display_name", "") if found else "", now),
        )
    if not found:
        return None, "", "adresse non localisée"
    return (float(found["lat"]), float(found["lon"])), found.get("display_name", ""), ""


def route(start: tuple[float, float], end: tuple[float, float]) -> tuple[int, int, str]:
    """(secondes, mètres, erreur). Conduite, sans trafic."""
    url = (f"{OSRM}/{start[1]},{start[0]};{end[1]},{end[0]}"
           "?overview=false&alternatives=false")
    payload, error = _fetch(url)
    if error:
        return 0, 0, error
    routes = (payload or {}).get("routes") or []
    if not routes:
        return 0, 0, "aucun itinéraire routier entre ces deux adresses"
    leg = routes[0]
    return int(round(leg["duration"])), int(round(leg["distance"])), ""


def _now() -> str:
    from datetime import datetime

    return datetime.now(config.TZ).isoformat(timespec="seconds")


def estimate(origin: str, destination: str, fallback: str = "") -> dict:
    """Estimation complète. Ne lève jamais : l'erreur est une donnée.

    `fallback` est la commune seule. Quand l'adresse exacte est introuvable —
    numéro absent du cadastre, nom de lieu-dit, salle des fêtes — la commune,
    elle, l'est presque toujours. On estime alors **depuis son centre**, et le
    résultat est marqué `approximate` : le back-office l'annonce comme tel.
    Une estimation approximative annoncée comme approximative reste utile ; la
    même annoncée comme exacte serait un mensonge.

    Renvoie `{seconds, meters, error, approximate, origin_label,
    destination_label}`.
    """
    blank = {"seconds": None, "meters": None, "origin_label": "",
             "destination_label": "", "approximate": False}
    if not origin:
        return {**blank, "error": "aucune adresse de départ (à renseigner dans Réglages)"}
    if not destination:
        return {**blank, "error": "aucune adresse de repas sur cette réservation"}

    start, start_label, error = geocode(origin)
    if error:
        return {**blank, "error": f"adresse de départ : {error}"}
    approximate = False
    end, end_label, error = geocode(destination)
    if error and fallback and error == "adresse non localisée":
        end, end_label, error = geocode(fallback)
        approximate = end is not None
    if error:
        return {**blank, "origin_label": start_label,
                "error": f"adresse du repas : {error}"}

    seconds, meters, error = route(start, end)
    if error:
        return {**blank, "origin_label": start_label, "destination_label": end_label,
                "error": error}

    km = meters / 1000
    if km > config.TRAVEL_MAX_KM:
        # Un géocodage qui se trompe ne se trompe pas discrètement : il renvoie
        # une rue homonyme à des centaines de kilomètres, et le routeur calcule
        # docilement le trajet. Sans cette borne, l'application afficherait une
        # durée crédible et fausse -- ce qu'aucun blanc n'aurait fait.
        log.warning("trajet écarté, %d km : %r localisé en %r", km, destination, end_label)
        return {**blank, "origin_label": start_label, "destination_label": end_label,
                "error": f"distance invraisemblable ({km:.0f} km) — l'adresse a été "
                         f"localisée ici : {end_label[:120]}"}

    log.info("trajet estimé%s : %s -> %s = %d s, %d m",
             " (approché)" if approximate else "", origin, destination, seconds, meters)
    return {"seconds": seconds, "meters": meters, "error": "", "approximate": approximate,
            "origin_label": start_label, "destination_label": end_label}


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"
