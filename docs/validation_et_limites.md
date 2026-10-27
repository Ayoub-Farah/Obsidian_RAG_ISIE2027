> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

> Mise à jour du 26 octobre 2026 : le profil matériel RAG_D à trois cartes a depuis
> été construit et vérifié avec Vivado 2025.2. Voir
> [la construction locale](construction_vivado_2026-10-26.md). Les états « non exécuté »
> ci-dessous restent la trace de l'archive initiale, sans mesure sur cartes.

# Validation, preuves et limites

Cette livraison est un ensemble de sources, scripts et tests. Les preuves réellement exécutées sont consignées dans les fichiers de `reports/`, avec les commandes, paramètres et statuts. Une assertion passée en simulation portable ne valide pas les transceivers, les fibres, la place disponible ou le timing du FPGA.

## État des exigences

| Élément | État de livraison | Preuve ou réserve |
|---|---|---|
| CRC16/CCITT-FALSE, CRC32/ISO-HDLC et ordre des octets | Implémentés et testés en logiciel/RTL | Vecteurs et `tb_crc` ; CRC32 envoyé en ordre peu significatif d'abord |
| RAG_C, RAG_D | Moteur synthétisable et tests portables | Voir profils exécutés dans le rapport RAG ; relais avant fin RX vérifié |
| AGG_C, AGG_D2, AGG_D2_PIPE | Moteur synthétisable et tests portables | Voir profils exécutés dans le rapport CT ; modes distincts |
| Modification du slot propre et protection de l'intégrité | Implémentées | CRC entrant et sortant distincts ; erreur entrante conservée par empoisonnement du CRC sortant |
| Pauses TX/RX et dernier mot impair | Couvertes par les bancs unitaires | Le transfert TX n'avance que sur handshake ; aucun `RX tready` Aurora n'est ajouté |
| Initialisation voisin ancrée en 0 et ARM/READY | Implémentées, banc de synchronisation portable | L'acquisition et l'armement ne font pas partie de T_useful |
| Maintenance parallèle et corrections différées | Implémentées, essais dédiés | Une fenêtre occupée est signalée ; pas de préemption d'une trame de données |
| Assemblage de trois cartes et segments virtuels | Banc d'intégration fourni | Consulter les modes, tailles et statuts effectivement exécutés dans `reports/` |
| Compteur brut et journal local | Implémentés | Lecture par JTAG et conversion CSV ; les compteurs de cartes différentes ne sont pas soustractibles |
| Arrêt de campagne coordonné | Implémenté | `G_RUN_CYCLES=128` par défaut ; même nombre de périodes après ARM, puis vidage ; 0 sélectionne le continu |
| Deux Aurora duplex avec ressources partagées | Scripts d'intégration fournis | Génération et vérification réelles des ports à faire dans Vivado 2025.2 |
| Brochage Obsidian et speed grade | Repris de sources identifiées | Contraintes et cible `xc7a35tcsg325-2` du dépôt source ; vérifier le composant assemblé |
| Synthèse et placement-routage Vivado du nouveau design | Non exécutés ici | Aucun BIT/LTX de ce nouveau projet n'est annoncé comme validé |
| Qualification des liens et mesures sur trois cartes | Non exécutées ici | Nécessitent les cartes, les fibres et une calibration |
| Capacité N=30/60/180 | Profils à essayer, pas garantie de ressources | Une simulation à N grand ne démontre pas que le design tient dans le XC7A35T |
| Campagnes 400/10 000 périodes et balayages complets | Scripts/bancs à exécuter selon profil | Seules les commandes réellement consignées constituent une preuve |
| Dérives d'horloges E2 | Accumulateur Q48.32 et essais numériques | Maintien testé à ±2 ppm ; perte de verrouillage explicite testée à ±50 ppm ; aucune qualification d'oscillateur matériel |

## Trois niveaux d'essai

| Niveau | Ce qui est représenté | Ce qui ne peut pas être conclu |
|---|---|---|
| E0 | Un nœud logique par carte, trois cartes physiques lors de la campagne matérielle | Le banc GHDL à trois interfaces n'est pas une mesure E0 matérielle |
| E1 | Plusieurs moteurs et liens virtuels indépendants, horloge physique commune à l'intérieur d'une carte | Ce n'est pas N oscillateurs, N CDR ou N chemins optiques physiques |
| E2 | Dérive logique injectée par nœud avec accumulateur Q48.32 ; transport Q48.16, événements quantifiés à 16 ns | Le modèle numérique ne reproduit pas tout le comportement analogique des oscillateurs et CDR |

