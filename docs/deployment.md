# Déploiement (Coolify / Dedibox)

Même moule que `flip7`, `skyjo` et `maison` : dépôt GitHub → Coolify, build
pack `dockerfile`, exposition derrière Traefik sur l'IP dédiée.

## Application Coolify

| Réglage | Valeur |
|---|---|
| Build pack | `dockerfile` |
| Dépôt | `AlbanMontaigu/chef`, branche `main` |
| Port exposé | `8000` |
| Domaine | `https://chef.montaigu.org` |
| Health check | `/health` |

## Volume — à faire AVANT la première réservation

```
/data/coolify/applications/<uuid>  →  /app/backend/data
```

Sans ce montage, `chef.db` vit dans la couche éphémère du conteneur et
**chaque redéploiement efface toutes les réservations**. C'est l'erreur la
plus coûteuse possible ici, et elle est silencieuse : le site continue de
fonctionner, simplement vide.

Contrôle après déploiement :

```sh
docker inspect <conteneur> --format '{{json .Mounts}}'
```

Le montage doit apparaître avec `"Destination":"/app/backend/data"`.

## Variables d'environnement

| Variable | Rôle | Sans elle |
|---|---|---|
| `ADMIN_PASSWORD` | mot de passe unique du back-office | **le back-office refuse toute connexion** |
| `SECRET_KEY` | signe le cookie de session (32 octets aléatoires) | sessions perdues à chaque redéploiement |
| `SMTP_HOST` | serveur d'envoi (Postfix Dedibox) | **aucun e-mail n'est envoyé** |
| `SMTP_PORT` | `25` en local sur la Dedibox | défaut `25` |
| `MAIL_FROM` | expéditeur, ex. `chef@montaigu.org` | défaut `chef@montaigu.org` |
| `MAIL_FROM_NAME` | nom affiché de l'expéditeur | adresse nue |
| `MAIL_TO` | boîte du chef, destinataire des notifications | le chef n'est jamais prévenu |
| `PUBLIC_URL` | `https://chef.montaigu.org` | liens des e-mails cassés, cookie non `Secure` |
| `TZ` | `Europe/Paris` | défaut `Europe/Paris` |
| `LOG_LEVEL` | `INFO` | défaut `INFO` |

`ADMIN_PASSWORD` et `SMTP_HOST` manquantes sont hurlées au démarrage
(`WARNING` dans les logs) et signalées dans le back-office : le site
fonctionne à moitié, il ne doit pas le faire en silence.

## E-mail : ce qui reste à vérifier côté serveur

Postfix tourne déjà sur la Dedibox (25 et 587). Deux points à confirmer avant
d'annoncer le site à des vrais clients :

1. **Relais depuis le conteneur.** Le conteneur atteint l'hôte par la
   passerelle Docker ; `mynetworks` de Postfix doit inclure le sous-réseau
   Docker, sinon l'envoi est refusé (`Relay access denied`). Le back-office
   affichera l'échec, mais autant le régler avant.
2. **SPF et DKIM sur le domaine expéditeur.** Sans eux, une confirmation de
   réservation part en spam — un échec invisible, exactement le genre que ce
   projet refuse. Vérifier avec un envoi réel vers une boîte Gmail avant
   ouverture.

## Migration vers le domaine propre du chef

Aucune modification de code. Dans Coolify : changer le domaine de
l'application, puis `PUBLIC_URL`, `MAIL_FROM` et `MAIL_FROM_NAME`. Côté DNS,
pointer le nouveau domaine sur l'IP dédiée et refaire SPF/DKIM pour lui.
