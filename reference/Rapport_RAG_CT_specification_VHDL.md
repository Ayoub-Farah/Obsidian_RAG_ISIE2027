# Comparaison RAG et trame agrégée en cut-through

## Étude scientifique et spécification d'un banc VHDL sur trois cartes Obsidian

**Projet :** Interface design - communication de convertisseurs modulaires.  
**Version :** 1.0 - 26 octobre 2026.  
**Période étudiée :** 100 µs, soit 10 kHz.  
**Statut :** cahier des charges d'implémentation, modèle temporel nominal et protocole expérimental. Aucun résultat matériel n'est présenté comme mesuré.

## Synthèse

L'étude compare deux organisations de communication sur le même transport optique Aurora 8B/10B. Dans les deux organisations, les relais sont cut-through : une sortie peut commencer avant la réception de la fin de la trame. Le premier mécanisme, nommé RAG, fait injecter un paquet local par plusieurs modules simultanément. Le second fait circuler une trame agrégée lancée par un initiateur, dans laquelle chaque module remplit son emplacement.

Quatre cas principaux sont définis : collecte centralisée RAG, trame agrégée centralisée, all-gather décentralisé RAG et collecte puis redistribution par trame agrégée. Une redistribution en pipeline est ajoutée comme variante d'optimisation du dernier cas. L'étude ne doit pas conclure à la supériorité universelle de l'une des familles à partir d'un seul scénario.

Les données et références sont synthétiques et déjà disponibles avant le cycle. Les références centralisées sont individuelles. Aucun MCU, acquisition, SPI, sorting ou calcul MMC n'intervient. Une impulsion de tâche à 10 kHz libère les échanges. Les cartes disposent de deux connexions de voisinage bidirectionnelles : les données utiles vont vers la droite ; les échanges de synchronisation emploient les deux sens.

Le banc distingue deux grandeurs : le délai jusqu'à la disponibilité de toutes les données utiles, et le délai jusqu'à la fin de circulation du protocole. Un cycle utile terminé peut encore laisser des trames en circulation. À 10 kHz, l'absence de recouvrement doit être vérifiée avec la seconde grandeur.

Trois cartes suffisent pour mesurer un anneau réel de trois nœuds et pour construire un anneau de N nœuds logiques répartis sur les FPGA. Les liaisons internes sont alors des modèles calibrés ; elles ne constituent pas N transceivers et N oscillateurs physiques indépendants. La capacité maximale doit être établie par synthèse et placement-routage.

Les fichiers joints définissent les paramètres, un modèle événementiel de référence, des vecteurs de trames, les résultats nominaux et les figures. L'IA chargée du VHDL doit respecter les exigences numérotées, produire les tests décrits et identifier explicitement toute limite de réalisation.

## 1. Périmètre, conventions et critères scientifiques

### 1.1 Exigences fixées

| Identifiant | Exigence |
|---|---|
| EX-01 | Les deux familles emploient un relais cut-through et la même configuration Aurora. |
| EX-02 | Les échanges de données utiles suivent le sens i vers (i+1) modulo N. |
| EX-03 | Chaque nœud dispose d'une donnée synthétique figée avant le début du cycle. |
| EX-04 | La tâche périodique est à 10 kHz, donc la période est 100 µs. |
| EX-05 | Les références sont individuelles dans les deux scénarios centralisés. |
| EX-06 | RAG possède un mécanisme de synchronisation de ses émissions initiales. |
| EX-07 | La synchronisation utilise des échanges matériels avec le voisin, dans les deux sens. |
| EX-08 | Aucun temps d'acquisition, de calcul de commande ou d'interface MCU n'est ajouté. |
| EX-09 | Les résultats doivent distinguer calcul nominal, simulation RTL et mesure matérielle. |
| EX-10 | Une trame ne peut être interrompue par une autre trame sur une même sortie. |

### 1.2 Définition de N

N est le nombre total de nœuds logiques dans l'anneau, numérotés de 0 à N-1. Chaque nœud possède D octets de données, y compris le nœud 0. En centralisé, le nœud 0 assure aussi la fonction de maître ; sa donnée locale est déjà disponible en interne. Il n'existe pas de carte maître supplémentaire dans la convention principale.

Pour représenter N modules plus un contrôleur externe, utiliser N+1 nœuds de transport et adapter les tableaux. Ne pas comparer des populations différentes sous le même N. Dans cette étude, N n'est ni un nombre de modules par bras, ni un nombre de modules par phase électrique : il désigne uniquement la population de l'anneau.

### 1.3 Noms des modes

| Mode | Organisation | Résultat utile |
|---|---|---|
| RAG_C | Références diffusées par 0 ; paquets de données injectés par 1 à N-1 et arrêtés à 0. | Tableau complet au maître et références reçues partout. |
| AGG_C | Une trame agrégée contenant références et emplacements de données fait un tour. | Même résultat utile. |
| RAG_D | Chaque nœud injecte son paquet ; chaque paquet fait un tour et est retiré par sa source. | Tableau complet chez tous les nœuds. |
| AGG_D2 | Un initiateur collecte un tableau puis, après réception complète et validation, le rediffuse. | Même résultat utile. |
| AGG_D2_PIPE | L'initiateur rediffuse le flux retourné dès que la sortie et les données le permettent. | Variante optimisée, avec validation tardive. |

RAG_C est une adaptation en collecte parallèle ; il ne réalise pas un all-gather complet chez tous les modules. AGG_D2 décentralise l'utilisation des données mais conserve un initiateur de communication privilégié. Le nœud 0 conserve une référence temporelle dans RAG_D ; cela n'en fait pas un contrôleur applicatif central.

### 1.4 Variables contrôlées

Les comparaisons principales fixent le débit, les fibres, les cœurs Aurora, les interfaces, les règles CRC, le délai de lecture d'en-tête, la politique de file et les tailles utiles. Les différences de nombre d'en-têtes et de nombre de passages sont conservées : elles appartiennent aux mécanismes comparés.

Les variantes doivent modifier un facteur à la fois, ou annoncer un plan factoriel. Un cas avec données dans les deux sens n'appartient pas à la comparaison principale : il changerait les deux algorithmes et nécessiterait une définition distincte.

## 2. Matériel et transport commun

### 2.1 Éléments vérifiés sur les fichiers fournis

La netlist Obsidian identifie U1 comme XC7A35T-CSG325. Deux canaux GTP sont câblés vers les connecteurs J12 et J1. La paire WR_CLK0 arrive sur MGTREFCLK0 du quad 216. Le guide local de mise en service indique une référence de 125 MHz issue de la chaîne 25 MHz / CDCM61002. [L1-L3]

| Fonction logique proposée | Réseau / connecteur | Broche FPGA |
|---|---|---|
| Port gauche RX P/N | MGT_RX0_P/N, J12 RD+/RD- | E4 / E3 |
| Port gauche TX P/N | MGT_TX0_P/N, J12 TD+/TD- | H2 / H1 |
| Port droit RX P/N | MGT_RX1_P/N, J1 RD+/RD- | A4 / A3 |
| Port droit TX P/N | MGT_TX1_P/N, J1 TD+/TD- | F2 / F1 |
| Référence GTP P/N | WR_CLK0_P/N | D6 / D5 |

Ces affectations viennent de la netlist, pas d'un XDC validé en implantation. Le générateur doit vérifier le composant exact, son speed grade, la localisation des GTP et les contraintes du projet existant. Il ne doit pas inventer un suffixe de speed grade ou des broches de debug. Les guides de mise en service décrivent des procédures ; ils ne prouvent pas que les cartes ont passé les essais.

### 2.2 Paramètres de départ

| Paramètre | Valeur de départ | Statut |
|---|---|---|
| Débit série par direction | 1,25 Gbit/s | Choix de travail à configurer dans l'IP. |
| Encodage | 8B/10B | Commun à tous les modes. |
| Nombre de voies par voisin | 1 | Deux voisins, donc deux cœurs duplex. |
| Interface utilisateur | 16 bits, cadrée | Un mot transporte deux octets. |
| Fréquence utilisateur nominale | 62,5 MHz | Déduite du débit et de la largeur. |
| Pas utilisateur nominal | 16 ns | Résolution temporelle de base. |
| Référence GTP | 125 MHz | À confirmer dans la configuration générée. |
| D, donnée par module | 6 octets | Taille synthétique configurable. |
| R, référence par module | 2 octets | Taille synthétique configurable. |
| Population par défaut | 30 | Campagne : 3, 10, 20, 30, 60 et 180. |

