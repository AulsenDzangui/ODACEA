# Journal des modifications

Toutes les modifications notables d'ODACEA sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [versionnage sémantique](https://semver.org/lang/fr/)
(`MAJOR.MINOR.PATCH`).

## [Non publié]

### Ajouté

- **Importer son propre plan de classement** : à l'étape d'audit, l'archiviste
  peut fournir directement son plan — en déposant un fichier (CSV Resip
  « dossiers seuls » ou Markdown), ou en **désignant un dossier existant du
  poste** dont l'arborescence sert de plan. Il est adopté tel quel, **sans passer
  par l'audit IA**, et sert ensuite au classement comme un plan issu de l'audit.
  Sans appel LLM (API `POST /plan/from-file` et `POST /plan/from-folder`, backend
  local).
- **Import direct d'un dossier local** : à l'étape d'import, une alternative à
  l'upload d'un CSV Archifiltre — le moteur scanne l'arborescence du vrac sur la
  machine (métadonnées seules, **le contenu des fichiers n'est jamais ouvert**)
  et en dérive le CSV canonique, ensuite traité comme un CSV importé. Le CSV
  dérivé est aussi téléchargeable. Disponible en ligne de commande
  (`odacea scan <dossier> -o vrac.csv`) et via l'API (`POST /parse/from-folder`).
  Fonctionne uniquement lorsque le backend tourne en local.

## [0.1.0] — 2026

### Ajouté

- Première version publique d'ODACEA : audit et classification d'archives
  électroniques (SEDA / RESIP) assistés par IA, sur **métadonnées uniquement**
  (chemins, noms, dates — jamais le contenu des documents).
- Flux en trois étapes : import CSV → audit → classification → export CSV au
  format RESIP.
- Moteur métier Python (FastAPI) + interface web React/Next.
- Support des modèles locaux (Ollama, LM Studio) pour garder les données
  sensibles sur site, en plus des fournisseurs cloud.

[Non publié]: https://github.com/AulsenDzangui/ODACEA/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AulsenDzangui/ODACEA/releases/tag/v0.1.0
