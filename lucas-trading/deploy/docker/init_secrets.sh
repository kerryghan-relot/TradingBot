#!/usr/bin/env bash
# Generate the nginx secrets the compose stack mounts:
#   - a self-signed TLS certificate (until a real domain + Certbot)
#   - an HTTP basic-auth .htpasswd for the dashboard
#
# Idempotent: existing files are left untouched.  Run once before the
# first `docker compose up`, from anywhere:
#   lucas-trading/deploy/docker/init_secrets.sh
#
# Credentials default to DASHBOARD_USER / DASHBOARD_PASSWORD from the
# repo-root .env when present; otherwise you are prompted.

set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DOCKER_DIR/../../.." && pwd)"
CERT_DIR="$DOCKER_DIR/certs"
HTPASSWD_FILE="$DOCKER_DIR/.htpasswd"

mkdir -p "$CERT_DIR"

# ── Self-signed TLS certificate ───────────────────────────────────────
if [ ! -f "$CERT_DIR/tradingbot.crt" ]; then
    echo "== Génération du certificat auto-signé…"
    HOST="$(curl -4 -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
    openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout "$CERT_DIR/tradingbot.key" \
        -out "$CERT_DIR/tradingbot.crt" \
        -subj "/CN=${HOST:-tradingbot.local}" >/dev/null 2>&1
    echo "   Certificat généré (CN=${HOST:-tradingbot.local}, auto-signé)."
else
    echo "== Certificat TLS déjà présent — inchangé."
fi

# ── HTTP basic-auth ───────────────────────────────────────────────────
if [ ! -f "$HTPASSWD_FILE" ]; then
    # Load DASHBOARD_USER/PASSWORD from .env if available.
    if [ -f "$REPO_DIR/.env" ]; then
        # shellcheck disable=SC1091
        set -a; . "$REPO_DIR/.env"; set +a
    fi
    AUTH_USER="${DASHBOARD_USER:-}"
    AUTH_PASS="${DASHBOARD_PASSWORD:-}"
    if [ -z "$AUTH_USER" ]; then
        read -rp "   Nom d'utilisateur dashboard : " AUTH_USER
    fi
    if [ -z "$AUTH_PASS" ]; then
        read -rsp "   Mot de passe dashboard : " AUTH_PASS; echo
    fi
    # htpasswd via a throwaway container so no host package is required.
    docker run --rm httpd:alpine \
        htpasswd -nbB "$AUTH_USER" "$AUTH_PASS" > "$HTPASSWD_FILE"
    echo "== .htpasswd créé pour l'utilisateur '$AUTH_USER'."
else
    echo "== .htpasswd déjà présent — inchangé."
fi

echo "== Secrets prêts dans $DOCKER_DIR (certs/ + .htpasswd)."
