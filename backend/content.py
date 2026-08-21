"""Site copy, loaded from content/site.json.

Everything the chef will want to reword -- prestations, tarifs, à propos,
zone d'intervention -- lives in that one JSON file, so editing the site is a
text edit and a push, not a code change. It is read once at startup (and on
every request in DEV, so a local edit shows up on reload).
"""

import json
import logging

from . import config

log = logging.getLogger("chef.content")

_FALLBACK = {
    "name": "Chef à domicile",
    "tagline": "",
    "hero_photo": "",
    "portrait": "",
    "sections": [],
    "formulas": [],
    "gallery": [],
    "about": "",
    "area": "",
    "contact": {},
    "booking": {"min_guests": 2, "max_guests": 20, "lead_days": 3, "cancel_days": 7},
}

_cache: dict | None = None


def load(force: bool = False) -> dict:
    global _cache
    if _cache is not None and not force and not config.DEV:
        return _cache
    try:
        with open(config.CONTENT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # A broken content file must not take the booking flow down with it.
        log.error("content file unusable (%s): %s", config.CONTENT_PATH, exc)
        data = dict(_FALLBACK)
    merged = {**_FALLBACK, **data}
    merged["booking"] = {**_FALLBACK["booking"], **data.get("booking", {})}
    _cache = merged
    return merged


def site_name() -> str:
    return load().get("name") or _FALLBACK["name"]
