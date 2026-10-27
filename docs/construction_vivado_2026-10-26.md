# Construction locale — Vivado 2025.2 — 26 octobre 2026

Les trois paires BIT/LTX du profil RAG_D sont générées et acceptées.
Cible : XC7A35T-CSG325-2 ; MODE=2, N=3, LOCAL=1, D=6, R=2, 128 cycles.
Les bases A/B/C valent 0/1/2. Aucune carte n'a été programmée ou mesurée.

| Carte | ID | WNS setup | WHS hold | Erreurs DRC |
|---|---|---|---|---|
| A | 0 | +0,242 ns | +0,031 ns | 0 |
| B | 1 | +0,021 ns | +0,056 ns | 0 |
| C | 2 | +0,008 ns | +0,056 ns | 0 |

Les horloges et endpoints internes sont contraints. Les contrôles de bus skew
passent. Les rapports CDC ne signalent aucun endpoint unsafe ou unknown.
Les 18 simulations XSim et les 15 tests Python passent.

## Commandes

Depuis la racine du projet, sous PowerShell :

```powershell
$env:VIVADO='C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat'
py -3 scripts/run_vivado_tests.py
py -3 scripts/build_campaign.py --mode 2 --nodes 3 --run-cycles 128
```

Chaque image est sous `build/rag_m2_n3_b<BASE>_l1_d6_r2_c128/`.
Les résultats XSim et les empreintes de leurs sources sont sous `build/xsim_tests/`.
Le build utilise directement les commandes Vivado. Ouvrir son
`obsidian_benchmark_routed.dcp` pour examiner une implémentation ; les runs GUI
synth_1/impl_1 ne représentent pas ce flux direct. Le checkpoint routé est conservé
avant les contrôles finaux afin de permettre une reprise.

## Corrections et optimisations

Le premier profil A occupait 43 998 LUT pour 20 800 disponibles. Le build final
occupe environ 17 000 LUT pour A et 19 000 à 20 000 LUT pour B/C. Les tailles des
files, les formats de trame et la cadence du protocole sont conservés.

- Aurora : paramètres internes autorisés du cœur membre et configuration des
  paramètres dépendants après sélection du SupportLevel approprié.
- ILA : profondeur de 1 024 échantillons, minimum accepté par cette IP ; la valeur
  512 du script initial était refusée.
- Filtre : décisions dans une RAM à un port d'écriture et classification protégée
  par l'ordre d'arrivée. Le blocage d'un descripteur non classifié après débordement
  est conservé. Comparaison à l'original sur 50 000 cycles pour chacune des
  profondeurs 2, 16, 128 et 2 048 mots.
- Codec : CRC RX calculé par mot de 16 bits et vérification par résidu CRC32 ;
  écritures mémoire par paire d'octets et calcul TX factorisé. La comparaison à
  l'original couvre huit types TX, stalls, timestamps et trames RX valides,
  corrompues ou tronquées.
- Médiane : comparaisons de rang indépendantes, même quatrième valeur triée,
  aucune latence ajoutée. Comparaison au tri d'origine sur 20 001 vecteurs signés
  de 64 bits, doublons et valeurs extrêmes inclus.
- Fermeture physique : B a nécessité une passe post-routage AggressiveExplore
  puis Explore. Le script applique cette reprise si le premier routage a un slack
  négatif, puis conserve les contrôles d'acceptation.
- Reset CDC : reset_cdc.xdc ne coupe que les six broches PRE/CLR des deux chaînes
  de reset à trois registres. Le script vérifie le nombre de cellules, ASYNC_REG
  et le nombre de broches. Aucun regroupement global des horloges n'est ajouté.
  Les quatre chemins D/C interétages restent chronométrés et passent.
- Contrôles : setup, hold, bus skew, horloges/endpoints internes et DRC sont
  vérifiés avant l'acceptation du bitstream.

Sous Windows restreint, la collecte WMI du lanceur AMD échouait. Le dossier
scripts/windows_compat sélectionne la branche legacy du lanceur WSH AMD sur ses
copies générées. Seul le PATH des processus de compilation est adapté ; aucun
fichier de Windows ou de l'installation AMD n'est modifié. Les codes de sortie et
marqueurs réels de fin/erreur sont conservés.

## Traçabilité

A a été générée avant le remplacement de la médiane, calcul éliminé pour l'ancre
ID 0. B et C utilisent la médiane par rangs, équivalente en valeur et sans latence
ajoutée. L'exception de reset CDC a été appliquée au checkpoint de B ; A et C
avaient déjà passé leurs contrôles. Les empreintes par image décrivent leurs
sources/contraintes réelles ; celles du paquet global décrivent le projet final.

Pour B, reset_cdc_scope.txt énumère les six broches concernées et
reset_sync_interstage_timing.rpt vérifie les quatre chemins conservés.
La structure de [synchroniseur de reset asynchrone est décrite par AMD](https://docs.amd.com/r/en-US/ug906-vivado-design-analysis/Asynchronous-Reset-Synchronizer) ;
les [exceptions de timing sont documentées dans UG903](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/False-Paths).

Les SHA256SUMS, ARTIFACT_MANIFEST.json et SOURCE_PROVENANCE.json d'origine restent
les preuves de l'archive initiale. Les sources autorisées ont ensuite été modifiées.
Les simulations et le timing statique ne remplacent pas les essais sur cartes.
