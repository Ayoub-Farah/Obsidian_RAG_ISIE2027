# PTP_EMULATION — branche test_sync

Ce profil part du commit `d92a3dcfdd0642c7e6094d15171a43990d3803db`, également
HEAD au début du travail. La spécification du 29 octobre 2026 est une cible
d'architecture. Les preuves d'exécution K=1 sont dans `reports/ptp_single_node_validation` et
les dossiers de build ; elles ne prouvent pas une validation matérielle.

La base validée est **K=1, N=3** : un module PTP sur chacune des trois cartes
physiques. Elle reste le profil par défaut des outils. Le
[bilan d'optimisation K=1](ptp_single_node_optimization.md) donne les ressources
et validations de cette base ; la [recherche de capacité](ptp_capacity.md)
détermine l'image destinée aux essais avec plusieurs modules par carte.

## Architecture

Le top dédié `obsidian_ptp_top` contient K instances complètes de `sync_system` :
accumulateur Q48.32, correction Q48.16, transactions parent/enfant, deux codecs,
historique de délai, séquences et compteurs indépendants. Il ne contient aucun
chemin DATA CT/RAG. Les anciens tops et commandes restent distincts.
Le servo d'offset, les huit estimations d'acquisition, les seuils et la politique
`G_EXTERNAL_SCHEDULER=true` sont conservés, sans correction de fréquence.

Les identifiants RTL commencent à zéro ; l'utilisateur sélectionne M1..MN.
La répartition donne le reste à A puis B : N=10 donne 4/3/3, N=60 donne
M1..M20 / M21..M40 / M41..M60. K est une capacité de construction ; N matériel
est borné à `min(60,3*K)`. L'extension N=180 est uniquement simulée.
Une simulation de 60 modules ne prouve pas K=20 sur XC7A35T.

Les relations internes utilisent deux FIFO indépendantes chacune. Les frontières
et la fermeture C/A passent par Aurora. READY remonte la chaîne ; ARM en fait
le tour. M1 n'est jamais enfant du dernier module. Les slots inactifs restent
au reset. Trois FPGA représentent trois oscillateurs physiques, même avec N=60.

## Configuration runtime

`config/ptp_emulation.schema.json` définit les bornes et défauts. Les tableaux
vides prennent les défauts ; sinon `drift_ppb` et `offset_ticks` ont N entrées,
et `links` N−1 entrées. `links[j]` décrit M(j+1) → M(j+2) et le retour.

| Paramètre | Défaut et unité | Bornes |
|---|---|---|
| period_ticks | 6250 ticks = 100 µs | 626..16777215 |
| maintenance_ratio | 10, maintien toutes les 1 ms | 1..65535 |
| pulse_width_ticks | 64 ticks = 1,024 µs | 1..625 |
| epoch_ticks | E0 = 500000 ticks | 0..2^47−1 |
| sample_period_ticks | 62500 ticks = 1 ms | 1..2^32−1 |
| duration_ticks | 0 = continu, depuis l'entrée locale en nominal | uint64 |
| drift_ppb | 0, par module | ±1000000 |
| offset_ticks | 0, signé par module | ±1000000000 |
| forward_ticks/reverse_ticks | 1 tick par direction | 1..4095 |
| jitter_mask | 0, tirage entier dans [0,masque] | 0 ou 2^m−1, jusqu'à 255 |
| drop_every | 0, sinon chaque Nième trame complète | 0..65535 |

La période des pulses est la période logique ; elle n'est pas indépendante
dans cette version. Maintien et cadence logique ont un rapport entier.
L'hôte calcule `2^32 + trunc(ppb*2^32/10^9)`, troncature signée vers zéro.
2000 ppb = 2 ppm. Cette dérive s'ajoute à celle de l'oscillateur de la carte.
Le jitter est tiré une fois par trame avec un LFSR reproductible ; les graines
sont décalées par carte et direction. Les files conservent l'ordre des mots
et des trames, même si cela augmente leur attente effective.

Une reconfiguration effectue STOP/vidage des trois cartes, écriture shadow avec
relecture, COMMIT B/C/A, vérification rôle/N/capacité/hash partout, puis START
sur A. Le hash est le SHA-256 tronqué à 64 bits du JSON normalisé. Cette
cohérence est orchestrée par l'hôte ; aucun consensus de hash FPGA n'est ajouté.
Une transaction partiellement refusée ne doit pas être démarrée. Donner un
`run_id` distinct à chaque essai. Le reset d'état émulé conserve le compteur
brut de carte ; le reset matériel du top le remet à zéro.

START est envoyé à A seule. B/C activent leurs snapshots au premier lock local ;
le journal d'événements enregistre déjà les trames antérieures. La durée
nominale commence lorsque tous les slots locaux sont
running ; chaque carte demande ensuite un arrêt avec vidage. Les débuts et fins
physiques gardent l'incertitude du PTP et du vidage : ce n'est pas une référence
de mesure intercartes.

Après STOP, la demande d'arrêt reste maintenue pour absorber les SYNC tardifs
sans relancer un parent. Une nouvelle configuration libère cet arrêt sur les
trois cartes. La commande `start` de reprise réarme B/C avant de lancer A ;
`run`, qui effectue déjà un COMMIT global, ne lance que A.

Préparer un Tcl sans connexion matérielle :

```powershell
py -3 scripts/run_ptp_campaign.py run --config config/ptp_emulation_3.example.json --node 3 --dry-run --output captures/ptp_preview
```

Après build validé et chargement manuel explicite du même BIT/LTX sur A/B/C :

```powershell
py -3 scripts/run_ptp_campaign.py run --config config/ptp_emulation_3.example.json --image-dir build/ptp_image_validee --node 3 --output captures/ptp_run
py -3 scripts/run_ptp_campaign.py observe --config config/ptp_emulation_3.example.json --image-dir build/ptp_image_validee --node 2 --output captures/ptp_m2
py -3 scripts/run_ptp_campaign.py collect --config config/ptp_emulation_3.example.json --image-dir build/ptp_image_validee --output captures/ptp_page_001
py -3 scripts/run_ptp_campaign.py stop --config config/ptp_emulation_3.example.json --image-dir build/ptp_image_validee --output captures/ptp_stop
```

`observe` vérifie la configuration active, modifie uniquement la carte
propriétaire et confirme `obs_node_active` et `obs_valid` par relecture. Il ne
fait ni STOP, ni reset, ni COMMIT PTP, ni programmation. Pour N=3/K=1,
M1 appartient à A, M2 à B et M3 à C, chaque fois à l'index local zéro.
Le fichier explicite `config/ptp_emulation.example.json` conserve l'exemple
N=60/K=20 pour une étape ultérieure ; il ne correspond pas au build K=1 et
ne constitue pas une capacité matérielle validée.

`run` et `start` attendent running/locked sans holdover sur les trois cartes,
avec timeout. Pour une durée finie, le drapeau persistant « nominal atteint »
permet aussi de reconnaître un essai déjà arrêté avant la lecture JTAG ; il
ne prouve pas que la durée demandée a été achevée si un STOP manuel est intervenu.
La sélection demandée par `run --node` est appliquée avant START.
`configure` n'attend que le COMMIT. Ces indicateurs locaux, ainsi
que `obs_valid` qui ne qualifie que le mux, ne mesurent pas l'erreur globale.

## Horodatage et instrumentation

TX est horodaté au premier mot effectivement accepté, après les éventuels
stalls. Les mots sont éligibles en RX à `tick_TX_accepté+délai+jitter` ; une
trame ne dépasse jamais les mots déjà en file. Aux frontières, l'injecteur suit
Aurora RX. Le compteur brut au mot RX Aurora est conservé dans la FIFO pour
l'audit. Le temps logique PTP est capturé à la présentation après injection,
afin que celle-ci influence t2/t4. Ces deux plans sont intentionnellement
distincts. Le délai physique Aurora reste inconnu et s'ajoute à l'injection
(au minimum un tick). Aucune latence physique de 37 cycles n'est supposée.

Aurora RX n'a pas de backpressure. Un débordement de FIFO de frontière
(128 mots) est sticky et invalide le banc ; les pertes injectées sont comptées.
Les fractions Q48.16 ne constituent pas une mesure physique sous-cycle.
Avec `theta=enfant-parent`, l'asymétrie ajoute `(aller-retour)/2` à theta ; le
résidu après correction idéale a le signe opposé. Le test vérifie ce signe,
sans imposer une loi d'erreur par saut lorsque la dynamique intervient.

Chaque module expose temps logique, correction cumulée, dernier offset estimé
accepté, délai estimé, âge en maintien, lock/holdover/error, estimations
acceptées/rejetées, ticks de correction différée, indices d'époque, sauts,
retours de temps et pertes injectées. L'âge est remis à zéro hors nominal,
conformément au synchroniseur existant.

Le décalage initial est injecté dans le registre de correction. La correction
exportée inclut donc ce décalage ; l'action cumulée du PTP seul s'obtient en
soustrayant `offset_ticks` du JSON initial, dans les mêmes unités. Ce registre
ne mesure pas l'erreur résiduelle par rapport à M1.

Un snapshot capture tous les modules d'une carte au même front. Une page stable
contient ce snapshot et jusqu'à 32 événements. PTP continue pendant la lecture
JTAG ; les snapshots et événements non conservés sont comptés. La collecte fait
deux lectures identiques puis ACK. Ce n'est pas une collecte exhaustive à la
cadence de décimation. Les compteurs 32 bits sont modulo 2^32 : surveiller leur
rebouclage pour les longues campagnes.

L'audit conserve les bits historiques et ajoute voisin 16 bits `[187:172]`,
nœud 16 bits `[203:188]`, extension bit 204. Le décodeur PTP utilise ces champs.
L'export joint run_id et config_id depuis l'en-tête. Les erreurs globales
matérielles restent null/indisponibles ; les snapshots de cartes différentes
ne sont pas simultanés.

```powershell
py -3 scripts/analyze_ptp.py page captures/ptp_page_001/A_page.json --output captures/ptp_page_001/decoded_A
py -3 scripts/analyze_ptp.py simulation reports/ptp_validation/sim_tb_ptp_chain_60.log --output captures/ptp_rtl_analysis --plot
```

Le test de chaîne soustrait directement les sorties logiques à M1 au même
instant du simulateur. Ses séries contiennent douze points nominaux espacés de
1000 ticks, acquisition exclue ; elles ne prouvent aucune stabilité longue durée.

## Pulses et oscilloscope

Chaque marqueur détecte localement le franchissement de `E0+n*period_ticks`
par le temps corrigé. Il ne réémet pas une époque déjà franchie, compte les
échéances sautées et attend une échéance future après un grand saut en avant.
`epoch_index` compte les échéances consommées : pendant le pulse d'indice n,
ce compteur vaut n+1. Un retour du temps ne recrée pas l'ancien pulse.

Le sélecteur termine le pulse engagé, commute à niveau bas et attend le bas
du nouveau marqueur. `obs_valid=0` pendant la transition ; une sélection
invalide conserve l'ancienne et signale `obs_error`. Les chemins fixe et
sélectionné ont le même étage de sortie. Leur routage reste à caractériser.

Vérification effectuée dans le netlist local `reference/Obsidian.net` :

| Sortie | FPGA | Point de test | Net | J4 |
|---|---|---|---|---|
| TEST_REF_M1 | U1/U15 | TP23 ou TP15 | B2_SPIN_SYNC | 26 |
| TEST_OBS | U1/T17 | TP24 ou TP16 | A7_SPIN_SPI_MOSI | 18 |

Chaque paire est un seul net, banque 14, LVCMOS33. Le schéma PDF et
l'implantation PCB n'ont pas été relus ici. Le XDC dédié ajoute ces sorties et
un budget registre→pad de 8 ns, sans changer les broches Aurora ou d'horloge.
Réserver les lignes SPIN à l'observation ; TEST_REF_M1 reste bas sur B/C.
Masse : TP28..TP32 ou TP20..TP22, au plus près. La génération est quantifiée
à 16 ns quelle que soit la précision de l'oscilloscope.

1. Calibrer voies/sondes/câbles avec le même signal. Conserver le délai
   instrumental et le plancher de dispersion ; ne pas retirer l'erreur du
   réseau par deskew. Documenter seuil, sondes, masses, bande passante, cadence
   réelle, routage GPIO et temps mort.
2. CH1 reste sur M1/A. CH2..CH4 observent jusqu'à trois modules, avec au plus
   une sélection par carte dans ce top. Pour le premier essai N=3/K=1,
   observer M2/B et M3/C par rapport à M1/A. Les campagnes avec davantage
   de modules feront l'objet d'une étape distincte.
3. Suspendre l'acquisition pendant une sélection et attendre sa relecture
   valide. Figer la sélection pendant chaque acquisition. Apparier seulement
   les fronts de même n ; conserver le comptage, les manques et les journaux.
   Si le premier indice ou un cycle est ambigu, la paire n'est pas valide.
   Ne pas apparier automatiquement le front suivant après un saut.
4. Désactiver le moyennage des formes d'onde. Exporter
   `node_id,epoch_index,reference_ns,observed_ns`, nœud zéro-basé. Un delta
   positif signifie module en retard ; son signe s'oppose à l'erreur d'horloge
   à instant commun lorsque les débits sont proches et les écarts faibles.
5. Garder les délais bruts et soustraire seulement le délai instrumental connu.
   L'outil calcule moyenne signée, sigma, RMS, min/max, crête-à-crête, maximum
   absolu échantillonné, nombre, durée, trous et fraction `|delta|>20 ns`.
   Un premier franchissement null signifie « seuil non atteint pendant
   l'observation ». Sigma ne comprend pas la moyenne ; RMS la comprend.
6. Séparer acquisition et nominal, conserver les pertes de lock et répéter les
   groupes à configuration identique. Leur acquisition successive ne restitue
   pas les corrélations instantanées des 60 modules. Définir les durées et
   répétitions à partir de la stabilité réellement observée.

```powershell
py -3 scripts/analyze_ptp.py scope captures/scope_paires.csv --instrument-delay-ns 1.5 --output captures/scope_analyse --plot
```

## Validation et construction

```powershell
py -3 tools/validate_ptp.py
py -3 scripts/generate_ptp_scenarios.py --nodes 3 --capacity 1 --seed 12345 --output captures/ptp_scenarios
py -3 scripts/build_ptp.py --capacity 1 --synth-only --output build/ptp_single_node_synth
py -3 scripts/build_ptp.py --capacity 1 --output build/ptp_single_node_final
```

Le build conserve rapports et empreintes dans un dossier neuf. Il reprend
setup/hold/bus-skew, chemins internes non contraints et DRC du build existant.
Les rapports CDC doivent être examinés ; leur génération seule ne les valide
pas. Aucune carte n'est programmée. Seul un build `routed_bitstream` réussi,
avec empreintes BIT/LTX vérifiées, est accepté par les campagnes matérielles.

Les travaux restants comprennent l'équivalence quantitative N=3 avec toutes les
interfaces historiques, les longues campagnes combinant perte de lien/pertes/
jitter et sensibilité de cadence, l'automatisation oscilloscope et l'examen
CDC/DRC/pinout matériel. Le profil K=1 et ses preuves sont consignés dans le
[bilan d'optimisation](ptp_single_node_optimization.md). Aucune capacité « optimale » n'est annoncée sans
recherche routée et marge documentée.
