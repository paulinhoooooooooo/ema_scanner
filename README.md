# EMA Scanner — Guide d'installation (Mac + Telegram iPhone)

## Ce que fait ce programme

Chaque soir à l'heure que tu choisis, il scanne tous tes tickers et t'envoie
une notification Telegram sur iPhone si un de ces événements se produit :

- 🟢 **Signal Long** — le prix croise au-dessus de ton EMA longue
- 🔴 **Signal Short** — le prix croise en dessous de ton EMA longue
- ⚠️ **Anticipation** — l'EMA courte est à moins de X% de l'EMA longue (croisement imminent)

---

## Étape 1 — Créer ton bot Telegram (5 minutes)

1. Ouvre Telegram et cherche **@BotFather**
2. Envoie `/newbot`
3. Donne un nom à ton bot (ex: `MonScannerEMA`)
4. Donne un username (ex: `MonScannerEMA_bot`)
5. BotFather te donne un **token** — copie-le (ressemble à `7123456789:AAFxxxx...`)

6. Cherche ton bot dans Telegram et envoie-lui `/start`
7. Ouvre ce lien dans ton navigateur (remplace TON_TOKEN) :
   `https://api.telegram.org/botTON_TOKEN/getUpdates`
8. Tu vois un JSON — note le `"id"` dans `"chat"` : c'est ton **chat_id**

---

## Étape 2 — Configurer le programme

Ouvre `config.json` et remplace :
- `"REMPLACE_PAR_TON_TOKEN"` → ton token BotFather
- `"REMPLACE_PAR_TON_CHAT_ID"` → ton chat_id (nombre entier, ex: 123456789)

Tu peux aussi changer l'heure du scan (`"heure": "19:00"`) et les paramètres EMA.

---

## Étape 3 — Ajouter tes tickers

Ouvre `tickers.txt` et ajoute tes actions, une par ligne :

```
AAPL
LVMH.PA
TTE.PA
NVDA
SAN.PA
```

**Suffixes par marché :**
- `.PA` → Euronext Paris (LVMH.PA, TTE.PA...)
- `.DE` → Frankfurt (SAP.DE, SIE.DE...)
- `.MC` → Madrid
- `.MI` → Milan
- Rien → US (AAPL, TSLA, NVDA...)

---

## Étape 4 — Installer Python et les dépendances

Ouvre le Terminal (Cmd+Espace → Terminal) :

```bash
# Vérifier que Python est installé
python3 --version

# Installer les dépendances
pip3 install yfinance pandas numpy requests
```

---

## Étape 5 — Lancer le programme

```bash
# Va dans le dossier du scanner
cd /chemin/vers/ema_scanner

# Test immédiat (lance un scan maintenant)
python3 scanner.py

# Lancement automatique chaque soir (garde ce Terminal ouvert, ou mets en arrière-plan)
python3 scheduler.py
```

### Pour que ça tourne même quand le Terminal est fermé :

```bash
# Lance en arrière-plan et détache du terminal
nohup python3 scheduler.py > /dev/null 2>&1 &

# Pour voir s'il tourne encore
ps aux | grep scheduler.py

# Pour l'arrêter
pkill -f scheduler.py
```

---

## Modifier les paramètres

### Changer les EMAs ou l'heure → `config.json`

```json
"ema": {
  "courte": 21,      ← EMA d'anticipation
  "longue": 55,      ← EMA principale (signal de croisement)
  "tendance": 200    ← EMA de tendance (affiché dans le message)
},
"scan": {
  "heure": "19:00"   ← Heure du scan (format 24h, Paris)
}
```

### Activer/désactiver des signaux → `config.json`

```json
"signaux": {
  "long_actif": true,         ← Notifications Long
  "short_actif": true,        ← Notifications Short
  "anticipation_actif": true, ← Alertes anticipation
  "anticipation_marge_pct": 1.5  ← Seuil d'anticipation en %
}
```

### Ajouter/enlever des actions → `tickers.txt`

Ouvre le fichier, ajoute ou supprime des lignes. Le prochain scan prendra
automatiquement en compte les changements, sans redémarrer le programme.

---

## Exemple de notification reçue sur iPhone

```
🟢 Signal Long — NVDA

Prix 875.32 vient de passer au-dessus de l'EMA55 (862.10)
Écart : +1.5% | EMA200 : 741.23
RSI : 58.3 | ADX : 32.1

📅 03/06/2026 19:04
```

---

## Fichiers du projet

```
ema_scanner/
├── config.json      ← Paramètres (EMAs, heure, Telegram, filtres)
├── tickers.txt      ← Tes actions à surveiller
├── scanner.py       ← Le moteur d'analyse
├── scheduler.py     ← Le planificateur automatique
├── scanner.log      ← Journal des scans (créé automatiquement)
└── scheduler.log    ← Journal du planificateur (créé automatiquement)
```
