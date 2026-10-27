# Contrat du banc physique CT/RAG

Ce document décrit le nouveau top `obsidian_physical_top`. Les anciens profils
RAG_C/RAG_D à populations virtuelles et leurs BIT restent des archives. Ils ne
constituent pas une validation de cette image. Trois cartes physiques sont
toujours présentes, avec un moteur par carte et deux liens voisins duplex.

## Registres et commandes

Fréquence utilisateur : 62,5 MHz ; un tick nominal vaut 16 ns. Aurora reste à
1,25 Gbit/s, 16 bits, 8B/10B, compensation d'horloge active, sans RX ready inventé.
Les registres de configuration sont shadow puis actifs. Le mot VIO de 160 bits
contient cinq mots de 32 bits, du poids faible vers le poids fort :

| Mot | Contenu |
|---|---|
| 0 | génération de configuration, uint32 |
| 1 | P sur 31:16, S sur 15:0 |
| 2 | zéro sur 31:24, mode sur 23:16, H sur 15:0 |
| 3 | répétitions uint32 ; 0 signifie continu |
| 4 | période uint32, en ticks de 16 ns |

CT=1, RAG=2. P=1..4096, S=1..1365, H=1..65535 et période=1..2^32-1.
En CT, P>=3S ; les trois emplacements sont aux offsets 0, S et 2S. En RAG, S
reste lisible mais n'affecte pas le payload. Le défaut est CT, P=4096, S=6, H=2,
128 essais, 6250 ticks (100 µs). `target_modules=N` se traduit seulement par
H=N-1, avec N=2..65536. Cela ne simule pas N oscillateurs ou N injecteurs.

| VIO out | Usage |
|---|---|
| 0 | reset applicatif explicite ; commence une nouvelle origine brute |
| 1 | démarrer, front montant, sur A |
| 2 | arrêter, front montant ; termine l'essai déjà préparé ou engagé |
| 3 | adresse journal, 13 bits |
| 4 | shadow config, 160 bits |
| 5 | rôle : A=0, B=1, C=2, 3=non configuré |
| 6 | configurer, front montant |
| 7 | acquitter une page figée, front montant |

| VIO in | Usage |
|---|---|
| 0 | statut 256 bits |
| 1 | mot journal 64 bits, lecture BRAM synchrone |
| 2 | config active 160 bits |
| 3 | compteur brut physique 64 bits |
| 4 | deux channel_up |
| 5 | hard/soft/frame errors Aurora |
| 6 | horloge logique Q48.16 |
| 7 | pertes calibration[63:32], pertes trace[31:0] |

Statut : état en 7:0 ; configuré=8, config en attente=9, config rejetée=10,
essai engagé=11, défaut persistant=12, campagne demandée=13, sync en marche=14,
verrouillée=15, occupée=16, maintien dépassé=17, page figée=18, maintenance
autorisée=19, moteur vidé=20, défaut moteur=21, erreur globale essai=22,
rôle=24:23, bitmap retraits=27:25. Génération active=63:32, run=95:64,
essais terminés=127:96, essai courant=159:128, échéances sautées=223:160,
nombre de résumés=231:224, signature `504803`=255:232.

Le rôle est fixé au premier configure et ne change pas pendant cette session.
Un reset explicite permet une nouvelle affectation ; le changement de mode ou
de paramètres ne demande aucun reset, aucune compilation et aucun rechargement.

## Trames, cut-through et erreurs

L'en-tête DATA fait 32 octets, big-endian sauf CRC32 final little-endian :

| Octets | Champ |
|---|---|
| 0..3 | C3 5A, version 02, mode |
| 4..7 / 8..11 / 12..15 | génération / run / essai |
| 16..17 | origine physique / zéro |
| 18..21 | P / S, uint16 |
| 22..27 | H initial / sauts restants / sauts déjà effectués, uint16 |
| 28..29 / 30..31 | zéro / CRC16-CCITT-FALSE sur les 30 premiers octets |

Le payload suit, puis CRC32/IEEE réfléchi de l'en-tête et du payload. Longueur
maximale : 4132 octets, 2066 mots de 16 bits. Les motifs sont déterministes et
dépendent de la carte, de l'essai et de l'offset. Les vérifications sont en flux.

