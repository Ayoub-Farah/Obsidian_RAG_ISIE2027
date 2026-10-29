# Temps total de transmission CT et RAG : équations et limites

**Complément :** [collecte au module 1 pour N=30 et P de 1 à 20 octets](../theoretical_payload_n30/rapport.md), avec payload CT de 29P octets et réception des 29 données RAG.

**Projet :** Obsidian_RAG  
**Date :** 27 octobre 2026  
**Périmètre :** anneau cible de 2 à 30 modules, 10 octets d'information locale par module.  
**Nature des résultats :** prédictions analytiques nominales, fondées sur des paramètres extraits d'un banc de trois cartes physiques.

## 1. Objet et définition des durées

Ce rapport décrit les équations utilisées pour produire la figure
[`rtt_vs_modules.png`](rtt_vs_modules.png), également exportée en PDF et SVG.
L'ordonnée **Total transmission time (µs)** correspond à deux conventions de
fin de transfert définies ci-dessous. Les noms de fichiers historiques
`rtt_vs_modules.*` sont conservés ; la courbe CT représente désormais un
temps total de collecte et de rediffusion.

### 1.1 CT à table commune

Le module 1 crée une table comportant un emplacement réservé de 10 octets par
module. Il remplit le sien ; les autres emplacements sont initialement vides.
La longueur du payload est donc fixée à **10N octets dès la création**.

La transmission comporte deux phases séquentielles :

1. **Collecte :** la trame parcourt l'anneau, chaque module complète son
   emplacement et relaie en cut-through. La table complète revient au module 1
   après **N sauts physiques**.
2. **Rediffusion :** après réception complète de cette trame, le module 1
   réémet la table complète. Les modules intermédiaires la relaient en
   cut-through, sans ajout d'information. Le transfert se termine à la
   **réception du dernier mot par le module N**, après **N−1 sauts** supplémentaires.

Le temps CT commence au premier mot TX accepté du module 1 pendant la collecte.
Il se termine au dernier mot RX de la table complète au module N pendant la
rediffusion. Il ne se limite donc pas au premier retour au module 1.

### 1.2 RAG décentralisé

Les N modules injectent simultanément chacun un paquet contenant leurs
10 octets d'information. Chaque paquet garde son origine et est relayé
jusqu'à son retrait après **H=N sauts**, conformément au choix de RTT complet.

Pour un paquet, la durée va de son premier mot TX accepté à son dernier mot RX
de retour à l'origine. Dans l'anneau parfaitement homogène et synchronisé du
modèle, les N paquets ont la même durée. Cette durée représente alors aussi
la fin du dernier retour. Avec des liens ou des départs différents, le temps
global serait le maximum des dates de retour, mesurées dans une référence
temporelle commune.

Les temps d'acquisition des mesures, de préparation avant le premier mot TX,
de synchronisation initiale et de lecture JTAG ne sont pas inclus.

## 2. Notations et paramètres

Toutes les équations numériques ci-dessous utilisent la microseconde, sauf
mention contraire.

| Symbole | Définition | Valeur retenue |
|---|---|---:|
| N | Nombre de modules de l'anneau cible | 2 à 30 |
| D | Information locale par module | 10 octets |
| P_CT | Payload de la table CT | ND = 10N octets |
| P_RAG | Payload d'un paquet RAG | D = 10 octets |
| B | En-tête utilisateur et CRC | 32 + 4 = 36 octets |
| τ | Intervalle nominal par mot accepté de 16 bits, sans pause | 0,016 µs |
| r | Plancher observé du délai local premier RX → premier TX de relais | 0,288 µs |
| d | Délai effectif d'un lien équivalent, supposé identique pour tous les liens | 0,624 µs |
| g | Intervalle minimal dernier TX → premier TX de la trame suivante sur le même émetteur | 0,048 µs |
| δ | Délai au module 1 entre le dernier RX de collecte et le premier TX de rediffusion | 0 µs dans la figure ; non mesuré |

### 2.1 Origine des coefficients

Les données proviennent de la campagne matérielle corrigée : **192 essais,
576 résumés valides**, sur trois cartes physiques. La campagne contient des
tailles de payload et des nombres de sauts variés ; elle ne constitue pas une
campagne sur 2 à 30 cartes.