Le débit utile hors cadrage vaut 1 Gbit/s, soit 125 Mo/s. Ne pas appliquer une seconde fois le facteur 8B/10B lorsque le calcul est réalisé à partir des mots de deux octets et des cycles utilisateur.

### 2.3 Propriétés d'Aurora à respecter

Les trames de longueur paire ont quatre octets de cadrage sur la configuration retenue ; une longueur impaire nécessite un octet de bourrage supplémentaire. Ce coût est distinct du CRC applicatif proposé ici. [S2]

La compensation d'horloge ne doit pas être désactivée pour améliorer un résultat. La configuration de référence documentée utilise six cycles de compensation toutes les 5 000 périodes utilisateur pour un chemin de deux octets. À 62,5 MHz, cela correspond à une fenêtre de 96 ns tous les 80 µs. Une période applicative de 100 µs peut croiser plusieurs fenêtres : la phase relative doit être explorée. [S3]

L'interface RX Aurora ne fournit pas de signal `m_axi_rx_tready`. Les mots valides doivent donc être capturés immédiatement. Des pauses de `m_axi_rx_tvalid` à l'intérieur d'une trame sont possibles et ne constituent pas de nouveaux débuts de trame. [S4]

Le délai de 37 cycles indiqué par AMD est un minimum de simulation dans une configuration par défaut à deux octets. Il ne constitue pas une mesure Obsidian incluant toutes les particularités de la carte. [S1]

### 2.4 Câblage des trois cartes

Relier le port droit de A au port gauche de B, le port droit de B au port gauche de C, puis le port droit de C au port gauche de A. Chaque voisinage est duplex. Le sens A vers B vers C vers A transporte les données ; le sens inverse transporte notamment les requêtes de délai vers le parent.

![Anneau hybride de trois cartes et segments de nœuds virtuels.](figures/architecture_emulation.png)

## 3. Formats de trames et intégrité

### 3.1 En-tête applicatif commun de 16 octets

| Octets | Champ | Format et règle |
|---|---|---|
| 0-1 | magic | 0xC35A, premier octet 0xC3. |
| 2 | version | 0x01. |
| 3 | type | Valeur du tableau des types. |
| 4-5 | origin_id | Entier non signé, ordre réseau. |
| 6-7 | node_count | N, entier non signé, ordre réseau. |
| 8-11 | cycle_id | Identifiant de cycle sur 32 bits. |
| 12-13 | payload_len | Nombre exact d'octets du payload. |
| 14-15 | header_crc16 | CRC des octets 0 à 13, ordre réseau. |

Le payload suit immédiatement. Un CRC32 de quatre octets termine la trame applicative. Sa longueur totale est donc 20 + payload_len octets, hors cadrage Aurora. Les octets de CRC32 sont transmis du moins significatif au plus significatif. Les autres champs multi-octets sont en ordre réseau ; ce choix différent pour le CRC est intentionnel et doit être testé avec les vecteurs.

Le wrapper utilise une convention explicite : premier octet dans `data(15 downto 8)`, deuxième octet dans `data(7 downto 0)` ; `keep="11"` pour deux octets, `keep="10"` pour un dernier octet seul. Adapter cette convention à l'option de boutisme réellement choisie dans l'IP. Aucun octet de bourrage Aurora n'entre dans les CRC applicatifs.

### 3.2 Types

| Code | Type | Payload |
|---|---|---|
| 0x01 | DATA | D octets du nœud origin_id. |
| 0x02 | REFERENCES | N blocs de R octets, dans l'ordre des ID. |
| 0x03 | AGG_CENTRAL | N références, puis N emplacements de données. |
| 0x04 | AGG_COLLECT | N emplacements de données. |
| 0x05 | AGG_BROADCAST | Tableau complet de N données. |
| 0x10 | SYNC | Payload de synchronisation de 16 octets. |
| 0x11 | FOLLOW_UP | Même format ; contient t1. |
| 0x12 | DELAY_REQ | Même format ; requête vers le voisin parent. |
| 0x13 | DELAY_RESP | Même format ; contient t4. |
| 0x14 | LOCK_ACK | Confirmation locale de synchronisation. |
| 0x20 | ARM | Époque future de départ et configuration de campagne. |
| 0x21 | READY | Acquittement de préparation, relayé vers l'ancre. |

Les messages de synchronisation sont consommés par le voisin directement connecté et ne sont pas diffusés comme des données RAG. ARM et READY sont des messages de gestion distincts, utilisés hors fenêtre mesurée.

Le payload ARM contient 24 octets : run_id sur 32 bits ; mode sur 8 bits ; flags sur 8 bits ; réservé sur 16 bits ; époque de départ Q48.16 sur 64 bits ; cycle initial sur 32 bits ; période nominale en cycles utilisateur sur 32 bits. Le code mode vaut 0 pour RAG_C, 1 pour AGG_C, 2 pour RAG_D, 3 pour AGG_D2 et 4 pour AGG_D2_PIPE. Un nœud dont les génériques contredisent ARM refuse l'armement. ARM fait un tour et est retiré par 0.

READY utilise 16 octets : run_id sur 32 bits ; nombre de nœuds prêts dans la sous-chaîne sur 16 bits ; statut sur 16 bits ; motif d'échec sur 32 bits ; réservé sur 32 bits. Le dernier nœud émet READY vers son parent avec un compteur égal à un. Chaque parent prêt émet à son tour une nouvelle trame READY vers la gauche, avec le compteur augmenté de un. Le nœud 0 exige N-1 nœuds distants prêts. Le succès correspond à statut=0 et motif=0 ; les autres valeurs décrivent les erreurs dans une table du paquet VHDL. Ces messages ne font pas partie du temps de transmission nominal.

### 3.3 CRC et validation tardive

CRC16 d'en-tête : CRC-16/CCITT-FALSE, polynôme 0x1021, initialisation 0xFFFF, sans réflexion, xor final nul. Le vecteur ASCII `123456789` donne 0x29B1.

CRC32 de trame : CRC-32/ISO-HDLC, polynôme réfléchi 0xEDB88320, initialisation 0xFFFFFFFF, réflexion des octets et xor final 0xFFFFFFFF. Le même vecteur donne 0xCBF43926. Le CRC couvre l'en-tête complet et le payload, sans ses propres quatre octets.

Un relais cut-through peut avoir propagé des octets avant de connaître le CRC32 reçu. Il est donc interdit d'annoncer la validité applicative au seul passage du slot de données. Les mots sont provisoires jusqu'à la fin de trame et la réussite des contrôles.

Pour DATA et REFERENCES non modifiés, conserver le CRC reçu pendant le relais. Pour une trame agrégée modifiée, calculer en parallèle le CRC entrant et le CRC sortant. **Il est interdit de recalculer un CRC sortant correct en masquant un CRC entrant incorrect.** Retenir les derniers mots nécessaires ; si la trame entrante est invalide, inverser le bit 0 du CRC32 sortant calculé. Cette trame empoisonnée sera rejetée à l'étage suivant. Un CRC d'en-tête incorrect conduit à une suppression avant émission de cet en-tête.

La longueur de rétention d'en-tête et de fin de trame doit garantir que l'état CRC entrant est connu avant l'émission du CRC sortant. Une vérification RTL doit démontrer cette causalité, y compris lors des pauses TX et RX.

### 3.4 Motifs synthétiques

Pour l'octet j du nœud i au cycle k, utiliser :

$$P_i(k,j)=(90+17i+31k+j)\bmod 256.$$

Pour sa référence individuelle :

$$R_i(k,j)=(165+29i+13k+j)\bmod 256.$$

Les motifs dépendent de l'ID, du cycle et de la position. Ils détectent les erreurs d'adressage, les décalages et les mélanges de cycles. Les emplacements non encore écrits d'AGG_COLLECT sont initialisés à zéro ; celui du nœud 0 contient déjà sa donnée.

## 4. Fonctionnement exact des quatre cas

### 4.1 Règles communes de relais

À chaque cycle, les données locales sont figées avant l'époque de départ. Le relais commence après reconnaissance et validation de l'en-tête, sans attendre le payload complet. Une trame conserve l'exclusivité de la sortie jusqu'à son dernier mot accepté. Une pause TX suspend le mot courant sans le modifier.

