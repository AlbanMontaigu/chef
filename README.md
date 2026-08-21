# Chef à domicile — site + réservation

Site vitrine et système de réservation pour un chef à domicile. Une seule
image Docker : FastAPI sert l'API et le front statique, SQLite stocke les
créneaux et les réservations.

- **Site public** — présentation, formules, à propos, calendrier des dates
  disponibles, formulaire de réservation.
- **Back-office** (`/admin`) — le chef ouvre et ferme ses créneaux sur un
  calendrier, voit ses réservations, en annule une si besoin.
- **E-mails** — confirmation au client, notification au chef, e-mail
  d'annulation. Chaque envoi est tracé et les échecs sont affichés dans le
  back-office.

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

## Modifier le contenu du site

Tout le texte est dans [`content/site.json`](content/site.json) : nom, accroche,
formules et tarifs, texte « à propos », zone d'intervention, bornes de
réservation. Éditer ce fichier et pousser suffit — aucun code à toucher.

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
