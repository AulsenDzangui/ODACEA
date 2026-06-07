# Scripts utilitaires — Données de démonstration

Ce dossier contient trois générateurs d'arborescence bureautique fictive,
calibrés pour démontrer ODACEA à des archivistes selon la taille du modèle
LLM utilisé. Les données générées alimentent ODACEA via
[Archifiltre Docs](https://archifiltre.fr) : on pointe Archifiltre sur
l'arborescence générée pour produire un CSV SEDA, ensuite chargé dans le
[moteur Python](../backend/) (CLI) ou la version Web ([`../web/`](../web/)).

L'arborescence simule un **service municipal des Affaires scolaires et
périscolaire** (Mairie fictive de Saint-Genis-le-Champêtre, période 2014 →
2025). Tous les fichiers générés sont **vides (0 octet)**, seuls les noms,
l'arborescence et les `mtime` ont de la valeur, ce dont Archifiltre Docs a
besoin pour produire un CSV SEDA exploitable.

## Les trois paliers

| Palier | Script | Fichiers | Dossiers | Modèles cibles |
|---|---|---|---|---|
| **Petit** | `generate_demo_tree_small.py` | 82 | 32 | 14B local (Qwen, Mistral, Llama) |
| **Moyen** | `generate_demo_tree.py` | 184 | 40 | 13–30B (Qwen 14B, Mixtral, Llama 70B quantizé) |
| **Grand** | `generate_demo_tree_large.py` | 604 | 72 | Cloud (Claude Opus/Sonnet, GPT-4/5, Gemini Pro) |

Chaque palier génère son propre dossier sous `demo_data/` ; les trois
peuvent coexister sans s'écraser.

## Exécution

Aucune dépendance externe, uniquement la stdlib Python.

```bash
# À la racine du repo
python demo/generate_demo_tree_small.py    # → demo_data/Mairie_Saint-Genis_Affaires_Scolaires_SMALL/
python demo/generate_demo_tree.py          # → demo_data/Mairie_Saint-Genis_Affaires_Scolaires/
python demo/generate_demo_tree_large.py    # → demo_data/Mairie_Saint-Genis_Affaires_Scolaires_LARGE/
```

Les scripts sont **idempotents** : ils suppriment et recréent leur dossier
cible à chaque exécution (seed `random` figée à 42 pour reproductibilité
des heures aléatoires injectées dans les `mtime`).

`demo_data/` est dans `.gitignore`. Chaque utilisateur regénère
localement, le repo ne porte que les scripts.

## Quel palier choisir ?

### Petit (82 fichiers) : pour développer et valider les prompts

Conformément à la philosophie du projet (« le petit modèle comme outil de
validation »), c'est sur ce palier
qu'on **valide la robustesse d'un prompt** : un 14B ne pardonne pas les
ambiguïtés. Si AUD-001 ou CLA-001 réussissent ici, ils réussiront ailleurs.

À utiliser pour :
- Tester une modification de prompt
- Démos rapides en réunion (5–10 min de traitement bout en bout)
- Vérifier qu'aucun pattern de désordre essentiel n'est ignoré par le modèle

### Moyen (184 fichiers) : démo standard avec modèle local

Volumétrie plus représentative d'un fonds réel sans être pénalisante. C'est
le palier de référence pour une démo devant des archivistes :
suffisamment riche pour que le rapport d'audit identifie plusieurs registres
distincts, mais traitable en quelques minutes sur un poste équipé d'une
GPU 12–24 Go.

### Grand (604 fichiers) : stress-test et démo cloud

Pour montrer ce que produisent les grands modèles sur un fonds plus
volumineux et plus profond (couverture de 7 années scolaires, factures et
menus mensuels, multiples chantiers travaux, dossier `OLD/` étendu).
Attention :

- Coût en tokens **significatif** sur les API facturées.
- L'option **Échantillonner les fichiers** (`sample_items_n=5`) reste activable et réduit drastiquement le contexte envoyé à AUD-001 sans perdre les patterns de désordre.

## Patterns de désordre injectés

Tous les paliers conservent les patterns suivants ; le grand y ajoute du
volume sans nouveau type :

| Pattern | Exemple |
|---|---|
| Doublons par copie Windows | `… - Copie.pdf`, `… - Copie (2).pdf` |
| Versions cumulées | `… v1`, `… v2`, `… VF`, `… VF_corrigé`, `… FINAL_VRAI` |
| Naming scanner brut | `SCAN_0034.pdf`, `IMG_4523.JPG`, `Document1.pdf` |
| Casse / accents incohérents | `ECOLE Marie Curie/` vs `Ecole maternelle Jean Jaures/` |
| Espaces vs underscores | `Liste eleves CP - 2021.xlsx` vs `liste_eleves_CE1_2021.xlsx` |
| Année scolaire vs civile | `Inscriptions 2022-2023/` et `Inscriptions 2023/` |
| Mauvais classement | photo `kermesse_2023_001.jpg` rangée dans `RESTAURATION/Factures/` |
| Données nominatives à la racine | `CV_Martine_DUPONT.pdf` |
| Dossier fourre-tout daté | `OLD/Sauvegarde poste Christine 2019/` |
| Email exporté isolé | `RE_ inscription cantine - urgent.msg` |
| Dossier vide | `Archives 2018/`, `Nouveau dossier/` |
| Fichier temp Office | `~$ conseil ecole juin 2023.docx` |
| Mélange formats | `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.jpg`, `.png`, `.msg`, `.eml`, `.zip`, `.exe` |
| Fichier au nom illisible | `aaaa.pdf`, `truc.docx`, `sans titre.docx` |

## Workflow complet de la démo

1. **Générer l'arborescence** avec le script du palier choisi (ci-dessus).
2. **Ouvrir Archifiltre Docs** ([archifiltre.fr](https://archifiltre.fr)) et
   pointer sur le dossier généré.
3. **Exporter au format SEDA** depuis Archifiltre → un CSV est produit.
4. **Lancer ODACEA** (voir le [README racine](../README.md) : `start-dev.ps1`,
   ou backend + front lancés séparément), puis charger le CSV.
5. **Étape 1 — Audit (AUD-001)** : lance l'audit, sélectionne un plan dans
   le rapport, valide.
6. **Étape 2 — Classement (CLA-001)** : produit le CSV final restructuré
   au format RESIP, téléchargeable.

## Personnalisation

Les listes de fichiers en tête de chaque script sont **explicites** : on
peut directement éditer un nom, ajouter un cas d'usage, retirer un pattern.
Pour un autre service municipal (urbanisme, état civil, RH, marchés
publics…), la structure du script est facile à dupliquer en remplaçant les
listes par celles du service voulu.
