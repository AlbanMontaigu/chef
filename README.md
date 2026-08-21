# Chef à domicile — site + réservation

Site vitrine et système de réservation pour un chef à domicile. Une seule
image Docker : FastAPI sert l'API et le front statique, SQLite stocke les
créneaux et les réservations.

- **Site public** — présentation, formules, à propos, calendrier des dates
  disponibles, formulaire de réservation, et un formulaire de **demande de
  devis** pour tout ce qui n'entre pas dans le calendrier (date non ouverte,
  mariage, gros buffet).
- **Page du client** (`/r/<jeton>`) — le lien reçu par e-mail : détail de la
  réservation, menu, facture, et annulation en autonomie jusqu'à quelques
  jours avant le repas. Le jeton est un secret de 128 bits, distinct de la
  référence dictable au téléphone.
- **Back-office** (`/admin`) — sept onglets : **agenda** (créneaux et
  réservations), **facturation**, **formules**, **devis**, **comptabilité**,
  **relances** et **réglages**.
- **Régimes et allergies** — déclarés à la réservation dans un catalogue
  fermé, avec le nombre de convives concernés. Les allergies sont signalées
  comme telles, jusque dans le sujet de l'e-mail au chef.
- **Menus** — le menu d'un repas se compose depuis le dossier, s'envoie au
  client et apparaît sur sa page. Le modifier après envoi le repasse en
  brouillon : le client connaît l'ancienne version tant qu'on ne lui renvoie
  pas la nouvelle.
- **Rappels et relances** — rappel au client avant le repas, relance des
  factures échues, signal au chef sur un repas servi non facturé. Chaque envoi
  revérifie sa raison d'être juste avant de partir.
- **Zone de déplacement** — des débuts de code postal, saisis dans Réglages.
  Hors zone, la réservation est refusée avec une invitation à demander un
  devis. La phrase affichée aux clients est dérivée de cette liste, il n'y a
  pas deux endroits à tenir à jour.
- **Comptabilité** — encaissé par trimestre (la base déclarable au régime
  micro), ventilation par moyen de paiement, export CSV des encaissements et
  des factures, prêt pour un tableur français.
- **Trajet** — l'adresse de départ du chef se saisit dans Réglages ; chaque
  réservation propose alors une estimation de durée (Nominatim + OSRM, calculée
  à la demande et conservée) et le lien vers l'application de cartes. L'adresse
  de départ reste privée : ni sur le site, ni sur les factures. Sans code postal
  ni ville côté client, l'estimation est refusée plutôt que devinée.
- **Facturation** — un brouillon se prépare depuis une réservation, s'émet avec
  un numéro séquentiel définitif, s'imprime et s'envoie au client. Les
  encaissements se saisissent au fil de l'eau ; le solde est toujours leur
  somme, jamais un compteur tenu à part.
- **E-mails** — confirmation, notification au chef, annulation (par le chef ou
  par le client), accusé de devis, menu, rappel avant repas, relance d'impayé,
  envoi de facture. Chaque envoi est tracé et les échecs sont affichés dans le
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

En local (`DEV=1`), une base vide est remplie d'un **jeu de démonstration** :
formules, créneaux, réservations dans tous les états, factures et
encaissements. Il ne touche que ses propres lignes et s'efface dès qu'une
vraie réservation existe. Pour rejouer un jeu enrichi, incrémenter
`SEED_VERSION` dans `backend/seed.py`.

```sh
.venv/bin/python tools/check-seed.py   # 125 états attendus, sort en 1 s'il en manque
```

Le semis refuse de rejouer dès qu'une réservation non-démo existe — c'est ce
qui empêche des exemples de se mélanger à de vraies réservations. Sur une
instance qui sert de bac à sable, ces « vraies » réservations sont des essais,
et il faut repartir de zéro :

```sh
.venv/bin/python tools/reset-db.py              # inventaire de ce qui serait détruit
DEV=1 .venv/bin/python tools/reset-db.py --yes  # vide et re-sème
```

## Modifier le contenu du site

Tout le texte est dans [`content/site.json`](content/site.json) : nom, accroche,
texte « à propos », zone d'intervention, bornes de réservation (`min_guests`,
`max_guests`, `lead_days`, `cancel_days`) et le bloc `legal` qui alimente
l'en-tête des factures. Éditer ce fichier et pousser
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
