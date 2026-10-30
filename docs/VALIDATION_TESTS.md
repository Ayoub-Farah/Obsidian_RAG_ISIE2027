> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

# Reproduire et interpréter les validations

Les fichiers `config/configuration_reference.json` et `config/vecteurs_trames.json`
ont été **recréés à partir du rapport fourni**. Les fichiers originaux cités dans
le rapport, ainsi que `modele_reference.py`, n'étaient pas joints. Aucun résultat
de ce modèle original n'est présenté comme régénéré ici.

`tools/frame_codec.py` est un oracle de format binaire Python. Il vérifie les
CRC et les transformations de trames ; il ne simule ni un FPGA ni Aurora. Ses
vecteurs sont aussi utilisés pour un contrôle exact du paquet VHDL dans
`sim/tb_crc.vhd`. Les CRC golden `123456789` sont indépendants des générateurs
de motifs de l'application.

```bash
python3 tools/frame_codec.py
python3 tools/validate_profile.py --mode RAG_D --nodes 3
python3 tools/run_tests.py --matrix --require-rtl
```

GHDL est nécessaire pour les simulations RTL portables. Python 3 suffit aux
vecteurs et aux validations statiques. Un test GHDL n'est déclaré réussi que
s'il termine sans erreur et produit explicitement `PASS` ; atteindre seulement
`--stop-time` constitue un échec. Les sorties et commandes réellement exécutées
sont conservées dans `build/validation/test_results.json`. Le CSV voisin contient les
résumés temporels émis par le test d'intégration.

La matrice d'intégration raccourcit uniquement l'attente d'armement à 10 000
cycles (160 µs) pour accélérer les simulations. Le défaut matériel conserve
312 500 cycles (5 ms). Cette attente se situe avant le début mesuré de la
transaction. La commande sans `--matrix` conserve également les 5 ms.

Pour un contrôle ciblé, choisir une famille et/ou une expression de nom de
testbench. La compilation inclut les dépendances portables communes, même
lorsqu'une seule famille est simulée.

```bash
python3 tools/run_tests.py --family RAG --only 'tb_rag_.*' --matrix --require-rtl
python3 tools/run_tests.py --family CT --only tb_aggregate_ring --matrix --require-rtl
python3 tools/run_tests.py --only tb_benchmark_system --require-rtl
```

Le test d'intégration instancie trois systèmes, avec un ou plusieurs nœuds par
segment, et un modèle de transport indépendant dans chaque direction à chaque
frontière. Le départ est demandé uniquement au nœud 0. Les douze périodes par
défaut franchissent une fenêtre de maintenance. Le lecteur extrait chaque
résumé avant réutilisation de la mémoire de 256 entrées et vérifie sa séquence,
ses métadonnées, les CRC, les erreurs et les durées locales. Il imprime des
lignes `BENCH_CSV` que le runner convertit en CSV.

Les campagnes de 400 et 10 000 périodes sont disponibles **sur demande
explicite de la commande**. Leur disponibilité ne signifie pas qu'elles ont été
exécutées pendant la préparation de l'archive ; consulter les rapports joints.

```bash
python3 tools/run_tests.py --only tb_benchmark_system --long 400 --require-rtl
python3 tools/run_tests.py --only tb_benchmark_system --long 10000 --require-rtl
```

Le banc portable d'intégration utilise une horloge commune et des liens
numériques. Ses temps bruts sont comparables dans ce banc seulement. Sur trois
cartes, il faut une mesure commune ou une correspondance temporelle calibrée.
Une durée extraite d'un segment est une durée locale, pas automatiquement la
complétude globale. Conserver les trois segments et prendre le dernier résultat
dans une base temporelle commune pour la mesure globale.

| Exigence | Preuve disponible | Limite de la preuve |
|---|---|---|
| Formats, CRC et motifs | Tests Python et `tb_crc` | Ne couvre pas le transport série |
| RAG_C / RAG_D, bitmap et stockage | `tb_rag_ring`, N=2/3, tailles paires/impaires, pauses | Profils effectivement exécutés seulement |
| RAG CT et rejets | `tb_rag_integrity`, scénarios paramétrés | Consulter les fautes réellement exécutées |
| AGG_C / AGG_D2 / PIPE | `tb_aggregate_ring`, matrice et corruption | Profils effectivement exécutés seulement |
| Initialisation et maintenance | `tb_sync_system`, puis `tb_benchmark_system` | Pas de dérive analogique, CDR ou asymétrie mesurée |
| Trois segments, journaux et périodes | `tb_benchmark_system` et CSV | Modèle d'interfaces numériques, pas trois cartes physiques |
| Campagnes 400 / 10 000 | Commandes reproductibles ci-dessus | Non exécutées sauf rapport explicite |
| N=180 synthétisable et timing | Scripts de construction Vivado | À établir sur chaque profil par Vivado |
| Calibration Aurora et précision de départ | Procédure matérielle et instrumentation | À établir sur les cartes |
| Dérive logique | Variantes `tb_sync_system` à 2 ppm et 50 ppm si présentes dans le rapport | Test de synchronisation à trois nœuds ; l'intégration E1 sans dérive ne devient pas une campagne E2 complète |

Les profils AGG du système commun utilisent également le mécanisme d'armement
et de synchronisation du banc. Cela permet la même instrumentation, mais ne
constitue pas la référence AGG sans coût de synchronisation définie dans le
rapport. Les mesures de fenêtre de données peuvent être comparées en indiquant
ce choix ; le coût total d'AGG sans synchronisation reste une expérience séparée.

Les rapports de synthèse, de placement-routage, de timing statique, la génération
de bitstreams et les mesures matérielles ne sont pas exécutés par le runner
Python/GHDL. Le JSON les marque explicitement `not_executed`.

La mémoire AGG est divisée en deux emplacements indépendants. Chaque trame
doit tenir dans un emplacement de `G_FIFO_WORDS/2` mots, en plus de respecter
`G_MAX_FRAME_BYTES`. Par exemple, 2 048 mots de FIFO autorisent environ
2 048 octets par trame agrégée ; une limite de trame configurée à 4 096 octets
ne double pas cette capacité. `validate_profile.py --fifo-words ...` vérifie
cette contrainte et ne constitue toujours pas une preuve de ressources FPGA.