En CT, A préremplit son emplacement, B/C sont vides ; chaque relais ne change
que son emplacement et le CRC final. A contrôle les trois contributions et le
reste du payload. Les champs de sauts CT restent inchangés ; les événements
locaux identifient néanmoins les trois liens physiques du parcours.

En RAG, l'injection a `remaining=H`, `hop=0`. Toute réception physique consomme
un saut : retrait si remaining=1, sinon relais avec remaining-1 et hop+1.
H=1 termine au voisin, H=2 au suivant, H=3 à l'origine, H>3 effectue plusieurs
tours réels. Le CRC16 de l'en-tête modifié est recalculé en flux.

Le CRC entrant est calculé sur les octets originaux, indépendamment du CRC
sortant. Aucun octet du CRC sortant n'est proposé avant le verdict entrant,
y compris lorsqu'il partage un mot avec un payload impair. Une entrée corrompue
produit `CRC_sortant_calculé XOR 1` et reste invalide aux relais suivants.
Un en-tête invalide est retiré avant relais et provoque un défaut persistant.

Une FIFO BRAM synchrone de 8192 mots et quatre descripteurs capturent le RX sans
contre-pression. Trois trames maximales occupent 6198 mots. La sortie garde son
propriétaire jusqu'au dernier mot accepté, même sous pause ou attente du CRC.
Le début de relais dépend de l'en-tête validé et de la disponibilité TX, jamais
de la réception complète. La contention RAG peut néanmoins retarder ce début.

## Coordination et maintien de la synchronisation

Le contrôle utilise des trames séparées de 64 octets, magic D3 A7, version 1,
type, source, séquence, timestamp, payload et CRC32. Aucun multiplexage ne coupe
une trame. Les rapports de contrôle peuvent attendre derrière une trame DATA ;
la maintenance de synchronisation reste interdite pendant l'essai engagé.

1. Stager les trois shadow configs et les rôles distincts. Le token PREPARE
   compare les cinq mots et accumule les accords. Sans trois accords, aucun
   COMMIT n'est émis et les registres actifs restent inchangés.
2. Suspendre les nouvelles injections. Un essai engage exactement un paquet CT
   ou trois paquets RAG. A attend les retraits complets distincts, puis un token
   DRAIN acquitté après vidage des trois moteurs. Un idle local ne suffit pas.
3. Sceller/collecter l'ancienne page avant changement de config. COMMIT circule
   hors trafic ; aucun départ n'est permis pendant cette transaction.
4. Conserver l'acquisition PTP séquentielle A-B puis B-C. Obtenir des accords de
   disponibilité avec correspondances fraîches, fermer la maintenance par un
   second token et attendre la fin des échanges déjà engagés.
5. Armer une époque future commune par ARM puis GO. Les départs DATA réels sont
   horodatés à leurs handshakes ; une libération commune ne garantit pas trois
   premiers mots TX simultanés lorsque les sorties attendent.

La grille périodique appartient à A. Les échéances indisponibles sont sautées,
pas rejouées en rafale. La préparation et la collecte peuvent aussi faire
sauter des échéances. Les répétitions comptent uniquement les essais lancés.
Une période acceptée dans les bornes n'est pas une garantie de débit soutenu.
Pour les périodes longues, la maintenance reste ouverte pendant l'attente ;
la préparation finale commence près de l'échéance (fenêtre nominale de
4096 ticks, soit 65,536 µs). Une préparation retardée qui manque cette fenêtre
rouvre la maintenance avant de viser une autre échéance de la même grille.

La maintenance nominale est demandée toutes les 10 périodes de 100 µs du
synchroniseur, indépendamment de la période de caractérisation. La validité de
maintien devient insuffisante après 2 ms sans échange accepté. Un long essai
continue jusqu'au retrait ; le maintien est enregistré et la fraîcheur est
rétablie avant le prochain départ. À grand H, des milliers d'échéances peuvent
être sautées. Les timeouts de contrôle ou pertes de lien bloquent tout nouveau
départ ; ils ne tronquent pas une trame pour déclarer artificiellement le vidage.

