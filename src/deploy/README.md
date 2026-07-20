# Deployment — Docker Compose

The whole stack (PostgreSQL, bot, dashboard, scorer, backups, reverse proxy) runs in containers, orchestrated by `docker-compose.yml` at the repo root. Dashboard access via HTTPS + password.

## The services

| Service     | Role |
|-------------|------|
| `db`        | PostgreSQL 16 (volume `pgdata`). Replaces the old `bars.db`. |
| `bot`       | `python -m live.bot` — trading engine, `restart: always`. |
| `web`       | Flask dashboard + built React, served by gunicorn (internal port 8501). |
| `nginx`     | Reverse proxy 80/443, self-signed TLS + basic auth in front of the dashboard. |
| `scheduler` | [ofelia](https://github.com/mcuadros/ofelia): weekly scorer + daily backup, via `docker exec` into the existing containers. |

Scheduling is **in the stack** — no more host cron or systemd. The scorer runs every Sunday at 18:00 (`job-exec` in `bot`), the `pg_dump` backup every night at 02:00 to the `backups` volume (30-day retention, `job-exec` in `db`).

## Prerequisites

- A Linux host (Ubuntu 22.04+ recommended) with Docker Engine + the `compose` plugin. The `setup_vps.sh` script installs them if absent.
- A `.env` file at the repo root: `cp .env.example .env` then fill in `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, a strong `POSTGRES_PASSWORD` and the `DASHBOARD_USER` / `DASHBOARD_PASSWORD` credentials.

## Quick start (VPS)

```bash
# 1. Get the repo onto the host (git clone or rsync).
# 2. Configure the secrets:
cp .env.example .env && nano .env

# 3. Install Docker + generate the nginx secrets + start the stack:
sudo bash src/deploy/scripts/setup_vps.sh
```

Then open `https://<VPS_IP>`. Since the certificate is self-signed, the browser shows a warning once — click "Advanced → continue", then enter the dashboard credentials.

## Manual start (local or server)

```bash
cp .env.example .env                          # fill in the values
bash src/deploy/docker/init_secrets.sh   # certs + .htpasswd
docker compose build
docker compose up -d
```

To populate the database with demo data (without running the bot):

```bash
docker compose run --rm bot python -m tools.seed_fake_data
```

## Common operations

```bash
# State and logs
docker compose ps
docker compose logs -f bot
docker compose logs -f web

# Code update
git pull
docker compose build
docker compose up -d

# Run the scorer on demand
docker compose exec bot python -m live.scorer

# Manual database backup
docker compose exec db sh -c \
  'pg_dump -U tradingbot tradingbot | gzip > /backups/manual_$(date +%F).sql.gz'

# Open a psql
docker compose exec db psql -U tradingbot -d tradingbot

# View the backups
docker compose exec db ls -lh /backups
```

## Migrating to a real domain later

The `/.well-known/acme-challenge/` location is already wired in `deploy/docker/nginx.conf` (served via the `certbot-webroot` volume). When a domain points to the host:

1. Fill in the real `server_name` in `nginx.conf`.
2. Add a `certbot/certbot` container (or run it one-off) in `--webroot -w /var/www/certbot -d your-domain.com` mode.
3. Mount the issued certificates in place of the self-signed certs and reload nginx (`docker compose exec nginx nginx -s reload`).

## Known limitation

The **Configuration** tab of the dashboard modifies `config.json` (active signals, thresholds, stop-loss) from the browser. It is protected by the Nginx password, but it remains a remotely exposed write — never share the dashboard credentials.