- **τ :** après retrait des pauses TX enregistrées, les 246 observations de
  sérialisation disponibles retrouvent 16 ns par intervalle de mot. La
  conversion en temps utilise le tick nominal du projet.
- **r :** les traces locales donnent un minimum de 18 cycles, soit 288 ns,
  entre le premier RX physique et le premier TX accepté d'un relais. Ce terme
  inclut notamment la réception/validation de l'en-tête et le pipeline local.
  Une résidence plus longue peut aussi contenir une attente d'arbitrage.
- **g :** pour les trames RAG consécutives dont les données sont prêtes, le
  minimum observé entre le dernier mot accepté et le premier de la trame
  suivante est de trois cycles, soit 48 ns. Il inclut le cycle de séparation
  des événements ; ce n'est pas une mesure du délai de réémission δ.
- **d :** il est déduit d'un trajet complet de premier mot en CT. Dans l'ILA,
  le premier RX retourné sur A suit le premier TX de A de 153 cycles :

  \[
  \beta=153\times0{,}016=2{,}448\ \mu s.
  \]

  En supposant trois liens équivalents et deux relais de durée r :

  \[
  \beta=3d+2r,
  \qquad
  d=\frac{2{,}448-2\times0{,}288}{3}=0{,}624\ \mu s.
  \]

Le calcul de β utilise deux horodatages du **même compteur de A**. Les
résidences de relais sont elles aussi calculées au sein de chaque carte.
Aucune soustraction directe de compteurs bruts appartenant à des cartes
différentes n'est utilisée.

**d est un paramètre effectif apparent du modèle.** L'hypothèse d'égalité
répartit un délai global entre trois liens. Elle ne fournit ni une calibration
indépendante de chaque lien ni la propagation de la fibre seule. Les différences
de fréquence et la quantification des horloges restent également à considérer.

## 3. Sérialisation d'une trame

Pour un payload P, le nombre de mots de 16 bits est :

\[
W(P)=\left\lceil\frac{P+36}{2}\right\rceil.
\]

Le temps entre le premier et le dernier mot accepté, sans pause, vaut :

\[
\boxed{\mathcal S(P)=\tau\,[W(P)-1].}
\]

Il y a **W−1 intervalles** entre W événements d'acceptation. Cette convention
est celle des horodatages du banc. La disponibilité de l'émetteur pour une
trame suivante est traitée séparément avec g.

Les emplacements d'information sont déjà inclus dans P_CT=10N ; ils ne sont
pas ajoutés une seconde fois. Le plafond couvre les tailles impaires et le
dernier mot partiellement rempli. Les 36 octets correspondent au protocole
utilisateur. Le débit de l'interface tient déjà compte de la configuration
Aurora ; aucun facteur 8B/10B supplémentaire n'est appliqué à cette équation.

Pour les tailles choisies :

\[
W_{CT}=5N+18,
\qquad
\mathcal S_{CT}=0{,}080N+0{,}272,
\]

\[
W_{RAG}=23,
\qquad
\mathcal S_{RAG}=0{,}352.
\]

Le cut-through permet de recouvrir les transmissions successives d'une même
trame. Une phase de parcours compte donc une sérialisation complète, plus
les délais de progression du premier mot. Les pauses qui affectent la fin
effective du transfert nécessitent un traitement du chemin critique.

## 4. Équations CT : collecte puis rediffusion

### 4.1 Collecte

La collecte comporte N liens et N−1 relais intermédiaires :

\[
\boxed{T_{CT,col}=\mathcal S_{CT}+Nd+(N-1)r.}
\]

Le premier retour au module 1 est donc :

\[
T_{CT,col}=0{,}992N-0{,}016.
\]

### 4.2 Rediffusion de la table complète

La rediffusion du module 1 au module N comporte N−1 liens et N−2 relais :

\[
\boxed{T_{CT,red}=\mathcal S_{CT}+(N-1)d+(N-2)r.}
\]

Elle transmet à nouveau la trame entière, ce qui impose une **seconde
sérialisation**. Pour N=2, cette phase comprend un lien et aucun relais.

