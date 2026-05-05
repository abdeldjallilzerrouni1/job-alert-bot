# Bot Alertes Alternance 24/7

Bot Python qui scanne des offres toutes les 15 minutes et envoie des notifications Telegram.

## Ce que fait le bot

- Sources suivies: LinkedIn, HelloWork, Indeed, Welcome to the Jungle, La Bonne Alternance.
- Règle de filtrage:
  - Le titre contient `alternance` ou `alternant` ou `apprenti`
  - ET le titre/extrait contient `solidworks` ou `catia` ou `creo` ou `topsolid` ou `solidedge`
- Anti-doublons avec base locale SQLite (`seen_jobs.db`).

## 1) Installation locale rapide

```powershell
cd "C:\Users\walid\Downloads\PhD_CV_Template\job_alert_bot"
& "C:\Users\walid\AppData\Local\spyder-6\envs\spyder-runtime\python.exe" -m pip install -r requirements.txt
```

## 2) Configurer Telegram

1. Crée un bot Telegram avec `@BotFather` et récupère le token.
2. Envoie un message à ton bot depuis ton compte Telegram.
3. Récupère ton `chat_id` (ex: via `https://api.telegram.org/bot<TOKEN>/getUpdates`).

## 3) Variables d'environnement (PowerShell)

```powershell
$env:TELEGRAM_BOT_TOKEN = "TON_TOKEN"
$env:TELEGRAM_CHAT_ID = "TON_CHAT_ID"
$env:RUN_MODE = "daemon"
$env:POLL_MINUTES = "15"
$env:SMART_SCHEDULE = "1"
$env:DAY_POLL_MINUTES = "10"
$env:NIGHT_POLL_MINUTES = "15"
$env:DAY_START_HOUR = "8"
$env:DAY_END_HOUR = "22"
$env:NOTIFY_SCAN_STATUS = "1"
$env:DAILY_RECAP_ENABLED = "1"
$env:DAILY_RECAP_HOUR = "22"
$env:TITLE_KEYWORDS = "alternance,alternant,apprenti"
$env:DESC_KEYWORDS = "solidworks,catia,creo,topsolid,solidedge"
```

## 4) Lancer le bot

```powershell
cd "C:\Users\walid\Downloads\PhD_CV_Template\job_alert_bot"
& "C:\Users\walid\AppData\Local\spyder-6\envs\spyder-runtime\python.exe" bot.py
```

## 5) Déploiement Railway (24/7 sans PC)

1. Crée un projet Railway et connecte ce dossier via GitHub.
2. Railway détecte Python automatiquement (`requirements.txt`).
3. Commande de démarrage: `python bot.py` (ou `Procfile` worker déjà prêt).
4. Ajoute les variables d'environnement:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `RUN_MODE=daemon`
   - `POLL_MINUTES=15`
   - `TITLE_KEYWORDS=alternance,alternant,apprenti`
   - `DESC_KEYWORDS=solidworks,catia,creo,topsolid,solidedge`
5. Déploie. Le bot tourne en continu.

## Personnalisation utile

- `REGION_FILTER` (optionnel), ex: `Nouvelle-Aquitaine`
- `MAX_RESULTS_PER_SOURCE` (défaut 25)
- `RUN_MODE=once` pour faire un test unique
- Mode intelligent:
  - `SMART_SCHEDULE=1`
  - `DAY_POLL_MINUTES=5`
  - `NIGHT_POLL_MINUTES=15`
  - `DAY_START_HOUR=8`
  - `DAY_END_HOUR=22`
- Messages de suivi:
  - `NOTIFY_SCAN_STATUS=1` (message Telegram à chaque fin de scan)
  - `DAILY_RECAP_ENABLED=1`
  - `DAILY_RECAP_HOUR=22` (récap quotidien à 22h)
