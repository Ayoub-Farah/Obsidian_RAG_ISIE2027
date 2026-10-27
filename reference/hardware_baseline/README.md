# Contre-exemple avant correction

Ces fichiers décrivent l'ancienne image SHA256
`9151d08ab6aa2bfb570e7df7313f40af063be768b40191fd12b7eacfaf08d21a`.
Ils ne constituent pas la validation de l'image corrigée.

Pour CT P=3, S=1, le premier TX de B/C est accepté au même cycle que leur
dernier RX. Les trois pages matérielles brutes et l'échec de simulation
reproduisent ce cas. Le moteur attendait un cycle supplémentaire pour relire
`desc.ready` après validation de l'en-tête.

La correction prend le relais sur ce même front de validation, uniquement si
le TX est libre, sans injection en attente, et pour le descripteur de tête
validé qui doit être relayé. Le contrôle entrant et la rétention du CRC sortant
restent indépendants. La régression stricte se trouve au niveau des interfaces
physiques du banc `tb_physical_system`.

Le journal du défaut initial est conservé séparément : son bit de défaut ne
distinguait pas les différentes causes possibles de réception au démarrage.