RAG réserve la première émission au paquet local de ce cycle. Une réception précoce est mise en file jusqu'à la fin de cette émission, même si l'émission locale est légèrement retardée. Après cette première émission, les trames reçues sont relayées en ordre FIFO. Aucun paquet local supplémentaire n'est injecté pendant ce cycle. Les paquets de synchronisation ne préemptent jamais une trame de données.

Un `cycle_id` inattendu, un ID hors plage, une longueur invalide, une duplication ou un dépassement de file invalide le cycle. Une ancienne trame est consommée jusqu'à sa fin puis écartée ; elle ne peut pas valider le cycle courant.

### 4.2 RAG_C : collecte centralisée parallèle

1. À t0, le nœud 0 émet une trame REFERENCES contenant les N références individuelles. Sa propre référence est incluse pour garder un format régulier, mais est disponible localement.
2. Les nœuds 1 à N-1 émettent chacun leur DATA à la même époque.
3. Les nœuds non maîtres relaient les DATA vers la droite. Le nœud 0 les collecte et les retire du réseau ; il ne les rediffuse pas.
4. REFERENCES est relayée en cut-through. Chaque nœud en extrait son bloc, le valide en fin de trame et le compare au motif attendu.
5. Lorsque REFERENCES revient à 0, elle est retirée. Les nœuds ne génèrent aucune nouvelle trame DATA à sa réception.

Au maître, un bitmap initialement réduit au bit 0 suit les données validées. Le résultat utile exige tous ses bits à 1 et une référence valide pour chaque module. Le retour de REFERENCES et la disparition de toute file active déterminent la fin de circulation.

### 4.3 AGG_C : trame agrégée centralisée

Le nœud 0 construit une trame AGG_CENTRAL. Le payload comporte d'abord `reference[0..N-1]`, puis `data[0..N-1]`. La taille reste constante pendant le tour.

Le nœud i lit sa référence et remplace uniquement les D octets de son emplacement de données. Il ne rajoute pas d'octets à la fin. Les offsets sont `16 + i*R` pour la référence et `16 + N*R + i*D` pour les données. Le CRC32 sortant est régénéré avec propagation des erreurs entrantes.

Au retour, le nœud 0 valide la trame complète. Une référence extraite avant la fin d'une trame n'est déclarée valide qu'après contrôle de son entrée. Le résultat utile et le retour de la trame sont ici pratiquement le même événement protocolaire, auquel s'ajoutent les vidages internes.

Le mécanisme est inspiré du traitement à la volée d'EtherCAT ; ce n'est pas une implémentation EtherCAT compatible. [S5]

### 4.4 RAG_D : all-gather décentralisé

Tous les nœuds émettent DATA simultanément. Chaque nœud conserve les données reçues des autres et relaie le paquet en cut-through. Au retour d'un paquet dont `origin_id` correspond au nœud local et dont le cycle est correct, ce nœud le consomme sans le retransmettre.

Chaque nœud possède un bitmap N bits, initialisé avec son propre bit. Un bit distant est activé uniquement après contrôle complet de DATA. `all_data_valid` correspond à N bits valides et des données cohérentes avec les motifs.

`own_return_seen` indique le retour valide du paquet propre. Il ne remplace pas le bitmap. La fin locale de protocole exige le retour propre et l'absence de trame en cours ; la fin globale exige cette condition partout.

Il est interdit d'arrêter de relayer les paquets des autres au seul motif que le tableau local est déjà complet : certains voisins pourraient encore en avoir besoin.

### 4.5 AGG_D2 : collecte puis redistribution stricte

Le nœud 0 initie AGG_COLLECT, avec N emplacements de D octets. Chaque nœud complète son emplacement pendant le passage. Le nœud 0 attend le retour complet et un CRC valide, puis lance AGG_BROADCAST après un délai de retournement configurable.

Les nœuds non initiateurs ne sont déclarés détenteurs du tableau complet qu'après réception validée d'AGG_BROADCAST. Cette trame poursuit son tour jusqu'à 0 pour avoir une terminaison uniforme ; 0 la retire. Son dernier retour ne doit pas être confondu avec le moment où le dernier autre nœud a obtenu le tableau.

L'initiateur peut lancer son cycle à 10 kHz avec sa seule horloge. Les autres nœuds répondent à la trame et n'ont pas besoin d'une époque d'injection locale commune. L'absence de synchronisation concerne uniquement ce déclenchement réseau dans le périmètre présent.

### 4.6 AGG_D2_PIPE : variante de rediffusion en pipeline

L'initiateur commence la deuxième émission après retour et validation de l'en-tête, disponibilité des premiers mots et libération de sa sortie. Il n'attend pas tout le CRC32 entrant. Il conserve une FIFO de recirculation et propage une erreur tardive par empoisonnement du CRC sortant.

Ce mode peut améliorer AGG_D2. Il reste une variante à deux passages et doit être présenté séparément : le mode strict demandé ne doit pas être remplacé silencieusement par cette optimisation.

## 5. Mesures de temps et occupation

### 5.1 Origine temporelle

t0 est l'instant de libération programmé du cycle par le nœud 0, observable par un signal de debug. Les données sont disponibles avant t0. Pour RAG, chaque nœud doit tenter son premier envoi à l'époque correspondante de son horloge logique synchronisée. Pour AGG, seul 0 émet initialement.

Enregistrer aussi le premier transfert accepté par l'interface TX de chaque source et, si accessible, l'événement série correspondant. L'alignement des demandes TX ne garantit pas l'alignement effectif après les pauses du cœur. L'écart des premiers transferts acceptés constitue une métrique distincte.

### 5.2 Grandeurs obligatoires

| Grandeur | Définition |
|---|---|
| T_data_master | Dernière donnée valide au maître, centralisé. |
| T_ref_all | Dernière référence individuelle valide parmi tous les nœuds. |
| T_all_data | Dernier tableau complet valide parmi tous les nœuds, décentralisé. |
| T_useful | max(T_data_master,T_ref_all) en centralisé ; T_all_data en décentralisé. |
| T_drained | Dernier retrait de trame, validation et vidage de sortie nécessaires à la fin de protocole. |
| Delta_launch | Écart entre les premiers transferts TX acceptés des sources RAG. |
| U_link_max | Plus forte occupation de trames sur un lien orienté pendant une période. |
| U_link_mean | Moyenne de cette occupation sur les N liens orientés. |

Les temps ci-dessus sont relatifs à t0. Calculer la marge utile et la marge de protocole par soustraction à 100 µs. Rapporter le minimum, la médiane, le percentile 99, le maximum et le nombre d'échecs. Le maximum observé est un résultat expérimental, pas une preuve de pire cas absolu.

L'occupation de trames compte les données, les en-têtes, les CRC, le cadrage et les pauses effectivement attribuées à ces trames. Les idles permanents du lien série ne doivent pas être comptés comme 100 % de charge applicative. Présenter à part le trafic de synchronisation et les fenêtres réservées.

### 5.3 Fin de période

La tâche de contrôle est ici un déclencheur, sans charge de calcul artificielle. En mode périodique, si le cycle précédent n'est pas terminé au prochain déclenchement, compter `deadline_miss` et ignorer la nouvelle injection. Le numéro de période continue d'avancer. Ne pas écraser les données du cycle actif et ne pas réétiqueter ses paquets.

En mode unitaire, autoriser une transaction à dépasser 100 µs pour mesurer son délai réel. Afficher ensuite sa non-compatibilité avec un échange par période. Ne pas tronquer les courbes à l'échéance.

## 6. Modèle temporel nominal et équations

### 6.1 Hypothèses et limites

Le modèle fourni est événementiel à la granularité d'un cycle utilisateur. Il gère une sortie occupée par nœud, une réception d'en-tête, une décision de relais et une validation finale distincte. Il n'est pas un simulateur RTL du cœur Aurora. Les compensations d'horloge, erreurs, variations CDC, dérives, FIFO finies et messages PTP sont exclus de ses chiffres nominaux.

Les valeurs de latence sont des hypothèses de départ non calibrées. Les formules servent à contrôler les ordres de grandeur et l'implémentation ; les résultats matériels devront les remplacer ou expliquer leurs écarts.

### 6.2 Variables

