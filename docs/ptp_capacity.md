# Capacité d'émulation du profil PTP

La base K=1 validée est enregistrée dans le commit `cfb9722`. La recherche
conserve son RTL, sa précision et les trois cartes XC7A35T-CSG325-2. K désigne
le nombre de moteurs par carte ; l'anneau contient au plus N=3K modules.
Les trois cartes utilisent une image commune avec rôle A/B/C réglé par VIO.

**Capacité retenue pour les essais : K=3, soit neuf modules sur l'anneau.**
Elle passe le routage et les critères de marge ci-dessous. K=4 est rejeté par
les ressources. Il s'agit de la limite observée de cette version, sans recherche
d'une architecture différente ni essai exhaustif de toutes les options Vivado.

## Critère de choix

Une capacité est exploitable seulement après placement-routage, génération
BIT/LTX et vérification des empreintes. La synthèse seule ne suffit pas.
Les contrôles couvrent setup, hold, pulse-width, bus-skew, horloges et chemins
internes contraints, DRC sans erreur et délai registre-vers-pad GPIO de 8 ns.

Le rapport distingue le plus grand K routé et la recommandation d'ingénierie :
au moins 15 % de LUT et FF libres et au moins 0,5 ns de marge setup. Ces marges
sont un choix pour les essais, pas une limite supplémentaire du FPGA.
La conclusion porte sur cette architecture et les candidats réellement testés.

## Mesures

Les entrées RTL et contraintes sont identiques pour les quatre capacités ;
seuls K et le maximum N changent. Les rapports et leurs empreintes permettent
de vérifier cette comparaison.

| K par carte | N maximal | LUT synthèse | FF synthèse | BRAM36 | DSP |
|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 7 226 | 10 909 | 8 | 1 |
| 2 | 6 | 11 792 | 16 564 | 10 | 2 |
| 3 | 9 | 16 624 | 22 231 | 12 | 3 |
| 4 | 12 | 21 107 | 27 869 | 14 | 4 |
| Limite FPGA | — | 20 800 | 41 600 | 50 | 90 |

K=4 est rejeté par le DRC préalable au placement, `UTLZ-1` : après optimisation,
21 389 LUT de logique sont requises pour 20 800 sites. Le placer ne s'exécute
pas et aucune image K=4 n'est validée. Les contrôles n'ont pas été abaissés.
Les mémoires et les DSP ne sont pas le facteur limitant observé.

| K | LUT après routage | FF après routage | LUT libres | Setup | Hold |
|---:|---:|---:|---:|---:|---:|
| 1 | 7 466 | 11 421 | 64,11 % | +1,453 ns | +0,024 ns |
| 2 | 12 012 | 17 079 | 42,25 % | +1,240 ns | +0,073 ns |
| 3 | 16 558 | 22 744 | 20,39 % | +0,573 ns | +0,037 ns |
| 4 | placement refusé | — | — | — | — |

K=3 utilise douze BRAM36 et trois DSP. Les quarante passages CDC détectés sont
classés sûrs, sans passage inconnu. Les quatre contraintes bus-skew passent,
ainsi que les GPIO : 6,294 ns pour REF et 6,212 ns pour OBS, pour un maximum de
8 ns. Le DRC ne contient aucune erreur. La précision Q48.32/Q48.16 est conservée.

Un avertissement `REQP-1839` reste présent pour K3, deux pour K2 : l'optimisation
de puissance a ajouté une commande de lecture BRAM sensible à l'assertion du
reset. L'audit du DCP confirme un port A exclusivement en lecture (`WRITE_WIDTH_A=0`),
avec ses commandes d'écriture à zéro. Les écritures du port B ne reçoivent pas
de commande asynchrone active ; les CLR des bascules ajoutées sont constants.
Les compteurs et pointeurs sont vidés pendant reset ; la première entrée est
réécrite entièrement et transférée directement avant exposition. Ce confinement
est un argument structurel et RTL, pas un essai physique de reset sous trafic.
Les rapports d'audit sont dans `reports/ptp_capacity/bram_control_audit/`.
Les autres avertissements portent sur les pipelines DSP et l'IP de débogage.

L'image retenue est `build/ptp_capacity_search/k3_route/obsidian_ptp.bit`, avec
`obsidian_ptp.ltx` dans le même dossier. Son `execution.json` est `passed`,
avec sources, scripts d'implémentation et empreintes d'artefacts vérifiés.

