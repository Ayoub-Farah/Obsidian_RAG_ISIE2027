# Validation du banc physique CT/RAG

Le BIT/LTX commun a été produit avec Vivado 2025.2 pour XC7A35T-CSG325-2.
Les paramètres de caractérisation et le rôle A/B/C sont des registres VIO.
L'image contient un seul moteur physique, sans nœud virtuel.

| Vérification finale | Résultat |
|---|---|
| Setup WNS | 1.192 ns, aucun endpoint en échec |
| Hold WHS | 0.056 ns, aucun endpoint en échec |
| LUT | 19333 / 20800 |
| Registres | 21545 / 41600 |
| BRAM équivalentes RAMB36 | 32.5 / 50 |
| Bus skew, DRC Error, horloges/chemins internes non contraints | critères de construction passants |
| Scénarios XSim | 17 passants, empreintes de sources vérifiées |
| Tests Python/Tcl simulé | 34 passants |

La construction a réellement exécuté génération des IP Aurora/VIO/ILA,
synthèse, placement, routage et optimisation physique. Les reprises de
checkpoints vérifient les empreintes RTL/XDC ; leur provenance est conservée
dans `build/physical_runtime/execution.json` et `attempts/`.

Les tests couvrent CT → RAG → CT dans une élaboration, tailles paires/impaires
et maximales, contributions, cut-through, H jusqu'à 65535 avec petit payload,
pauses, CRC corrompu dans un emplacement remplacé, configurations divergentes,
configuration/arrêt pendant trafic, arrêt pendant préparation différée,
maintien prolongé, période de 10 ms avec maintenance pendant l'attente,
absence de maintenance pendant DATA et 129 essais paginés.
L'acquittement JTAG maintenu haut ne libère qu'une page. Le contre-exemple avant
correction reste dans `reports/physical_validation/ack_held_before_fix.log`.

Les CSV et courbes de `reports/physical_validation/` proviennent de simulations
RTL et portent cette étiquette. Les modèles de transport numériques ne sont
pas une simulation analogique des transceivers Aurora ni une mesure de fibre.
Les métriques intercartes restent absentes sans calibration externe valide.

Les trois cartes ont été programmées explicitement et la campagne matérielle
a validé 192 essais, soit 576 résumés de cartes.
Voir [le diagnostic et les mesures réelles](validation_materielle.md) et
[les preuves](../reports/hardware_validation/verification.json).
Les mesures intercartes restent absentes sans calibration externe.
Les constructions et les campagnes ne programment pas les cartes automatiquement.

BIT SHA256 : `d844d4fbc15c4702dd8eb6e468fd1ab3128bfc21a0c1e0972d15b96c581835c4`  
LTX SHA256 : `c7061aa49dc0073b3c5d09dab514abaad53ead809e9a51ce3df5ffa1186e61e8`

Voir [le guide](physical_runtime.md), [les tests](../reports/physical_validation/validation.json)
et [les rapports de construction](../build/physical_runtime/execution.json).
