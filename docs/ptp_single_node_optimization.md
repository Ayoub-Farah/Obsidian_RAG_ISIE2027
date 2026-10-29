# Optimisation de la base PTP : un module par carte

La cible actuelle est **K=1, N=3** sur les trois cartes A/B/C. Chaque carte
conserve son moteur PTP complet et ses liens physiques vers les deux voisines.
M1/A est l'ancre, M2/B et M3/C sont les suiveurs. L'émulation de plusieurs
modules par carte et l'étude de la dégradation avec le nombre de sauts viennent
après cette étape.

La précision Q48.32/Q48.16, les estimations d'acquisition, le servo d'offset,
le maintien, les délais et les réglages runtime restent des contraintes de
fonctionnement. Le profil dédié ne contient aucun chemin DATA CT/RAG.

## Mesure de départ

La synthèse historique `build/ptp_k1_attempt2/synthesis_utilization.rpt`
donne pour l'ensemble du top :

| Ressource | Référence historique | Synthèse optimisée K=1 |
|---|---:|---:|
| LUT | 17 045 | 7 226 (−57,6 %) |
| Registres FF | 21 382 | 10 909 (−49,0 %) |
| RAMB36 / RAMB18 | 0 / 0 | 8 / 0 |
| DSP | 1 | 1 |

Ce coût comprend le PTP, les injecteurs de liens, l'observation, le journal,
le pilotage VIO et les interfaces optiques. Il ne représente pas le seul calcul
de synchronisation. La synthèse peut déplacer des cellules entre niveaux de
hiérarchie : les lignes « own » des anciens rapports ne suffisent pas à isoler
le coût arithmétique du moteur.

Ce build historique a été réalisé alors que des sources évoluaient encore.
Ses nombres servent de point de comparaison, sans valider l'image finale ni
une marge de timing pour les sources courantes. Toute mesure après optimisation
doit citer un dossier neuf, les empreintes sources et ses rapports de synthèse
ou d'implémentation.

Les mesures optimisées proviennent de
`build/ptp_single_node_final/synthesis_utilization.rpt`. Le placement-routage et
ses ressources sont également mesurés dans le même dossier :

| Ressource après routage | Référence historique | Version finale K=1 |
|---|---:|---:|
| LUT | 17 319 | 7 466 (−56,9 %) |
| Registres FF | 21 893 | 11 421 (−47,8 %) |
| RAMB36 | 0 | 8 |
| DSP | 1 | 1 |

Le timing final donne **+1,453 ns de marge setup**, **+0,024 ns de marge hold**,
sans endpoint en échec. Les quatre contraintes bus-skew passent. Les sorties
GPIO respectent explicitement leur maximum registre-vers-pad de 8 ns :
6,255 ns pour REF et 6,432 ns pour OBS. Ces valeurs ne constituent pas une
calibration des sondes ni une mesure de synchronisation sur carte.

Le DRC ne contient aucune erreur ; l'avertissement `REQP-1839` sur les commandes
BRAM a disparu après correction. Les huit avertissements restants concernent
les suggestions de pipeline DSP et la logique de l'IP de débogage, avec timing
respecté. Les 40 passages CDC détectés sont classés sûrs, sans passage inconnu
ni registre ASYNC_REG manquant. Les horloges et endpoints internes sont contraints.

L'image commune est `build/ptp_single_node_final/obsidian_ptp.bit`, accompagnée
de `obsidian_ptp.ltx`. `execution.json` et `source_sha256.json` dans ce dossier
attestent la compilation et identifient les sources et artefacts. Les rapports
recopiés sont dans `reports/ptp_single_node_builds/`. Le premier passage optimisé
`build/ptp_single_node/` précède la correction WE ; utiliser la version `_final`.

## Pourquoi le coût semblait appartenir au PTP

Dans l'ancien checkpoint, Vivado avait réattribué au moteur PTP **4 457 LUT
du journal** en reconstruisant la hiérarchie. La ligne « own = 6 162 » ne
mesurait donc pas son seul calcul : retrancher ce sous-ensemble laisse environ
1 705 LUT, proches des 1 726 LUT historiques du moteur. Le diagnostic et les
requêtes de cellules sont dans `build/sync_k1_optimization/findings.json` et
ses rapports de sous-ensembles. Le profil PTP ne contient aucun moteur DATA
CT/RAG, même si leurs sources et leurs profils historiques restent disponibles.

## Modifications réalisées