\[
T_{CT,red}=0{,}992N-0{,}928.
\]

### 4.3 Temps total CT

Les deux phases se succèdent après réception complète au module 1 :

\[
\boxed{
T_{CT,total}
=2\mathcal S_{CT}+(2N-1)d+(2N-3)r+\delta.
}
\]

Pour D=10 et les coefficients retenus :

\[
\boxed{T_{CT,total}(N)=1{,}984N-0{,}944+\delta\quad[\mu s].}
\]

La figure utilise **δ=0**. Il s'agit d'une hypothèse de réémission immédiate,
sans coût supplémentaire de validation finale, d'accès mémoire, de commande ou
de préparation au module 1. Une réalisation concrète doit mesurer ce délai.
La campagne source a caractérisé la collecte CT ; **la nouvelle phase de
rediffusion n'y a pas été mesurée ni validée sur le matériel**. Réutiliser r
pour ses relais est une hypothèse supplémentaire.

## 5. Équations RAG : injections simultanées

### 5.1 Cadence des tours de transmission

Un paquet doit à la fois disposer de son en-tête reçu et trouver l'émetteur
libre. Dans le modèle homogène et symétrique, on retient la cadence :

\[
\boxed{C=\max\bigl(d+r,\ \mathcal S_{RAG}+g\bigr).}
\]

Le premier terme représente la progression d'un premier mot et sa préparation
au relais. Le second représente le service minimal d'une trame par un
émetteur verrouillé jusqu'au dernier mot accepté, suivi de la séparation g.

Si f_k désigne le début du k-ième tour de transmission, cette approximation
symétrique s'écrit :

\[
f_0=0,
\qquad f_{k+1}=f_k+C.
\]

Elle représente la contrainte élémentaire de service de l'émetteur. Elle ne
remplace pas une simulation générale des FIFO et de l'arbitrage pour des
arrivées hétérogènes ou désynchronisées.

Pour des paquets de 10 octets :

\[
d+r=0{,}912,
\qquad
\mathcal S_{RAG}+g=0{,}352+0{,}048=0{,}400.
\]

La cadence nominale est donc C=0,912 µs. Dans cette configuration idéale,
le service de l'émetteur ne domine pas la cadence de progression. Le modèle
n'ajoute donc pas une attente de file supplémentaire dépendant de N à ces
petits paquets. Cela ne prouve pas l'absence de contention dans toute
réalisation à N modules.

### 5.2 Retour complet après N sauts

Le dernier mot atteint son origine après N transmissions, avec N−1 étapes de
relais :

\[
\boxed{T_{RAG,total}=\mathcal S_{RAG}+d+(N-1)C.}
\]

D'où, pour les courbes actuelles :

\[
\boxed{T_{RAG,total}(N)=0{,}912N+0{,}064\quad[\mu s].}
\]

Cette expression intègre la contrainte de service via le maximum définissant
C. Elle ne consiste pas à additionner N sérialisations indépendantes sans
tenir compte de leur recouvrement.

### 5.3 Vérification de cohérence sur les captures existantes

Avec un payload RAG de 257 octets et H=3 :

\[
\mathcal S=2{,}336,
\quad C=\max(0{,}912,2{,}336+0{,}048)=2{,}384,
\]

\[
T=2{,}336+0{,}624+2\times2{,}384=7{,}728\ \mu s.
\]

Les captures existantes donnent 7,728 à 7,840 µs pour ce cas, sur des retours à
l'origine mesurés avec un seul compteur. Ce rapprochement constitue un
contrôle de cohérence nominale. Le délai g provient de la même campagne :
ce n'est pas une validation statistique indépendante du modèle, et cela ne
valide pas des anneaux physiques de 2 à 30 modules.

## 6. Résultats numériques de la figure

Les valeurs suivantes supposent δ=0 et ne contiennent aucune nouvelle mesure
matérielle.

