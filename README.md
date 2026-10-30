# Obsidian_RAG — CT / RAG sur trois cartes physiques

Le [rapport final](reports/final_report.md) réunit les équations CT/RAG et les mesures de dégradation de synchronisation. Sa [version PDF](reports/final_report.pdf) et l’[index des preuves](reports/README.md) sont les points d’entrée des résultats. Les captures et validations historiques sont regroupées dans six archives vérifiées ; les sorties de génération restent dans `build/`.

Le profil **PTP_EMULATION** de la branche `test_sync` utilise une image dédiée
au PTP sur trois cartes. Le [bilan d'optimisation](docs/ptp_single_node_optimization.md)
détaille la base **K=1/N=3**, un module par carte, ses ressources et ses validations.
La [recherche de capacité](docs/ptp_capacity.md)
compare les nombres de modules émulés ; [ptp_emulation.md](docs/ptp_emulation.md)
décrit les paramètres runtime et les sorties de mesure.

Une image commune pour trois Obsidian **XC7A35T-CSG325-2**, câblées
**A → B → C → A**. Les liens restent duplex pour la synchronisation.
Le rôle A/B/C est attribué par VIO. Aucun nœud virtuel dans le nouveau top.

- **CT :** A injecte une trame ; B/C insèrent leur contribution dans leurs
  emplacements réservés en cut-through ; A vérifie et retire le résultat.
- **RAG :** les trois cartes injectent au départ commun ; chaque paquet est
  retiré après H sauts physiques, y compris après plusieurs tours.
- Mode, payload P, emplacement S, H, répétitions et période sont des **registres
  runtime**. CT → RAG → CT ne demande ni compilation ni rechargement.

Limites : **P=1..4096 octets**, **S=1..1365**, **P≥3S en CT**, **H=1..65535**,
répétitions uint32 (0=continu), période uint32 en ticks de 16 ns. Défaut :
CT, P=4096, S=6, H=2, 128 essais, **100 µs**. Pour N modules cibles : H=N−1 ;
le banc conserve trois injecteurs et trois oscillateurs physiques.

## Construire et vérifier

Python 3 avec NumPy/Matplotlib, Vivado **2025.2** installé et licence Artix-7.
Définir `VIVADO` si nécessaire. Sous Windows :

```powershell
py -3 tools/validate_physical.py
py -3 scripts/build_physical.py
```

Le build génère Aurora, VIO et ILA, puis synthèse et placement-routage. Il refuse
les violations setup/hold/bus-skew, les chemins internes non contraints et les
DRC Error. Les sorties sont dans `build/physical_runtime/` :
`obsidian_benchmark.bit`, `.ltx`, rapports, manifestes et empreintes. Le même
couple BIT/LTX s'utilise sur les trois cartes. Vérifier `execution.json` et
`build_manifest.txt` avant utilisation. **Aucune carte n'est programmée par ces commandes.**

L'état livré et les marges mesurées par les outils sont résumés dans
[validation_physique.md](docs/validation_physique.md).
Le diagnostic des premiers échecs et les mesures du banc réel sont consignés
dans [validation_materielle.md](docs/validation_materielle.md).

## Utiliser les images déjà chargées

Le chargement JTAG des trois FPGA est une commande **explicite**, distincte du
build et des campagnes ; elle ne programme pas la mémoire flash :

```powershell
py -3 scripts/program_physical.py --targets OBS001A OBS003A OBS002A --output captures/program_001
```

Elle charge le BIT/LTX commun puis maintient les trois resets applicatifs avant
de les relâcher. Cela évite de conserver un défaut de parseur acquis pendant le
chargement séquentiel des voisins. Après un chargement manuel, exécuter une fois
`run_physical_campaign.py initialize --output captures/init_001` avec les mêmes
`--targets`. Cette initialisation remet les origines des compteurs à zéro ; les
changements de configuration et de mode suivants ne demandent aucun reset.

Les numéros de
série ci-dessous doivent suivre l'ordre physique de l'anneau ; les modifier si
le câblage diffère. Le script vérifie trois cibles distinctes et la signature VIO.

```powershell
py -3 scripts/run_physical_campaign.py run --targets OBS001A OBS003A OBS002A --mode CT --payload-bytes 4096 --local-bytes 64 --repetitions 128 --output captures/ct_001
py -3 scripts/run_physical_campaign.py run --targets OBS001A OBS003A OBS002A --mode RAG --payload-bytes 257 --target-modules 30 --output captures/rag_001
py -3 scripts/run_physical_campaign.py sweep --config config/physical_sweep.example.json --output captures/sweep_001
```

`configure`, `start`, `stop`, `status` et `collect` sont également disponibles.
`--dry-run` produit un Tcl révisable sans contacter les cartes. Les campagnes
n'ont aucune option de programmation. Configurer pendant un transfert demande
son vidage ; les paramètres actifs ne changent pas en pleine trame.

Les résultats comprennent pages JSON brutes lues deux fois, CSV, événements,
synchronisation et provenance. Une page contient 128 résumés ; les campagnes
plus longues font des pauses de collecte explicites. Les échéances indisponibles
sont sautées, sans chevauchement d'essais. La trace détaillée est bornée et ses
pertes sont comptées ; les résumés sont conservés.

La collecte affiche sa progression par passe ; une page peut demander plusieurs
dizaines de secondes par carte. Ne pas confondre cette lecture avec la durée de
l'essai, mesurée dans le FPGA. Vérifier une campagne collectée avec :

```powershell
py -3 scripts/verify_physical_capture.py captures/ct_001 --output captures/ct_001/verification.json
```

## Exploiter

```powershell
py -3 scripts/analyze_physical.py plot captures/ct_001/results.csv --output captures/ct_001/durations.png
py -3 scripts/analyze_physical.py fit-model captures/ct_001/results.csv --events captures/ct_001/events.json --output captures/ct_001/model.json
```

Le RTT CT utilise seulement le compteur brut de A, du premier TX accepté au
dernier RX. Les mesures intercartes restent vides sans correspondance calibrée.
Le workflow de calibration, les registres VIO, les formats et les limites sont
décrits dans [physical_runtime.md](docs/physical_runtime.md).

Les anciens BIT, rapports et documents restent historiques ; voir
[README_legacy.md](docs/README_legacy.md). Ils ne prouvent pas la validation de
la nouvelle image. Aucun résultat matériel n'est inventé.
