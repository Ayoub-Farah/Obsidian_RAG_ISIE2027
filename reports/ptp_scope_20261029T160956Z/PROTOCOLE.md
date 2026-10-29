# Protocole de mesure PTP — MHO984, 29 octobre 2026

Ce document décrit la méthode et les qualifications du dossier. Les résultats par module figurent dans le rapport associé. L'image K3 est déjà chargée en SRAM ; cette mesure ne modifie pas le RTL et ne nécessite aucun rechargement.

## Montage et périmètre

CH1 reste sur TEST_SYNC de A ; CH2 observe MOSI sur la carte étudiée, avec confirmation des déplacements par l'opérateur. Le netlist associe ces nets aux points TP23/TP15 et TP24/TP16, mais le point de contact exact n'a pas été indiqué. L'identité des sorties OBS a été vérifiée par désactivation/réactivation. Les masses sont prises sur la carte sondée.

A=OBS001A, B=OBS003A, C=OBS002A. Neuf moteurs virtuels se répartissent M1–M3 / M4–M6 / M7–M9 sur **trois horloges physiques**. Le tick logique vaut 16 ns ; la période programmée est de 100 µs et la largeur de pulse de 1,024 µs.

La campagne utilise successivement A+B puis A+C en JTAG/USB, en plus du scope, car trois ports USB sont disponibles. La carte sans USB reste alimentée selon confirmation de l'utilisateur ; l'absence de câble JTAG ne signifie pas l'arrêt du FPGA.

La commande d'observation modifie seulement le sélecteur GPIO, sans STOP ni reset PTP. Attendre l'identifiant actif et `obs_valid`, puis figer la sélection et remettre à zéro les statistiques/écrans du scope avant chaque condition.

## Grandeurs et réglages

Le délai signé est **Δ = instant du front OBS − instant du front REF**. Δ positif signifie pulse observé en retard. Pour des fronts de même époque et des fréquences proches, son signe s'oppose à l'erreur des horloges logiques comparées à instant commun.

La moyenne mesure le biais ; la SD d'échantillon décrit la dispersion, avec dénominateur n−1. Le RMS, racine de la moyenne des Δ², inclut aussi le biais. Une SD sur un seul point n'est pas définie.

- Acquisition `NORM`, sans moyennage ; persistance `INF` uniquement pour l'enveloppe visuelle.
- Limitation de bande `BWLimit=OFF` sur les deux voies ; la bande réelle reste celle du scope et des sondes.
- Entrées 1 MΩ, facteur de sonde ×10 cohérent avec les sondes physiques, niveaux numériques proches de 3,3 V ; inversion et correction temporelle de voie désactivées.
- Fréquence effectivement relue : **2 Géch/s**, soit `Xincrement=0,5 ns` ; elle n'est pas déduite du zoom affiché.
- Conditions officielles après vérification : profondeur 10 000 points, donc fenêtre RAW nominale de 5 µs, bien que l'écran soit à 100 ns/div.
- La calibration commune `A_same_sync` utilise 100 000 points, soit 50 µs, à la même fréquence d'échantillonnage.

