# ODACEA

**Outil Documentaire d'Audit et de Classement d'Archives Électroniques**

ODACEA assiste les archivistes dans l'analyse et la réorganisation de vracs ou arborescences bureautiques. Il prend en entrée un CSV exporté par [Archifiltre](https://www.programmevitam.fr/pages/ressources/logiciel_archifiltre/) ou un export natif [RESIP](https://www.programmevitam.fr/pages/ressources/resip/) (converti automatiquement), et produit en sortie un CSV réorganisé, prêt à être réutilisé pour un export SIP SEDA ou une réorganisation d'arborescence dans RESIP.

L'IA ne voit que les **métadonnées** (chemins, noms de fichiers, dates), jamais le contenu des documents. L'outil est conçu pour fonctionner avec des **modèles locaux** (Ollama, LM Studio, JAN), de sorte qu'aucune donnée ne quitte l'infrastructure de l'institution.

## Workflow en trois étapes

1. **Audit** : l'IA analyse le vrac (volumétrie, formats à risque, doublons, données personnelles, logique de classement existante) et propose un plan de classement adapté au fonds.
2. **Validation** : l'archiviste examine le plan, le modifie si nécessaire, puis le valide. C'est l'archiviste qui décide.
3. **Classement** : l'IA applique le plan validé à chaque fichier (dossier cible + nom normalisé). Le résultat est un CSV RESIP téléchargeable.

> **Préparation facultative — enrichissement des métadonnées.** Si les noms de fichiers sont peu explicites (`doc1.docx`, `scan0042.pdf`…), une étape `enrich` peut renseigner la colonne `Content.Description` en lisant les métadonnées internes des documents locaux (PDF, DOCX, XLSX, PPTX) avant l'audit. Elle s'exécute **entièrement en local, sans IA et sans réseau**, et ne modifie jamais le fichier d'origine. Détails dans le [guide utilisateur](docs/GUIDE_UTILISATEUR.md#étape-de-préparation-facultative--enrichir-les-métadonnées).

## Architecture

Un **moteur Python** porte toute la logique métier (lecture/écriture CSV RESIP, prompts AUD-001/CLA-001, dispatch LLM *(routage du modèle selon le fournisseur : Anthropic, OpenAI, Google, Ollama local, etc.)*, conversion RESIP). Deux interfaces le consomment, sans duplication :

| Composant | Dossier | Techno | Rôle |
|---|---|---|---|
| **Moteur + API + CLI** | [`backend/`](backend/) | Python · FastAPI · LiteLLM | Backend HTTP qui sert le front + interface batch (`cli.py`) pour l'automatisation |
| **Front web** | [`web/`](web/) | Next.js 16 · React 19 | Interface graphique ; appelle le backend via `/api/py/*` (proxy same-origin) |

Le front (`web/`) ne fait que de la présentation : tout le traitement passe par le backend Python (`backend/api/`), qui peut tourner sur un **modèle local** pour que les données ne quittent pas l'infrastructure.

### Démarrage rapide

Le front a besoin du backend lancé en parallèle. Sous Windows, un script démarre les deux ensemble :

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1   # → http://localhost:9000
```

Ou manuellement, en deux terminaux (après `pip install` / `npm install` une première fois) :

```bash
# Terminal 1 : backend (port 8000)
cd backend
pip install -r requirements.txt
cp .env.example .env            # renseigner les clés API si modèle cloud
uvicorn api.main:app --port 8000 --reload

# Terminal 2 : front (port 9000)
cd web
npm install
npm run dev
```

En production, le front sert le backend via un proxy same-origin (`/api/py/*`, Route Handler `web/app/api/py/[...path]/route.ts`) qui préserve le streaming SSE de l'audit et du classement ; pointez l'URL du backend avec la variable d'environnement `ODACEA_API_URL`.

### Automatisation (sans interface)

Le moteur est aussi exposé en ligne de commande, pour l'intégration dans des chaînes de traitement (GED, scripts d'import, pipelines de versement) :

```bash
cd backend
python cli.py enrich --input fichier.csv --source-root <dossier>   # préparation facultative (local, sans IA)
python cli.py run --input fichier.csv                              # audit + classement enchaînés
python cli.py {enrich,audit,classement,run} --help
```

## Volumétrie recommandée

ODACEA envoie les métadonnées du vrac au modèle en une fois (à l'audit) puis par lots (au classement). Pour un traitement fiable, visez **800 à 1000 items par passe**, ce qui tient confortablement dans une fenêtre de contexte de **128K tokens**. Au-delà, découpez le versement en plusieurs lots, ou activez les options de réduction de contexte (échantillonnage des fichiers, filtrage des colonnes) ; voir le [guide utilisateur](docs/GUIDE_UTILISATEUR.md). La volumétrie utile dépend aussi du modèle : un 14B local sature plus vite qu'un grand modèle cloud.

## Jeu de données de démonstration

Le dossier [`demo/`](demo/) contient trois générateurs d'arborescence bureautique fictive (petit, moyen, grand) calibrés selon la taille du modèle LLM utilisé. Les arborescences générées simulent un service municipal d'Affaires scolaires et reproduisent les patterns de désordre typiques d'un vrac réel (doublons, versions cumulées, naming incohérent, etc.).

```bash
python demo/generate_demo_tree_small.py    # → demo_data/…_SMALL/  (82 fichiers, modèle 14B)
python demo/generate_demo_tree.py          # → demo_data/…/         (184 fichiers, modèle 13-30B)
python demo/generate_demo_tree_large.py    # → demo_data/…_LARGE/   (604 fichiers, modèles cloud)
```

Le dossier `demo_data/` est gitignoré : chaque utilisateur le régénère localement. Voir [`demo/README.md`](demo/README.md) pour le workflow complet de démo.

## Documentation

- [`docs/GUIDE_UTILISATEUR.md`](docs/GUIDE_UTILISATEUR.md) : guide utilisateur (interface web + CLI)

## Origine

ODACEA est une **déclinaison applicative** de la [Bibliothèque de prompts archivistiques](https://github.com/AulsenDzangui/bibliotheque-prompts-archivistiques).

## Licence

ODACEA applique une **double licence** :

- **Code applicatif** : [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).
- **Textes de prompts** (la valeur textuelle des chaînes `SYSTEM_PROMPT` de `backend/prompts/*.py`, et tout fichier portant l'en-tête « Licence CC BY-SA 4.0 ») : [Creative Commons Attribution - Partage dans les Mêmes Conditions 4.0 International](LICENSE-PROMPTS) (CC BY-SA 4.0), comme la bibliothèque dont ils sont issus.
