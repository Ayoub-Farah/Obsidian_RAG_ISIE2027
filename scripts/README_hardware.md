> Guide historique. Nouveau VIO et nouvelles commandes : [physical_runtime.md](../docs/physical_runtime.md).

# Construction et mesure sur trois cartes

Ce nouveau flux utilise uniquement les paramètres et les contraintes utiles de `SyncRAG_Estimator`, commit `e7d486a22b16bc1e52630341f7cdd1b560a97ce1`. Il régénère deux IP Aurora 8B/10B 11.1 duplex pour Vivado **2025.2** et `xc7a35tcsg325-2`, speed grade défini dans le dépôt de départ. Le marquage du composant assemblé doit correspondre à cette cible.

Aucun ancien BIT, DCP ou résultat de placement-routage n'est réutilisé comme preuve du nouveau projet. Les scripts ne programment jamais la carte lors d'une construction. Les résultats RTL et logiciels accompagnent les archives ; la génération d'IP, la synthèse, le placement-routage et les mesures matérielles de ce nouveau design restent à exécuter avec Vivado et les cartes.

## Générer les trois images

Depuis la racine extraite, ouvrir VS Code. Vivado doit être dans `PATH`, ou sa commande dans la variable `VIVADO`. Utiliser un chemin de projet court sur Windows.

Le format des arguments est `MODE N BASE LOCAL D R RUN_CYCLES`. Les trois bases physiques pour N=3 sont 0, 1 et 2, avec LOCAL=1. `RUN_CYCLES` est facultatif et vaut 128 : les cartes arrêtent les départs de façon coordonnée après 128 périodes, puis vident le protocole avant extraction. La valeur 0 sélectionne le fonctionnement continu. Pour RAG_D :

```bash
python3 scripts/vivado.py project 2 3 0 1 6 2
python3 scripts/vivado.py build 2 3 0 1 6 2
python3 scripts/vivado.py build 2 3 1 1 6 2
python3 scripts/vivado.py build 2 3 2 1 6 2
```

Pour AGG_D2 remplacer MODE par 3 ; RAG_C=0, AGG_C=1, AGG_D2_PIPE=4. Seuls les modes explicitement admis par l'état de validation du projet doivent être considérés comme qualifiés.

Sous Windows, remplacer `python3` par `py -3`, ou :

```powershell
.\scripts\build.ps1 -Mode 2 -Nodes 3 -NodeBase 0 -LocalNodes 1
```

`-ProjectOnly` génère le XPR sans exécuter la synthèse. Les limites de format et la capacité d’une trame dans un emplacement ping-pong CT (1 024 mots de deux octets avec la configuration actuelle) sont contrôlées avant toute création de projet ou génération d’IP. Cette vérification statique ne prouve pas la compatibilité avec les ressources ou le timing. Chaque profil admis crée un répertoire propre à sa configuration dans `build/`. Les fichiers attendus après une construction réussie sont `obsidian_benchmark.bit`, `obsidian_benchmark.ltx`, `timing_summary.rpt`, `implementation_utilization.rpt`, `drc.rpt`, `cdc.rpt` et le manifeste. Le script refuse la production acceptée d'un bitstream lorsque le timing, les chemins non contraints ou les DRC de niveau erreur échouent.

Le générateur choisit SFP0 comme propriétaire de l'unique `GTPE2_COMMON` et des horloges USER_CLK/SYNC_CLK. SFP1 partage ces ressources. Il lit les déclarations VHDL réellement générées et refuse un port d'entrée inconnu : ne pas ignorer une erreur de contrat après un changement de version Vivado. Aucun `m_axi_rx_tready` n'est inventé. La compensation d'horloge native reste activée.

## Câblage

- SFP1 de A ↔ SFP0 de B, SFP1 de B ↔ SFP0 de C, SFP1 de C ↔ SFP0 de A.
- Utiliser les deux fibres de chaque voisinage duplex.
- SFP0 représente le voisin gauche, SFP1 le voisin droit ; les données utiles vont vers la droite.
- Référence GTP : paire D6/D5 (125 MHz), fabric : D13 (20 MHz).
- SFP0 : TX H2/H1, RX E4/E3 ; SFP1 : TX F2/F1, RX A4/A3.
- Aucun GPIO de debug supplémentaire n'est affecté. La mesure passe par JTAG/VIO/ILA.

## Programmer et choisir la bonne carte

L'action `program` est explicite et indépendante du build :

```bash
python3 scripts/vivado.py program build/PROFIL/obsidian_benchmark.bit build/PROFIL/obsidian_benchmark.ltx xc7a35t_0
```

Si plusieurs câbles sont connectés, sélectionner leur URL exacte avec `OBSIDIAN_HW_TARGET`. Les scripts refusent un ensemble ambigu, même si plusieurs cartes portent toutes le nom `xc7a35t_0`. Les URL sont visibles dans le Hardware Manager ; ne pas deviner les numéros de série.

## Instrumentation

