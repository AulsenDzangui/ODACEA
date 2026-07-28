# Journal des modifications

Toutes les modifications notables d'ODACEA sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [versionnage sémantique](https://semver.org/lang/fr/)
(`MAJOR.MINOR.PATCH`).

La version courante est portée par trois fichiers tenus synchrones
(`backend/pyproject.toml`, `web/package.json`, `backend/api/main.py`) — voir
[`docs/RELEASE.md`](docs/RELEASE.md) pour la procédure de release.

## [Non publié]

## [0.3.0] — 2026-07-28

Cette version aligne le dépôt sur la version de travail : le moteur, la ligne de
commande, les tests, l'agent d'exploration et le harnais d'évaluation arrivent
d'un bloc. Elle corrige aussi **trois défauts qui empêchaient l'installation**
sur un poste Windows récent — voir « Corrigé ».

### Ajouté

- **Agent conversationnel d'exploration** (lecture seule) : hors du parcours
  guidé, l'archiviste dialogue avec un agent pour interroger son vrac — volumes,
  types de fichiers, doublons, périodes, thématiques. Principe non négociable :
  le CSV **ne transite jamais dans un prompt**, il reste côté serveur et l'agent
  l'interroge par des **outils déterministes**, si bien que tout chiffre affiché
  est calculé, jamais deviné. Chaque appel d'outil et son résultat sont montrés
  dans l'interface. Aucun outil de modification : l'agent ne classe rien et ne
  mémorise rien.
- **Interface en ligne de commande `odacea`** : les sous-commandes `enrich`,
  `scan`, `audit`, `classement`, `run`, `apply` et `eval` couvrent le parcours
  complet en traitement par lot, avec sortie machine `--json`, diagnostic à
  blanc `--dry-run` (prompts assemblés et tokens estimés **sans aucun appel au
  modèle**), fichier de configuration `odacea.toml`, confirmation interactive
  avant écriture, et inventaire `manifest.json` des artefacts d'un traitement.
- **Harnais d'évaluation des prompts** (`odacea eval`) : mesure déterministe de
  la qualité d'un prompt sur un corpus, en croisant prompt × modèle × méthode
  d'identifiant, avec rapport historisé. Chaque prompt porte sa version, de
  sorte que deux exécutions restent comparables dans le temps.
- **Enrichissement local facultatif** : ODACEA peut lire les binaires
  bureautiques du poste pour remplir la colonne `Content.Description` (titres
  internes, mots récurrents, extraits) et calculer une **empreinte SHA-256** qui
  révèle les **doublons stricts**. Étape explicite, locale, sans appel au
  modèle, signalée comme accédant au contenu — le reste de l'outil continue de
  ne traiter que des métadonnées.
- **Plan de classement de référence** : l'archiviste peut soumettre son propre
  plan à l'audit — « s'en inspirer » ou « s'y conformer » — en important un CSV
  de dossiers seuls.
