"""Offline analytical payload sweep: collection of peers' data at module 1."""
from pathlib import Path
import csv
import json
import math

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from plot_theoretical_rtt import ROOT, parameters


def main():
    p = parameters()
    n = 30
    tau = p['tick_ns'] / 1000
    d = p['equivalent_link_ns'] / 1000
    r = p['relay_minimum_ns'] / 1000
    g = p['tx_last_to_next_first_ticks'] * tau
    serialization = lambda payload: tau * (math.ceil((payload + 36) / 2) - 1)
    rows = []
    for payload in range(1, 21):
        sc = serialization((n - 1) * payload)
        sr = serialization(payload)
        cadence = max(d + r, sr + g)
        # Source at distance h: first TX at (h-1)*cadence, last RX at
        # that time + d + sr. The farthest peer is h=N-1 from module 1.
        arrivals = [sr + d + (h - 1) * cadence for h in range(1, n)]
        rows.append(dict(payload_per_peer_bytes=payload, ct_payload_bytes=29*payload,
                         rag_payload_bytes=payload, ct_serialization_us=sc,
                         rag_serialization_us=sr, rag_cadence_us=cadence,
                         ct_collection_us=sc+n*d+(n-1)*r,
                         rag_collection_us=max(arrivals),
                         rag_full_return_us=sr+d+(n-1)*cadence))
    assert all(math.isclose(row['rag_cadence_us'], .912) for row in rows)
    assert math.isclose(rows[9]['ct_collection_us'], 29.664)
    assert math.isclose(rows[9]['rag_collection_us'], 26.512)
    out = ROOT / 'reports/theoretical_payload_n30'
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'collection_vs_payload.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = dict(modules=n, payload_range_bytes=[1,20], parameters=p,
                    source='nominal_analytical_model_not_hardware_measurements',
                    equations=dict(serialization='0.016*(ceil((payload+36)/2)-1) us',
                                   CT='S(29*P)+30*d+29*r',
                                   RAG='S(P)+d+28*max(d+r,S(P)+g)'),
                    assumptions=['CT reserves all 29 peer slots from the first TX; no module-1 data.',
                                 'CT cut-through slot filling adds no delay; collection only, no redistribution.',
                                 'RAG uses the report synchronous homogeneous cadence; equal-sized peer packets.',
                                 'Module 1 may inject an equal-sized packet as in the report; its return is not required.',
                                 'Time zero: module-1 first CT TX / simultaneous first RAG TX.',
                                 'Completion: last word of all 29 peer payloads at module 1.',
                                 'No extra pauses, acquisition, preparation, host readout or heterogeneous arbitration.',
                                 'Coefficients extrapolated from three physical boards; no validation at N=30.'])
    (out / 'model_assumptions.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    fig, ax = plt.subplots(figsize=(10, 6), layout='constrained')
    xs = [row['payload_per_peer_bytes'] for row in rows]
    ax.plot(xs, [row['ct_collection_us'] for row in rows], 'o-', label='CT — retour de la table de 29P octets')
    ax.plot(xs, [row['rag_collection_us'] for row in rows], 's--', label='RAG — réception des 29 données (29 sauts max.)')
    ax.set(xlabel='Payload par module autre que 1, P (octets)',
           ylabel='Temps de collecte au module 1 (µs)',
           title='N = 30 modules — prédiction analytique nominale', xticks=xs)
    ax.grid(alpha=.25)
    ax.legend()
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(out / f'collection_vs_payload.{ext}', dpi=200)
    plt.close(fig)
    print(json.dumps([rows[i] for i in (0,4,9,14,19)], indent=2))


if __name__ == '__main__':
    main()
