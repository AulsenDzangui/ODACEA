# Versionnage et releases

> **Tags semver, CHANGELOG.md, artefacts de release (image Docker, wheel
> CLI).** Ce document décrit la politique de version et la procédure de
> release. Il ne réintroduit aucune logique métier — c'est de l'**outillage
> de distribution**.

## 1. Politique de versionnage — semver

ODACEA suit le [versionnage sémantique](https://semver.org/lang/fr/)
`MAJOR.MINOR.PATCH` :

- **MAJOR** — rupture de compatibilité (format CSV/RESIP de sortie, contrat
  d'API HTTP, options CLI supprimées).
- **MINOR** — fonctionnalité ajoutée de façon rétro-compatible (nouvelle
  sous-commande, nouvel endpoint, nouvelle option).
- **PATCH** — correctif rétro-compatible (bug, durcissement, documentation).

Une **modification de prompt** (AUD-001/CLA-001) suit en plus son propre
`PROMPT_VERSION`, indépendant de la version du produit : un prompt peut
évoluer sans changer la version du paquet, et inversement. Toute modification de
prompt reste conditionnée à une évaluation chiffrée avant adoption.

## 2. Source de vérité de la version

La version courante est portée par **trois fichiers tenus synchrones** :

| Fichier | Emplacement | Rôle |
| --- | --- | --- |
| `backend/pyproject.toml` | `version = "X.Y.Z"` | packaging du wheel CLI |
| `web/package.json` | `"version": "X.Y.Z"` | front |
| `backend/api/main.py` | `FastAPI(title="ODACEA API", version="X.Y.Z")` | bannière/route OpenAPI de l'API |

Ils **ne doivent jamais diverger**. Deux garde-fous :

- `scripts/bump_version.py` réécrit les trois d'un seul geste.
- `backend/tests/test_release.py` échoue si les trois ne concordent pas (donc en
  CI sur chaque PR).

> Historique : les tags `v0.1.1` et `v0.1.2` ont été posés avant cette
> synchronisation ; les fichiers étaient restés à `0.1.0`. C'est précisément la
> dérive que la release supprime.

## 3. Procédure de release (pas-à-pas)

1. **Mettre à jour le `CHANGELOG.md`** : déplacer le contenu de `[Non publié]`
   sous une nouvelle section `[X.Y.Z] — AAAA-MM-JJ`, et mettre à jour les liens
   de comparaison en bas de fichier.
2. **Bumper la version** dans les trois fichiers :
   ```bash
   python scripts/bump_version.py minor    # ou major | patch | X.Y.Z
   python scripts/bump_version.py --check   # vérifie la concordance
   ```
3. **Vérifier les portes de qualité** localement (ou via la CI sur la PR) :
   ```bash
   cd backend && python -m pytest && ruff check . && python -m mypy
   cd web && npm run lint && npx tsc --noEmit && npm run build && npm test
   ```
4. **Commiter** (`chore(release): X.Y.Z`) et fusionner sur `main`.
5. **Poser le tag** semver et le pousser :
   ```bash
   git tag -a vX.Y.Z -m "ODACEA vX.Y.Z"
   git push origin vX.Y.Z
   ```
6. Le workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml)
   se déclenche sur le tag `v*.*.*` et produit les **artefacts de release**
   (cf. §4). La pose du tag est l'**acte de release** ; le script ne tague pas
   de lui-même.

## 4. Artefacts de release

Sur un tag `vX.Y.Z`, le workflow `release.yml` :

1. **Vérifie la cohérence de version** : les trois fichiers concordent **et** le
   tag (`vX.Y.Z`) correspond à la version du dépôt (échec sinon — pas de release
   incohérente).
2. **Wheel + sdist de la CLI** : `python -m build` (depuis `backend/`) produit
   `odacea-X.Y.Z-py3-none-any.whl` + `odacea-X.Y.Z.tar.gz`, attachés à la GitHub
   Release et conservés comme artefacts du run. Installation hors dépôt :
   ```bash
   pip install odacea-X.Y.Z-py3-none-any.whl
   odacea --help
   ```
3. **Images Docker** `backend` et `web` (les Dockerfiles de référence)
   buildées et poussées vers le **GitHub Container Registry** (`ghcr.io`),
   taguées par la version **et** `latest` :
   - `ghcr.io/<owner>/odacea/backend:X.Y.Z`
   - `ghcr.io/<owner>/odacea/web:X.Y.Z`

   Le [`compose.yml`](../compose.yml) reste le mode d'installation institutionnel
   de référence (build depuis les sources) ; les images publiées offrent une
   variante sans build local pour une institution qui préfère tirer des images.

> **Note d'environnement** : comme pour le build/up Docker, la publication
> effective vers `ghcr.io` requiert l'exécution réelle du workflow sur GitHub
> Actions (registre joignable). Le *contrat* de release (présence du workflow,
> étapes de build du wheel et des images, garde de cohérence de version) est
> verrouillé hors-ligne par `backend/tests/test_release.py`.

## 5. Vérifier une release localement (sans GitHub)

```bash
# Wheel CLI
cd backend && pip install build && python -m build && ls dist/

# Images Docker (registre joignable requis pour le pull des bases)
docker compose build           # backend + web depuis compose.yml
```
