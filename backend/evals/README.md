# Harnais d'évaluation des prompts

> Contrainte : **toute modification de `prompts/` passe
> par ce harnais** — une PR touchant un prompt cite des chiffres avant/après.

## Lancer une évaluation

Depuis `backend/` :

```bash
# Matrice complète : 1 jeu × 2 modèles × audit + classement (mode Path)
python cli.py eval --input ../demo_data/demo_small.csv \
  --model gpt-5.4-mini-2026-03-17 --model "openai/mistral-small-3.2" --base-url http://localhost:1234/v1

# Objectiver le compromis Path/Ref sur le même modèle
python cli.py eval --input ../demo_data/demo.csv --model gpt-5.4-mini-2026-03-17 --cla-mode both

# Budget de profondeur d'entrée : faire varier l'échantillonnage AUD-001
python cli.py eval --input ../demo_data/demo_large.csv --agent aud \
  --sweep-sample 0 --sweep-sample 3 --sweep-sample 5 --sweep-clean-dates

# Classement seul, plan figé (isole CLA-001 des variations d'AUD-001)
python cli.py eval --input vrac.csv --agent cla --plan plan_reference.md --cla-mode both

# Agent : exactitude des tool-calls et des filtres émis, corpus golden
python cli.py eval --agent agt --input "../demo_data/…SMALL/…-resip_….csv" \
  --cases evals/cases/agt_demo_small.json --model gpt-5.4-mini-2026-03-17
# … et sur un local 13–30B (repli JSON choisi automatiquement par --tool-mode auto)
python cli.py eval --agent agt --input "../demo_data/…SMALL/…-resip_….csv" \
  --cases evals/cases/agt_demo_small.json \
  --model "openai/ministral-3-14b-reasoning" --base-url http://localhost:1234/v1

# Étiqueter un run pour la comparaison avant/après
python cli.py eval --input ../demo_data/demo.csv --label avant_fewshot
```

- Le **tableau lisible** sort sur stdout (les logs sur stderr).
- Le **rapport JSON** est historisé dans `evals/results/<horodatage>_<label>.json`
  (gitignoré — données potentiellement sensibles ; consigner les chiffres
  significatifs dans la PR ou le journal).
- Chaque rapport consigne `promptVersions` : incrémenter `PROMPT_VERSION`
  dans `prompts/AUD_001.py` / `prompts/CLA_001.py` à **chaque** modification du
  texte d'un prompt, sinon deux runs ne sont pas interprétables.

## Corpus

Corpus de référence : les 3 jeux `demo/` (régénérables localement, cf.
`demo/README.md`) + vracs anonymisés réels à constituer au fil des missions.
Un échec d'un modèle sur une cellule de la matrice n'interrompt pas le run :
l'erreur est consignée dans le rapport.

| Jeu | Volume | Usage |
|---|---|---|
| `demo_small` (82 fichiers) | itération rapide | tout modèle |
| `demo` (184 fichiers) | référence locale | modèles 13–30B |
| `demo_large` (604 fichiers) | charge réaliste | modèles cloud |

## Métriques (déterministes, sans appel LLM — `core/evals.py`)

**AUD-001** — qualité *structurelle* du rapport (la pertinence archivistique
du plan reste un jugement humain) :

| Métrique | Sens |
|---|---|
| `planExtracted` | `extract_plans()` a trouvé la Partie 2 |
| `planStructureBlock` | balises `<!-- PLAN_STRUCTURE_START/END -->` présentes |
| `planTreeParsed` + `planFolders/Depth/MaxWidth/Leaves` | arborescence exploitable et sa forme |
| `gabaritComplete` (`gabaritSectionsPresent`) | sections 1.1–1.5 présentes (None en `--brief`) |
| `volumetryMatches` (`volumetryReported`) | la ligne §1.1 réutilise les chiffres exacts du digest déterministe (None si hors gabarit) |
| `ordreExistant` | verdict « Ordre existant » rendu (gabarit ≥ 1.1.0) : `STRUCTURÉ` / `PARTIELLEMENT STRUCTURÉ` / `ABSENT` — None si absent (rapport ancien format) |
| `sourceFoldersRetained`/`sourceFoldersTotal` (`sourceRetainedPct`) | **conservation de l'ordre existant** : part des dossiers sources *non vides* retrouvés parmi les rubriques du plan (rapprochement sémantique, accents/préfixes repliés). ⚠️ mesure la conservation *littérale* : une rubrique renommée compte comme non retrouvée |
| `planFoldersCreated` | rubriques du plan sans correspondant source (créations — racine du fonds exclue) |

