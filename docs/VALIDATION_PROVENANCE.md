> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

# Versions des preuves de validation

Les résultats portent sur des simulations d'interfaces numériques et du RTL
portable. Ils ne sont ni des mesures optiques, ni des résultats Vivado.

| Rapport | Essais réellement exécutés | Version de code |
|---|---|---|
| `reports/portable_final.json` | 15 tests Python ; 57 scénarios RTL, CRC, liens, codec, RAG, agrégation, synchronisation et dérive logique | SHA256 conservés dans le rapport ; avant les deux corrections ciblées ci-dessous |
| `reports/integration_matrix.json` et `.csv` | Cinq modes, N=3 et N=6, douze périodes chacun ; 360 résumés de segments ; fenêtre de maintenance franchie | Chaque cas possède un `validation_run_id` et ses SHA256 ; les deux cas RAG_C ont été remplacés après correction |
| `reports/rag_corrected_final.json` | 24 scénarios RTL : 22 régressions RAG, dont le nouveau test de disponibilité centralisée, et deux intégrations RAG_C | Après correction du résultat utile RAG_C ; sources inchangées pendant cette campagne |
| `reports/start_edge_final.json` | START maintenu à 1, redémarrage explicite, intégration RAG_D à trois nœuds sur trois périodes | Dernier code ; SHA256 des sources exécutées inchangés pendant les essais |

La première correction concerne la disponibilité utile au maître RAG_C. Sa
propre référence est déjà disponible localement : il doit pouvoir annoncer son
tableau complet avant le retour de la trame REFERENCES. Le retour reste requis
pour la fin de protocole. Le test `tb_rag_c_useful` impose précisément cet ordre.
Les disponibilités utiles globales corrigées sont 1,680 µs à N=3 et 4,080 µs à
N=6 dans ce banc ; les fins de protocole correspondantes restent 2,640 et
5,040 µs. Ces valeurs sont des maxima observés sur douze périodes du modèle
numérique commun, pas des garanties matérielles.

La deuxième correction concerne uniquement la commande de démarrage. Un START
JTAG/VIO maintenu à 1 ne doit pas relancer automatiquement une campagne bornée
après son arrêt. Le contrôleur accepte désormais son front montant. Les essais
ciblés vérifient l'arrêt avec START maintenu, le redémarrage explicite et une
intégration sur le dernier code. La matrice complète de dix profils n'a pas été
réexécutée après cette correction de commande ; ses versions exactes restent
identifiées dans le rapport.

Le fichier `reports/integration_summary.csv` calcule les résultats globaux des
trois segments à partir de la base temporelle commune de la simulation. Il se
régénère avec :

```bash
python3 tools/summarize_simulation.py reports/integration_matrix.csv --output reports/integration_summary.csv
```

Les horodatages bruts de trois cartes physiques ne disposent pas de cette base
commune par construction. Le même calcul exige alors une correspondance
temporelle calibrée ou une acquisition commune. Le script de synthèse refuse
les CSV qui ne déclarent pas une simulation à horloge commune.

Les anciens résultats RAG_C figurent dans `reports/history/` pour la traçabilité
et sont remplacés par les résultats corrigés dans le CSV principal. Les
campagnes de 400 et 10 000 périodes, la qualification matérielle, la synthèse
Vivado et l'implantation n'ont pas été exécutées dans ces validations.