Les commandes et paramètres sont décrits dans le [guide de programmation RIGOL MHO900](https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/oscilloscopes/MHO900-ProgrammingGuide.pdf?t=1760543891885), notamment acquisition, voies et chapitre 3.28. Les raccordements et fonctions de base sont présentés dans le [guide rapide RIGOL](https://www.rigol.com/dam/global/downloads/brochures/en/quick-guide/oscilloscopes/MHO900-QuickGuide.pdf?t=1762233853844) ; les éditions disponibles sont répertoriées sur la [page officielle MHO900/MHO984](https://www.rigol.com/europe/products/oscilloscope/MHO900.html).

## Acquisition et décodage

1. Réduire les bornes de transfert à `START=1, STOP=1000`, pour chaque voie, **avant de diminuer la profondeur mémoire** ; cela évite de conserver une borne hors de la nouvelle mémoire.
2. Réinitialiser l'affichage et les statistiques ; conserver une fenêtre demandée de 20 s de persistance, avec durée réelle et compte natif enregistrés séparément.
3. Pour chaque condition officielle, effectuer **100 nouvelles acquisitions SINGLE**. Attendre `STOP`, puis lire les deux voies sans relancer l'acquisition entre elles.
4. Lire la mémoire complète en `RAW`, format `BYTE`, avec son préambule. Vérifier fréquence, longueur et bornes ; sauvegarder chaque paire `single_*.npz` et son JSON.
5. Préserver les octets LF présents dans le bloc binaire, selon sa longueur déclarée. Vérifier l'égalité des longueurs, incréments et origines temporels des deux voies.

Le préambule comporte dix champs. `FORMAT=0, TYPE=2` désigne ici BYTE/RAW ; ce TYPE n'indique pas un moyennage. Le [guide SCPI, chapitre 3.28](https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/oscilloscopes/MHO900-ProgrammingGuide.pdf?t=1760543891885) définit le transfert et les échelles utilisées :

```text
V = (octet − Yorigin − Yreference) × Yincrement
t = (i − Xreference) × Xincrement + Xorigin      (i commence à zéro)
```

Les fronts utilisent une séparation initiale P10/P99,8, puis les médianes des plateaux, un seuil médian et une hystérésis. Leur instant est interpolé linéairement. Un signal insuffisant, une saturation ADC ou un appariement ambigu est rejeté et conservé comme erreur de validation.

L'appariement utilise le plus proche front unique dans la fenêtre autorisée, sans correction modulo 100 µs. Les vues larges servent à vérifier la période ; une capture fine à un seul front ne prouve ni la période ni l'identité absolue d'époque. Les temps morts USB empêchent de conclure à l'absence de pulses perdus entre captures.

Seuls les `single_*` alimentent les statistiques officielles. Le nombre d'acquisitions reste distinct du nombre de fronts appariés. `persistence_last_pair` est un diagnostic ; les statistiques RRDelay natives sont séparées, avec validation des sentinelles telles que `9,9e37`. Leur quantification et l'interpolation offline ne constituent pas une preuve de précision picoseconde.

## Calibration et vérification physique

La calibration `A_same_sync` place les deux sondes sur le même net SYNC de A. Sur ses 100 acquisitions archivées, le biais estimé vaut −0,2967 ns et la SD 0,0359 ns. Ce sont des estimations de cet enregistrement, sans garantie d'exactitude absolue. Seul ce biais instrumental/sondes est soustrait comme tel ; aucune variance de calibration n'est retranchée.

Sélectionner M1 sur OBS/A fournit une comparaison des chemins REF/OBS, incluant les sorties FPGA et les pistes. Cette baseline n'est pas une calibration purement instrumentale ; son transfert aux cartes B/C laisse leurs différences de chemins à qualifier.

Le contrôle physique a désactivé OBS/A : CH2 est devenue plate, avec un bruit observé d'environ ±0,102 V, tandis que CH1 conservait ses pulses proches de 3,3 V. Après réactivation de M1, un diagnostic court a donné une moyenne de −0,2836 ns et une SD de 0,0405 ns, confirmant l'identification de la sortie observée.

Les premières séries `01_A_M1` et `02_A_M2` restent archivées, mais leurs marqueurs sont renommés `case_unverified.json` et elles sont exclues du rapport officiel. Leur dispersion initiale n'a plus été reproduite après déplacement/reconnexion des sondes et vérification désactivation/réactivation. La cause initiale demeure indéterminée ; aucune erreur de câblage de l'utilisateur n'est établie.

Un contrôle conditionnel recherche ensuite les excursions visibles en persistance sur M7/C. Le déclenchement Delay compare CH1 descendant au front CH2 montant suivant : `D = période_REF − largeur_REF + Δ`. Les bornes positives sont calculées sur une capture RAW large, puis relues ; la fenêtre finale correspond à environ Δ = [−50 ; +50] ns. Trois acquisitions neuves hors fenêtre confirment −67,98 ns, +57,16 ns et −58,66 ns. Leurs formes d'onde et préambules sont archivés dans `17_C_M7_outlier_trigger_quantized`.

Ces acquisitions sélectionnées ne contribuent ni aux moyennes des 100 captures de chaque module (900 au total), ni à une estimation de fréquence des pointes. Les essais précédents, conservés dans les dossiers 15 et 16, sont inconclusifs : élargissement automatique d'une fenêtre de 60 ns puis rejet trop strict de l'arrondi des bornes. Le déclenchement CH1 montant, l'acquisition normale et la persistance infinie ont été restaurés ; M9/C est sélectionné à la fin.

## Limites de qualification

Les lectures JTAG avant/après acquisition donnent des états ponctuels, pas une preuve continue d'absence de défaut. Les pages figées et les pertes comptées ne permettent pas d'affirmer que le journal est sans perte.

Les comparaisons successives ne mesurent pas simultanément les neuf modules. Elles ne représentent pas neuf cartes indépendantes et ne suffisent pas à ajuster une loi de dégradation ou à extrapoler au-delà des résultats physiques collectés.

`analysis.complete` signifie que les cas découverts satisfont la validation du rapport. L'achèvement de l'expérience entière est suivi séparément par `experiment.json`, champ `campaign_complete`.