La configuration nominale est `config/ptp_emulation_9.example.json` :
A porte M1..M3, B M4..M6 et C M7..M9. Conserver `capacity=3` dans les essais
de populations inférieures ; le champ `nodes` peut alors varier de 3 à 9.
La base K=1 reste disponible et demeure la valeur par défaut des outils.

Prévisualisation de la commande destinée aux cartes déjà chargées :

```powershell
py -3 scripts/run_ptp_campaign.py run --config config/ptp_emulation_9.example.json --image-dir build/ptp_capacity_search/k3_route --node 9 --dry-run --output captures/ptp_n9_preview
```

Le rapport complet est généré par :

```powershell
py -3 tools/report_ptp_capacity.py --output reports/ptp_capacity
```

Il distingue les candidats synthétisés, les rejets et les images routées dont
les sources et artefacts sont vérifiés. Un échec de préparation de l'outil ou
une preuve périmée ne constitue pas une limite de capacité.

## Validation fonctionnelle et données préparatoires

Les six scénarios RTL passent pour K=2 puis pour K=3 : population complète,
population inégale, reconfiguration arrêtée vers N=3K−2, observation locale,
pages/journal figés, maintien, STOP/réarmement, phases, dérive, jitter et asymétrie.
Le retour vers N=3 dans la même capacité synthétisée est également vérifié :
les slots et liens internes devenus inactifs ne participent plus.
Les cas et leurs paramètres sont dans `tools/ptp_capacity_cases.py`.
La suite Python comprend 86 tests réussis. Les preuves des douze cas RTL et
les sources compilées sont archivées dans `reports/ptp_capacity_validation/`.

```powershell
py -3 tools/validate_ptp.py --scope capacity --capacity 3
```

Les huit séries quantitatives K2/K3 sont exportées dans
`reports/ptp_capacity_validation/k*/data/`. Chaque série contient 32 instants
communs à tous les modules, séparés de 997 ticks, soit une fenêtre échantillonnée
de 0,494512 ms. Les identifiants de données sont indexés à partir de zéro :
`node_id=0` correspond à M1. L'export conserve les temps Q48.16 exacts, l'erreur
par rapport à M1, l'erreur par liaison et les états de verrouillage/holdover.

Les sauts physiques sont les passages A→B et B→C dans la chaîne de correction.
La fermeture C→A transporte notamment les informations de préparation ; M1
n'est pas un suiveur du dernier module. Les autres sauts sont internes à une
carte. Les modules d'une même carte partagent son oscillateur physique.

Les scénarios symétriques donnent zéro erreur aux instants échantillonnés.
L'asymétrie injectée de 3 ticks aller contre 1 retour produit le biais prévu de
−16 ns par saut, soit −128 ns au dernier module pour N=9. Ce résultat vérifie
le scénario injecté ; il ne constitue pas une loi empirique du matériel.

Le scénario combinant phases, dérive alternée et jitter ne reste pas toujours
verrouillé. Hors ancre, 86/160 échantillons K2 et 96/256 échantillons K3 sont
verrouillés sans holdover ni erreur. Les autres sont conservés et exclus des
statistiques de verrouillage. Les fractions diffèrent aussi parce que le dernier
module n'a pas la même dérive relative à l'ancre dans les deux populations.

Ces essais utilisent une seule graine déterministe et une courte fenêtre.
Ils ne séparent pas les contributions du jitter, des phases et de la dérive.
Aucun modèle physique n'a été ajusté et aucune extrapolation n'est annoncée.

## Suite des essais et modélisation

Utiliser une seule image de capacité retenue, puis faire varier N à l'exécution
pour conserver le même placement. Mesurer les fronts de M1 et du module observé
sur des époques appariées, en gardant les mêmes durées, cadences et réglages de
liens entre populations. Les pages locales ne sont pas des mesures globales
simultanées ; les pertes du journal sont distinctes des pertes de trames.

Les mesures physiques serviront à estimer les paramètres des liens physiques,
l'asymétrie, la dérive et le bruit. Le modèle devra conserver les trois domaines
d'horloge physiques, les corrélations entre modules d'une carte, les sauts internes
et les pertes de verrouillage. Sa comparaison aux populations mesurables précède
la simulation au-delà de la capacité matérielle retenue.

Aucune carte ni flash n'a été programmée pendant cette recherche.
