# Décalage et jitter PTP selon la distance à M1

[Rapport PDF](Rapport_PTP_distance_modele.pdf) : conditions d'essai, résultats, courbes, dérivation théorique, ajustements et utilisation en simulation.

La distance est le nombre de sauts du chemin de référence **M1 → M2 → … → M9**, et non la distance minimale autour de l'anneau physique. Le nombre total de moteurs reste **N=9**. Le rapport réutilise les données vérifiées de la [campagne du 29 octobre 2026](../ptp_scope_20261029T160956Z/README.md), sans nouvelle acquisition ni modification des captures.

Pour le module Mi, on pose :

$$h=i-1,\qquad p=\lfloor h/3\rfloor,\qquad v=h-p.$$

h compte les sauts logiques, p les passages entre FPGA et v les liens internes. Le retour physique C→A sert notamment à ARM ; M9 se synchronise sur M8.

![Mesures selon la distance](figures/distance_offset_jitter.png)

Le décalage est OBS moins REF ; un nombre négatif est une impulsion en avance. La moyenne ci-dessous retire le biais instrumental commun de −0,29667 ns. Chaque module fournit 100 captures neuves ; les 100 captures de calibration et les trois excursions ciblées restent séparées.

| Module | h | p | Moyenne corrigée (ns) | Écart-type (ns) |
|---|---:|---:|---:|---:|
| M1 | 0 | 0 | +0,007 | 0,036 |
| M2 | 1 | 0 | +0,002 | 0,037 |
| M3 | 2 | 0 | −0,002 | 0,038 |
| M4 | 3 | 1 | −22,042 | 4,489 |
| M5 | 4 | 1 | −22,891 | 5,227 |
| M6 | 5 | 1 | −24,510 | 4,564 |
| M7 | 6 | 2 | −8,837 | 6,188 |
| M8 | 7 | 2 | −10,277 | 6,191 |
| M9 | 8 | 2 | −9,894 | 5,756 |

Le modèle descriptif de la moyenne est :

$$\mu(h)\simeq 0{,}002319-23{,}150096\,\mathbf1_{h\ge3}
+13{,}478333\,\mathbf1_{h\ge6}\quad\mathrm{ns}.$$

Les deux frontières ont des biais effectifs de signes opposés. La moyenne ne suit donc pas une loi universelle croissante avec h. L'erreur RMS de cet ajustement vaut 0,688 ns, contre 8,684 ns pour une droite en h.

La loi centrale de dispersion proposée pour ce profil est :

$$\sigma(h)\simeq\sqrt{0{,}035885^2+19{,}185273\,p(h)}
\quad\mathrm{ns}.$$

Elle correspond à un incrément effectif **σ physique = 4,38010 ns** par frontière. Son erreur RMS sur les neuf écarts-types est de 0,326 ns. Elle suppose des incréments indépendants ; la contribution virtuelle est fixée à zéro par parcimonie dans le régime sans dérive virtuelle, sans constituer une précision intrinsèque nulle mesurée.

Le rapport dérive aussi la loi générale :

$$\Delta_h=b+\sum_{k=1}^h a_k+\sum_{k=1}^h\xi_k+J_h,$$

dont la variance conserve les covariances entre sauts. Une hypothèse de quatre erreurs effectives indépendantes et uniformes conduit à q/√12 = 4,619 ns pour q=16 ns, soit le même ordre de grandeur. Les horodatages RTL sont cependant en Q48.16 : 16 ns est la grille physique des événements, pas leur LSB numérique.

Les excursions brutes **−67,979 / +57,156 / −58,656 ns** sont confirmées sur M7. Leur probabilité n'est pas identifiée. Le modèle central et ses extrapolations ne les bornent pas ; elles ne sont pas ajoutées aux 900 échantillons d'ajustement.

Les [scénarios d'extrapolation](figures/extrapolation_scenarios.png) distinguent une horloge par module, des groupes de trois avec ajout de FPGA et trois FPGA fixes. Ces scénarios ne sont pas des mesures à d'autres N. Les biais des nouvelles frontières physiques et la faisabilité de capacités supérieures restent à spécifier.

Les [paramètres JSON](model_parameters.json) sont utilisables avec [le modèle Python](../../tools/ptp_distance_model.py) :

    from tools.ptp_distance_model import load_parameters, predict, sample_chain
    p = load_parameters("reports/ptp_distance_model_20261029/model_parameters.json")
    moments = predict(8, 2, p, include_measurement=False)
    phases_ns = sample_chain([0,0,0,1,1,1,2,2,2], 10000, p, seed=20261029)

Le simulateur conserve les incréments communs aux préfixes et distingue les domaines d'horloge. Sa distribution uniforme et ses lignes indépendantes sont des hypothèses de modèle, non une dynamique temporelle identifiée. Pour une frontière inconnue, aucune moyenne n'est inventée : fournir ses biais ou choisir explicitement un scénario de moyenne nulle. Ne pas cumuler ce bruit avec une simulation RTL qui reproduit déjà les mêmes effets.

Reproduction depuis la racine du dépôt :

    py -3 scripts/fit_ptp_distance_model.py --source reports/ptp_scope_20261029T160956Z --output reports/ptp_distance_model_20261029
    py -3 scripts/build_ptp_distance_report.py
    py -3 -m unittest sim.test_ptp_distance_model

Les calculs utilisent NumPy, SciPy et Matplotlib. Pour le PDF : installer reportlab et pypdf dans build/ptp_report_deps.

Les [résultats d'ajustement](fit_results.json), les [mesures par distance](measurements.csv) et l'[audit des équations RTL](theory_audit.json) séparent les valeurs mesurées, les coefficients ajustés et les hypothèses. Le bootstrap fourni est conditionnel à l'hypothèse iid ; il ne couvre ni nouveau démarrage, ni nouvelles cartes, ni queues rares.
