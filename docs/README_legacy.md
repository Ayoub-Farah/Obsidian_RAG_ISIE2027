# Archive historique — ne décrit pas le nouveau banc physique

# Obsidian RAG — banc Aurora à 10 kHz

Projet source indépendant issu de la branche `SyncRAG_Estimator`, pour trois cartes Obsidian **XC7A35T-CSG325-2**. Il compare les transferts de données synthétiques déjà disponibles, sans SPIN, acquisition, SPI ni calcul MMC.

**Modes de cette archive :** RAG_C (collecte centralisée) et RAG_D (all-gather décentralisé). Le mode par défaut est **RAG_D** (`2`). Les relais sont cut-through dans les deux familles : RAG désigne l'injection parallèle de paquets locaux ; CT désigne ici l'agrégation dans une trame circulante.

**État de validation :** les trois images A/B/C du profil par défaut **RAG_D, N=3, D=6, R=2, 128 cycles** ont été générées avec **Vivado 2025.2** le 26 octobre 2026, avec timing setup/hold, bus skew et DRC passants. Les scripts et le RTL ont été corrigés/optimisés ; 18 simulations XSim et 15 tests Python passent. Aucune carte n'a été programmée ou mesurée. Voir le [rapport de construction locale](docs/construction_vivado_2026-10-26.md). Les autres profils nécessitent leur propre construction et validation ; les preuves historiques de l'archive restent dans `reports/` et [validation_et_limites.md](docs/validation_et_limites.md).

## 1. Ouvrir et vérifier

Extraire cette archive dans un chemin court, par exemple `C:\fpga\Obsidian_RAG` ou `~/fpga/Obsidian_RAG`, puis ouvrir ce dossier dans VS Code. Il n'est pas nécessaire de cloner le dépôt d'origine. Les fichiers générés restent sous `build/`.

Dépendances : **Python 3**, **GHDL** pour les tests portables, et **Vivado 2025.2** avec Aurora 8B/10B 11.1 et Artix-7 pour construire le matériel. Le launcher utilise `vivado` dans `PATH`, ou le chemin indiqué par `VIVADO`.

```bash
python3 tools/run_tests.py --family RAG --matrix --require-rtl --stop-time 20ms
python3 tools/validate_profile.py --mode RAG_D --nodes 3 --data-bytes 6 --ref-bytes 2
```

Sous Windows, remplacer `python3` par `py -3`. Les tâches VS Code proposent la simulation, la création du projet et le build. Une validation statique de profil vérifie les tailles et les identifiants ; elle ne prouve ni le respect de 100 µs ni la capacité du FPGA.

## 2. Construire trois images distinctes

La commande suivante construit les trois images A, B et C avec leurs ID distincts :

```bash
python3 scripts/build_campaign.py --mode 2 --nodes 3 --run-cycles 128
```

Sous PowerShell :

```powershell
py -3 scripts/build_campaign.py --mode 2 --nodes 3 --run-cycles 128
```

Ajouter `--project-only` pour générer uniquement les trois projets Vivado, ou `--dry-run` pour afficher les commandes sans les exécuter.

Par défaut, **128 cycles** sont exécutés puis les nœuds arrêtent leurs départs à la même époque et terminent les transferts en cours. Cela représente 12,8 ms de périodes nominales après l'initialisation et laisse la campagne complète dans le journal de 256 entrées. `--run-cycles 0` sélectionne le fonctionnement continu.

Pour une construction individuelle, les arguments sont `MODE N BASE LOCAL D R RUN_CYCLES` ; le dernier est facultatif et vaut 128. Exemple pour la carte A :

```bash
python3 scripts/vivado.py build 2 3 0 1 6 2 128
```

`N` compte tous les nœuds, ancre 0 comprise ; `BASE` et `LOCAL` définissent le segment contigu de la carte. `D` est la taille des données locales et `R` celle de la référence individuelle. Au départ : `N=3`, `LOCAL=1`, `D=6`, `R=2`, période 100 µs. Les bases des cartes A/B/C sont 0/1/2.

