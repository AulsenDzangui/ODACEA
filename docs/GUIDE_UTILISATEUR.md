# Documentation ODACEA

## Qu'est-ce qu'ODACEA ?

ODACEA est un outil qui automatise le traitement d'un vrac bureautique à partir d'un export CSV Archifiltre ou RESIP. Il prend en charge deux étapes :

1. **L'audit** : analyse la structure du vrac, identifie les problèmes et propose un plan de classement.
2. **Le classement** : applique ce plan en attribuant à chaque fichier un dossier cible et un titre normalisé, puis génère un CSV directement importable dans RESIP.

L'outil peut fonctionner entièrement avec un modèle d'IA local (Ollama, LM Studio, JAN) pour garantir la **confidentialité des données**. ODACEA n'analyse que les **métadonnées** du CSV (chemins, noms, dates) — jamais le contenu de vos fichiers. Avec un modèle local, aucune donnée ne quitte l'infrastructure de votre institution ; avec un modèle cloud, seules ces métadonnées sont transmises au fournisseur que vous avez choisi.

---

## Format du fichier CSV attendu

ODACEA accepte deux types de fichiers d'entrée :

- un export **Archifiltre Docs** ;
- un export **Resip**.

| Propriété | Valeur attendue |
|---|---|
| Séparateur | `;` |
| Encodage | UTF-8 avec BOM (`utf-8-sig`) |
| Extension | `.csv` |

Colonnes obligatoires : `ID`, `ParentID`, `File`, `Content.DescriptionLevel`, `Content.Title`, `Content.StartDate`, `Content.EndDate`.

Un CSV produit directement par RESIP est également accepté tel quel et converti automatiquement au format attendu. Le CSV de sortie reste, lui, toujours au format Archifiltre.

Le fichier peut contenir des colonnes supplémentaires. Elles sont conservées dans le CSV de sortie.

---

## Configuration du modèle d'IA

### Modèles en ligne (cloud)

Saisissez votre **clé API** dans le champ prévu et sélectionnez un modèle dans la liste (ou entrez son nom au format LiteLLM).

| Préfixe | Fournisseur |
|---|---|
| `claude-*` | Anthropic |
| `gpt-*` | OpenAI |
| `gemini/...` | Google |

### Modèles locaux

Laissez la clé API vide, sélectionnez l'URL prédéfinie correspondant à votre outil (Ollama, LM Studio ou JAN) ou entrez une URL personnalisée, puis indiquez le nom du modèle au format LiteLLM :

| Outil | Exemple de nom de modèle |
|---|---|
| Ollama | `ollama/qwen2.5:32b` |
| LM Studio / JAN | `openai/mon-modele` |

Cliquez sur **Tester la connexion** pour vérifier que le modèle répond avant de lancer un traitement.

---

## Étape de préparation (facultative) : enrichir les métadonnées

ODACEA analyse uniquement les **métadonnées** du CSV (chemins, noms, dates), pas le contenu des fichiers. Cependant, si vos fichiers ont des noms peu explicites (`doc1.docx`, `scan0042.pdf`...), l'étape `enrich` vous permet d'enrichir le CSV avec les métadonnées internes des documents (titre, sujet, auteur…) avant l'analyse.

L'étape `enrich` remplit automatiquement cette colonne en lisant les fichiers présents sur votre machine. Elle extrait les propriétés internes du document (titre, sujet, mots-clés, auteur) ainsi qu'un extrait des premières lignes de texte, pour les formats **PDF, DOCX, XLSX et PPTX**.

Cette étape s'exécute **entièrement en local**, sans IA et sans connexion réseau. Elle ne modifie jamais le fichier d'origine : le résultat est écrit dans un nouveau fichier `<nom>_enrichi.csv`.

> **Remarque :** les PDF scannés (images sans couche texte) et les fichiers image (`.jpg`, `.png`) ne produisent aucune description. Cela est normal et signalé dans le bilan.

