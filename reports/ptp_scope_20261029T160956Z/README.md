# Bilan physique PTP — neuf modules virtuels sur trois FPGA

Les neuf moteurs du profil **K=3, N=9 fonctionnent sur les trois cartes**. Les séries intercartes présentent une dispersion courante de **4,5 à 6,2 ns**, mais cet écart-type ne borne pas l'erreur : des excursions proches de **68 ns** sont confirmées dans les formes d'onde RAW. Un modèle gaussien fondé sur σ seul manquerait ces queues.

## Séries principales

Chaque module dispose de **100 acquisitions SINGLE fraîches validées** : 900 acquisitions module, auxquelles s'ajoutent 100 acquisitions de calibration. La persistance de 20 s et ses statistiques natives sont conservées séparément.

Le délai signé est **Δ = front OBS − front REF M1/A** ; positif signifie pulse observé en retard. Le tableau donne la moyenne brute, la moyenne après soustraction du biais instrumental commun et la SD d'échantillon des 100 délais, en ns.

| Module | Carte | μ brute (ns) | μ corrigée (ns) | σ (ns) |
|---|---|---:|---:|---:|
| M1 | A | −0,290 | +0,007 | 0,036 |
| M2 | A | −0,295 | +0,002 | 0,037 |
| M3 | A | −0,298 | −0,002 | 0,038 |
| M4 | B | −22,339 | −22,042 | 4,489 |
| M5 | B | −23,188 | −22,891 | 5,227 |
| M6 | B | −24,807 | −24,510 | 4,564 |
| M7 | C | −9,134 | −8,837 | 6,188 |
| M8 | C | −10,574 | −10,277 | 6,191 |
| M9 | C | −10,191 | −9,894 | 5,756 |

La calibration `A_same_sync`, deux sondes sur le même net SYNC, estime un biais de **−0,29667 ns**, avec SD **0,03588 ns** sur 100 acquisitions. La correction retire cette moyenne uniquement ; aucune variance de calibration n'est retranchée. Les différences de sorties FPGA et de pistes entre cartes restent comprises dans les mesures.

La faible dispersion sur A est cohérente avec une horloge physique partagée. L'échantillonnage ADC à **500 ps** et l'interpolation ne démontrent pas une exactitude absolue de 35 ou 40 ps. La moyenne, la SD et le RMS sont des grandeurs distinctes ; les définitions et réglages figurent dans [PROTOCOLE.md](PROTOCOLE.md).

## Excursions confirmées hors de la dispersion courante

Un déclenchement conditionnel sur M7/C a obtenu trois nouvelles captures RAW : **−67,979 ns, +57,156 ns et −58,656 ns**, délais bruts. Toutes sont hors de la fenêtre relue d'environ **[−49,9928 ; +50,0072] ns**, avec tolérance de relecture de 50 ps.

Ces trois acquisitions sélectionnées **ne sont pas ajoutées aux 900 acquisitions principales** et ne permettent pas d'estimer une fréquence d'occurrence. Voir les [résultats du déclenchement](17_C_M7_outlier_trigger_quantized/outlier_trigger.json), une [capture illustrée](17_C_M7_outlier_trigger_quantized/outlier_0000.png) et la [figure des excursions confirmées](outliers_confirmes.png).

La fenêtre native de 20 s de M7/C comptait 303 mesures, avec minimum −68,5 ns, maximum +4 ns et SD 7,24 ns ; la persistance montrait aussi une queue positive. Ce jeu natif est distinct des 100 RAW. Pour M4/B, le maximum natif `9,9e37` invalide le jeu de statistiques natif, sans invalider ses 100 RAW ; les drapeaux correspondants sont conservés dans le CSV.

La première tentative M9 est inconclusive : le scope avait élargi à 100 ns la fenêtre de 60 ns demandée. Une validation intermédiaire M7 a refusé un arrondi de relecture d'environ 7 ps ; la capture finale accepte explicitement une tolérance de 50 ps puis vérifie les écarts dans les RAW. Une absence de déclenchement dans ces tentatives ne prouve donc pas une borne.

## Qualification et traçabilité

Les premières séries `01_A_M1` et `02_A_M2` sont préservées comme diagnostics, avec marqueurs `case_unverified.json`, et exclues du bilan officiel. Leur dispersion initiale n'a plus été reproduite après déplacement/reconnexion des sondes et contrôle désactivation/réactivation d'OBS. La cause reste indéterminée ; aucune erreur de câblage de l'utilisateur n'est établie.

Les sorties observées ont été identifiées par désactivation contrôlée : CH2 devient plate et CH1 reste active, puis le signal revient après réactivation. Le cache VIO du pilote hôte a également été synchronisé avant écriture pour préserver les autres sorties actives. Cette correction est logicielle côté hôte ; aucun RTL ni rechargement FPGA n'a été nécessaire pendant les mesures.

La configuration reste `K=3`, `N=9`, `run_id=9`, `config_id=b548f1927173517b`. L'[audit des sources, broches et empreintes](provenance/source_pin_audit.json) relie l'image chargée aux sources et rapports de construction. Les lectures JTAG avant/après sont des contrôles ponctuels sur les cartes accessibles, pas une preuve continue d'absence de défaut ; aucune absence de perte du journal n'est affirmée.

**36 tests unitaires ont passé la validation finale.** L'analyse offline a validé les 1 000 acquisitions officielles ; la [revérification croisée](verify_and_plot.py) contrôle ce jeu et redécode les trois excursions. `analysis.complete=true` qualifie les dix cas découverts ; l'état global de campagne est suivi séparément dans [experiment.json](experiment.json).

## Limites et suite

Il s'agit d'une seule configuration N=9, mesurée successivement par module. Neuf moteurs virtuels partagent **trois horloges physiques**, avec un tick logique de **16 ns** ; ce montage ne représente pas neuf cartes indépendantes. Il ne permet pas de déduire une loi de dégradation avec N.

Un futur modèle devra distinguer les dérives physiques partagées, les dérives virtuelles indépendantes, les biais de chemins et les queues de distribution. Les moyennes et σ seuls ne suffisent pas à extrapoler ni à garantir un délai maximal.

L'installation finale reste en fonctionnement : CH1 sur TEST_SYNC de A, CH2 sur MOSI de C sélectionné M9. Le scope est en `RUN`, acquisition `NORM`, 2 Géch/s, mémoire 10k, affichage 100 ns/div, persistance `INF`, déclenchement `EDGE` positif sur CH1 à 1,65 V. Les [réglages finaux](18_final_live/final_settings.json) et la [vue finale](18_final_live/M9_live_persistence.png) sont archivés. Tous les workers matériels sont fermés, dont le [worker JTAG final](hardware_rpc/r026_worker_close.json).

Les trois ports USB accueillent A, C et le scope ; B reste alimentée sans USB. Aucun déplacement physique supplémentaire n'est demandé.

## Données disponibles

- [Résumé numérique](summary.csv) et [analyse détaillée](analysis.json) : acquisitions, statistiques, corrections et drapeaux de validité.
- [Traces et histogrammes](delaytrace_histogram.png) : résultats bruts des séries principales.
- [Protocole reproductible](PROTOCOLE.md) : acquisition, décodage, calibration et limites instrumentales.
- [Excursions confirmées](outliers_confirmes.png) et [RAW conditionnels](17_C_M7_outlier_trigger_quantized/outlier_trigger.json) : hors statistiques principales.