- **Audit comparatif multi-plans** : relancer l'audit N fois et **comparer les
  plans obtenus** (dossiers communs, dossiers propres à chaque variante, forme
  de l'arbre) pour choisir en connaissance de cause.
- **Manifeste d'arborescence modèle** et **journal de traitement** : deux
  exports facultatifs et locaux — la structure de dossiers cible en clair, et un
  document de traçabilité horodaté (fichier traité, modèle, durée, anomalies,
  déclaration de confidentialité).
- **Tableau de bord local du fonds** : mesures de volumétrie et de composition
  conservées avec le projet, sans serveur.
- **Options d'export** : retrait des numéros de dossiers dans l'arborescence
  produite, et option **« arborescence seule »** à l'audit — n'envoyer que les
  dossiers, aucun fichier, quand seule la structure importe.
- **Réinjection des corrections** : les rattachements corrigés à la main peuvent
  être renvoyés au classement comme exemples, pour qu'il applique la même
  logique au reste du fonds.
- **Déploiement sur site** : `docker compose up -d --build` installe ODACEA sans
  `npm` ni `pip`, en mode institutionnel par défaut, avec un
  [guide d'installation](docs/INSTALLATION_ONPREM.md) couvrant le choix d'un
  modèle local.
- **Éditer le plan dans l'explorateur de fichiers** : à l'étape d'audit, le plan
  validé peut être **matérialisé en dossiers vides réels** dans un répertoire de
  travail du poste. L'archiviste le réorganise alors avec ses gestes habituels
  — déplacer, renommer, créer, supprimer — puis recharge le dossier : ODACEA
  reconstruit le plan et affiche un **aperçu des changements** (renommés,
  déplacés, ajoutés, supprimés) avant adoption. Les préfixes numériques sont
  recalculés depuis la position, si bien qu'un aller-retour sans modification
  restitue le plan à l'identique. Aucun fichier n'est lu ni écrit : dossiers
  vides uniquement (API `POST /plan/materialize`, backend local).
- **Consignes de classement** : à l'étape de classement, l'archiviste peut
  donner des consignes qui guident l'IA — au niveau du fonds ou **ancrées à un
  dossier précis du plan** (« regrouper CV, lettre de motivation et références
  par employeur »). Elles font autorité dans le cadre du plan validé, sont
  conservées avec le projet et réutilisées à chaque relance. Une consigne peut en
  outre **autoriser la création de sous-dossiers** sous le dossier visé : le
  classement crée alors les subdivisions nécessaires (un sous-dossier par
  personne, par organisme, par affaire…), rattachées au bon dossier parent et
  numérotées dans la continuité du plan — ces créations sont listées après coup
  et ne comptent pas comme un écart au plan. Sans consigne, le classement est
  strictement inchangé. Disponible aussi en ligne de commande
  (`odacea classement … --directives consignes.txt`).

### Corrigé

- **L'installation échouait entièrement sur un Python récent.** `litellm` était
  déclaré sans borne haute ; à partir de sa version 1.84 il exige une compilation
  Rust faute de paquet précompilé universel. Sur Python 3.14 sous Windows,
  `pip install -r requirements.txt` s'arrêtait donc sur une erreur de
  compilation — et comme pip résout tout avant d'installer, **aucune dépendance
  n'était installée** : le backend était inutilisable. Les bornes hautes
  (`litellm<1.84`, `pandas<3` par prudence) rétablissent une installation en
  paquets précompilés, sans Rust.
- **`start-dev.ps1` refusait de démarrer sous Windows PowerShell 5.1**, la
  version livrée d'origine avec Windows 10 et 11 — et celle que recommande le
  README. Le script était enregistré sans marqueur d'encodage : PowerShell 5.1
  le relisait alors dans l'encodage hérité de Windows, où le tiret cadratin des
  messages se transformait en guillemet fermant, refermant une chaîne au milieu
  d'une ligne. Le script échouait à l'analyse, avant même de s'exécuter. Il est
  désormais enregistré avec marqueur d'encodage, et une note en tête du fichier
  prévient la régression.
- **Les modèles nommés `organisation/modèle` étaient inutilisables** avec une
  passerelle distante compatible OpenAI (vLLM, TGI, LiteLLM Proxy,
  OpenRouter…) : la connexion échouait sur « LLM Provider NOT provided ».
  ODACEA n'ajoutait le préfixe de routage que si le nom ne contenait aucun `/`,
  ce qui convenait aux noms courts d'Ollama ou LM Studio mais pas à la
  convention HuggingFace, pourtant la norme sur ces passerelles. Le préfixe est
  maintenant ajouté dès que le premier segment du nom n'est pas un fournisseur
  connu — plus besoin de le saisir à la main. Les noms déjà préfixés
  (`ollama/…`, `openai/…`, `gemini/…`) sont inchangés.

### Modifié

- **Le métier vit désormais entièrement côté Python.** Le format RESIP, la
  lecture du plan et la conversion du classement ne sont plus implémentés en
  double : l'interface web ne fait plus que présenter et transporter. Un même
  fonds traité par l'interface ou par la ligne de commande donne le même
  résultat, au fichier près.
- **L'audit respecte l'ordre existant du fonds par défaut.** Le plan proposé
  dérive de l'organisation déjà en place plutôt que de la refondre : verdict
  gradué sur la structuration constatée, liberté de conception proportionnelle
  au désordre réel, et écarts limités à une liste fermée de défauts chiffrés,
  listés à part pour que l'archiviste les relise un par un. La refonte libre
  reste disponible, sur demande explicite. Mesuré sur corpus de démonstration :
  conservation de l'existant environ doublée, créations de dossiers divisées par
  deux, résultats plus stables d'une exécution à l'autre.

### Renforcé

- **Tests et intégration continue** : suite de tests du moteur, de l'API et de
  la ligne de commande, tests unitaires et bout-en-bout côté web, jeux de
  données figés, chaîne d'intégration continue (lint, typage, tests, build,
  audit des dépendances) déclenchée sur chaque proposition de modification.
- **Robustesse des appels au modèle** : nouvelle tentative automatique sur
  erreur passagère, reprise d'un classement interrompu **sans repayer les lots
  déjà réussis**, arrêt propre en cours de traitement, et messages d'erreur
  typés (authentification, serveur injoignable, CSV invalide…) assortis d'une
  action recommandée.
- **Coûts et performance** : traitement de plusieurs lots en parallèle sur un
  modèle distant, mise en cache de la partie stable du prompt, estimation du
  coût en euros avant de lancer, recommandation d'échantillonnage selon la
  taille du fonds, et maintien de la connexion pendant les longues réflexions.
- **Confidentialité** : la clé API n'est pas conservée par défaut, une page
  détaille les données réellement transmises, et le mode démonstration publique
  est durci (aucune donnée visiteur analysée, quotas, limite de taille).
- **Interface** : éditeur d'arborescence structuré, validation du plan en
  direct, re-classement d'un fichier sans rappeler le modèle, vue avant/après,
  triage des anomalies, prise en main guidée et accessibilité.

## [0.2.0] — 2026-07-24

### Ajouté

- **Appliquer le classement au fonds (copie physique)** : à l'étape de
  classement, une fois le CSV RESIP produit, ODACEA peut **copier** chaque fichier
  vers une nouvelle arborescence cible (dossier distinct) selon le plan validé.
  Aperçu obligatoire avant écriture (garde-fous du dossier cible, binaires
  introuvables, collisions de noms), progression en direct, reprise d'une copie
  interrompue. **Le fonds d'origine n'est jamais modifié** (copie seule). Backend
  local (API `POST /apply/preview` et `POST /apply`).
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

[Non publié]: https://github.com/AulsenDzangui/ODACEA/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/AulsenDzangui/ODACEA/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/AulsenDzangui/ODACEA/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AulsenDzangui/ODACEA/releases/tag/v0.1.0
