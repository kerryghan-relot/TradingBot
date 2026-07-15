# Déploiement — Docker Compose

Tout le stack (PostgreSQL, bot, dashboard, scorer, backups, reverse proxy) tourne en conteneurs, orchestré par `docker-compose.yml` à la racine du repo. Accès au dashboard via HTTPS + mot de passe.

## Les services

| Service     | Rôle |
|-------------|------|
| `db`        | PostgreSQL 16 (volume `pgdata`). Remplace l'ancien `bars.db`. |
| `bot`       | `python -m live.bot` — moteur de trading, `restart: always`. |
| `web`       | Dashboard Flask + React buildé, servi par gunicorn (port interne 8501). |
| `nginx`     | Reverse proxy 80/443, TLS auto-signé + basic auth devant le dashboard. |
| `scheduler` | [ofelia](https://github.com/mcuadros/ofelia) : scorer hebdo + backup quotidien, via `docker exec` dans les conteneurs existants. |

La planification est **dans le stack** — plus de cron hôte ni de systemd. Le scorer tourne chaque dimanche 18h (`job-exec` dans `bot`), le backup `pg_dump` chaque nuit à 2h vers le volume `backups` (rétention 30 jours, `job-exec` dans `db`).

## Prérequis

- Un hôte Linux (Ubuntu 22.04+ recommandé) avec Docker Engine + le plugin `compose`. Le script `setup_vps.sh` les installe si absents.
- Un fichier `.env` à la racine du repo : `cp .env.example .env` puis renseigne `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, un `POSTGRES_PASSWORD` solide et les identifiants `DASHBOARD_USER` / `DASHBOARD_PASSWORD`.

## Démarrage rapide (VPS)

```bash
# 1. Récupérer le repo sur l'hôte (git clone ou rsync).
# 2. Configurer les secrets :
cp .env.example .env && nano .env

# 3. Installer Docker + générer les secrets nginx + lancer la stack :
sudo bash src/deploy/scripts/setup_vps.sh
```

Puis ouvre `https://<IP_DU_VPS>`. Le certificat étant auto-signé, le navigateur affiche un avertissement une fois — clique « Avancé → continuer », puis saisis les identifiants du dashboard.

## Démarrage manuel (local ou serveur)

```bash
cp .env.example .env                          # remplir les valeurs
bash src/deploy/docker/init_secrets.sh   # certs + .htpasswd
docker compose build
docker compose up -d
```

Pour peupler la base avec des données de démo (sans faire tourner le bot) :

```bash
docker compose run --rm bot python -m tools.seed_fake_data
```

## Opérations courantes

```bash
# État et logs
docker compose ps
docker compose logs -f bot
docker compose logs -f web

# Mise à jour du code
git pull
docker compose build
docker compose up -d

# Lancer le scorer à la demande
docker compose exec bot python -m live.scorer

# Backup manuel de la base
docker compose exec db sh -c \
  'pg_dump -U tradingbot tradingbot | gzip > /backups/manual_$(date +%F).sql.gz'

# Ouvrir un psql
docker compose exec db psql -U tradingbot -d tradingbot

# Voir les sauvegardes
docker compose exec db ls -lh /backups
```

## Migrer vers un vrai domaine plus tard

L'emplacement `/.well-known/acme-challenge/` est déjà câblé dans `deploy/docker/nginx.conf` (servi via le volume `certbot-webroot`). Quand un domaine pointe vers l'hôte :

1. Renseigne le `server_name` réel dans `nginx.conf`.
2. Ajoute un conteneur `certbot/certbot` (ou lance-le ponctuellement) en mode `--webroot -w /var/www/certbot -d ton-domaine.com`.
3. Monte les certificats émis à la place des certs auto-signés et recharge nginx (`docker compose exec nginx nginx -s reload`).

## Limite connue

L'onglet **Configuration** du dashboard modifie `config.json` (signaux actifs, seuils, stop-loss) depuis le navigateur. C'est protégé par le mot de passe Nginx, mais ça reste une écriture exposée à distance — ne partage jamais les identifiants du dashboard.