> **Confidentialité :** une fois la description remplie, si vous transmettez ensuite ce texte à l'IA (lors de l'audit ou du classement), préférez un **modèle local** pour que les données ne quittent pas votre infrastructure.

En ligne de commande :

```bash
python cli.py enrich vrac.csv --source-root "D:\chemin\vers\le\dossier\source"
```

---

## Étape 1 : Audit

### Déroulement

1. Déposez votre fichier CSV via le bouton d'import.
2. (Facultatif) Rédigez une **observation** pour orienter l'analyse : contexte du producteur, problèmes connus, consignes particulières.
3. Lancez l'audit. Le LLM streame son analyse en direct.
4. Relisez le rapport, en particulier la **Partie 2 : Plan de classement**.
5. Passez à l'étape 2 en conservant le plan proposé ou en l'ajustant dans l'éditeur.

### Réduire la taille du CSV envoyé à l'IA

La section **Optimisation › Audit** (dans les réglages) permet de réduire le volume de données transmises, utile pour les grands vracs ou les modèles à fenêtre de contexte limitée :

- **Filtrer les colonnes** : ne garde que les 7 colonnes essentielles.
- **Supprimer les dates des fichiers** : vide les dates des lignes *Item* (peu utiles pour l'audit).
- **Échantillonner les fichiers par dossier** : envoie au maximum N items par dossier.

Ces options n'ont aucun effet sur le classement (étape 2).

### Constats déterministes (fiabilité de l'audit)

Avant d'interroger l'IA, ODACEA calcule lui-même, **sans IA**, les constats purement
mécaniques du vrac et les transmet au modèle comme **source faisant autorité** :

- **Volumétrie** : nombre d'*Item* et de *RecordGrp*, profondeur de l'arborescence.
- **Formats** : les plus représentés, formats à risque (à migrer), archives compressées.
- **Bruit numérique** : fichiers sans valeur archivistique repérés par leur nom — fichiers
  système (`Thumbs.db`, `.DS_Store`, `desktop.ini`…), verrous bureautiques (`~$rapport.docx`)
  et fichiers temporaires (`.tmp`, `.download`, `.crdownload`…).
- **Dossiers vides** : dossiers ne contenant **aucun fichier** dans toute leur arborescence
  (y compris ceux qui ne contiennent que d'autres dossiers eux-mêmes vides). Candidats à la
  suppression. Ce constat reconstruit l'arbre parent/enfant — un calcul qu'un petit modèle
  ne fait pas de façon fiable sur des milliers de lignes.
- **Noms de fichiers répétés** : noms de fichiers identiques apparaissant à plusieurs
  endroits (par ex. `Compte rendu.docx` présent dans cinq dossiers), motif classique d'un
  vrac où un même document a été copié un peu partout. ODACEA fournit la **liste des
  candidats** ; c'est l'IA qui juge ensuite, à partir des titres et des dates, s'il s'agit
  réellement de doublons ou de fichiers distincts au nom identique.

Pourquoi : un modèle local de petite taille compte et repère mal sur des milliers de
lignes. Lui fournir ces chiffres exacts évite les oublis et les approximations, et rend
l'audit reproductible. Les analyses qui demandent un **jugement** (doublons sémantiques,
anomalies de nommage, plan de classement) restent, elles, confiées au modèle.

> Le repérage du bruit numérique s'appuie sur des listes fixes de noms et d'extensions :
> il ne signale que des fichiers générés par le système ou les logiciels, jamais vos
> documents de travail. Un fichier caché légitime (par exemple `.gitignore`) n'est pas
> compté comme du bruit.

---

## Étape 2 : Classement

### Déroulement

1. Vérifiez et, si besoin, modifiez le plan de classement via l'éditeur de texte ou le bouton d'arbre interactif.
2. Lancez le classement. L'IA attribue à chaque fichier un dossier cible et un titre normalisé.
3. Vérifiez les avertissements éventuels (fichiers non trouvés, dossiers inconnus, extensions corrigées).
4. Téléchargez le CSV final, directement importable dans **RESIP**.

### L'avis de classement

Par défaut, avant de produire le CSV, l'IA rédige un court **avis de classement** : une analyse de quelques lignes, affichée dans le panneau **Démarche de l'IA**. Elle y commente la pertinence générale du plan au regard des fichiers réellement présents, ses choix notables, les fichiers ambigus et surtout **les dossiers du plan laissés vides, avec la raison**.

Cet avis est purement informatif : il n'apparaît pas dans le CSV et ne modifie pas le classement. Il vous aide à juger la qualité du plan et à repérer ce qui mérite une relecture.

Vous pouvez le désactiver dans les réglages, section **Optimisation › Classement**, via l'option **Demander l'avis de classement**. Le désactiver retire l'instruction correspondante du prompt : l'IA produit alors directement le CSV.

### Identifiant court (Ref) — vitesse ou finesse

L'option **Identifiant court (Ref)** (réglages › **Optimisation › Classement**) change la façon dont l'IA identifie chaque fichier dans sa réponse :

- **Désactivée (défaut)** : l'IA recopie le chemin complet du fichier. Recopier le chemin l'ancre sur le dossier d'origine → classement plus fin, mais réponse plus longue donc plus lente.
- **Activée** : l'IA ne recopie qu'un identifiant court. Réponse plus rapide à générer, mais l'ancrage moindre peut laisser davantage de dossiers du plan vides, surtout sur les petits modèles locaux.

Les deux donnent un CSV final identique en structure. À tester selon votre modèle : comparez le **Rapport de couverture** (écarts au plan) et la **durée** entre les deux réglages.

### Format du plan de classement

Le plan doit contenir un bloc **Arborescence technique** avec des noms de dossiers préfixés par des chiffres :

```
## Arborescence technique

1_Dossiers_personnels
1-1_Recrutement
1-2_Carriere
2_Finances
2-1_Budgets
```

Le préfixe numérique (`1_`, `1-1_`, `2-3_`, etc.) définit la hiérarchie parent/enfant.

### Ce que garantit l'outil

- L'extension du fichier original est toujours préservée, même si l'IA la modifie.
- Les dossiers vides (non référencés par aucun fichier) sont exclus automatiquement.
- Les dates de chaque dossier sont recalculées à partir des fichiers qu'il contient.
- Le CSV de sortie conserve toutes les colonnes du fichier original.

### Traitement par lots (grands vracs)

Lorsque le nombre d'items dépasse un certain seuil, ODACEA bascule automatiquement en **traitement par lots**. Ce seuil est modifiable dans les réglages, section **Traitement par lots** (valeur par défaut : 400 items, minimum : 50).

**Comment ça se passe :**

1. Le classement est découpé en lots. Par défaut ils sont traités les uns après les autres.
2. Si un lot échoue (problème réseau, délai dépassé...), les autres continuent. Les lots en erreur sont signalés avec un bouton **Relancer ce lot** (ou **Relancer tous les lots en erreur**). Il n'est pas nécessaire de tout recommencer.
3. Une fois tous les lots traités, les résultats sont assemblés et le CSV final est produit.

Le découpage n'affecte pas la cohérence du classement : chaque lot reçoit le même plan complet, et les dossiers sont dédoublonnés en une seule passe finale sur la totalité du vrac. Le **Rapport de couverture** permet de vérifier qu'aucun item n'a été oublié.

**Accélérer les gros vracs (lots en parallèle) :** le réglage **Lots traités en parallèle** (section **Traitement par lots**) permet d'envoyer plusieurs lots simultanément à un fournisseur **cloud** (jusqu'à 4), ce qui réduit sensiblement le temps total sur un grand versement. Séquentiel (1) par défaut. Avec un **modèle local** (Ollama / LM Studio), l'option est **forcée à 1** : un serveur local traite une seule requête à la fois, paralléliser ne ferait que sérialiser les appels — voire saturer la machine.

