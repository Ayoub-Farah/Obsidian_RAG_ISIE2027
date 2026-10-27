> Document historique. Le nouveau banc physique CT/RAG est décrit dans [physical_runtime.md](physical_runtime.md).

# Synchronisation voisin et ordonnanceur

`sync_system` est une logique portable VHDL-2008. Chaque nœud logique a une instance et deux canaux de gestion indépendants (`management_codec`). Le nœud 0 est l'ancre et répond uniquement au signal `start_i` de campagne. Les autres nœuds écoutent leur parent sans commande JTAG locale.

Les échanges utilisent les trames de la spécification : SYNC, FOLLOW_UP, DELAY_REQ, DELAY_RESP, LOCK_ACK, READY et ARM. La capture temporelle porte sur le premier mot TX accepté ou RX valide. Les CRC16/CRC32, la longueur, le type, le voisin émetteur et la configuration ARM sont contrôlés. Le format de transport est Q48.16 en cycles utilisateur nominaux ; aucune précision sous le cycle physique n'est revendiquée.

L'initialisation progresse de 0 vers N-1. Après huit estimations successives dans ±2 cycles, un enfant devient parent. L'estimation de délai est comparée à la médiane des huit valeurs précédentes (rejet au-delà de quatre cycles). READY remonte avec un compteur de suffixe vérifié. ARM porte l'époque future commune et fait un tour ; son retour est exigé par l'ancre. La période par défaut est 6250 cycles de 16 ns, soit 100 µs. La fenêtre de maintenance par défaut occupe les 625 derniers cycles de la dixième période ; tous les couples peuvent fonctionner simultanément.

La correspondance logique reste stable pendant les transactions parent et enfant concurrentes. Une correction est appliquée lorsque ces transactions sont terminées, les deux TX de gestion vides et le chemin de données inactif. Une correction supérieure à quatre cycles en maintenance provoque une perte de verrouillage explicite. L'absence d'estimation acceptée durant deux intervalles de maintenance provoque également un échec explicite et un arrêt avec vidage. La résolution et les seuils ne garantissent pas l'alignement global sur des fibres réelles : celui-ci doit être mesuré, avec calibration de l'asymétrie et de l'incertitude des deux directions.

`raw_counter_o` est monotone jusqu'au reset matériel. Il ne reçoit aucune correction PTP. `offset_o` contient la correction cumulée de correspondance, et `path_delay_o` la dernière estimation de délai, tous deux Q48.16. Les valeurs brutes de différentes cartes ne sont pas directement soustractibles.

`G_DRIFT_PPB` permet le scénario E2 : un accumulateur de temps Q48.32 indépendant du compteur brut avance de `2^32 + (G_DRIFT_PPB*2^32)/10^9` à chaque cycle physique. La sortie est tronquée en Q48.16. `2000` représente +2 ppm et `50000` +50 ppm. Les échanges restent quantifiés aux cycles physiques ; cette dérive synthétique ne simule pas un nouveau transceiver ou une nouvelle horloge physique.

`management_o` vaut un avant la campagne et durant une fenêtre de maintenance admise. Le wrapper doit acheminer les trames sans préemption et présenter `data_idle_i` uniquement après vidage complet des files et des transmissions. Une fenêtre occupée incrémente `sync_window_miss_o` et ne préempte pas les données. Si les données dépassent l'époque suivante, l'erreur est mémorisée, aucun nouveau cycle n'est libéré et le chemin de données reste sélectionné jusqu'au vidage.

`stop_i` demande un arrêt avec vidage. L'arrêt attend les données et les transactions de gestion engagées, puis revient au mode de gestion. Il s'agit d'une commande locale ; l'opérateur doit la demander sur toutes les cartes si l'arrêt manuel est utilisé. `G_RUN_CYCLES` vaut 128 par défaut : chaque nœud arrête automatiquement la campagne à l'époque suivant son dernier cycle, ce qui permet une extraction cohérente sans commandes JTAG successives. La valeur zéro sélectionne une campagne continue.

Le mode AGG principal ne requiert pas d'émissions initiales simultanées. Le wrapper doit permettre sa campagne sans cette synchronisation, ou désigner explicitement un essai AGG synchronisé. Une comparaison ne doit pas lui imputer arbitrairement le coût d'alignement RAG.

## Validation exécutée

Les simulations GHDL vérifient trois nœuds avec compteurs bruts initialement décalés, acquisition séquentielle, READY/ARM, lancement aligné, maintenance et monotonie brute. Les variantes testent les stalls TX, les pauses RX induites, la fenêtre occupée, STOP avec données en vol, l'échéance dépassée sans préemption, le nombre de cycles borné et la dérive synthétique.

Avec une période de 100 µs et une maintenance à 1 ms, le scénario ±2 ppm termine douze lancements dans la cible de quatre cycles. Le scénario ±50 ppm déclenche une erreur explicite de synchronisation ; le test de sensibilité vérifie ce rejet. Ce résultat est celui du banc RTL idéal à liens symétriques, sans prétendre à une mesure sur cartes.

La synthèse portable GHDL de `sync_system` est exécutée séparément. Elle confirme l'absence de construction non synthétisable sur ce profil, sans établir le timing, les ressources ou l'implantation Vivado sur XC7A35T.
