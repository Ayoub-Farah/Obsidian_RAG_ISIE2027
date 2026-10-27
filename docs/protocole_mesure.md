> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

# Mesurer et interpréter les transferts

Le banc transporte des motifs déterministes, figés avant la libération du cycle. La période vaut 6 250 cycles de 16 ns, soit 100 µs. Le temps de synchronisation initiale est mesuré séparément du transfert nominal.

## Grandeurs

| Grandeur | Signification |
|---|---|
| `t0_raw_ticks` | Compteur brut local au départ programmé du segment |
| `T_useful_us` | Délai local jusqu'à la disponibilité utile de tous les nœuds du segment |
| `T_drained_us` | Délai local jusqu'aux conditions de vidage du segment et de ses files |
| `T_return_us` | Profil dynamique : retour complet du paquet du premier module du segment, motif et CRC valides |
| `first_tx_delay_ns` | Délai du premier transfert TX accepté dans ce segment |
| `Delta_launch_ns` | Écart entre départs de plusieurs cartes ; non déductible des compteurs bruts seuls |
| `fifo_highwater` | Niveau maximal observé des files surveillées |
| `crc_errors_cumulative` | Somme des compteurs CRC des moteurs du segment |

Dans les modes centralisés, le résultat utile d'un nœud esclave est la référence reçue et sa contribution locale ; seul l'ancre rassemble le tableau complet. Dans les modes décentralisés, chaque nœud doit disposer du tableau complet validé. Il faut comparer RAG_C à AGG_C, puis RAG_D à AGG_D2 ; la variante PIPE garde sa propre étiquette.

Le marqueur de disponibilité n'autorise pas à appliquer des octets provisoires : les données sont validées après contrôle du CRC complet. La circulation des trames peut continuer après la disponibilité utile. Le respect de 10 kHz exige donc aussi une fin de protocole avant la période suivante, et pas seulement un petit `T_useful_us`.

La capture physique RX ajoute un étage constant d'un cycle ; ce délai entre dans la calibration des horodatages de voisinage. Le démultiplexage du chemin DATA retient deux mots pour identifier la trame et ne se place pas sur le chemin d'horodatage PTP. La décision d'en-tête RAG respecte un minimum de dix cycles.

Le système ajoute des étages réels de capture, de parsing et d'ordonnancement. Un écart avec une formule nominale doit être expliqué par ces étages ou par les pauses et files ; il ne faut pas déplacer t0 pour ajuster les résultats.

## Journal JTAG

Chaque entrée fait 512 bits ; le journal circulaire possède 256 entrées. Le numéro de séquence permet de remettre en ordre les entrées conservées. La campagne par défaut s'arrête de façon coordonnée après 128 cycles (`G_RUN_CYCLES=128`), puis vide les transferts ; elle tient donc dans le journal. La valeur 0 active le fonctionnement continu. L'extraction lit deux fois le journal après arrêt et refuse une copie changeante. Un journal non initialisé peut contenir des valeurs inconnues ; le décodeur écarte les entrées non hexadécimales ou de séquence nulle.

| Bits inclus | Champ |
|---|---|
| 31:0 | cycle_id |
| 95:32 | t0 brut local |
| 159:96 | T_useful en cycles |
| 223:160 | T_drained en cycles |
| 287:224 | premier TX en cycles si flag 8=0 ; retour du paquet en cycles si flag 8=1 |
| 319:288 | erreurs CRC cumulées |
| 351:320 | flags |
| 367:352 | niveau maximal FIFO |
| 383:368 | premier ID du segment |
| 399:384 | nombre de nœuds du segment |
| 415:400 | N total |
| 447:416 | code mode |
| 479:448 | séquence de journal, non nulle |
| 511:480 | période en cycles |

Un temps 64 bits à tous les bits 1 signifie « indisponible » ; il est exporté vide, sans conversion en une durée gigantesque.

| Bit flags | Signification |
|---|---|
| 0 | erreur globale du segment |
| 1 | overflow de capture physique |
| 2 | dépassement de période |
| 3 | erreur de synchronisation |
| 4 | synchronisation verrouillée |
| 5 | disponibilité utile manquante |
| 6 | perte de lien |
| 7 | overflow du chemin DATA, incluant le filtre de trames |
| 8 | format dynamique : bits 287:224 = temps de retour du paquet ; ce bit ne signale pas une erreur |

Le compteur brut n'est jamais remis à l'heure par la synchronisation. Un reset applicatif explicite peut le réinitialiser : il faut alors commencer un nouveau run et ne pas joindre les deux séries comme une trace continue.

## Métadonnées

Créer un fichier JSON par configuration, par exemple :

```json
{
  "run_id": "RAG_D_N3_001",
  "git_commit": "COMMIT_DU_NOUVEAU_PROJET",
  "bitstream_id": "SHA256_DU_BITSTREAM",
  "D": 6,
  "R": 2,
  "line_rate": 1250000000,
  "virtual_model_id": "E0_physical_N3",
  "sync_interval": 10,
  "measurement_uncertainty_ns": "A_ETABLIR"
}
```

Ces valeurs sont des exemples de structure. Remplacer l'identifiant de commit et de bitstream par ceux de la construction réelle. Une incertitude inconnue reste inconnue ; ne pas saisir zéro pour compléter le tableau.

```bash
python3 scripts/decode_log.py captures/A_log.json captures/B_log.json captures/C_log.json --metadata captures/metadata.json --output captures/three_boards.csv
```

L'outil réunit les lignes et conserve la carte, le cycle, le statut et les erreurs. Il ne transforme pas cette réunion en une mesure globale. Les échecs restent dans le CSV ; annoncer le nombre de cycles invalides avant de calculer les statistiques de latence.

## Mesure globale et calibration

Les bases des compteurs bruts des trois cartes sont distinctes. La synchronisation fournit une correspondance logique, dont l'incertitude doit être évaluée. Le modèle E2 utilise un accumulateur Q48.32 et transporte les temps en Q48.16 ; les événements restent quantifiés à 16 ns. Les essais numériques à ±2 ppm et ceux provoquant une perte de verrouillage à ±50 ppm doivent conserver des étiquettes distinctes.

Pour une mesure globale indépendante, vérifier des broches de sortie accessibles et exporter le départ de l'ancre ainsi que les fins locales des trois segments vers un oscilloscope commun. L'archive n'affecte pas de broche de debug non vérifiée. Mesurer également les décalages de sondes et les délais de sortie.

Pour les segments virtuels, calibrer d'abord le transport physique de trois nœuds. Les 37 cycles initiaux sont un choix nominal ; ils ne doivent pas être ajoutés une seconde fois à un délai déjà inclus dans un wrapper calibré. Distinguer à chaque résultat : calcul nominal, simulation RTL E0/E1/E2 ou mesure physique.

## Critère d'admission

Une configuration est admise seulement si les tableaux attendus sont validés, les erreurs CRC et overflows restent nuls, tous les cycles requis sont présents, le protocole est vidé avant le lancement suivant et l'écart de départ mesuré respecte la cible de campagne. Avec la fenêtre de maintenance 90–100 µs réservée, le budget de données visé est inférieur à 90 µs. La marge doit dépasser l'incertitude de mesure et de calibration.

Le profil configurable et la mesure du module 1 sont decrits dans [configuration_dynamique.md](configuration_dynamique.md). En RAG_D, le paquet retourne est celui des donnees locales du module ; en RAG_C, celui des references de l'ancre.