**Pourquoi la qualité du résultat est la même qu'en un seul appel :**

Chaque décision de classement est indépendante ; l'IA attribue un dossier à un fichier en le comparant au plan, pas en le comparant aux autres fichiers. Le lot ne change donc pas la décision ; il ne fait que réduire la taille du message envoyé à l'IA.

**Modèles locaux et fenêtres de contexte limitées :** si vous utilisez un modèle local compact (via Ollama ou LM Studio), réduisez la taille de lot à **50 items** dans les réglages ou plus selon les capacités de votre machine. Les modèles de petite taille disposent d'une fenêtre de contexte restreinte ; 50 items tient confortablement dans cette fenêtre sans dégradation de qualité. Multiplier les appels n'a aucun coût puisque le traitement est entièrement local.

```text
CSV original (ex. 600 items)
        │
        ▼
Extraction des items (paths, titres, dates)
        │
   ┌────┼────┐
   │    │    │
lot 1 lot 2 lot 3      ← même plan pour tous les lots
(200) (200) (200)
   │    │    │
  IA   IA   IA         ← chaque lot : Path;TargetFolder;NewTitle
   │    │    │
   └────┴────┘
        │ concaténation
        ▼
   600 décisions LLM
        │
        ▼
  Conversion RESIP      ← une seule passe sur tout le vrac
  (IDs, ParentIDs,
   dates des dossiers)
        │
        ▼
  CSV RESIP final
```

