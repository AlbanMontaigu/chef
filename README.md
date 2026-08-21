# Chef à domicile — site + réservation

Site vitrine et système de réservation pour un chef à domicile. Une seule
image Docker : FastAPI sert l'API et le front statique, SQLite stocke les
créneaux et les réservations.

- **Site public** — présentation, formules, à propos, calendrier des dates
  disponibles, formulaire de réservation.
- **Back-office** (`/admin`) — trois onglets : l'**agenda** (ouvrir et fermer
  les créneaux, suivre les réservations), la **facturation** (factures,
  encaissements, soldes) et les **formules** (tarifs).
- **Facturation** — un brouillon se prépare depuis une réservation, s'émet avec
  un numéro séquentiel définitif, s'imprime et s'envoie au client. Les
  encaissements se saisissent au fil de l'eau ; le solde est toujours leur
  somme, jamais un compteur tenu à part.
- **E-mails** — confirmation au client, notification au chef, e-mail
  d'annulation, envoi de facture. Chaque envoi est tracé et les échecs sont
  affichés dans le back-office.

## Démarrer en local

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
DEV=1 ADMIN_PASSWORD=motdepasse SECRET_KEY=devsecret \
  .venv/bin/python -m uvicorn backend.main:app --reload --port 8000
```

Le site est sur <http://127.0.0.1:8000>, le back-office sur
<http://127.0.0.1:8000/admin>. Sans `SMTP_HOST`, aucun e-mail ne part : c'est
le mode par défaut en local, et il est signalé au démarrage comme dans le
back-office.

En local (`DEV=1`), une base vide est remplie d'un **jeu de démonstration** :
formules, créneaux, réservations dans tous les états, factures et
encaissements. Il ne touche que ses propres lignes et s'efface dès qu'une
vraie réservation existe. Pour rejouer un jeu enrichi, incrémenter
`SEED_VERSION` dans `backend/seed.py`.

```sh
.venv/bin/python tools/check-seed.py   # 42 états attendus, sort en 1 s'il en manque
```

## Modifier le contenu du site

Tout le texte est dans [`content/site.json`](content/site.json) : nom, accroche,
texte « à propos », zone d'intervention, bornes de réservation, et le bloc
`legal` qui alimente l'en-tête des factures. Éditer ce fichier et pousser
suffit — aucun code à toucher.

**Les formules et leurs tarifs ne sont plus dans ce fichier** : elles se
gèrent depuis le back-office, onglet « Formules », parce qu'elles servent de
base aux factures et qu'un montant doit être un nombre, pas une phrase.

Les photos vont dans `frontend/img/`, référencées depuis la clé `gallery` :

```json
"gallery": [{ "src": "/img/plat-1.jpg", "alt": "Filet de bar", "caption": "" }]
```

## Documentation

- [`docs/deployment.md`](docs/deployment.md) — déploiement Coolify, variables
  d'environnement, volume, DNS, e-mail.
- [`docs/architecture.md`](docs/architecture.md) — structure du code, modèle de
  données, cycle de vie d'une réservation.
- [`CLAUDE.md`](CLAUDE.md) — contraintes à respecter en modifiant le projet.