Les liens virtuels modélisent une cadence de mots, un délai, des files finies, des intervalles de cadrage et des pauses de compensation. Leur délai initial de 37 cycles n'est pas calibré sur Obsidian. Les phases de pause peuvent être indépendantes. Toute comparaison entre modèles ou campagnes conserve l'identité de ce modèle et ses paramètres.

## Limites pratiques

Le journal conserve 256 entrées par carte. La campagne par défaut de 128 cycles s'arrête à une époque commune puis se vide ; son historique tient dans le journal. Une campagne plus longue conserve la fin de sa trace circulaire, pas 10 000 résumés simultanés en BRAM. Des compteurs ou des captures de simulation permettent les essais longs ; il ne faut pas déclarer un fichier complet de 10 000 mesures matérielles après une seule lecture du journal.

L'arrêt normal est coordonné par `G_RUN_CYCLES`, commun aux images des trois cartes et sélectionnable par le septième argument du build ou `build_campaign.py --run-cycles`. L'arrêt JTAG manuel reste local pour les campagnes continues : il peut perturber les derniers cycles et ne remplace pas cet arrêt coordonné. Les scripts de dump vérifient la stabilité du journal sans effacer les échecs.

Le contrôle de largeur, de longueur et de population refuse une configuration non représentable. La segmentation des très grandes trames est hors V1. Une FIFO trop petite doit produire une erreur ou un échec explicite ; augmenter MAX_FRAME_BYTES seul n'augmente pas automatiquement la capacité des autres files. Le moteur CT répartit ses 2 048 mots par défaut entre deux buffers ping-pong : la capacité d'une trame est donc 2 048 octets, en-tête et CRC compris.

La capture physique RX ajoute un cycle constant, inclus dans la calibration de voisinage. Le démultiplexage DATA retient deux mots et ne décale pas les événements PTP. Le relais RAG impose au moins dix cycles pour la décision d'en-tête.

La fréquence utilisateur de 62,5 MHz donne une quantification de 16 ns pour les événements physiques. Le modèle E2 conserve un accumulateur Q48.32 et transporte les temps en Q48.16 ; cela permet le calcul des corrections sans apporter une résolution physique sous la période utilisateur. Les seuils de 32 ns pour l'acquisition et 64 ns pour la correction/dispersion sont des cibles d'essai, pas une preuve de précision obtenue sur les cartes.

Les modes AGG utilisent dans cette intégration le même environnement de synchronisation que RAG afin de faciliter une campagne à époque commune. Pour une comparaison incluant le coût total du mécanisme, distinguer ce profil d'une agrégation à initiateur sans synchronisation de tous les départs. Le temps de transfert mesuré après t0 ne doit pas être confondu avec le temps d'initialisation.

## Traçabilité des entrées

Le matériel et les paramètres Aurora proviennent de la branche `SyncRAG_Estimator` du dépôt `Ayoub-Farah/Obsidian_Aurora_loopback_test-`, commit `e7d486a22b16bc1e52630341f7cdd1b560a97ce1`. Les anciennes sorties de build, les BIT et les résultats du projet d'origine ne sont pas des preuves du nouveau design.

Le rapport `Rapport_RAG_CT_specification_VHDL.md` et la consigne `CONSIGNE_IA_VHDL.md` sont les entrées fonctionnelles fournies. Les fichiers auxiliaires JSON et le modèle nominal cités dans ces textes n'étaient pas joints. Les paramètres et vecteurs présents dans cette archive sont donc explicitement recréés ; ils ne prétendent pas être ces fichiers originaux.

Les erreurs CRC disposent de compteurs séparés. Les erreurs d’en-tête, de doublon, de cycle et de perte de lien sont conservées comme états d’échec ; cette version ne fournit pas encore tous les compteurs détaillés ni tous les histogrammes listés dans la spécification. Le signal interne `channel_resets` n’est pas exporté et ne doit pas être utilisé comme nombre de réinitialisations matérielles.