---

## Combien d'items traiter par passe ?

**Recommandation : entre 800 et 1 000 items par passe.** Au-delà, le contexte transmis au LLM peut devenir trop volumineux, ce qui risque de dégrader la qualité des résultats.

Pour traiter de plus grands volumes :

- Découpez le versement en plusieurs lots de 800 à 1 000 items et traitez-les séparément.
- Utilisez les options de réduction du contexte dans les réglages (filtrer les colonnes, supprimer les dates, échantillonner les items).
- Ajustez la taille de lot selon votre modèle : augmentez-la si votre modèle dispose d'une grande fenêtre de contexte, réduisez-la à 50 si vous utilisez un modèle local compact.

L'estimation du nombre de tokens affichée à l'import vous aide à calibrer avant de lancer un traitement.

---

## Mesures de performance

Après chaque étape, ODACEA affiche des indicateurs pour vous aider à évaluer et comparer les traitements :

- **Tokens consommés** : le nombre réel de tokens utilisés par l'audit (AUD-001) et le classement (CLA-001), ainsi qu'un total de session. Utile pour estimer le coût d'un modèle cloud.
- **Durée de traitement** : le temps réellement passé par le modèle sur chaque étape, et le total de session. La durée s'affiche même lorsque le serveur local (Ollama, LM Studio…) ne communique pas le décompte de tokens : c'est alors votre principal repère pour comparer des modèles ou des réglages.

En ligne de commande, la durée de chaque étape (et le total du pipeline avec `run`) est journalisée sur la sortie d'erreur, par exemple : `✓ Réponse reçue (12 340 car.) en 1 min 05 s`.

---

## Sauvegarde et reprise de travail

Dès qu'un audit réussit, ODACEA crée automatiquement un projet et sauvegarde l'état complet (CSV, rapport, plan, résultat) dans le stockage local du navigateur. Les modifications ultérieures (plan édité, résultat du classement) sont également enregistrées automatiquement.

Le panneau latérale **Projets** permet de gérer les projets (suppression, renommage).

---

## Exporter le rapport d'audit

Le rapport d'audit peut être téléchargé au format Markdown via le bouton **Exporter en Markdown**, disponible dans la section résultats de l'étape 1.

---

## Utilisation en ligne de commande

Pour intégrer ODACEA dans un flux de travail automatisé, un outil en ligne de commande est disponible via `cli.py`.

### Sous-commandes disponibles

| Commande | Rôle |
|---|---|
| `enrich` | Étape de préparation (facultative) : remplit `Content.Description` en lisant les fichiers locaux |
| `audit` | Lance l'audit sur un CSV et produit un rapport, un plan et des notes |
| `classement` | Lance le classement à partir d'un CSV et d'un plan validé, et produit le CSV RESIP |
| `run` | Pipeline complet : enchaîne audit puis classement sans intervention manuelle |