| N | Payload CT (octets) | Collecte CT (µs) | Rediffusion CT (µs) | Total CT (µs) | Total RAG (µs) |
|---:|---:|---:|---:|---:|---:|
| 2 | 20 | 1,968 | 1,056 | 3,024 | 1,888 |
| 3 | 30 | 2,960 | 2,048 | 5,008 | 2,800 |
| 5 | 50 | 4,944 | 4,032 | 8,976 | 4,624 |
| 10 | 100 | 9,904 | 8,992 | 18,896 | 9,184 |
| 20 | 200 | 19,824 | 18,912 | 38,736 | 18,304 |
| 30 | 300 | 29,744 | 28,832 | 58,576 | 27,424 |

Dans ces hypothèses, CT paie le retour de collecte puis la diffusion de la
table agrégée, tandis que RAG profite de la circulation simultanée de petits
paquets. Le classement observé sur la figure dépend de ces tailles, de cette
convention de fin de transfert et des hypothèses de contention.

## 7. Limites d'interprétation

### 7.1 Paramètres partiellement identifiés

Le banc comporte trois cartes. Le délai d est un partage égal d'un délai
effectif global ; il ne sépare pas fibre, transceivers, buffers Aurora et
phases d'horloge. Les mesures ne déterminent pas trois délais indépendants.
Les liens d'un futur anneau peuvent avoir des longueurs et des interfaces
différentes. Le plancher r et l'intervalle minimal g ne sont pas des durées
garanties dans toutes les situations.

### 7.2 Une nouvelle étape CT reste à caractériser

Le retour de la table complète au module 1, son contrôle, sa disponibilité
pour émission et le lancement de la rediffusion peuvent ajouter δ. Ce délai
est indépendant de la séparation entre deux trames TX déjà prêtes. La valeur
g mesurée ne permet donc pas de fixer automatiquement δ. Une modification
de δ translate la courbe CT sans modifier sa pente dans le présent modèle.

### 7.3 Le trafic RAG à N injecteurs est extrapolé

Faire circuler un paquet sur H sauts dans un anneau de trois cartes conserve
trois injecteurs et trois ressources de relais physiques. Cela permet de
caractériser des composants et des parcours longs. Cela n'identifie pas à
lui seul les files et les attentes d'un anneau de N injecteurs réels.

La récurrence symétrique suppose des paquets de même taille, des départs
simultanés, des liens égaux, un ordre de relais régulier et des buffers
suffisants. La variabilité des départs, une charge externe, des paquets de
tailles différentes ou des FIFO proches de la saturation demandent une
simulation par événements ou par cycles, avec arbitrage et verrouillage de
trame explicites. Pour des payloads plus grands, le terme de service peut
dominer C et modifier fortement le comportement.

### 7.4 Pauses et chemin critique

Les courbes excluent les pauses supplémentaires de compensation d'horloge,
les aléas de disponibilité, les erreurs de trame, les pertes de lien et les
reprises sur défaut. Des attentes peuvent aussi apparaître avant que le
CRC entrant permette de libérer le CRC sortant.

Les pauses relevées sur différentes cartes peuvent se recouvrir avec les
transmissions et les buffers des liens. Leur somme ne représente pas
automatiquement l'allongement du temps total. Le modèle détaillé doit suivre
la fin effective du transfert et son chemin critique.

### 7.5 Horodatages et calibration

Les conversions utilisent la période nominale de 16 ns. La quantification et
les différences de fréquence réelles limitent la précision absolue.
Les durées intercartes exigent une correspondance temporelle calibrée, avec
un intervalle de validité et une incertitude. Les résultats matériels
intercartes restent vides dans les exports existants quand cette calibration
manque. Le délai de fibre seul nécessite une caractérisation supplémentaire.

### 7.6 Conventions de comparaison

CT se termine ici lorsque tous les modules ont pu recevoir la table complète
par la seconde phase, le module N étant le dernier destinataire. RAG conserve
le retour complet H=N choisi pour les figures. Dans un échange RAG idéal où
l'objectif serait seulement de livrer chaque information aux autres modules,
H=N−1 suffirait. Ce serait une autre convention :

\[
T_{RAG,H=N-1}=\mathcal S_{RAG}+d+(N-2)C.
\]

Cette variante n'est pas tracée. Le choix du point de fin doit rester explicite
lors de l'utilisation des courbes. Les instants d'acquisition des mesures et
la cohérence d'un instantané applicatif ne sont pas évalués par ces durées.