| Symbole | Définition | Valeur nominale |
|---|---|---|
| tau | Période d'un mot de deux octets sur le lien 8B/10B. | 16 ns. |
| L | Longueur applicative, en-tête et CRC inclus. | Selon la trame. |
| M(L) | Nombre de mots : ceil(L/2). | Entier. |
| p | Premier mot TX accepté vers premier mot RX valide du voisin. | 37 tau = 592 ns, indicatif. |
| q | Premier mot RX vers premier mot TX de relais, sortie libre. | 10 tau = 160 ns, choix de conception. |
| c | Délai de validation après le dernier mot RX, modèle. | 2 tau = 32 ns. |
| g | Retournement collecte / redistribution. | 2 tau = 32 ns. |
| s(L) | Espacement minimal de deux premiers mots TX consécutifs. | (M(L)+2) tau. |
| b(L) | Premier mot RX vers validation complète nominale. | (M(L)-1) tau + c. |

Les deux cycles ajoutés dans s(L) représentent le cadrage. Ils ne sont pas ajoutés une deuxième fois à p, qui est défini entre interfaces utilisateur. b(L) est un modèle de flux sans pause ; le vrai intervalle premier mot / validation doit être mesuré, notamment à cause du traitement de fin de trame.

On définit :

$$\tau=\frac{20}{R_{\mathrm{line}}},\qquad d=p+q.$$

$$L_D=20+D,\quad L_R=20+NR,\quad L_C=20+N(D+R),\quad L_G=20+ND.$$

$$h=\max\left(d,s(L_D)\right).$$

Pour RAG homogène et synchrone, h représente l'espacement entre les premières émissions des vagues successives sur un lien. Lorsque la trame locale n'est pas entièrement sérialisée avant la possibilité de relais, elle impose l'attente. Ainsi, RAG ne peut pas s'affranchir de la bande passante en augmentant N ou D.

### 6.3 RAG_D

Le nœud le plus éloigné d'une source se situe à N-1 sauts. Le premier saut part de la source à t0 ; les N-2 relais suivants sont espacés de h. Le retour propre ajoute une étape.

$$T_{\mathrm{useful,RAG\_D}}=(N-2)h+p+b(L_D).$$

$$T_{\mathrm{drained,RAG\_D}}=(N-1)h+p+b(L_D).$$

Ces expressions supposent des liens identiques, aucun décalage initial, aucun trafic concurrent et une capacité de file suffisante. Pour les autres conditions, utiliser la simulation et les mesures.

### 6.4 RAG_C

La vague REFERENCES suit les injections DATA. Dans le cas nominal homogène défini ici, la dernière référence et la dernière donnée au maître donnent :

$$T_{\mathrm{useful,RAG\_C}}=(N-2)h+p+\max\left(b(L_D),b(L_R)\right).$$

$$T_{\mathrm{drained,RAG\_C}}=(N-1)h+p+b(L_R).$$

Le choix d'une unique grande trame REFERENCES, injectée par 0 en premier, appartient à cette définition. Des paquets de références individuels ou un déclenchement des DATA à leur réception constitueraient d'autres scénarios.

### 6.5 AGG_C

Il n'y a qu'une trame initiale, donc pas de concurrence entre injections locales. Chaque relais ajoute d ; le dernier saut vers 0 ajoute p, suivi de la réception de la fin de trame.

$$T_{\mathrm{useful,AGG\_C}}\simeq T_{\mathrm{drained,AGG\_C}}=(N-1)d+p+b(L_C).$$

La durée de sérialisation de la grande trame n'est pas multipliée par N : ce serait un modèle store-and-forward erroné pour ce protocole.

### 6.6 AGG_D2 et variante en pipeline

Pour la collecte :

$$T_{\mathrm{collect}}=(N-1)d+p+b(L_G).$$

La deuxième émission du mode strict commence à :

$$a_2=T_{\mathrm{collect}}+g.$$

La dernière réception utile et le retour de fin sont alors :

$$T_{\mathrm{useful,AGG\_D2}}=a_2+(N-2)d+p+b(L_G).$$

$$T_{\mathrm{drained,AGG\_D2}}=a_2+(N-1)d+p+b(L_G).$$

Pour la variante en pipeline, sous les mêmes hypothèses de flux régulier :

$$a_{2,\mathrm{pipe}}=\max\left(s(L_G),(N-1)d+p+q+g\right).$$

Remplacer a2 par cette valeur et prendre aussi le maximum avec T_collect pour la disponibilité utile du nœud 0. Le premier terme garantit que la source ne superpose pas sa deuxième trame à la première. Les pauses et le niveau de FIFO doivent être vérifiés avant d'accepter cette approximation.

### 6.7 Occupation des liens

Avec le retrait du paquet propre après un tour, chaque lien RAG_D transporte N petites trames. Les liens AGG_D2 transportent deux grandes trames. Pour RAG_C, le lien sortant du nœud j transporte REFERENCES et j trames DATA.

$$B_{\mathrm{RAG\_D}}=N\,s(L_D),\qquad B_{\mathrm{AGG\_D2}}=2\,s(L_G).$$

$$B_{\mathrm{RAG\_C},j}=s(L_R)+j\,s(L_D),\qquad B_{\mathrm{AGG\_C}}=s(L_C).$$

L'occupation fractionnaire est B / 100 µs. Ce budget ne comprend pas encore PTP ou les pauses de compensation. RAG peut donner un délai de disponibilité plus court et consommer davantage de bande passante ; ce sont deux observations compatibles.

## 7. Résultats nominaux reproductibles

Les tableaux suivants proviennent de `modele_reference.py` avec `configuration_reference.json`. Il s'agit de calculs exécutés, sans synchronisation ni compensation d'horloge, et non de résultats de cartes ou de VHDL.

### 7.1 Disponibilité utile

| N | RAG_C (µs) | AGG_C (µs) | RAG_D (µs) | AGG_D2 (µs) | AGG_D2_PIPE (µs) |
|---:|---:|---:|---:|---:|---:|
| 3 | 1,568 | 2,464 | 1,568 | 4,112 | 3,952 |
| 10 | 6,944 | 8,176 | 6,832 | 15,312 | 14,816 |
| 20 | 14,624 | 16,336 | 14,352 | 31,312 | 30,336 |
| 30 | 22,304 | 24,496 | 21,872 | 47,312 | 45,856 |
| 60 | 45,344 | 48,976 | 44,432 | 95,312 | 92,416 |
| 180 | 137,504 | 146,896 | 134,672 | 287,312 | 278,656 |

Fin de protocole à N=60 et marge sur 100 µs :

| Mode | Fin de protocole (µs) | Marge (µs) | Occupation maximale nominale d'un lien |
|---|---:|---:|---:|
| RAG_C | 46,096 | 53,904 | 15,312 % |
| AGG_C | 48,976 | 51,024 | 4,032 % |
| RAG_D | 45,184 | 54,816 | 14,400 % |
| AGG_D2 | 96,064 | 3,936 | 6,144 % |
| AGG_D2_PIPE | 93,168 | 6,832 | 6,144 % |

À N=60, le mode AGG_D2 ne garde que 3,936 µs de marge nominale avant la prochaine période. Les pauses, incertitudes et blocages supplémentaires doivent donc être mesurés avant de le déclarer compatible. À N=180, tous les modes du paramétrage initial dépassent 100 µs. Aucune de ces observations ne constitue un verdict pour un débit ou une implémentation différents.

### 7.2 Interprétation

Le délai augmente fortement avec le nombre de relais, même lorsque l'occupation d'un lien reste faible. Dans le régime où d domine s(L_D), les vagues RAG sont espacées par la traversée du lien et le traitement d'en-tête. Dans le régime où s(L_D) domine, la sérialisation et les files deviennent déterminantes.

Les courbes doivent être lues avec leurs hypothèses. La latence minimale documentaire, la rétention d'en-tête choisie et l'absence de pauses empêchent d'utiliser les chiffres comme des garanties à 10 kHz. Le tableau exécuté, le temps de fin de protocole et les variantes sont présentés dans les figures et les CSV.

![Délais nominaux et échéance de 100 µs.](figures/delais_nominaux.png)