### Exemples d'utilisation

**Enrichissement des métadonnées (facultatif) :**

```bash
python cli.py enrich input.csv --source-root "D:\archives\service_scolaire"
```

Produit `input_enrichi.csv`. Aucune connexion réseau, aucune IA.

**Audit seul :**

```bash
python cli.py audit input.csv \
    --out-report rapport.md \
    --out-plan plan.md \
    --out-notes notes.md \
    --note "Archives RH 2015-2022"
```

**Classement à partir d'un plan édité manuellement :**

```bash
python cli.py classement input.csv \
    --plan plan.md \
    --out classement_final.csv
```

**Classement par lots (grands vracs) :**

```bash
python cli.py classement input.csv \
    --plan plan.md \
    --out classement_final.csv \
    --batch-size 200
```

**Classement sans l'avis de classement (sortie CSV seule, moins de tokens) :**

```bash
python cli.py classement input.csv \
    --plan plan.md \
    --out classement_final.csv \
    --no-avis
```

**Pipeline complet :**

```bash
python cli.py run input.csv --out-dir ./resultats/
```

**Pipeline complet avec classement par lots :**

```bash
python cli.py run input.csv --out-dir ./resultats/ --batch-size 200
```

Le dossier de sortie contient `rapport.md`, `plan.md`, `notes.md` et `classement_final_AAAAMMJJ_HHMMSS.csv`.

### Options communes

| Option | Effet |
|---|---|
| `--model MODELE` | Choisit le modèle (format LiteLLM) |
| `--api-key CLE` | Clé API (pour les modèles en ligne) |
| `--base-url URL` | URL du serveur local (LM Studio, Ollama, JAN) |
| `--verbose`, `-v` | Streame les chunks du LLM (raisonnement + réponse) sur stderr |

### Options de classement (classement et run)

| Option           | Effet                                                                                                                     |
|------------------|---------------------------------------------------------------------------------------------------------------------------|
| `--batch-size N` | Découpe le classement en lots de N items. Sans cette option (ou avec `0`), tous les items sont envoyés en un seul appel. |
| `--no-avis`      | Ne demande pas l'avis de classement (« Démarche de l'IA »). |
| `--ref`          | Identifiant court : l'IA recopie un identifiant court au lieu du chemin complet (sortie plus rapide, classement parfois moins fin). Sans cette option : recopie du chemin complet (défaut). |

### Options de préparation du CSV (audit et run)

| Option | Effet |
|---|---|
| `--no-filter-columns` | Envoie toutes les colonnes à l'IA (par défaut, seulement les 7 essentielles) |
| `--no-clean-dates` | Conserve les dates StartDate/EndDate sur les fichiers |
| `--no-sample` | Envoie tous les items (sans échantillonnage par dossier) |
| `--sample-n N` | Nombre maximum d'items par dossier parent (défaut : 5) |
| `--description` | Transmet `Content.Description` à l'IA. À activer pour exploiter un CSV enrichi. |

### Options spécifiques à `enrich`

| Option | Effet |
|---|---|
| `--source-root DOSSIER` | **Obligatoire.** Dossier racine contenant les fichiers référencés par la colonne `File` |
| `--output FICHIER` | Fichier de sortie (défaut : `<entrée>_enrichi.csv`) |
| `--overwrite` | Écrase les descriptions déjà renseignées (par défaut : préservées) |
| `--max-chars N` | Longueur maximale d'une description générée (défaut : 300 caractères) |
| `--verbose`, `-v` | Affiche chaque fichier traité |

### Codes de sortie

| Code | Signification |
|---|---|
| `0` | Succès |
| `1` | Erreur IA ou réseau |
| `2` | Fichier CSV invalide |
| `3` | Réponse de l'IA inexploitable |
| `4` | Configuration manquante (aucun modèle défini) |