### 7.7 Portée des nombres et capacités

Les prédictions ne constituent ni une borne de pire cas ni un intervalle de
confiance. Les écarts observés sur les essais CT à trois cartes ne doivent
pas être transférés comme marge garantie à la nouvelle procédure à deux
phases ou à N=30.

Le script maintient un payload CT inférieur ou égal à 4096 octets. Avec D=10
et N≤30, le maximum est 300 octets. Cela reste une condition de taille du
modèle : le bitstream mesuré attribue seulement les rôles physiques A/B/C.
La figure ne démontre pas qu'il gère directement 30 cartes. Aucun nœud
virtuel n'a été ajouté au matériel pour générer les courbes.

## 8. Sensibilité des prédictions

Pour CT :

\[
\frac{\partial T_{CT,total}}{\partial d}=2N-1,
\qquad
\frac{\partial T_{CT,total}}{\partial r}=2N-3,
\qquad
\frac{\partial T_{CT,total}}{\partial\delta}=1.
\]

Pour RAG à D=10, tant que la branche C=d+r reste dominante :

\[
\frac{\partial T_{RAG,total}}{\partial d}=N,
\qquad
\frac{\partial T_{RAG,total}}{\partial r}=N-1.
\]

À N=30, augmenter le délai supposé de chaque lien de 0,100 µs augmente ainsi
le total CT de 5,900 µs et le total RAG de 3,000 µs. Ajouter 0,048 µs de
réémission au module 1 porte CT de 58,576 à 58,624 µs. Ce sont des scénarios
de sensibilité, pas des incertitudes statistiquement établies.

## 9. Éléments nécessaires à une validation plus complète

Pour affiner les prédictions, il faut caractériser la réémission δ et les
relais de rediffusion CT, calibrer les liens et les correspondances d'horloge,
puis croiser les balayages de taille et de nombre de sauts. La caractérisation
de la charge RAG doit distinguer le nombre de sauts du nombre d'injecteurs.
Des cas asymétriques, des départs décalés et les pauses Aurora devront être
représentés avant de rechercher des bornes de délai ou des garanties.

Les coefficients actuels constituent une base nominale pour construire cette
simulation ; les paramètres non identifiés restent des hypothèses explicites.

## 10. Fichiers sources et reproduction

Les courbes utilisent le schéma `theoretical_ring_total_time_v2` de
[`model_assumptions.json`](model_assumptions.json). Ce fichier conserve les
coefficients, les hypothèses et les empreintes SHA256 des sources matérielles.

| Fichier | Rôle |
|---|---|
| [`rtt_vs_modules.csv`](rtt_vs_modules.csv) | Les 29 points théoriques, leurs payloads, nombres de sauts et durées par phase |
| [`rtt_vs_modules.png`](rtt_vs_modules.png) | Figure en anglais ; exports PDF et SVG dans le même dossier |
| [`../../scripts/plot_theoretical_rtt.py`](../../scripts/plot_theoretical_rtt.py) | Génération des données et figures |
| [`../hardware_validation/model.json`](../hardware_validation/model.json) | Observations de sérialisation et résidences minimales |
| [`../hardware_validation/events.json`](../hardware_validation/events.json) | Événements TX/RX utilisés pour identifier g |
| [`../hardware_validation/results.csv`](../hardware_validation/results.csv) | Résumés des essais physiques |
| [`../hardware_validation/ila/verification.json`](../hardware_validation/ila/verification.json) | Vérification des trames et horodatages ILA |

Depuis la racine du projet, pour reproduire les figures nominales :

```powershell
py -3 scripts/plot_theoretical_rtt.py --local-bytes 10 --min-modules 2 --max-modules 30
```

Pour explorer un délai de réémission supposé de 48 ns sans remplacer les
figures nominales :

```powershell
py -3 scripts/plot_theoretical_rtt.py --local-bytes 10 --min-modules 2 --max-modules 30 --ct-redistribution-delay-ns 48 --output-dir reports/theoretical_rtt_10bytes_delay48ns
```

Ces commandes calculent des prédictions hors ligne. Elles ne contactent pas
les cartes et ne modifient pas leurs configurations.
