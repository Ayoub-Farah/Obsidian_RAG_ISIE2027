# Résultats et preuves

Le [rapport final](final_report.md), disponible en [PDF](final_report.pdf), réunit les équations de transmission CT/RAG et la caractérisation de synchronisation selon les sauts. Il distingue les projections analytiques, les simulations et les mesures physiques.

Les [mesures de synchronisation](data/synchronization.csv) et les [paramètres des modèles](data/model_parameters.json) restent directement lisibles. Le dernier essai couvre neuf modules sur trois FPGA, avec 4 200 captures valides et un tirage fixe de dérives logiques ±4 ppm. Les mesures sont brutes, sans calibration des sondes ; un contrôle avant M4 signale un déverrouillage agrégé sur B.

## Archives communes

Chaque ZIP contient les fichiers originaux et un `MANIFEST.json` avec taille et SHA-256 de chaque membre. Les chemins internes conservent leur ancienne position depuis la racine du dépôt. Le [catalogue](data/catalog.json) donne les empreintes des archives et permet aux outils de retrouver automatiquement les preuves.

| Archive | Contenu et statut |
|---|---|
| [scope_20261030_run11.zip](data/scope_20261030_run11.zip) | Campagne complète ±4 ppm : neuf modules, 4 200 captures, événement d'état B, configuration et provenance |
| [scope_20261030_run10.zip](data/scope_20261030_run10.zip) | Campagne interrompue par reset/déconnexion ; calibration et données conservées séparément |
| [scope_20261029.zip](data/scope_20261029.zip) | Référence historique sans dérive logique injectée, calibration propre et excursions conditionnelles |
| [hardware.zip](data/hardware.zip) | Campagne CT/RAG sur trois cartes, 192 essais et 576 résumés ; manifestes de livraison du 27 octobre |
| [validation.zip](data/validation.zip) | Simulations, validation physique, capacité PTP K=1..3, préparation ±4 ppm et journaux associés |
| [models_history.zip](data/models_history.zip) | Anciens rapports de transmission et modèle PTP du 29 octobre, conservés comme historique |

Les essais exclus et incidents restent archivés : ils expliquent les limites des résultats. Les campagnes ne sont pas mélangées. Les anciens manifestes `ARTIFACT_MANIFEST.json` et `SHA256SUMS` décrivent la livraison historique et figurent dans `hardware.zip` ; ils ne sont pas présentés comme empreintes des sources actuelles.

## Vérifier et reproduire

```powershell
py -3 scripts/report_archive.py verify reports/data/scope_20261030_run11.zip
py -3 scripts/report_archive.py extract reports/data/scope_20261030_run11.zip --output build/report_replay
py -3 scripts/report_ptp_scope_distance.py build/report_replay/reports/ptp_scope_4ppm_dsox3014t_run11_20261030 --config build/report_replay/config/ptp_emulation_9_uniform_4ppm_run11.json --allow-uncalibrated
py -3 scripts/build_final_report.py
```

L'analyse est hors ligne : aucune carte n'est programmée et aucun instrument n'est ouvert. L'extraction et la réanalyse écrivent dans `build/`, ignoré par Git. Les générateurs de résultats produisent aussi leurs sorties dans `build/validation/` ou `build/report_outputs/` ; seuls les résultats publiés sont regroupés ici.

## Rangement du dépôt

Les sources, scripts maintenus, configurations, contraintes et tests restent dans leurs dossiers habituels. Les BIT/LTX existants sont conservés. Les caches Vivado/simulation explicitement approuvés ont été supprimés. Le [bilan du rangement](data/cleanup_summary.json) conserve les volumes, les opérations et les vérifications effectuées.
