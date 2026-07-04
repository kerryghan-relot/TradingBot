#!/usr/bin/env bash
# One-shot Ubuntu VPS setup for lucas-live-trading.
# =====================================================
# Installs Nginx (reverse proxy + self-signed TLS + basic auth),
# firewall rules, the Python environment (via uv), and systemd
# services for bot.py and the Streamlit dashboard.  Also wires up the
# weekly scorer and daily DB backup as cron jobs.
#
# Idempotent: safe to re-run after a `git pull` (re-applies config,
# does not recreate the TLS cert / htpasswd if they already exist).
#
# Usage (from the repo root, as the user who will own the bot — NOT root):
#   sudo deploy/scripts/setup_vps.sh
#
# Requires: Ubuntu 22.04+, sudo privileges, a copy of .env already
# placed at the repo root (ALPACA_API_KEY / ALPACA_SECRET_KEY).

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit etre lance avec sudo (il configure nginx/ufw/systemd)." >&2
    echo "Usage: sudo $0" >&2
    exit 1
fi

DEPLOY_USER="${SUDO_USER:-}"
if [ -z "$DEPLOY_USER" ] || [ "$DEPLOY_USER" = "root" ]; then
    echo "Lance ce script via 'sudo', pas en te connectant directement en root," >&2
    echo "pour que le bot tourne sous ton utilisateur normal, pas root." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIVE_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
REPO_DIR="$(cd "$LIVE_DIR/.." && pwd)"

echo "== Repertoire du repo : $REPO_DIR"
echo "== Utilisateur du bot : $DEPLOY_USER"

if [ ! -f "$REPO_DIR/.env" ]; then
    echo "ERREUR: $REPO_DIR/.env introuvable." >&2
    echo "Copie d'abord ton .env (ALPACA_API_KEY / ALPACA_SECRET_KEY) a la racine du repo." >&2
    exit 1
fi
chmod 600 "$REPO_DIR/.env"
chown "$DEPLOY_USER:$DEPLOY_USER" "$REPO_DIR/.env"

# ── Packages systeme ─────────────────────────────────────────────────
echo "== Installation des paquets systeme..."
apt-get update -qq
apt-get install -y -qq nginx apache2-utils ufw curl sqlite3 openssl

# ── Pare-feu ──────────────────────────────────────────────────────────
echo "== Configuration du pare-feu (ufw)..."
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable

# ── Environnement Python (uv) ────────────────────────────────────────
if ! sudo -u "$DEPLOY_USER" bash -lc 'command -v uv' >/dev/null 2>&1; then
    echo "== Installation de uv..."
    sudo -u "$DEPLOY_USER" bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
echo "== Installation des dependances (uv sync)..."
sudo -u "$DEPLOY_USER" bash -lc "cd '$REPO_DIR' && \$HOME/.local/bin/uv sync"

# ── Certificat TLS auto-signe ─────────────────────────────────────────
mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/tradingbot.crt ]; then
    echo "== Generation du certificat auto-signe..."
    VPS_IP="$(curl -4 -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
    openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/tradingbot.key \
        -out /etc/nginx/ssl/tradingbot.crt \
        -subj "/CN=${VPS_IP}" >/dev/null 2>&1
    echo "   Certificat genere pour IP=${VPS_IP} (auto-signe — le navigateur avertira)."
else
    echo "== Certificat TLS deja present — inchange."
fi

# ── Authentification basique ─────────────────────────────────────────
HTPASSWD_FILE=/etc/nginx/.htpasswd-tradingbot
if [ ! -f "$HTPASSWD_FILE" ]; then
    echo "== Creation du compte d'acces au dashboard."
    read -rp "   Nom d'utilisateur : " AUTH_USER
    htpasswd -c "$HTPASSWD_FILE" "$AUTH_USER"
else
    echo "== Fichier d'authentification deja present — inchange."
    echo "   (pour ajouter/changer un utilisateur : htpasswd $HTPASSWD_FILE <nom>)"
fi

# ── Nginx ─────────────────────────────────────────────────────────────
echo "== Configuration de Nginx..."
cp "$DEPLOY_DIR/nginx/tradingbot.conf.template" /etc/nginx/sites-available/tradingbot
ln -sf /etc/nginx/sites-available/tradingbot /etc/nginx/sites-enabled/tradingbot
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
systemctl enable nginx >/dev/null

# ── Services systemd ──────────────────────────────────────────────────
echo "== Installation des services systemd..."
for svc in tradingbot-bot tradingbot-dashboard; do
    sed \
        -e "s#__DEPLOY_USER__#${DEPLOY_USER}#g" \
        -e "s#__REPO_DIR__#${REPO_DIR}#g" \
        "$DEPLOY_DIR/systemd/${svc}.service.template" \
        > "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
systemctl enable --now tradingbot-bot.service
systemctl enable --now tradingbot-dashboard.service

# ── Cron : scorer hebdomadaire + backup quotidien ─────────────────────
echo "== Installation des taches cron..."
chmod +x "$DEPLOY_DIR/scripts/run_scorer.sh" "$DEPLOY_DIR/scripts/backup_db.sh"
CRON_SCORER="0 18 * * 0 $DEPLOY_DIR/scripts/run_scorer.sh"
CRON_BACKUP="0 2 * * * $DEPLOY_DIR/scripts/backup_db.sh"
EXISTING_CRON="$(sudo -u "$DEPLOY_USER" crontab -l 2>/dev/null || true)"
{
    echo "$EXISTING_CRON" | grep -v -F "$DEPLOY_DIR/scripts/run_scorer.sh" | grep -v -F "$DEPLOY_DIR/scripts/backup_db.sh" | grep -v '^$'
    echo "$CRON_SCORER"
    echo "$CRON_BACKUP"
} | sudo -u "$DEPLOY_USER" crontab -

# ── Recapitulatif ─────────────────────────────────────────────────────
VPS_IP="$(curl -4 -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo " Deploiement termine."
echo " Dashboard : https://${VPS_IP}  (avertissement navigateur normal"
echo "             tant qu'aucun nom de domaine n'est configure)"
echo ""
echo " Statut des services : systemctl status tradingbot-bot tradingbot-dashboard"
echo " Logs live           : journalctl -u tradingbot-bot -f"
echo " Logs applicatifs    : $LIVE_DIR/bot.log , $LIVE_DIR/scorer_task.log"
echo " Scorer hebdo        : dimanche 18h  (voir $LIVE_DIR/scorer_task.log)"
echo " Backup DB quotidien : 02h00         ($LIVE_DIR/backups/)"
echo "════════════════════════════════════════════════════════════════"
