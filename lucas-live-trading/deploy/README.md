# Déploiement sur VPS Ubuntu

Met le bot, le dashboard, le scorer hebdomadaire et les sauvegardes en
service permanent sur un VPS, accessible via HTTPS + mot de passe.

## Ce que ça installe

- `tradingbot-bot.service` — `bot.py`, redémarre automatiquement en cas
  de crash ou de reboot du VPS.
- `tradingbot-dashboard.service` — Streamlit, bindé sur `127.0.0.1`
  uniquement (jamais exposé directement).
- Nginx en reverse proxy sur le port 443, avec certificat TLS
  auto-signé et authentification HTTP basique devant le dashboard.
- `ufw` : seuls SSH, 80 et 443 sont ouverts.
- Cron : scorer chaque dimanche 18h, backup de `bars.db` chaque nuit
  à 2h (rétention 30 jours).

## Étapes

**1. Transférer le repo sur le VPS** (depuis ta machine Windows, avec
Git Bash ou WSL — `scp`/`rsync` n'existent pas nativement dans
PowerShell) :

```bash
rsync -avz --exclude '.venv' --exclude '__pycache__' \
    /c/Users/Lucas/Documents/TradingBot/ user@VPS_IP:~/TradingBot/
```

Ou simplement `git clone` ton repo directement sur le VPS si tu l'as
poussé sur GitHub/GitLab.

**2. Copier le `.env`** (jamais commité dans git) — depuis ta machine :

```bash
scp /c/Users/Lucas/Documents/TradingBot/.env user@VPS_IP:~/TradingBot/.env
```

**3. Lancer le script d'installation**, sur le VPS :

```bash
cd ~/TradingBot
sudo bash lucas-live-trading/deploy/scripts/setup_vps.sh
```

Il va demander un nom d'utilisateur + mot de passe pour l'accès au
dashboard (authentification HTTP basique), installer tout, et
afficher l'URL finale à la fin.

**4. Ouvrir `https://<IP_DU_VPS>`** dans un navigateur. Le certificat
étant auto-signé, le navigateur affichera un avertissement de
sécurité une fois — c'est normal, clique sur "Avancé → continuer".
Renseigne ensuite le nom d'utilisateur / mot de passe créés à l'étape 3.

## Opérations courantes

```bash
# Statut des services
systemctl status tradingbot-bot tradingbot-dashboard

# Logs en direct
journalctl -u tradingbot-bot -f
journalctl -u tradingbot-dashboard -f

# Redémarrer après une mise à jour du code
git pull
sudo systemctl restart tradingbot-bot tradingbot-dashboard

# Lancer le scorer manuellement (dry-run)
.venv/bin/python lucas-live-trading/scorer.py --dry-run

# Voir les sauvegardes de la base
ls -lh lucas-live-trading/backups/
```

## Migrer vers un vrai domaine plus tard

Quand tu pointes un nom de domaine vers l'IP du VPS, remplace le
certificat auto-signé par un vrai certificat Let's Encrypt :

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ton-domaine.com
```

Certbot réécrit automatiquement la configuration Nginx et gère le
renouvellement — plus d'avertissement navigateur.

## Limite connue

L'onglet **Configuration** du dashboard permet de modifier
`config.json` (signaux actifs, seuils, stop-loss) directement depuis
le navigateur. C'est protégé par le mot de passe Nginx comme le reste
du dashboard, mais ça reste une opération d'écriture exposée à
distance — ne partage jamais les identifiants du dashboard.
