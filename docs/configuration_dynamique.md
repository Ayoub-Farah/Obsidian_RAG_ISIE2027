> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

﻿# Configuration dynamique RAG

Le profil dynamique utilise une image commune aux trois cartes. Il permet de choisir RAG_C (0) ou RAG_D (2), le nombre total de modules actifs, leur base d'identifiants et leur nombre par carte. Les paramètres D=6, R=2 et la capacité maximale restent fixés à la construction.

Une capacité de 30 signifie dix moteurs RAG et dix synchroniseurs indépendants par FPGA. La possibilité de simuler cette capacité ne prouve pas qu'elle tient sur le XC7A35T. Consulter les rapports de synthèse et de timing du profil avant utilisation.

## Construire

```powershell
$env:VIVADO='C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat'
py -3 scripts/build_campaign.py --mode 2 --nodes 30 --runtime-config --synth-only
```

`--nodes` désigne ici la capacité compilée : un multiple de trois entre 3 et 30. Sans `--synth-only`, le flux réalise aussi placement/routage et ne produit un BIT accepté que si timing et DRC passent. Le profil est suffixé `_runtime`. Une seule image est construite, car les identifiants sont configurés par JTAG.

Pour réutiliser les IP déjà générées et essayer une capacité différente :

```powershell
py -3 scripts/vivado.py runtime build/rag_m2_n30_b0_l10_d6_r2_c128_runtime/rag_m2_n30_b0_l10_d6_r2_c128_runtime.xpr 6 implement
```

Le dernier argument peut être `synth`. La capacité ci-dessus est un exemple, pas une affirmation de faisabilité matérielle.

## Configurer et exécuter

```powershell
py -3 scripts/run_runtime_campaign.py --capacity 6 --nodes 4 --mode RAG_D --output captures/runtime_n4_d --program
py -3 scripts/run_runtime_campaign.py --capacity 6 --nodes 6 --mode RAG_C --output captures/runtime_n6_c
```

Le second appel réutilise les images déjà programmées. `--program` ne programme que les FPGA, sans écrire la flash QSPI. `--dry-run` écrit le Tcl et le plan sans contacter les cartes. Le script exige une image acceptée par le flux de construction et un nouveau dossier de résultats.

L'ordre optique fonctionnel constaté est OBS001A -> OBS003A -> OBS002A. `--targets` permet de fournir trois autres numéros de série, dans l'ordre réel de l'anneau. N est réparti aussi également que possible : N=4 donne 2+1+1, N=30 donne 10+10+10.

Le script arrête les trois cartes, applique reset/configuration, libère les resets, vérifie les liens et les paramètres relus, puis demande le départ uniquement sur l'ancre. Les 128 cycles sont extraits en deux lectures identiques. Le CSV et le résumé ne sont validés que si les 384 enregistrements attendus sont présents, ordonnés et sans faute.

## Mesure retenue : module 1

Le module 1 de la discussion est l'ID RTL 0, premier module de la carte A (OBS001A). `T_return_us` mesure depuis son lancement de cycle jusqu'à la réception et validation complète (motif, en-tête et CRC) de son propre paquet revenu dans l'anneau, à la sortie du chemin RX applicatif. La mesure comprend donc le traitement local de réception jusqu'à cette validation. Elle n'attend pas le vidage de toutes les files du segment.

En RAG_D, il s'agit de son paquet de données. En RAG_C, l'ancre émet actuellement le paquet de références : son retour ne représente pas à lui seul la collecte des données de tous les autres modules. Les données des autres modules sont collectées par l'ancre et retirées de l'anneau. Il faut conserver cette distinction pour interpréter la comparaison des modes.

`T_useful_us` et `T_drained_us` restent des diagnostics du segment complet, pas des mesures individuelles du module 1 si plusieurs modules occupent la même carte. Le champ `first_tx_delay_ns` des nouveaux journaux est vide ; l'emplacement correspondant contient désormais le temps de retour, identifié par le bit 8 des flags. Les anciens journaux restent décodables.

La synchronisation initiale précède le lancement mesuré. Les liens virtuels restent un modèle numérique non calibré : latence nominale 37 cycles, pauses de compensation et intervalle intertrame. Les modules d'un même FPGA partagent son horloge physique. Cette campagne ne mesure pas un réseau de 30 oscillateurs physiques.

Le profil dynamique utilise le VIO et le journal. L'ILA de flux reste disponible dans les profils statiques.

## Registre VIO

Le profil dynamique expose `probe_out4`, mot de 32 bits :

| Bits | Contenu |
|---|---|
| 1:0 | Mode : 0 RAG_C, 2 RAG_D |
| 7:2 | N actif, entre 3 et la capacité compilée |
| 13:8 | Base des identifiants du segment |
| 19:14 | Nombre de modules actifs sur la carte |
| 31:20 | Réservés, écrire zéro |

Les valeurs sont mémorisées pendant le reset applicatif ; changer le mot pendant une campagne ne modifie pas le réseau actif. Une valeur invalide maintient les moteurs en reset et positionne le bit 38 du statut. Les modules et liens internes inactifs sont bypassés dans les deux sens, sans délai de lien virtuel ajouté.

## Vérifications

`sim/tb_runtime_system.vhd` exerce les deux modes et les populations 3, 4, 6, 15, 29, 30 puis 3, selon la capacité instanciée, sans réélaboration entre campagnes. Il contrôle les journaux, les CRC, le verrouillage, les métadonnées, le retour de l'ancre, les configurations invalides et la mémorisation des paramètres.

Les résultats réellement exécutés sont conservés dans `reports/runtime_*.log` ; ne pas considérer une commande disponible comme une validation effectuée. Le rapport final de capacité doit distinguer simulation, synthèse et essais matériels.
