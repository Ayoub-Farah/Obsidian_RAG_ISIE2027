# Mission : générer et valider le banc VHDL RAG / agrégation cut-through

Lis intégralement `Rapport_RAG_CT_specification_VHDL.md`. Il constitue la spécification autonome et contient les formats, le fonctionnement, les interfaces, l'émulation, la synchronisation et les tests. Lis aussi `configuration_reference.json` et `vecteurs_trames.json`. N'interprète pas les chiffres nominaux comme des mesures matérielles.

## Objectif

Produire un projet VHDL-2008 pour trois cartes Obsidian XC7A35T-CSG325. Comparer RAG_C, AGG_C, RAG_D et AGG_D2, puis ajouter AGG_D2_PIPE comme variante. Les deux organisations sont cut-through. Données prêtes, références individuelles, aucune SPIN, aucune acquisition et aucun calcul MMC. Période 100 µs. Données vers la droite ; liens voisins bidirectionnels pour la synchronisation.

N est le nombre total de nœuds logiques, nœud 0 compris. En centralisé, 0 est aussi le maître et conserve sa propre donnée. En décentralisé, chaque nœud doit avoir reçu toutes les données du cycle. Une transaction n'est pas terminée pour le prochain cycle tant que sa circulation protocolaire n'est pas vidée.

## Travail à livrer

1. VHDL synthétisable et testbenches pour les blocs de la section 10.
2. Scripts de simulation et assertions de la section 12, avec résultats réellement exécutés.
3. Scripts Tcl de génération des deux cœurs Aurora duplex et de construction Vivado ; XDC fondé sur les broches vérifiées, sans broches de debug inventées.
4. Quatre modes principaux pour trois nœuds réels, puis segments virtuels répartis sur les trois cartes. Chaque liaison virtuelle doit respecter cadence, délai, files et pauses.
5. Synchronisation voisin à deux étapes, initialisation séquentielle 0→1→...→N-1 et maintenance parallèle. Le nœud 0 reste l'ancre. Horloge de mesure brute distincte de l'horloge logique corrigée.
6. Instrumentation des disponibilités, fins de protocole, écarts de départ, files et erreurs ; export CSV.
7. Rapports de synthèse, de placement-routage et de timing pour chaque profil disponible ; indiquer clairement les tailles qui ne tiennent pas.
8. README de génération, câblage, exécution et reproduction des mesures.

## Interdictions essentielles

- Ne pas transformer RAG en store-and-forward en attendant le CRC32 complet pour commencer chaque relais.
- Ne pas inventer `m_axi_rx_tready` sur Aurora ; capturer les mots RX valides.
- Ne pas masquer un CRC entrant erroné en régénérant un CRC correct dans une trame agrégée modifiée. Préserver l'erreur jusqu'au récepteur final.
- Ne pas remplacer N nœuds virtuels par un délai global ni sérialiser des liens indépendants dans un serveur partagé.
- Ne pas mesurer seulement le retour au premier nœud pour conclure à la complétude chez tous.
- Ne pas désactiver la compensation d'horloge réelle pour obtenir de meilleurs délais.
- Ne pas remettre à l'heure les compteurs bruts de mesure et ne pas mélanger les `cycle_id`.
- Ne pas annoncer une synthèse, un bitstream ou une validation matérielle qui n'a pas été exécuté.

Le speed grade exact, les ressources du projet Vivado existant, les broches de debug et les paramètres mesurés des cartes restent à confirmer à partir du matériel disponible. Cette liste ne bloque pas la logique portable et les simulations ; conserve ces valeurs comme paramètres explicitement non validés.

## Démarrage recommandé

Commence par les CRC et les vecteurs, puis les parseurs, le routage CT et les quatre modes sur trois nœuds simulés. Exécute `python3 modele_reference.py --verify` pour comprendre les événements nominaux et comparer les traces. Ajoute ensuite Aurora, les CDC, les files finies, les messages de synchronisation et les segments virtuels. Termine par les campagnes de la matrice fournie.

Toute divergence entre le modèle nominal et le RTL doit être expliquée par un événement ou un étage identifié ; ne change pas silencieusement le protocole ou l'origine temporelle pour rapprocher les courbes.
