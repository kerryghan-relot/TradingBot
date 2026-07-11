#!/usr/bin/env bash
# One-shot Ubuntu VPS setup for lucas-trading — Docker edition.
# =====================================================================
# Installs Docker Engine + the compose plugin, generates the nginx
# secrets (self-signed TLS + basic auth), then builds and starts the
# whole stack (PostgreSQL, bot, web dashboard, nginx, scheduler) with
# `docker compose up -d`.
#
# Scheduling (weekly scorer + daily DB backup) is handled inside the
# stack by the ofelia `scheduler` service — no host cron, no systemd.
#
# Idempotent: safe to re-run after a `git pull` (rebuilds images,
# leaves existing certs / .htpasswd untouched).
#
# Usage (from the repo root, via sudo so Docker can be installed):
#   sudo deploy/scripts/setup_vps.sh
#
# Requires: Ubuntu 22.04+, and a repo-root .env (copy .env.example)
# with the Alpaca keys and a strong POSTGRES_PASSWORD.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit etre lance avec sudo (il installe Docker)." >&2
    echo "Usage: sudo $0" >&2
    exit 1
fi

DEPLOY_USER="${SUDO_USER:-root}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TRADING_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
REPO_DIR="$(cd "$TRADING_DIR/.." && pwd)"

echo "== Repertoire du repo : $REPO_DIR"

if [ ! -f "$REPO_DIR/.env" ]; then
    echo "ERREUR: $REPO_DIR/.env introuvable." >&2
    echo "Copie d'abord .env.example -> .env et renseigne les cles Alpaca" >&2
    echo "et un POSTGRES_PASSWORD solide." >&2
    exit 1
fi
chmod 600 "$REPO_DIR/.env"

# ── Docker Engine + compose plugin ────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "== Installation de Docker Engine..."
    curl -fsSL https://get.docker.com | sh
fi
if [ "$DEPLOY_USER" != "root" ]; then
    usermod -aG docker "$DEPLOY_USER" || true
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ── Pare-feu ──────────────────────────────────────────────────────────
if command -v ufw >/dev/null 2>&1; then
    echo "== Configuration du pare-feu (ufw)..."
    ufw allow OpenSSH >/dev/null || true
    ufw allow 80/tcp  >/dev/null || true
    ufw allow 443/tcp >/dev/null || true
    ufw --force enable || true
fi

# ── Secrets nginx (certs auto-signes + basic auth) ────────────────────
echo "== Generation des secrets nginx..."
bash "$DEPLOY_DIR/docker/init_secrets.sh"

# ── Build + demarrage de la stack ─────────────────────────────────────
echo "== Build des images..."
docker compose -f "$REPO_DIR/docker-compose.yml" --project-directory "$REPO_DIR" build

echo "== Demarrage de la stack..."
docker compose -f "$REPO_DIR/docker-compose.yml" --project-directory "$REPO_DIR" up -d

# ── Recapitulatif ─────────────────────────────────────────────────────
VPS_IP="$(curl -4 -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo " Deploiement termine."
echo " Dashboard : https://${VPS_IP}  (avertissement navigateur normal"
echo "             tant qu'aucun nom de domaine n'est configure)"
echo ""
echo " Etat des services : docker compose ps"
echo " Logs bot          : docker compose logs -f bot"
echo " Logs dashboard    : docker compose logs -f web"
echo " Scorer hebdo      : dimanche 18h  (service scheduler, ofelia)"
echo " Backup DB quotidien : 02h00       (volume 'backups', pg_dump)"
echo "════════════════════════════════════════════════════════════════"
