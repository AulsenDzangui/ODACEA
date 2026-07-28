# Installation on-prem d'ODACEA

> Mode d'installation **institutionnel de référence** : une archive
> départementale fait tourner ODACEA sur sa propre infrastructure, avec un
> **modèle local** (Ollama / LM Studio), **sans `npm` ni `pip`**, et
> **sans qu'aucune donnée ne quitte le réseau interne**.
>
> Ce guide couvre : (1) le déploiement par Docker Compose, (2) l'installation
> d'un moteur de modèle local et le choix d'un modèle 13–30B, (3) la
> configuration réseau interne.

## Vue d'ensemble

ODACEA est composé de deux services :

| Service | Rôle | Port |
|---|---|---|
| `backend` | moteur Python (FastAPI) — toute la logique métier | `8000` (interne) |
| `web` | interface Next.js — présentation + proxy `/api/py/*` | `9000` (exposé) |

Le navigateur ne parle **qu'au front** (`web`), qui relaie vers le `backend` sur
le réseau interne du compose. Le backend est **sans état** : aucune donnée n'est
persistée côté serveur ; les projets vivent dans le `localStorage` du navigateur
de l'archiviste.

```text
  Poste archiviste                Hôte Docker
  ┌───────────────┐    :9000    ┌──────────────────────────────┐
  │   Navigateur  │ ──────────► │  web (Next.js)               │
  └───────────────┘             │     │ proxy /api/py/*          │
                                │     ▼ backend:8000            │
                                │  backend (FastAPI / moteur)   │
                                └───────────┬──────────────────┘
                                            │ http (réseau interne)
                                            ▼
                                   Ollama / LM Studio (modèle local)
```

## 1. Prérequis

- Un serveur **Linux** avec **Docker Engine ≥ 24** et le plugin **Docker Compose
  v2** (`docker compose version`).
- Pour un déploiement **100 % local** (recommandé pour les données sensibles) :
  une machine capable de faire tourner un modèle 13–30B (cf. §3) — idéalement
  un GPU avec ≥ 16 Go de VRAM, ou un CPU récent avec ≥ 32 Go de RAM (plus lent).
- Aucune clé API n'est nécessaire en mode local ; pour un modèle cloud, prévoir
  la clé du fournisseur (saisie dans l'UI, **non persistée par défaut**).

## 2. Déploiement par Docker Compose

Depuis la racine du dépôt (ou d'une copie des fichiers `compose.yml`,
`backend/`, `web/`) :

```bash
# (facultatif) surcharger les défauts
cp .env.compose.example .env        # éditer DEFAULT_MODEL, port, etc.

# construire et démarrer les deux services
docker compose up -d --build

# l'interface est sur http://<hôte>:9000
```

Vérifications :

```bash
docker compose ps                   # les deux services « running »
curl -s http://localhost:9000/      # le front répond (HTTP 200)
docker compose logs -f backend      # journaux du moteur
```

Arrêt / mise à jour :

```bash
docker compose down                 # arrêt
git pull && docker compose up -d --build   # mise à jour vers une nouvelle version
```

### Variables d'environnement

Toutes ont un défaut dans `compose.yml` ; un fichier `.env` à la racine les
surcharge (voir `.env.compose.example`).

| Variable | Défaut | Rôle |
|---|---|---|
| `DEFAULT_MODEL` | `ollama/qwen2.5:14b` | modèle proposé au démarrage de l'UI (surchargeable dans l'UI) |
| `ODACEA_WEB_PORT` | `9000` | port d'exposition du front sur l'hôte |
| `ODACEA_MAX_CSV_MB` | `20` | taille maximale du CSV accepté |
| `ODACEA_MAX_CSV_ROWS` | `50000` | garde mémoire sur le nombre de lignes |
| `ALLOWED_ORIGINS` | *(vide ⇒ `*`)* | CORS ; le navigateur ne parle qu'au front, laisser vide |
| `DEMO_MODE` | `0` | **0 = institutionnel** ; 1 = démonstration publique |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | *(vide)* | clés cloud **optionnelles** ; préférer la saisie dans l'UI |

> **Mode institutionnel (`DEMO_MODE=0`)** : le modèle, la clé et le point d'accès
> local sont saisis dans l'UI (**Paramètres → Modèle & connexion**) et transmis à
> chaque requête. Le mode démonstration (`DEMO_MODE=1`) impose au contraire le CSV
> embarqué et des quotas — réservé à une vitrine publique.

## 3. Installer un moteur de modèle local

ODACEA est conçu pour que **les données ne quittent pas l'institution**. On fait
donc tourner un modèle local et on pointe ODACEA dessus.

### Ollama (recommandé)