Chaque configuration possède son propre dossier `build/PROFIL/`. Une construction acceptée fournit `obsidian_benchmark.bit`, `obsidian_benchmark.ltx`, les rapports de timing, ressources, DRC et CDC ainsi qu'un manifeste. Les scripts de build ne programment pas les cartes.

Les deux cœurs duplex partagent l'infrastructure GTP et les horloges utilisateur. Le générateur contrôle les ports réellement produits par Vivado et s'arrête si le contrat diffère ; une erreur de ce contrôle doit être corrigée avant de continuer. La compensation d'horloge Aurora reste activée.

## 3. Câbler et lancer

| Carte | ID ou segment | Port droit SFP1 connecté au port gauche SFP0 de |
|---|---|---|
| A | 0 | B |
| B | 1 | C |
| C | 2 | A |

Chaque voisinage utilise une liaison **duplex** : les données vont vers la droite, la synchronisation utilise aussi le sens inverse. Le composant et le speed grade assemblés doivent correspondre à la cible du dépôt source. Les broches sont reprises des contraintes et de la netlist Obsidian ; aucun GPIO de debug supplémentaire n'est inventé.

Programmer chaque carte avec son BIT et son LTX correspondants, puis :

1. Vérifier les deux `channel_up` sur les trois cartes.
2. Appliquer le reset applicatif sur les trois cartes.
3. Armer les ILA si une capture détaillée est souhaitée.
4. Demander `start` **sur A, l'ancre 0, uniquement**. Les autres nœuds écoutent automatiquement leur parent.
5. Attendre l'acquisition séquentielle et l'armement à une époque future, puis vérifier le verrouillage et les compteurs d'erreurs.

Exemples, après avoir remplacé `PROFIL_A` par le dossier réellement généré :

```bash
python3 scripts/vivado.py program build/PROFIL_A/obsidian_benchmark.bit build/PROFIL_A/obsidian_benchmark.ltx xc7a35t_0
python3 scripts/vivado.py capture build/PROFIL_A/obsidian_benchmark.ltx captures/A xc7a35t_0 reset
python3 scripts/vivado.py capture build/PROFIL_A/obsidian_benchmark.ltx captures/A xc7a35t_0 arm
python3 scripts/vivado.py capture build/PROFIL_A/obsidian_benchmark.ltx captures/A xc7a35t_0 start
```

Si plusieurs câbles sont présents, sélectionner leur URL exacte avec `OBSIDIAN_HW_TARGET`. Le nom `xc7a35t_0` seul ne distingue pas plusieurs cartes ; les scripts refusent une sélection ambiguë.

## 4. Récupérer les temps

Le journal contient jusqu'à **256 résumés de cycle par carte**. Il distingue la disponibilité utile de la fin de circulation du protocole. Les erreurs et dépassements sont conservés.

Avec la campagne par défaut, attendre l'arrêt coordonné et le vidage des 128 cycles, puis extraire chaque carte :

```bash
python3 scripts/vivado.py dump build/PROFIL_A/obsidian_benchmark.ltx captures/A_log.json xc7a35t_0 A
python3 scripts/decode_log.py captures/A_log.json --metadata captures/metadata.json --output captures/A_times.csv
```

La demande JTAG `stop` reste disponible pour interrompre une campagne continue. Elle est locale : la demander sur les trois cartes et conserver les éventuels échecs des derniers cycles perturbés par cet arrêt successif. Pour une série de mesures reproductible, préférer une durée commune fixée par `--run-cycles`.

`metadata.json` contient l'identité du run, du bitstream, les tailles, le modèle virtuel et l'incertitude. Le format est décrit dans [protocole_mesure.md](docs/protocole_mesure.md). Les lectures VIO/ILA et les exports ne programment ni FPGA ni flash.

