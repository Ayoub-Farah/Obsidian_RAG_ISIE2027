Largest verified routed capacity: K=3 (9 modules across three boards).
Recommended engineering margin: K=3 (9 modules across three boards).
Selection requires at least 15.0% free LUT, 15.0% free FF and 0.5 ns setup margin.
Hardware validation: none; this report checks build artifacts.

| K | Ring nodes | Classification | LUT (free %) | FF (free %) | BRAM36 equivalent | DSP | Setup ns | Sources match |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3 | routed_pass | 7466 (64.11%) | 11421 (72.55%) | 8.0 | 1 | 1.453 | True |
| 2 | 6 | routed_pass | 12012 (42.25%) | 17079 (58.94%) | 10.0 | 2 | 1.24 | True |
| 2 | 6 | synthesis_candidate | 11792 (43.31%) | 16564 (60.18%) | 10.0 | 2 | — | True |
| 3 | 9 | routed_pass | 16558 (20.39%) | 22744 (45.33%) | 12.0 | 3 | 0.573 | True |
| 3 | 9 | synthesis_candidate | 16624 (20.08%) | 22231 (46.56%) | 12.0 | 3 | — | True |
| 4 | 12 | resource_rejection | 21107 (-1.48%) | 27869 (33.01%) | 14.0 | 4 | — | True |
| 4 | 12 | resource_rejection | 21107 (-1.48%) | 27869 (33.01%) | 14.0 | 4 | — | True |

Next observed rejection: K=4 (resource_rejection). Untested intermediate capacities: []; intermediate capacities without a verified route: []. Larger capacities were not all tested.

Selections apply only to the listed, source-matched builds. A synthesis fit is a candidate; a failed next candidate does not establish that every larger capacity was tested. Hardware synchronization and functional RTL validation are separate evidence.

Build evidence:

- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_single_node_final
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k2_route2
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k2_synth
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k3_route
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k3_synth
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k4_route2
- C:\Users\afarahhass\Documents\Xilinx_project\Obsidian_RAG\build\ptp_capacity_search\k4_synth
