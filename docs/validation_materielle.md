> Rapports consolidés : [rapport final](../reports/README.md) et [index des archives](../reports/README.md). Les anciens chemins `reports/...` cités ci-dessous sont conservés dans les archives ; les nouvelles sorties sont générées sous `build/`.

# Diagnostic et validation matérielle — 27 octobre 2026

Image commune corrigée : SHA256
`d844d4fbc15c4702dd8eb6e468fd1ab3128bfc21a0c1e0972d15b96c581835c4`.
Vivado 2025.2 : setup **+1,188 ns**, hold **+0,055 ns**, contrôles de timing,
bus skew et DRC acceptés. Les interfaces Aurora et contraintes Obsidian sont
conservées. Les rôles sont A=OBS001A, B=OBS003A, C=OBS002A.

## Corrections

Le premier démarrage avait placé A et B en `FAULTED` avant injection. Le statut
de cette image ne mémorise pas la cause détaillée : le transitoire précis n'a
pas été capturé. Les parseurs peuvent conserver un défaut reçu pendant le
chargement séquentiel des voisins. La procédure corrigée charge les trois
cartes, maintient **tous** les resets applicatifs, efface les commandes puis
relâche les resets. Le démarrage de la nouvelle image a réussi ainsi, sans
récupération intermédiaire. Cette initialisation remet les origines brutes à
zéro ; aucun changement de mode ou de paramètres ne l'appelle.

Le « blocage JTAG » était une lecture lente sans indication d'avancement.
Résoudre les sondes pour chaque mot coûtait environ 100 ms par lecture. Le
collecteur lie maintenant les sondes adresse/donnée une fois par carte et
affiche la progression des deux passes. Les pages restent figées jusqu'à
vérification de leur égalité, puis acquittées B/C/A.

Vivado expose aussi le port VIO des erreurs Aurora comme trois sous-sondes.
Leur lecture assemble les bits d'après `PROBE_PORT_BITS` et
`PROBE_PORT_BIT_COUNT`, avec rejet des chevauchements et des trous. L'export
ILA utilise l'API de lecture disponible dans cette installation, sans la
propriété `STATUS.CAPTURE_STATE` absente et sans déclenchement artificiel.

Enfin, la campagne a révélé un cycle de trop au démarrage du relais CT.
Avec P=3, le premier TX de B/C coïncidait avec le dernier RX. La régression
ajoutée aux frontières physiques échoue sur l'ancien RTL et passe après
correction. Le moteur prend maintenant le TX libre sur le front de validation
de l'en-tête, sans attendre de relire `desc.ready` au cycle suivant. Les
contrôles du CRC entrant et la rétention du CRC sortant restent indépendants.
Sur les deux essais matériels P=3, S=1, B et C commencent désormais **16 ns
avant** leur dernier RX, sans pause TX. Les contre-exemples sont conservés dans
[la référence avant correction](../reference/hardware_baseline/README.md).

## Preuves déjà obtenues sur l'image corrigée

Les 17 scénarios XSim et les 34 tests Python/Tcl passent. La séquence matérielle
CT → RAG → CT a validé 48 essais, soit 144 résumés de cartes, sans erreur CRC,
erreur de motif ou défaut. Le mode et les paramètres ont changé par registres,
sans reset ni rechargement entre les configurations.

| Mode | P | S | H | Essais | RTT CT sur A |
|---|---:|---:|---:|---:|---:|
| CT | 257 | 7 | 2 | 16 | 4,784 µs |
| RAG | 257 | 7 | 4 | 16 | sans objet |
| CT | 4096 | 1365 | 2 | 16 | 35,472 à 35,600 µs |

Les ILA confirment six trames de 293 octets au premier essai CT : les octets de
chaque réception/émission sont identiques à la référence attendue, CRC compris.
Les emplacements A/B/C sont vérifiés à chaque étape et la longueur reste
constante. Le RTT ILA vaut **299 cycles = 4,784 µs**, exactement comme les
événements du journal. B et C transmettent avant leur dernier RX.

Les durées en µs utilisent le tick nominal de 16 ns. Aucun compteur brut d'une
carte n'est directement soustrait de celui d'une autre. Sans calibration
directionnelle externe, les durées intercartes et écarts de départ restent
vides. Le champ RAG local ne s'applique que lorsque le paquet revient à son
origine physique. La propagation optique seule n'est pas identifiée.

Les erreurs de CRC injectées et leur non-guérison sont testées en simulation ;
aucune injection optique d'erreur n'est revendiquée sur le banc réel.

Les huit configurations de limites ont également validé 15 essais, soit 45
résumés, avec H=1, 2, 3, 4, 29 et 65535, P=1 à 4096 selon le mode, et S=1 à
1365. Les périodes de 1,024 µs et 10 ms ont exercé les échéances sautées et la
maintenance entre essais. À H=65535, chaque carte compte exactement 65535 RX
et 65534 relais ; les durées locales du retour à l'origine vont de
60,000752 à 60,001696 ms. La saturation de trace est comptée séparément.

Le test de pagination à 129 essais passe : chaque carte fournit une page de
128 résumés puis une page d'un résumé, soit 387 résumés valides. Les compteurs
bruts ne sont pas remis à zéro. Les pauses sont exportées de la métadonnée de
scellement d'une page au départ de l'essai suivant, sur le même compteur.
Cet intervalle d'environ 508,914 s inclut collecte, acquittement,
synchronisation et réarmement ; il ne représente pas uniquement le temps de
lecture JTAG. Les échéances sautées pendant cette pause restent explicites.

## Bilan et fichiers

La campagne finale a validé **192 essais et 576 résumés de cartes**, avec zéro
résumé invalide. Toutes les configurations utilisent la même image corrigée,
sans reset ni rechargement après l'initialisation. Les cartes sont laissées au
repos en CT, P=257, S=7, répétitions=129, période=100 µs, synchronisation active.
Le dernier relevé donne `links=3`, `aurora_errors=0` et aucun défaut sur A/B/C.

- [Vérification et empreintes](../reports/README.md)
- [Résultats CSV](../reports/README.md)
- [Pauses entre pages](../reports/README.md)
- [Durées observées](../reports/README.md)
- [Modèle extrait des observations](../reports/README.md)
- [Vérification indépendante ILA](../reports/README.md)

Les configurations reproductibles se trouvent dans `config/hardware_validation/`.
La programmation est une commande explicite, séparée des campagnes :

```powershell
py -3 scripts/program_physical.py --targets OBS001A OBS003A OBS002A --output captures/nouveau/programming
py -3 scripts/run_physical_campaign.py sweep --config config/hardware_validation/runtime_sequence.json --output captures/nouveau/runtime
py -3 scripts/run_physical_campaign.py sweep --config config/hardware_validation/edge_sequence.json --output captures/nouveau/edges
py -3 scripts/run_physical_campaign.py run --config config/hardware_validation/paged_config.json --output captures/nouveau/paged
```

La programmation charge les SRAM FPGA ; la mémoire flash non volatile n'a pas
été écrite. Les scripts de construction et de campagne ne programment pas les
cartes automatiquement.