| Outil | Port | Contenu |
|---|---|---|
| VIO sortie | 0 | Reset applicatif explicite |
| VIO sortie | 1 | Demande de départ |
| VIO sortie | 2 | Arrêt avec vidage |
| VIO sortie | 3 | Adresse journal 0–255 |
| VIO entrée | 0 | Status 256 bits, voir schéma de mesure |
| VIO entrée | 1 | Journal bits 255:0 |
| VIO entrée | 2 | Journal bits 511:256 |
| VIO entrée | 3 | Compteur brut 64 bits |
| VIO entrée | 4 | channel_up SFP1,SFP0 |
| VIO entrée | 5 | hard_err,soft_err,frame_err, deux bits chacun |
| ILA | 0 | Status 256 bits |
| ILA | 1 | Compteur brut 64 bits |
| ILA | 2 | Flux RX droit, RX gauche, TX droit, TX gauche, 24 bits chacun |

Un bloc de flux ILA contient : data16, keep2, valid1, last1, ready1, zéros3. Le bit ready enregistré au RX vaut 1 car le cœur Aurora n'accepte aucune contre-pression RX ; les FIFO de capture restent responsables de la détection des débordements.

La profondeur ILA par défaut est 512 échantillons, soit 8,192 µs. Elle permet d'inspecter une portion de transaction ; le journal mesure les transactions plus longues sans limiter leur durée à celle de la capture. Une ILA 416 bits × 4 096 échantillons consommerait presque toute la BRAM du XC7A35T : ne pas augmenter sa profondeur sans examiner le nouveau rapport de ressources. `OBSIDIAN_ILA_DEPTH` peut sélectionner 128, 256, 512, 1 024, 2 048 ou 4 096 échantillons lors de la génération du projet.

Les commandes `capture` acceptent `read` (passif), `arm`, `start`, `stop`, `reset` ou `trigger` :

```bash
python3 scripts/vivado.py capture build/PROFIL/obsidian_benchmark.ltx captures/A xc7a35t_0 arm
python3 scripts/vivado.py capture build/PROFIL/obsidian_benchmark.ltx captures/A xc7a35t_0 start
python3 scripts/vivado.py capture build/PROFIL/obsidian_benchmark.ltx captures/A xc7a35t_0 read
```

Pour une condition de déclenchement précise, sélectionner les bits du statut dans Hardware Manager, puis armer l'ILA. L'armement seul ne définit pas de condition particulière ; le journal constitue la source principale des durées locales.

## Extraire les durées

```bash
python3 scripts/vivado.py dump build/PROFIL/obsidian_benchmark.ltx captures/A_log.json xc7a35t_0 A
```

Cette commande empêche les prochains départs, attend le vidage puis lit deux fois les 256 résumés. Elle refuse un journal qui change pendant la lecture. Elle ne remet aucun compteur à zéro et n'écrit pas en flash. Le JSON brut est décodé avec l'outil d'export CSV et le schéma de mesure du projet.

Une soustraction d'horodatages bruts n'a de sens qu'au sein d'une même carte. Comparer les départs entre cartes exige une correspondance d'horloges calibrée et son incertitude, ou des sorties physiques et un oscilloscope commun. L'absence de GPIO validés interdit de prétendre que JTAG seul apporte une mesure absolue indépendante du décalage global. Les durées par segment et les états d'intégrité restent exploitables dans le journal.

Pour construire les trois images d’une campagne, avec répartition équilibrée :

```bash
python3 scripts/build_campaign.py --mode 2 --nodes 30 --run-cycles 128 --dry-run
python3 scripts/build_campaign.py --mode 2 --nodes 30 --run-cycles 128
```

Le premier appel affiche les trois commandes sans exécuter Vivado ; le second construit les images. `--project-only` génère les trois XPR. Une autre répartition peut être fournie avec `--partitions 8 10 12` (somme égale à N). Un identifiant de base contigu est calculé pour chaque segment. Le fonctionnement de dérive logique E2 reste désactivé par défaut ; les génériques `G_ENABLE_LOGICAL_DRIFT` et `G_DRIFT_PPB` sont exposés au top pour les essais documentés.

Les scripts de collecte partagent `hw_helpers.tcl`. Ils exigent exactement un VIO (et un ILA pour une capture) sur la carte sélectionnée. Les sondes sont identifiées par leur `TYPE` et leur numéro `PROBE_PORT`, car leur nom peut correspondre au réseau connecté. Une lecture passive utilise `INPUT_VALUE` pour une entrée et `OUTPUT_VALUE` pour une sortie. Le test `tclsh scripts/test_hw_helpers.tcl` vérifie ce comportement avec des API simulées, sans établir une validation matérielle.

Références des propriétés : [AMD UG912 — HW_PROBE](https://docs.amd.com/r/en-US/ug912-vivado-properties/HW_PROBE) et [AMD UG912 — HW_VIO](https://docs.amd.com/r/en-US/ug912-vivado-properties/HW_VIO).