Les durées du journal sont **locales à une carte ou à son segment**. Les compteurs bruts de cartes différentes ont des origines distinctes : leur soustraction ne donne pas une latence globale ou un écart de départ. Une mesure globale nécessite une correspondance temporelle calibrée ou un instrument commun avec des sorties physiques vérifiées. Le CSV laisse cet écart vide lorsqu'il n'est pas mesuré.

## 5. Augmenter N

Pour émuler 30 nœuds sur trois cartes, utiliser les segments `BASE=0,10,20`, `LOCAL=10`, avec le même `N=30` partout. Chaque nœud possède son moteur, ses files et ses contrôles ; les liens virtuels sont indépendants dans les deux sens.

```bash
python3 scripts/build_campaign.py --mode 2 --nodes 30 --partitions 10 10 10 --run-cycles 128
```

Le délai virtuel initial de 37 cycles et ses pauses sont des **paramètres non calibrés**, pas une mesure de la carte. Les nœuds d'un même FPGA partagent son horloge physique. Une simulation à N=180 ne prouve pas que ce profil tient dans un XC7A35T ni qu'il respecte 100 µs. Examiner les rapports de ressources, de timing et les niveaux de file à chaque profil.

Le modèle E2 peut injecter une dérive logique par nœud avec `G_ENABLE_LOGICAL_DRIFT` et `G_DRIFT_PPB` dans le système portable. Son accumulateur Q48.32 conserve 32 bits fractionnaires, avec des événements physiques toujours quantifiés à 16 ns. Les essais fournis distinguent le maintien à ±2 ppm et la perte de verrouillage explicite à ±50 ppm ; ils ne qualifient pas des oscillateurs matériels.

Le relais RAG attend au minimum dix cycles pour sa décision d'en-tête validée. Le moteur CT possède deux buffers ping-pong : avec `G_FIFO_WORDS=2048`, une trame dispose de 2 048 octets, en-tête et CRC compris. Les profils dépassant cette capacité sont refusés ; augmenter seulement `G_MAX_FRAME_BYTES` ne suffit pas.

Le débit de 1,25 Gbit/s, la largeur de 16 bits et la fréquence utilisateur de 62,5 MHz sont fixés à la génération des IP. Changer le débit demande une nouvelle génération et une nouvelle qualification.

## Contenu et traçabilité

| Dossier | Usage |
|---|---|
| `rtl/protocol/` | Moteur(s) de la famille et CRC |
| `rtl/sync/` | Échanges voisin, horloge logique, initialisation et maintenance |
| `rtl/links/` | Capture RX sans contre-pression et liens virtuels |
| `rtl/system/` | Segments, multiplexage et journal de mesure |
| `rtl/board/`, `constraints/` | Intégration Obsidian |
| `scripts/`, `.vscode/` | Build, programmation explicite, debug et CSV |
| `sim/`, `tools/`, `config/` | Tests, codec de référence et paramètres |
| `reports/`, `docs/` | Preuves exécutées et limites |

Source matérielle : `Ayoub-Farah/Obsidian_Aurora_loopback_test-`, branche `SyncRAG_Estimator`, commit **`e7d486a22b16bc1e52630341f7cdd1b560a97ce1`**. Les deux documents joints restent le cahier des charges. Les JSON et vecteurs fournis ici ont été recréés explicitement depuis ce texte : les fichiers auxiliaires cités dans le rapport n'étaient pas joints. Aucun fichier SPIN_OSC n'est utilisé.

Voir aussi [le guide matériel](scripts/README_hardware.md) pour les ports VIO/ILA et les commandes détaillées.

## Configuration dynamique

Le flux configurable RAG_C/RAG_D, la selection de la population active et la mesure du retour du paquet du module 1 sont decrits dans [configuration_dynamique.md](docs/configuration_dynamique.md). La capacite simulee et la capacite admise sur FPGA doivent etre distinguees ; consulter les rapports de validation associes.