**CLA-001** — compteurs calculés à la source par
`convert_classement_to_resip` :

| Métrique | Sens |
|---|---|
| `planMatches`, `foldersOffPlan`, `foldersMissing` | conformité stricte au plan validé |
| `itemsClassified`/`itemsTotal` (`classifiedPct`), `itemsUnclassified` | couverture du classement |
| `itemsMalformed` | nom de fichier dans TargetFolder (filet `_looks_like_file`) |
| `extensionsFixed` | extensions réalignées (filet `_preserve_extension`) |
| `targetsUnknown`, `pathsNotFound` | cibles/chemins inexploitables |
| `refsUnresolved` | identifiants hallucinés (mode Ref uniquement) |

**AGT-001** — **exactitude des tool-calls et des filtres émis** par
l'agent (agent **lecture seule**, exploration/recherche uniquement,
depuis le retrait des outils `classer`/`noter`), mesurée contre un **corpus
golden** (`--cases`, cf. `evals/cases/`) : des requêtes d'archiviste en langage
naturel, chacune avec la requête attendue. Chaque cas tourne sur une **session
fraîche** (pas d'historique entre cas) ; `--tool-mode auto` choisit le mode
réel (function calling natif pour un cloud, repli JSON pour un local) :

| Métrique | Sens |
|---|---|
| `exactitudePct` (`reussis`/`cases`) | part de cas dont **toutes** les vérifications demandées passent — la métrique de seuil |
| `outilAttendu` | un des outils admis a été appelé |
| `filtreEquivalent` | un appel admis émet un filtre **sémantiquement équivalent** au golden : même sélection de fichiers sur le CSV évalué — jamais une comparaison de forme (`{"mots_cles": ["pdf"]}` ≠ `{"extension": "pdf"}` en texte, équivalents s'ils sélectionnent les mêmes fichiers) |
| `reponseExacte` | `verifierTotal` : le total exact (recalculé par Pandas sur le filtre golden — jamais écrit en dur dans le corpus) figure dans la réponse finale |
| `stepsMoyen`, `erreurs` | coût en étapes d'outils ; cas en échec LLM (consignés, non bloquants) |

Le golden d'un cas (`attendu`, `type: "requete"`) : `outils` (noms admis),
`filtre` (facultatif), `verifierTotal`. Corpus disponibles :
`evals/cases/agt_demo_small.json` (comptages, périmètres par dossier,
mots-clés/thématiques, répartitions).

> **Seuil d'acceptation** (fixé au démarrage de la mesure, 2026-07-03) :
> `exactitudePct` ≥ **90 %** sur le cloud de référence, ≥ **70 %** sur un
> local 13–30B (repli JSON). Sous le seuil local, la correction se cherche
> d'abord dans le prompt (AGT-001), conformément à la philosophie —
> chiffres avant/après exigés pour tout bump de `PROMPT_VERSION`.
>
> **Mesuré le 2026-07-03** (AGT-001 0.4.0, corpus `agt_demo_small`) —
> **seuils dépassés des deux côtés** :
>
> - local 13–30B `ministral-3-14b-reasoning` (LM Studio, repli JSON) :
>   **12/12 (100 %)**, outil 12/12, filtre 10/10, cible 3/3, réponse 4/4,
>   2,5 étapes/cas, 7 min 45 s, 43 951 tokens
>   (`results/20260703_230648_j9_local_ministral.json`) ;
> - cloud de référence `gpt-5.1` (function calling natif) : **12/12
>   (100 %)**, mêmes dimensions au plein, 2,3 étapes/cas, 47 s,
>   57 052 tokens (`results/20260703_231926_j9_cloud_gpt51.json`).
>
> Mesure historique : le corpus de l'époque incluait des cas de classement et
> de prise de note (`classer`/`noter`, retirés depuis — AGT-001 0.5.0). Le
> corpus actuel ne couvre plus que les requêtes de lecture ; à re-mesurer.

### Rapport d'audit en contexte (AGT-001 0.6.0) — garde-fou chiffré + validation qualitative

Le canal **optionnel** `audit_report` (rapport d'audit du projet injecté dans le
system prompt de l'agent) est **opt-in** : sans rapport, le prompt est
**byte-identique** à la 0.5.0. Le corpus `agt_demo_small` crée ses sessions
**sans** rapport → il exécute donc ce chemin froid et sert de **garde-fou
anti-régression** pour le bump de version.

> **Mesuré le 2026-07-08** (AGT-001 0.6.0, corpus `agt_demo_small`, exploration
> **à froid** = sans rapport) — cloud `gpt-5.4-mini-2026-03-17` (function
> calling natif) : **9/9 (100 %)**, outil 9/9, filtre 8/8, réponse 4/4,
> 2,0 étapes/cas, 21,5 s, 26 184 tokens
> (`results/20260708_221306_0_6_0-cold.json`). Le prompt froid étant identique
> à la 0.5.0, le « avant » l'est par construction → **aucune régression**.

**Apport du canal (validation qualitative, non golden).** L'utilité du rapport
ne se chiffre pas par le corpus déterministe : les requêtes « quels fichiers
vont dans tel dossier **proposé par le plan** ? » relèvent d'un **jugement
sémantique** (pas de filtre déterministe unique → pas de golden propre). Exemple
de validation manuelle (2026-07-08, `gpt-5.4-mini`, rapport injecté) :

> **Q.** « L'audit propose un dossier *Restauration scolaire* — combien de
> fichiers du vrac iraient dedans ? » → l'agent en identifie **13**, dont
> `OLD/anciens reglements/reglement cantine 2015.pdf` — un fichier **hors** du
> dossier `RESTAURATION/`, rapproché par sa **thématique**. Sans le rapport,
> « Restauration scolaire » (un libellé du plan cible, pas un dossier du vrac)
> n'a aucun sens pour l'agent : ce rapprochement inter-dossiers est précisément
> ce que le canal débloque.

Ce type de cas se garde donc comme **exemple qualitatif** (preuve que l'agent
raisonne sur le plan cible), pas comme métrique automatisée — le garde-fou froid
ci-dessus reste la mesure de non-régression exigée.

Plus `durationS` et `usage` (tokens réels) par run — le coût fait partie du
compromis mesuré.

## Protocole d'une modification de prompt

1. **Avant** : `python cli.py eval … --label avant_<experience>` sur le corpus
   et les modèles cibles (au moins : 1 cloud de référence + 1–2 locaux 13–30B).
2. Modifier le prompt, **incrémenter `PROMPT_VERSION`**.
3. **Après** : même commande, `--label apres_<experience>`.
4. Comparer les deux JSON ; n'adopter que si les métriques progressent (ou ne
   régressent pas) sur les modèles cibles. Citer les chiffres dans la PR.

### Expériences candidates (chacune = une expérience mesurée, à n'adopter que si l'éval progresse)

| # | Hypothèse | Métriques à surveiller |
|---|---|---|
| (a) | Exemples few-shot compacts dans CLA-001 (1 ligne bien classée / 1 piège) | `itemsMalformed`, `extensionsFixed`, `foldersMissing` ↓ |
| (b) | Consigne « fichiers inclassables → dossier `A_trier` normalisé » (plutôt que la racine) | `targetsUnknown` ↓ sans `foldersOffPlan` ↑ |
| (c) | Variante AUD-001 à profondeur de plan bornée paramétrable | `planDepth` conforme à la borne, `planTreeParsed` stable |
| (d) | Consigne RGPD plus discriminante (faux positifs sur noms de personnes) | lecture humaine §1.5 (pas de métrique auto — échantillonner) |

### Respect de l'ordre originel (AUD-001 1.1.0) — mesuré le 2026-07-09 (cloud)

La 1.1.0 fait de la **conservation de l'ordre existant le défaut** du prompt
(verdict `STRUCTURÉ`/`PARTIELLEMENT STRUCTURÉ`/`ABSENT`, écarts limités à une
liste fermée de défauts chiffrés, gabarit « Écarts à l'ordre existant ») ; la
refonte libre devient l'opt-out (gabarit de note côté front). Le digest gagne un
bloc « Structuration existante » (fichiers à la racine, plus gros dossiers,
préfixes d'ordre) ancrant le verdict. Protocole (rejouer la 1.0.0 : `git stash`
ciblé sur `prompts/AUD_001.py`, ou `git checkout <commit-1.0.0> -- …`) :

```bash
python cli.py eval --input <SMALL> --input <demo> --agent aud --model <cloud-ref> --label avant_…
# swap du prompt, puis même commande --label apres_… ; stabilité inter-runs :
python cli.py audit <SMALL> --variants 3 --brief --model <cloud-ref> --out-dir variantes --json
```

> **Mesuré le 2026-07-09** — cloud `gpt-5.4-mini-2026-03-17`, corpus démo
> SMALL (82 fichiers, 30 dossiers sources non vides) et demo (184 fichiers,
> 38 dossiers) ; runs historisés `…avant_ordre_originel_v2.json` /
> `…apres_ordre_originel_v2.json` (v1 = métrique d'avant durcissement) :
>
> - **Conservation** (`sourceRetainedPct`) : SMALL 10,0 % → **20,0 %** ;
>   demo 15,8 % → **39,5 %**. Sur les 3 variantes `--brief` (mêmes artefacts,
>   recalcul déterministe) : moyenne 8,9 % (créations 31–43) → **34,4 %**
>   (créations 12–26).
> - **Verdict** `ordreExistant` : jamais rendu (1.0.0, ligne absente du
>   gabarit) → `PARTIELLEMENT STRUCTURÉ` **partout** — le bon verdict pour ces
>   corpus au désordre simulé ; pas de conservation servile du chaos : les
>   non-conservés sont les défauts visés (`A CLASSER`, `OLD`, `mes documents`,
>   `Telechargements`, sauvegardes de poste…).
> - **Stabilité inter-runs** (`--variants 3 --brief`, SMALL) : dossiers communs
>   aux 3 plans **1 → 9**, union des libellés **120 → 55** (vocabulaire deux
>   fois plus stable) ; profondeur stable (2 niveaux) — la feuille blanche
>   était bien une source de variance.
> - **Forme** : `planTreeParsed`/`gabaritComplete`/`volumetryMatches` restent ✓
>   partout ; coût +~1 100 tokens/run (gabarit enrichi), durées équivalentes.
>
> **Durcissement de la métrique en cours de mesure** : la v1 sous-comptait la
> conservation (13 % mesurés pour ~30–43 % réels) — des renommages triviaux
> comptaient comme créations (`Inscriptions 2022-2023` →
> `Inscriptions_2022_2023`, `Conseils d'ecole` → `Conseils_ecole`,
> `ATSEM - Personnel` → `Personnel_ATSEM`). `conservation_label` replie
> désormais tirets/élisions/ordre des mots (sac de mots trié, chiffres isolés
> préservés). Limite restante : un renommage *enrichi* (`RESTAURATION` →
> `Restauration_scolaire`) compte toujours comme création — le taux mesuré est
> un plancher.
>
> **Reste à mesurer** : 1–2 locaux 13–30B (LM Studio `ministral-3-14b`) et,
> idéalement, le fonds réel de 2 600 fichiers du test du 2026-07-05 (attendu :
> verdict STRUCTURÉ → conservation ≫ corpus démo).

## Budget de profondeur d'entrée

`prepare_for_llm` peut **échantillonner** au plus `sample_items_n` Item par dossier
(et blanchir les dates des Item) pour borner les tokens d'entrée d'AUD-001. Le bon
réglage dépend de la **taille du vrac**. Deux outils :

1. **Recommandation par taille** — `core/prep_budget.py::recommend_prep(item_count)`
   donne un `sampleN` recommandé par palier de volume (table locale, datée,
   éditable, comme la grille tarifaire). Surfacée par le `--dry-run` de la CLI :

   ```bash
   odacea audit vrac.csv --model m --dry-run # ligne « Budget d'entrée »
   odacea audit vrac.csv --model m --dry-run --json | jq '.agents[0].budgetRecommendation'
   ```

2. **Mesure de l'apport** — `eval --sweep-sample N` (répétable) lance un run
   AUD-001 par valeur d'échantillonnage ; `--sweep-clean-dates` ajoute la variante
   sans nettoyage de dates. Le tableau accole la variante au modèle (`m [n=3]`,
   `m [n=tous,dates=off]`) ; la colonne `tokens` montre le coût, les métriques
   `planTreeParsed`/`gabaritComplete`/`volumetryMatches`/`planFolders…` montrent
   l'effet sur la qualité.

> ⚠️ **Les seuils de `BUDGET_TIERS` sont des défauts heuristiques.** L'apport réel
> de l'échantillonnage sur la qualité se mesure avec le sweep ci-dessus sur des
> **modèles réels** (cloud de référence + 1–2 locaux 13–30B, sur `demo`/`demo_large`).
> Une fois ces chiffres obtenus, réviser `BUDGET_TIERS` et `BUDGET_TIERS_DATE`.
> Ce n'est **pas** une modification de prompt (non concernée).