```bash
# installation (Linux)
curl -fsSL https://ollama.com/install.sh | sh

# télécharger un modèle 13–30B (cf. choix ci-dessous)
ollama pull qwen2.5:14b

# Ollama écoute par défaut sur http://localhost:11434 (API compatible OpenAI
# sur /v1). Pour qu'il accepte les connexions du conteneur backend, l'exposer
# sur toutes les interfaces :
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

### LM Studio

Installer LM Studio (interface graphique), télécharger un modèle 13–30B au format
GGUF, puis démarrer le **serveur local** (onglet « Developer » / « Local Server »)
— il expose une API compatible OpenAI sur `http://localhost:1234/v1`.

### Choix d'un modèle (13–30B)

Les prompts d'ODACEA (AUD-001, CLA-001) sont **validés sur des modèles locaux
14B** : un échec à cette taille signale un défaut de prompt, pas une limite du
modèle. Repères :

| Taille | Exemples | Usage |
|---|---|---|
| **14B** | `qwen2.5:14b`, `qwen2.5-coder:14b` | socle de référence — bon compromis qualité/ressources, tient sur un GPU 16 Go |
| **~30B** | `qwen2.5:32b` | meilleure qualité de classement (CLA-001) sur les gros fonds ; demande ≈ 32 Go (VRAM ou RAM) |

Conseils :

- Privilégier un modèle **récent et instruct** ; un contexte d'au moins **32K
  tokens** (idéalement 128K) facilite les gros vracs — voir « Volumétrie
  recommandée » dans le [README](../README.md).
- Mesurer avant d'envoyer : `odacea audit vrac.csv --model … --dry-run` estime
  les tokens d'entrée sans aucun appel LLM.
- Sur un fonds volumineux, découper le classement en lots (`--batch-size`) et
  réduire le contexte (échantillonnage des fichiers, filtrage des colonnes).

## 4. Configuration réseau interne

### Pointer ODACEA vers le modèle local

Dans l'UI (**Paramètres → Modèle & connexion**), renseigner le **point d'accès
local** selon l'emplacement du moteur de modèle :

| Le modèle tourne… | Point d'accès à saisir dans l'UI |
|---|---|
| sur **l'hôte Docker** (même machine) | `http://host.docker.internal:11434/v1` (Ollama) — le service `backend` résout `host.docker.internal` (`extra_hosts` du `compose.yml`) |
| sur **une autre machine** du réseau | `http://<ip-serveur-modele>:11434/v1` |
| dans **un conteneur** du même compose | l'ajouter comme service et utiliser son nom de service |

Le **nom de modèle** suit la convention LiteLLM : `ollama/<modèle>` pour Ollama,
`openai/<modèle>` + point d'accès pour LM Studio / JAN / tout serveur compatible
OpenAI. Les serveurs locaux reçoivent automatiquement une clé factice
(`lm-studio`) — aucun secret à fournir.

### Accès et cloisonnement

- **N'exposer que le port `9000`** (le front). Le backend (`8000`) reste interne
  au réseau Docker (`expose`, pas `ports`) et n'a pas besoin d'être joignable
  depuis l'extérieur.
- Restreindre l'accès au port `9000` au **réseau interne** de l'institution
  (pare-feu / VLAN). ODACEA est un outil **mono-poste ou intranet** : pas
  d'authentification multi-utilisateurs (non-objectif assumé).
- Pour un accès HTTPS interne, placer un **reverse-proxy** (nginx, Caddy,
  Traefik) devant le service `web` et y terminer TLS. Conserver le streaming :
  désactiver la mise en tampon des réponses (`proxy_buffering off;` côté nginx) —
  l'audit et le classement utilisent du SSE.
- **Aucune sortie réseau** n'est nécessaire en mode 100 % local : ODACEA ne
  fait aucune télémétrie, et le backend ne contacte que le modèle configuré.

## 5. Dépannage

| Symptôme | Piste |
|---|---|
| Le front charge mais l'audit échoue (`llm_unreachable`) | vérifier le point d'accès local et que le modèle écoute sur `0.0.0.0` (et non `127.0.0.1`) ; depuis le conteneur : `docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version').read())"` |
| `host.docker.internal` introuvable | s'assurer que `extra_hosts: ["host.docker.internal:host-gateway"]` est présent sur `backend` (cas par défaut du `compose.yml`) |
| CSV refusé (`csv_too_large`) | relever `ODACEA_MAX_CSV_MB` / `ODACEA_MAX_CSV_ROWS`, ou découper le vrac |
| Réponses tronquées derrière un proxy | désactiver la mise en tampon (`proxy_buffering off;`) ; le heartbeat SSE maintient la connexion ouverte pendant la réflexion du modèle |
| Le backend redémarre en boucle | `docker compose logs backend` — souvent une dépendance ou un port déjà pris |

## Voir aussi

- [Guide utilisateur](GUIDE_UTILISATEUR.md) — parcours web et CLI.