## Journal et CSV

La RAM journal fait 8192 mots de 64 bits, à lecture synchrone :

| Région | Contenu |
|---|---|
| 0..4095 | 128 résumés de 32 mots, jamais écrasés |
| 4096..6143 | 1024 événements TX/RX de 2 mots |
| 6144..7167 | 256 événements de synchronisation de 4 mots |
| 7168..7183 | signature, page, compteurs, pertes, config, échéances, timestamp |
| reste | réservé, non interprété |

La trace conserve les premiers événements ; sa saturation incrémente un
compteur, sans bloquer les données ou perdre le résumé. H=65535 implique trop
d'événements pour promettre une trace exhaustive. La capacité de trace est
distincte de la capacité H. Les lectures doubles incluent uniquement les
régions utilisées ; le JSON remplit le stockage inutilisé de zéros et le signale.

Après 128 essais ou une fin de campagne, les trois pages sont figées après
vidage. La maintenance peut continuer sans modifier la page. La collecte lit
deux fois, vérifie stabilité, signature, rôle et compteurs, puis acquitte B/C/A.
La campagne reprend sur une époque commune si des répétitions restent à faire.

Le résumé contient config, run/essai, événements bruts d'injection/retrait,
compteurs, temps de résidence RX-premier vers TX-premier, attentes d'injection,
pauses TX après premier mot, erreurs et niveaux de FIFO. Le RTT CT est
exactement `A dernier RX brut - A premier TX accepté brut`, sans attendre le
verdict de parsing ; les erreurs restent dans le même enregistrement.

`decode_physical.py` conserve les échecs. Les graphiques excluent les essais
invalides. Les CSV ne confondent pas trace perdue, faute d'intégrité et invalidité
de calibration. Les anciennes archives restent décodables avec `decode_log.py`.

## Correspondance temporelle et identification

Les événements PTP exportent séparément raw, logical, direction, voisin et
séquence ; un marqueur 0x15 identifie un échange accepté. Le traitement hors FPGA
assemble t1/t2/t3/t4, ajuste la fréquence et l'origine vers A par intervalles
valides, et conserve résidus, quantification et incertitude de calibration.
Il n'extrapole pas hors de l'intervalle couvert par défaut.

Les échanges bidirectionnels seuls ne séparent pas asymétrie de trajet et
décalage d'horloge. Remplir `directional_calibration.template.json` avec une
calibration externe et sa provenance pour obtenir le statut `calibrated`.
Sans cela, l'hypothèse de symétrie est étiquetée non calibrée et les durées
intercartes ainsi que les écarts de départ restent vides. Aucune valeur n'est
inventée pour compléter les courbes.

Le script de campagne collecte une page de maintenance après le run pour
encadrer les événements mesurés. Les pauses de lecture JTAG font partie des
métadonnées ; elles ne sont pas présentées comme un maintien de cadence 10 kHz.

L'identification utilise la sérialisation observée et les pauses, le délai local
RX-premier vers TX-premier, puis les délais de liens calibrés. Le délai de lien
inclut Aurora, PHY et fibre. Isoler la fibre demande une calibration indépendante
ou plusieurs longueurs de fibre connues. En cut-through, additionner toutes les
sérialisations de tous les sauts serait incorrect : les transmissions se
recouvrent. Les paramètres absents restent non identifiés.

Exemple après une campagne, avec une calibration externe renseignée :

```powershell
py -3 scripts/analyze_physical.py calibrate captures/run_001/sync.json --bias-calibration captures/directional_calibration.json --output captures/run_001/time_map.json
$pages = Get-ChildItem captures/run_001 -Recurse -Filter '*_page_*.json' | ForEach-Object FullName
py -3 scripts/decode_physical.py @pages --calibration captures/run_001/time_map.json --output captures/run_001/calibrated.csv
py -3 scripts/analyze_physical.py fit-model captures/run_001/calibrated.csv --events captures/run_001/calibrated.events.json --calibration captures/run_001/time_map.json --output captures/run_001/model.json
```