![Occupation nominale maximale d'un lien.](figures/occupation_liens.png)

![Chronogrammes TX nominaux de RAG_D et AGG_D2 pour dix nœuds.](figures/chronogrammes_N10.png)

## 8. Synchronisation des émissions RAG

### 8.1 Profil retenu

Le banc utilise un échange à quatre horodatages inspiré de PTP, transporté dans des messages Aurora personnalisés. Il n'implémente ni Ethernet, ni UDP, ni BMCA, ni un profil IEEE 1588 interopérable. Aucun objectif subnanoseconde n'est annoncé. Les travaux de Rong et la revue de Gao distinguent la mesure temporelle, la fréquence et la phase ; ces niveaux ne doivent pas être confondus. [P1-P2]

Le nœud 0 constitue l'ancre temporelle. Le nœud i, pour i>0, suit i-1. Le nœud 0 ne suit pas N-1 : cela fermerait une boucle de références différente de la cascade étudiée.

### 8.2 Échange voisin à deux étapes

Le parent émet SYNC ; son premier mot accepté est horodaté t1. Le voisin capture t2 au premier mot RX. FOLLOW_UP transmet le t1 effectivement capturé. Le voisin émet DELAY_REQ en direction du parent et capture t3. Le parent capture t4 à la réception et le transmet dans DELAY_RESP.

Le payload de 16 octets contient `sync_sequence` sur 32 bits, `timestamp` sur 64 bits, `flags` sur 16 bits et `reserved` sur 16 bits. Les champs sont en ordre réseau. SYNC et DELAY_REQ peuvent transporter zéro dans timestamp : leurs instants d'émission sont capturés matériellement. Les séquences doivent être appariées et les messages vérifiés par CRC.

Si theta désigne l'avance de l'horloge enfant sur l'horloge parent :

$$\widehat{\theta}=\frac{(t_2-t_1)-(t_4-t_3)}{2},\qquad \widehat{d}=\frac{(t_2-t_1)+(t_4-t_3)}{2}.$$

La correction de l'enfant vaut -theta estimé. Les équations supposent une faible dérive pendant l'échange et un trajet aller-retour symétrique, ou une asymétrie calibrée. Une asymétrie de délai laisse un biais égal à sa moitié. [S6, P1]

Les horodatages aux interfaces utilisateur incluent des délais de cœur qui peuvent être différents selon les directions, les pauses et les resets. Les mesurer dans les deux sens et conserver leur version de calibration. Un horodatage à résolution fine dans un registre ne crée pas une précision physique plus fine que les événements observés.

### 8.3 Initialisation séquentielle

1. Attendre des liens stables et la validation des paramètres communs.
2. Le nœud 0 échange avec 1 jusqu'à obtention d'un nombre configurable d'estimations cohérentes ; valeur de départ : huit.
3. Le nœud 1, une fois verrouillé, commence la même procédure avec 2 ; poursuivre jusqu'à N-1.
4. Faire remonter READY vers 0, puis diffuser ARM avec une époque future commune. Prévoir un délai d'armement de plusieurs millisecondes, configurable, après disponibilité de tous les voisins.
5. Ne lancer aucune campagne mesurée avant acquittement de tous les nœuds et contrôle du décalage d'émission.

Le temps d'initialisation est mesuré séparément. Il croît avec la cascade et ne doit pas être ajouté à chaque période nominale.

Pour la V1, appliquer après chaque échange accepté une correction de phase de gain un, sans servo de fréquence obligatoire. Conserver les huit dernières estimations de délai. Rejeter comme aberrante une estimation de délai s'écartant de leur médiane de plus de 64 ns, après constitution du premier historique. Le verrouillage exige huit estimations successives acceptées avec un décalage estimé en valeur absolue inférieur ou égal à 32 ns. Ces seuils décrivent un critère interne de verrouillage ; la cible globale de départ doit toujours être vérifiée séparément.

### 8.4 Maintenance parallèle

En nominal, tous les couples 0/1, 1/2, ..., N-2/N-1 peuvent procéder à leur échange voisin dans la même fenêtre, les ports étant distincts. Les messages vers l'enfant utilisent la sortie droite ; les requêtes vers le parent utilisent la sortie gauche.

Chaque nœud fige sa correspondance d'horloge logique au début de la ronde. Il termine les horodatages avec cette correspondance, puis applique la correction en attente pendant une phase inactive. Il est interdit de changer la base de temps entre t1 et t4. Le fait que les échanges soient parallèles ne garantit pas une propagation instantanée d'une correction de l'ancre jusqu'au dernier module.

La valeur de départ est une ronde toutes les dix périodes, soit 1 ms, avec une fenêtre réservée de 90 à 100 µs sur la dixième période. **Ces 10 µs sont une provision de conception, à confirmer par mesure, pas un résultat établi.** Si les données ne sont pas terminées à 90 µs, ne pas les préempter : compter `sync_window_miss` et invalider l'admission de cette configuration.

Dans cette fenêtre, les corrections ne doivent ni remettre à zéro le compteur brut de mesure, ni créer deux lancements pour un même cycle. Une correction qui franchirait une époque de lancement impose un réarmement explicite ou un cycle manqué enregistré, jamais une rafale de rattrapage.

En maintenance V1, limiter la correction de phase acceptée à 64 ns en valeur absolue. Au-delà, déclarer la perte de verrouillage et refaire une acquisition avant une nouvelle campagne valide. Le gain, les seuils, la taille d'historique et le délai d'armement, initialement de 5 ms, sont configurables. Les tests à forte dérive sont autorisés à échouer : ils servent précisément à identifier les intervalles de resynchronisation admissibles.

### 8.5 Définir la précision requise

Le seuil initial d'essai pour Delta_launch est 64 ns, soit quatre cycles utilisateur à 62,5 MHz. Ce seuil est une cible configurable pour le banc ; il n'est pas déduit d'un critère électrique et n'est pas garanti pour N nœuds physiques.

Une borne conservatrice fondée sur des erreurs par voisin peut s'écrire :

$$E_{\mathrm{global}}\leq (N-1)\left(\varepsilon_{\mathrm{pair}}+2\rho T_{\mathrm{hold}}\right)+E_{\mathrm{sched}}.$$

Ici rho borne l'écart de fréquence résiduel de chaque horloge, T_hold est le temps depuis la dernière correction et epsilon_pair borne l'erreur résiduelle après échange voisin. Cette borne additionne des erreurs défavorables ; des mesures directes peuvent donner une borne plus précise. Si une borne globale initiale est disponible avec des fréquences absolues connues, une autre expression de maintien peut être utilisée, mais les hypothèses doivent être indiquées.

Tester 0, ±2 et ±50 ppm. À ±50 ppm par oscillateur, deux voisins peuvent dériver de 100 ns en 1 ms avant correction. Un intervalle de 1 ms peut donc être incompatible avec une cible de 64 ns. Réduire l'intervalle, améliorer la syntonisation ou relâcher la cible après mesure ; ne pas annoncer un verrouillage sur la seule base de la fréquence des messages.

### 8.6 Coût de synchronisation

Un message de synchronisation de 16 octets de payload donne 36 octets applicatifs et 40 octets avec cadrage nominal, soit 320 ns de sérialisation au débit initial. Un échange minimal transporte trois messages vers l'enfant et une requête vers le parent, hors ACK de verrouillage initial.

Le coût par lien, le délai de l'échange complet, la fenêtre réservée et le coût moyen amorti sont quatre mesures différentes. Rapporter le délai du cycle comportant la maintenance, pas seulement une moyenne divisée par dix.

Pour AGG, le cas principal n'exige pas de synchronisation de tous les départs : ne pas lui imposer le coût RAG par construction. Ajouter éventuellement un cas où les mêmes contraintes de synchronisation sont imposées aux deux organisations, en le nommant explicitement.

## 9. Émuler N modules avec trois FPGA

### 9.1 Principe

Répartir les ID en trois segments contigus de tailles aussi proches que possible. Pour N=30 : A héberge 0-9, B 10-19 et C 20-29. Pour N=60 : 20 nœuds par carte. N doit être au moins égal à trois pour cette répartition physique ; N=2 reste un cas de simulation utile.

Une carte implémente sa chaîne de nœuds et des liaisons virtuelles entre eux. Son entrée gauche provient d'Aurora et sa sortie droite revient à Aurora. Les trois frontières de carte sont des liaisons physiques ; les N-3 autres liaisons sont modélisées. Le chemin inverse doit aussi exister pour la synchronisation des voisins virtuels.

### 9.2 Contenu obligatoire d'un nœud virtuel

Chaque nœud possède un ID, une donnée locale, sa logique d'injection, ses états de trame, une file indépendante, un état CRC, ses compteurs, son bitmap et un signal de complétude. En centralisé, seul le nœud logique 0 exerce la fonction maître, même si plusieurs nœuds partagent le même FPGA.

Il est interdit de remplacer un segment entier par un délai unique. Ce raccourci ne représenterait ni les multiples injections RAG, ni leurs attentes de sortie, ni la modification des emplacements de la trame agrégée.

### 9.3 Modèle d'une liaison virtuelle

La liaison virtuelle doit reproduire, à l'interface utilisateur, le délai du premier mot, le débit, le cadrage, les pauses RX et TX, les capacités de file et la compensation d'horloge retenue. Elle représente une seule liaison manquante. Elle ne doit pas rajouter un transceiver virtuel par-dessus une liaison physique déjà traversée.

La cadence d'une liaison virtuelle de deux octets à 62,5 MHz correspond déjà au débit utile 8B/10B de 1,25 Gbit/s série. Ajouter les créneaux de cadrage ; ne pas recoder une deuxième fois chaque mot avec un facteur 10/8.

Les pauses de compensation doivent avoir des phases configurables et indépendantes entre liens virtuels. Un retard pur de 37 cycles sans limitation de débit et sans files n'est pas suffisant pour valider le modèle complet.

### 9.4 Calibration sans double comptage

1. Mesurer les deux ports réels, dans les deux directions, pour les longueurs 26, 36, 140, 380 et 500 octets applicatifs, puis pour les tailles exactes de campagne.
2. Relever séparément premier mot / premier mot, premier mot / dernier mot, validation CRC, espacement minimal de trames et pauses. Répéter après plusieurs resets de lien.
3. Régler le modèle virtuel sur ces observables, et vérifier un nœud interne avec des traces identiques aux entrées/sorties mesurées.
4. Comparer les organisations physiques équivalentes à N=3, puis les résultats N=6 ou N=9 obtenus avec des répartitions différentes.
5. Conserver les paramètres, leur dispersion et leur incertitude. Une calibration n'élimine pas la nécessité de valider les conflits de files.

Les sauts virtuels ajoutent leur modèle p et le nœud ajoute q. Les sauts physiques utilisent le délai réel d'Aurora et le même traitement de nœud ; n'ajouter aucun p virtuel à la frontière physique.

### 9.5 Trois niveaux de preuve

| Niveau | Expérience | Ce qui est établi |
|---|---|---|
| E0 | Trois nœuds, un par carte, liens réels. | Fonctionnement réel du petit anneau et calibration locale. |
| E1 | N nœuds virtuels, transport calibré, horloges communes à l'intérieur d'une carte. | Échelle de trafic, files, délais et complétude sous ce modèle. |
| E2 | E1 avec horloges logiques propres et dérives injectées. | Réaction du protocole de synchronisation à un modèle de dérive. |

Les horloges logiques peuvent être émulées par des accumulateurs numériques et des déclenchements quantifiés. Cela ne reproduit pas N CDR, N oscillateurs analogiques ou N comportements de réinitialisation indépendants. Les conclusions doivent conserver cette limite.

### 9.6 Ressources et solution de repli

Le premier objectif matériel est N=3, puis 10, 20, 30 et 60. N=180 est un objectif de capacité à vérifier. Une synthèse et un placement-routage sont requis pour chaque profil. Ne pas déduire la faisabilité de la seule présence de trois FPGA.

Les valeurs initiales sont 2 048 mots de deux octets par RX physique, 256 mots par liaison virtuelle et 16 descripteurs par file. Elles servent à démarrer ; elles ne constituent pas une preuve de capacité suffisante. L'admission exige zéro perte et une marge de niveau de FIFO dans les essais défavorables.

Pour N=3, conserver réellement les tableaux de données. En émulation étendue, un mode de validation en flux peut vérifier tous les motifs et les CRC et ne conserver que les bitmaps et métriques ; le nœud initiateur strict conserve toujours le tableau nécessaire à la rediffusion. Ce mode économise la mémoire sans supprimer les octets échangés. Il doit être identifié et ne peut pas servir à annoncer les ressources d'un récepteur applicatif stockant tous les tableaux.

Si un profil ne tient pas, livrer la taille maximale vérifiée et poursuivre les tailles supérieures en simulation RTL ou par modèle calibré, avec un statut distinct. Ne pas mutualiser un serveur unique de trames qui sérialiserait artificiellement des liens censés fonctionner en parallèle.

## 10. Architecture VHDL demandée

### 10.1 Organisation des blocs

| Bloc | Responsabilité |
|---|---|
| benchmark_pkg | Types, constantes, longueurs, générateurs de motifs et registres. |
| aurora_neighbor_wrapper | Deux ports duplex, adaptation des interfaces et états d'erreur. |
| frame_rx_capture | Capture RX sans backpressure, limites de trame, CRC, descripteurs. |
| cut_through_router | Décision après en-tête, retrait local, relais FIFO et verrouillage TX. |
| rag_engine | Injection locale unique, réception par ID, bitmap et retour propre. |
| aggregate_engine | Lecture des références, écriture des slots et gestion des deux passes. |
| crc16_header / crc32_stream | Calculs parallèles par octet valide et vecteurs de test. |
| logical_clock | Horloge brute et correspondance logique distinctes. |
| neighbor_sync | Quatre horodatages, échanges vers parent/enfant et correction différée. |
| virtual_neighbor_link | Débit, délai, pauses, files et liaison inverse du modèle virtuel. |
| virtual_segment | Chaîne des nœuds présents sur une carte. |
| cycle_scheduler | Époques à 10 kHz, maintenance, armement et politiques de dépassement. |
| benchmark_monitor | Horodatages, statistiques, bitmaps et journal de taille bornée. |
| obsidian_benchmark_top | Connexion des blocs aux cœurs IP et à JTAG/VIO/ILA. |

Le tableau décrit des responsabilités. Le générateur peut ajuster les frontières de fichiers pour réduire les duplications, sans déplacer le comportement réseau dans un script externe ni supprimer les files indépendantes.

### 10.2 Génériques minimaux

`G_MODE`, `G_NODES`, `G_NODE_BASE`, `G_LOCAL_NODES`, `G_DATA_BYTES`, `G_REF_BYTES`, `G_MAX_FRAME_BYTES`, `G_RX_FIFO_WORDS`, `G_VLINK_FIFO_WORDS`, `G_DESC_DEPTH`, `G_PERIOD_CYCLES`, `G_HEADER_DELAY_CYCLES`, `G_CRC_COMMIT_CYCLES`, `G_TURNAROUND_CYCLES`, `G_SYNC_INTERVAL`, `G_SYNC_WINDOW_CYCLES`, `G_STORE_FULL_DATA` et `G_ENABLE_LOGICAL_DRIFT`.

Le débit et les horloges des IP sont fixés à la génération Vivado. Ne pas les présenter comme de simples registres modifiables à chaud. Pour la première version, sélectionner N, le mode et les tailles par génériques ; armer, lancer, arrêter et lire les compteurs via JTAG/VIO. Aucun MCU, soft-CPU ou bus SPI n'est nécessaire.

Vérifier à l'élaboration les ID contigus, les tailles positives, les longueurs inférieures à 65 536 octets et à MAX_FRAME_BYTES, ainsi que la cohérence entre période et horloge. La segmentation de très grandes trames est hors V1 et doit produire une erreur explicite si elle est nécessaire.

Un en-tête de 16 octets contient huit mots sur cette interface. La rétention minimale doit laisser recevoir ces huit mots et terminer le CRC16 et la décision de routage. Le choix initial de dix cycles suppose une architecture satisfaisant cette causalité. Réduire ce paramètre sans modifier et revalider le parseur est interdit ; le RTL doit fournir une assertion du délai minimal réellement requis.

### 10.3 Contrat de flux interne

Le chemin interne utilise `data[15:0]`, `keep[1:0]`, `valid`, `ready`, `sof` et `last`. Un transfert a lieu uniquement quand valid et ready sont à 1. Sous attente, data, keep, sof, last et valid restent stables. sof marque uniquement le premier mot transféré ; les pauses n'en créent pas de nouveau.

Au RX physique, ready n'existe pas : la capture écrit chaque mot valide dans une FIFO. L'interface interne ready ne doit jamais être raccordée à un port RX Aurora imaginaire. L'overflow est une erreur enregistrée ; il ne peut pas supprimer silencieusement un mot.

Le TX avance uniquement sur handshake. Les index de slots, CRC et longueurs comptent les octets effectivement transférés. Le RX compte les octets dont valid et keep sont actifs. Un octet absent de keep n'entre ni dans le motif attendu ni dans les CRC.

### 10.4 Machines d'état

Supervision globale : `RESET`, `WAIT_LINKS`, `INITIAL_SYNC`, `ARMED`, `RUN`, `DRAIN`, `FAULT`. AGG sans synchronisation de départ peut passer de WAIT_LINKS à ARMED après validation de configuration.

Réception : `WAIT_FIRST`, `READ_HEADER`, `STREAM_BODY`, `CHECK_TRAILER`, `COMMIT`, `DROP`. La décision de relais se prend après READ_HEADER, pendant que STREAM_BODY continue. Une sortie indépendante peut donc émettre avant CHECK_TRAILER.

Émission : `IDLE`, `LOCAL_FIRST`, `RELAY`, `FINISH_FRAME`. Le verrou de trame ne peut pas être libéré entre deux mots en raison d'une pause valid/ready. En phase de synchronisation, un sélecteur choisit les messages de gestion entre les trames, jamais au milieu.

AGG_D2 à l'initiateur : `EMIT_COLLECT`, `RECEIVE_COLLECT`, `VALIDATE_COLLECT`, `TURNAROUND`, `EMIT_BROADCAST`, `WAIT_RETURN`, `DONE`. Ces états peuvent avoir des chemins RX/TX simultanés ; ne pas imposer la fin de EMIT_COLLECT avant toute réception.

### 10.5 Horloges et CDC

Préserver les domaines utilisateur réellement produits par les deux cœurs Aurora. S'ils sont distincts, utiliser des FIFO asynchrones ou les mécanismes CDC appropriés. Ne pas connecter un bus multi-bit à un double synchroniseur et ne pas déclarer les horloges synchrones sans justification.

Privilégier une horloge utilisateur et une logique partagée communes lorsque la configuration multi-cœur générée par AMD l'autorise. Sinon, capturer les événements RX/TX dans leurs domaines respectifs et définir une conversion temporelle cohérente vers le compteur logique local. Un simple transfert asynchrone d'un bus d'horodatage est interdit. Les délais et incertitudes de cette conversion doivent entrer dans la calibration PTP et dans la métrologie ; ne pas horodater silencieusement après une FIFO à délai variable.

Le compteur brut de mesure sur 64 bits ne subit jamais de remise à l'heure PTP. Les messages transportent un temps logique au format Q48.16, en unités de cycles utilisateur nominaux. Si un accumulateur de fréquence est utilisé, conserver au moins 32 bits fractionnaires en interne ; tronquer pour le transport. Une représentation fractionnaire ne réduit pas la quantification physique de l'émission.

Les corrections nominales sont différées jusqu'à une fenêtre inactive. L'initialisation peut corriger la phase avant armement. La version initiale peut utiliser des corrections de phase périodiques sans servo de fréquence ; elle doit alors démontrer le respect du décalage cible pour les ppm et intervalles sélectionnés.

### 10.6 Mémoire et niveau de file

Stocker les mots reçus et les métadonnées de trame sans perte. Le cut-through peut utiliser une rétention limitée d'en-tête et de queue, mais un blocage prolongé de sortie peut transformer une partie du comportement en attente sur paquet complet. Cette attente doit apparaître dans les traces.

Pour chaque file, enregistrer le niveau maximal, le nombre d'overflows et les causes de blocage. Une règle de dimensionnement initiale est la quantité de données reçue pendant la plus longue indisponibilité de sortie, augmentée de la rétention d'en-tête, de la queue CRC, des métadonnées et d'une marge. La durée d'indisponibilité doit être calculée à partir des trames réellement en conflit, puis vérifiée.

## 11. Instrumentation et données de sortie

### 11.1 Signaux et compteurs

Exporter par nœud ou par segment : `cycle_id`, `task_tick`, `tx_first`, `rx_first`, `all_data_valid`, `reference_valid`, `own_return_seen`, `protocol_drained`, `sync_locked`, `sync_sequence`, `offset_estimate`, `path_delay_estimate`, `fifo_highwater`, `crc_error_count`, `header_error_count`, `duplicate_count`, `missing_count`, `overflow_count`, `deadline_miss`, `sync_window_miss`, `channel_reset_count` et compteurs TX/RX.

Garder séparément les compteurs du lien Aurora et ceux du protocole applicatif. Ne pas compter une trame transmise à chaque relais comme une nouvelle donnée locale.

### 11.2 Mesure globale avec trois cartes

Utiliser, si quatre voies de mesure sont disponibles, un signal t0 de A et un signal `local_all_done` pour A, B et C. `local_all_done` est un ET des complétudes des nœuds du segment, pas seulement celle de son premier nœud. Le dernier front observé donne la complétude globale. Une seconde acquisition peut utiliser les fins locales de protocole.

Choisir des sorties de debug accessibles et vérifiées ; le présent rapport n'invente pas leurs broches. Mesurer ou borner le délai de sortie et le déséquilibre des sondes/câbles. Ne pas transporter un acquittement de fin autour de l'anneau et inclure ce transport dans le temps de données sans le signaler.

Les horodatages bruts provenant de cartes différentes ne sont pas directement soustractibles. Employer l'oscilloscope commun, ou une correspondance temporelle calibrée avec son incertitude. Les fichiers doivent préciser la méthode utilisée.

### 11.3 Journal et export CSV

Un journal circulaire de départ de 256 résumés de 64 octets par carte limite la consommation de BRAM. Les campagnes longues alimentent des compteurs et histogrammes ; les traces détaillées sont capturées sur un petit nombre de cycles. Arrêter proprement après vidage avant extraction par JTAG/VIO/ILA.

Colonnes minimales d'un résultat : `run_id`, `git_commit`, `bitstream_id`, `tool_version`, `board_id`, `mode`, `N`, `D`, `R`, `line_rate`, `mapping`, `virtual_model_id`, `cycle_id`, `t0_method`, `T_useful`, `T_drained`, `Delta_launch`, `sync_interval`, `fifo_highwater`, `crc_errors`, `overflows`, `deadline_miss`, `status` et `measurement_uncertainty`.

Un échec reste dans les résultats. Ne pas calculer les statistiques de latence sur les seuls cycles réussis sans annoncer le taux de pertes et les cycles manquants.

## 12. Plan de validation

### 12.1 Ordre de réalisation

1. Valider les fonctions CRC et les vecteurs binaires.
2. Valider les parseurs et la tenue du flux lors des pauses.
3. Simuler deux puis trois nœuds avec un modèle de lien simple, sans synchronisation.
4. Vérifier les quatre modes, la complétude et les temps attendus.
5. Ajouter les files finies, les pauses de compensation et les erreurs.
6. Valider les liens Aurora réels et calibrer les latences.
7. Valider le protocole sur trois cartes, d'abord avec un départ de banc connu, puis avec la synchronisation voisin.
8. Ajouter les segments virtuels, comparer les répartitions, puis augmenter N.
9. Exécuter les campagnes périodiques et les essais de resynchronisation.

Un déclenchement commun de banc utilisé en étape 7 est un moyen de métrologie. Il ne doit pas être conservé pour présenter RAG comme autonome lors de sa validation finale.

### 12.2 Essais obligatoires et assertions

| Test | Résultat attendu |
|---|---|
| CRC golden et trames fournies | Correspondance bit à bit. |
| N=2 et N=3 | Tableau exact, pas de doublon, terminaison correcte. |
| Relais CT d'une trame assez longue | Premier TX de relais avant dernier RX, si sortie libre. |
| TX ready interrompu | Mot stable, pas d'avance des index ni du CRC TX. |
| RX valid interrompu | Aucun faux sof ; reprise au bon octet. |
| Dernier mot impair | keep correct ; aucun octet de bourrage contrôlé comme donnée. |
| Départs décalés | Attentes observées et conservation de tous les paquets admis. |
| CRC payload faux | Aucune validation ; propagation d'erreur à travers AGG. |
| En-tête faux ou ID hors plage | Suppression contrôlée et erreur comptée. |
| Ancien cycle et duplication | Aucun bitmap courant validé à tort. |
| FIFO volontairement trop petite | Overflow et échec explicites. |
| Reset d'un lien en pleine trame | Cycle invalide, récupération contrôlée, pas de succès partiel. |
| Durée supérieure à 100 µs | Mesure unitaire complète ; deadline_miss en périodique. |
| Fenêtre PTP occupée à 90 µs | Pas de préemption ; sync_window_miss explicite. |
| Phase CC défavorable | Pas de perte ; variation de délai et niveau de file enregistrés. |
| Dérive logique et perte de PTP | Erreur d'alignement mesurée ; arrêt ou mode dégradé annoncé. |

Assertions structurelles : pas de deux trames sur une sortie ; pas de lecture FIFO vide ; pas d'écriture FIFO pleine non signalée ; pas de slot écrit par le mauvais nœud ; pas de validation avant CRC ; pas de double lancement du même cycle ; aucun compteur de mesure modifié par PTP.

### 12.3 Matrice de campagne

Le noyau de campagne couvre les quatre modes, N dans {3,10,20,30,60,180}, D=6, R=2 et le débit initial. Ajouter AGG_D2_PIPE comme sensibilité. Pour chaque profil admissible, enregistrer au moins 400 cycles détaillés ou résumés de latence, puis 10 000 périodes pour la continuité. Ces durées représentent respectivement 40 ms et 1 s à 10 kHz.

Balayer ensuite D dans {6,32,128}, R dans {2,8}, les phases CC, la profondeur des files et les décalages d'émission. Rejeter explicitement les combinaisons dépassant MAX_FRAME_BYTES au lieu de tronquer le payload. Un autre débit, par exemple 3,125 Gbit/s, exige une nouvelle configuration d'IP et une qualification optique ; il n'est pas supposé disponible sans vérification.

Pour la synchronisation, tester des intervalles de 1, 10 et 100 périodes et des dérives jusqu'à ±50 ppm. Distinguer E1 et E2 dans tous les tableaux. Les essais de charge maximale doivent inclure des phases relatives de compensation indépendantes et des tailles de référence longues.

### 12.4 Critères d'admission à 10 kHz

Une configuration est admise uniquement si tous les cycles requis réussissent, si les CRC et motifs sont corrects, si aucune file ne déborde, si la fin de protocole reste avant le prochain lancement et si le décalage de départ respecte la cible annoncée pour RAG.

Sur une période réservant la fenêtre PTP finale, les données doivent être terminées avant 90 µs avec la provision initiale. Cette limite peut être revue après mesure du vrai budget de synchronisation ; conserver l'historique du changement. L'occupation moyenne seule n'est jamais un critère suffisant.

La marge doit être comparée à l'incertitude de calibration et de mesure. Une marge plus petite que cette incertitude ne permet pas de conclure à la compatibilité.

## 13. Conclusions attendues et rédaction des résultats

L'étude doit répondre à quatre questions : quelle organisation termine le plus vite pour un résultat équivalent ; quelle bande passante elle consomme ; quel coût d'alignement elle exige ; et jusqu'à quel N elle respecte réellement une période de 100 µs.

Il faut comparer RAG_C à AGG_C et RAG_D à AGG_D2, puis exposer AGG_D2_PIPE. Comparer directement un résultat uniquement disponible au maître à un tableau disponible partout créerait un avantage artificiel. La notion d'initiateur de communication doit également être séparée de celle de contrôleur applicatif.

La conclusion matérielle finale doit préciser la plus grande population physique et la plus grande population émulée effectivement validées. Une formule en N ou une compilation réussie n'est pas une mesure sur N cartes.

Le modèle nominal suggère des compromis à tester : RAG réduit certains délais de diffusion grâce aux émissions concurrentes, mais multiplie les petites trames et exige un alignement mesuré ; l'agrégation réduit les en-têtes, mais son organisation décentralisée à deux passages augmente le chemin temporel. Ces tendances restent conditionnelles aux paramètres et à l'optimisation réellement implémentée.

## 14. Consigne à l'IA chargée du VHDL

Ce document et `configuration_reference.json` sont la spécification fonctionnelle. Le fichier `vecteurs_trames.json` fixe des exemples binaires. `modele_reference.py` fournit un contrôle temporel nominal, sans constituer une preuve RTL ni matérielle.

Produire du VHDL-2008 synthétisable, les testbenches, un script de simulation, les scripts Tcl de génération des IP, un projet Vivado reproductible et une documentation de câblage. Séparer la logique portable des IP AMD et conserver les interfaces réelles d'Aurora. Ne pas générer de soft-CPU ni de dépendance à SPIN.

Commencer par la validation de trois nœuds réels et des quatre modes, puis ajouter la virtualisation et la synchronisation. Tous les blocs doivent finir par être livrés ; cette progression n'autorise pas à présenter un prototype partiel comme la réalisation complète.

Pour chaque profil, fournir le rapport de synthèse et d'implantation, le timing, les ressources, les assertions exécutées et les traces. Une version non exécutée dans Vivado doit être marquée comme telle. Toute hypothèse manquante sur le part exact, les broches de debug ou le projet existant doit être exposée dans le README ; ne pas inventer de valeurs pour prétendre avoir produit un bitstream valide.

Les nombres du tableau nominal doivent être régénérés depuis les CSV de référence. Si le RTL diffère, localiser l'écart : temps d'IP, parsing, CDC, pauses, files, CRC ou déclenchement. Ne pas modifier le modèle pour forcer une concordance sans explication.

## 15. Références et traçabilité

### Documentation primaire consultée

- **[S1] AMD, PG046, Aurora 8B/10B, Latency, v11.1.** Minimum de simulation à deux octets et dépendance à la configuration. https://docs.amd.com/r/en-US/pg046-aurora-8b10b/Latency
- **[S2] AMD, PG046, Framing Efficiency.** Cadrage et bourrage. https://docs.amd.com/r/en-US/pg046-aurora-8b10b/Framing-Efficiency
- **[S3] AMD, PG046, Clock Compensation.** Périodicité et durée des séquences. https://docs.amd.com/r/en-US/pg046-aurora-8b10b/Clock-Compensation
- **[S4] AMD, PG046, Receiving Data.** Interface RX et pauses de valid. https://docs.amd.com/r/en-US/pg046-aurora-8b10b/Receiving-Data
- **[S5] EtherCAT Technology Group, Functional Principle.** Lecture et insertion à la volée. https://www.ethercat.org/en/technology.html
- **[S6] J. Eidson / NIST, Tutorial on IEEE 1588, 2005.** Échange d'horodatages et synchronisation des horloges. https://www.nist.gov/document/tutorial-basicpdf

La documentation AMD consultée est postérieure à certaines configurations historiques du projet. L'IP générée et sa documentation de version font foi pour l'implémentation. Consultation documentaire : 26 octobre 2026.

### Articles fournis et utilisés pour le cadrage

- **[P1] Y. Rong et al., 2021.** High-performance Distributed Power Electronics Communication Network Design with 5 Gbps Data Rate and Sub-nanosecond Synchronization Accuracy. DOI : 10.1109/ECCE47101.2021.9595693. Les équations de décalage sont données pour leur propre convention de signe ; le présent rapport définit explicitement la sienne. Le résultat de cet article ne constitue pas une garantie pour Obsidian.
- **[P2] M. Gao et al., 2024.** Overview of FPGA-based Synchronization Techniques in Distributed Control Systems for Multilevel Power Converters. DOI : 10.1109/IECON55916.2024.10905279. Utilisé pour distinguer synchronisation temporelle, fréquentielle et de phase.
- **[P3] S. Rietmann et al., 2019.** Field Bus for Data Exchange and Control of Modular Power Electronic Systems with High Synchronisation Accuracy of ±4 ns. DOI : 10.1541/ieejjia.8.295. Contexte des échanges courts et de la commande modulaire.
- **[P4] B. Steinmann, G. Fernandez, N. Cherix, 2019.** Tree-shaped networked control system for modular power converters with sub-µs latency and ns-scale synchronization accuracy. Exemple d'utilisation d'Aurora dans une autre topologie ; ses délais ne sont pas réutilisés comme mesures de notre anneau.

### Fichiers locaux inspectés

- **[L1] Obsidian.net**, réseaux MGT_RX0/1, MGT_TX0/1, WR_CLK0 et composant U1. Source des broches du tableau matériel.
- **[L2] 05_phase_d_clocks_dac_25mhz_125mhz_pll.md**, section D4. Chaîne de référence et procédures de validation.
- **[L3] 06_phase_e_gtp_ibert_aurora.md**, sections E1-E2. Procédures de validation des ports et signaux de lien.

Les équations de comparaison, les formats de trames, les seuils de départ, les tailles de FIFO et l'architecture d'émulation sont des propositions de cette étude. Ils ne sont pas attribués aux articles cités. Aucun fichier du projet SPIN_OSC n'a été utilisé.