- **Journal :** 32 lignes de 256 bits dans quatre BRAM36, avec une écriture
  complète par cycle et lecture synchrone de 64 bits. L'ordre des mots, les
  champs, la capacité, les pertes et le gel atomique jusqu'à ACK sont conservés.
  Aucun arrêt du PTP ni perte de débit d'admission n'est introduit.
- **FIFO de liens :** données, échéance et horodatage source regroupés dans
  une RAM synchrone. Prélecture et transfert direct lors d'une insertion dans
  une file vide conservent exactement la latence, y compris au délai minimal
  d'un cycle. Les deux FIFO de frontière utilisent quatre BRAM36 au total.
- **Reset des BRAM :** aucun reset asynchrone ne commande leur autorisation
  d'écriture. Le reset synchrone des compteurs et pointeurs invalide les lignes ;
  toute écriture pendant reset est abandonnée, et chaque ligne est réécrite
  entièrement avant d'être exposée. Un essai avec données parasites pendant
  reset vérifie la première insertion dès le cycle de reprise.
- **Médiane runtime :** un comparateur signé de 64 bits et une lecture partagée
  remplacent les comparaisons parallèles. La médiane basse est identique,
  y compris sur les égalités. Les 43 cycles de calcul, plus le transfert de
  l'historique, terminent en 44 cycles ; deux estimations acceptables sont
  séparées d'au moins trois trames de 18 mots, soit 54 cycles. La précision
  et la décision suivante restent identiques. Le profil historique conserve
  son calcul parallèle.
- **CRC TX :** accumulation sur les deux octets de chaque mot effectivement
  accepté, puis émission du même CRC final. Les pauses TX et les timestamps
  gardent leur calendrier. Les grandes boucles CRC combinatoires à la requête
  disparaissent.
- **Registres :** les bits et mots réservés restent constants à zéro. Une
  écriture réservée non nulle est rejetée sans changer la configuration.
  Les champs utiles, dont époque et offset sur 64 bits, gardent leur précision.
- **VIO :** historique d'activité des entrées désactivé ; mêmes sondes et
  valeurs JTAG. Son coût synthétisé passe de 1 488 à 356 LUT.

Les synthèses isolées mesurent 4 350 → 3 498 LUT pour le cœur lors du changement
de médiane, et 535 → 219 LUT par FIFO à profondeur 128. Le journal seul mesure
112 LUT, 41 FF et quatre BRAM36. Ces mesures isolées précèdent l'ajustement de
l'autorisation d'écriture pendant reset. Elles ne s'additionnent pas pour
prédire le top : Vivado fusionne et déplace la logique entre les hiérarchies.
Le gain global retenu est celui du rapport complet, à paramètres K=1/N=3.

## Validation ciblée K=1

Le banc `sim/tb_ptp_single_node.vhd` utilise trois horloges de phases
distinctes, un transport physique simulé avec pauses TX et un seul moteur par
carte. Il couvre :

- configuration cohérente puis START de A seule ;
- pas logique runtime à 0, +2000 et -2000 ppb, avec offsets initiaux ;
- observation limitée au module local et référence émise par A seule ;
- stabilité des pages et événements pendant une collecte lente ;
- poursuite du maintien pendant cette collecte, vérifiée par l'augmentation
  des estimations acceptées après ACK ;
- compte des snapshots et événements non conservés ;
- STOP avec vidage, nouvelle configuration sans remise à zéro du temps brut,
  puis essai de durée finie avec arrêt persistant.

La commande suivante cible cette étape par défaut, sans lancer les chaînes
d'émulation de plusieurs modules :

```powershell
py -3 tools/validate_ptp.py
```

La validation finale passe **19 cas RTL et 55 tests Python**, avec les empreintes
des sources vérifiées. Elle comprend les comparaisons exactes des CRC, de la médiane,
du moteur et des FIFO ; elle vérifie aussi les profils de synchronisation
historiques. La médiane couvre 1 024 vecteurs signés, les extrêmes, les égalités
et tous les instants de reset ; les FIFO couvrent six configurations et
70 000 cycles chacune. Les tests Python vérifient les défauts K=1/N=3, les
contrats de configuration et de campagne, ainsi que les preuves d'exécution.

`reports/ptp_single_node_validation/validation.json` donne le résultat final,
les journaux et les empreintes exactes des sources compilées. Le cas de
registres utilise une capacité supérieure uniquement pour tester les bornes
de configuration, sans démarrer de synchronisation multi-module.

Les commandes de construction et de préparation des campagnes K=1 sont dans
[ptp_emulation.md](ptp_emulation.md). Aucun accès ni programmation des cartes
n'est nécessaire pour ces tests et builds.
