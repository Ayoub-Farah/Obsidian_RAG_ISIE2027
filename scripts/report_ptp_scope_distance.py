"""Qualify measured PTP GPIO timing versus directed distance from M1.

Consumes marked offline scope cases and the actual runtime configuration. No
VISA/JTAG access, statistical extrapolation, or inferred absolute PTP epochs.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from ptp_config import normalize,config_id,partition
from ptp_scope_report import build_report


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify(directory,configuration,*,minimum_count=200,allow_uncalibrated=False):
    directory=Path(directory).resolve()
    cfg=normalize(json.loads(Path(configuration).read_text(encoding='utf-8')))
    if cfg['capacity']!=3 or cfg['nodes']!=9:
        raise ValueError('This qualification requires the K=3/N=9 hardware topology')
    cid=f'{config_id(cfg):016x}'
    base=build_report(directory,threshold_v=1.65)
    calibration=base['calibrations']['A_same_sync']
    offset=calibration['mean_s'] if calibration['available'] else None
    rows=[];problems=[];health_events=[]
    calibration_ok=offset is not None or allow_uncalibrated
    if not calibration_ok:problems.append('Missing complete common-net instrument calibration')
    for case in sorted(base['cases'],key=lambda c:c.get('case',{}).get('observer_node') or 0):
        meta=case.get('case',{})
        if meta.get('kind')!='module':continue
        node=meta['observer_node']
        expected_board=next(b for b,(first,count) in enumerate(partition(cfg['nodes'])) if first<=node<first+count)
        if meta['board']!='ABC'[expected_board]:raise ValueError('Case board differs from runtime partition')
        values=np.array([item['signed_mean_s'] for item in case['acquisitions'] if item['status']=='passed'])*1e9
        if not len(values):
            problems.append(f'M{node+1}: no valid waveform timing')
            continue
        corrected=values-offset*1e9 if offset is not None else None
        measured=corrected if corrected is not None else values
        row=dict(module=f'M{node+1}',node_id=node,board=meta['board'],hops=node,
                 physical_crossings=expected_board,internal_hops=node-expected_board,
                 drift_ppb=cfg['drift_ppb'][node],relative_injected_drift_ppb=cfg['drift_ppb'][node]-cfg['drift_ppb'][0],
                 acquisitions=case.get('acquisition_count',0),valid_acquisitions=len(values),
                 rejected_acquisitions=case.get('invalid_acquisition_count',0),
                 raw_mean_ns=float(values.mean()),sample_sd_ns=float(values.std(ddof=1)) if len(values)>1 else None,
                 timing_basis='common_net_bias_corrected' if corrected is not None else 'raw_uncalibrated',
                 measured_mean_ns=float(measured.mean()),measured_rms_ns=float(np.sqrt(np.mean(measured**2))),
                 measured_min_ns=float(measured.min()),measured_max_ns=float(measured.max()),
                 measured_max_abs_ns=float(np.max(np.abs(measured))),
                 measured_p95_abs_ns=float(np.quantile(np.abs(measured),.95)),
                 measured_p99_abs_ns=float(np.quantile(np.abs(measured),.99)),
                 corrected_mean_ns=float(corrected.mean()) if corrected is not None else None,
                 corrected_rms_ns=float(np.sqrt(np.mean(corrected**2))) if corrected is not None else None,
                 corrected_min_ns=float(corrected.min()) if corrected is not None else None,
                 corrected_max_ns=float(corrected.max()) if corrected is not None else None,
                 corrected_max_abs_ns=float(np.max(np.abs(corrected))) if corrected is not None else None,
                 corrected_p95_abs_ns=float(np.quantile(np.abs(corrected),.95)) if corrected is not None else None,
                 corrected_p99_abs_ns=float(np.quantile(np.abs(corrected),.99)) if corrected is not None else None,
                 wall_started_utc=case['acquisitions'][0].get('utc'),wall_finished_utc=case['acquisitions'][-1].get('utc'))
        for threshold in (20,50,64):
            row[f'fraction_abs_over_{threshold}ns']=float(np.mean(np.abs(measured)>threshold))
        row['health_verified']=True
        row['configuration_verified']=True
        for phase in ('before','after'):
            receipt=meta.get(f'health_{phase}_receipt')
            if not receipt:
                row['health_verified']=False
                row['configuration_verified']=False
                continue
            health=json.loads((directory/receipt).read_text(encoding='utf-8'))
            cards=health.get('cards',[])
            flagged=[card for card in cards if card.get('available') is not True or card.get('nominal') is not True]
            if health.get('status')!='ok' or flagged:
                health_events.append(dict(case=meta['id'],phase=phase,receipt=receipt,
                                          status=health.get('status'),cards=flagged))
            if len(cards)!=3 or any(card.get('available') is not True or card.get('config_id_hex')!=cid for card in cards):
                row['configuration_verified']=False
            if health.get('status')!='ok' or len(cards)!=3 or any(
                card.get('available') is not True or card.get('nominal') is not True or
                card.get('config_id_hex')!=cid for card in cards):
                row['health_verified']=False
        row['qualified_dataset']=bool(case['complete'] and len(values)>=minimum_count and
                                      row['health_verified'] and meta.get('wiring_verified') is True and calibration_ok)
        row['captured_dataset']=bool(case['complete'] and len(values)>=minimum_count and
                                      row['configuration_verified'] and meta.get('wiring_verified') is True and calibration_ok)
        if not row['captured_dataset']:problems.append(f'M{node+1}: incomplete waveform/configuration/wiring/calibration evidence')
        elif not row['health_verified']:problems.append(f'M{node+1}: non-nominal health snapshot; waveform dataset is complete')
        rows.append(row)
    nodes={row['node_id'] for row in rows}
    missing=[f'M{node+1}' for node in range(cfg['nodes']) if node not in nodes]
    if missing:problems.append('Missing modules: '+', '.join(missing))
    captured=bool(len(rows)==cfg['nodes'] and not missing and base['complete'] and all(row['captured_dataset'] for row in rows))
    complete=bool(not problems and captured)
    result=dict(schema='ptp_scope_distance_qualification_v1',source='physical_scope_measurements',
                configuration_path=str(Path(configuration).resolve()),
                generated_utc=datetime.now(timezone.utc).isoformat(),configuration=cfg,config_id=cid,
                campaign_complete=captured,nominal_checks_passed=complete,
                status='complete' if complete else 'complete_with_health_events' if captured else 'partial',problems=problems,
                instrument_calibration=calibration,minimum_acquisitions_per_module=minimum_count,
                timing_basis='common_net_bias_corrected' if offset is not None else 'raw_uncalibrated',
                uncalibrated_measurements_authorized=bool(allow_uncalibrated),
                modules=rows,missing_modules=missing,
                health_events=health_events,
                limits=['One fixed N=9 chain and one assignment of logical drifts; no law versus N is identified.',
                        ('OBS minus REF rising-edge delay after common-net mean-bias subtraction; GPIO/PCB paths remain.' if offset is not None else
                         'Raw OBS minus REF rising-edge delay; channel/probe skew and GPIO/PCB paths are included. No calibration from another run is reused.'),
                        'Segmented records within a burst are correlated; 200 consecutive triggers span about 20 ms. Export timestamps are not trigger timestamps.',
                        'Sequential module acquisitions do not identify simultaneous cross-module covariance.',
                        'Fresh triggered records do not prove no pulses were lost during USB dead time or absolute epoch identity.',
                        'Observed maxima and empirical quantiles are not deterministic limits or calibrated rare-tail probabilities.',
                        'Scope ADC time steps and interpolated times do not establish absolute picosecond accuracy.',
                        '20/50/64 ns exceedance fractions are descriptive; no user acceptance threshold was specified.'])
    (directory/'distance_qualification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (directory/'provenance').mkdir(exist_ok=True)
    (directory/'provenance'/'health_events.json').write_text(json.dumps(health_events,indent=2)+'\n',encoding='utf-8')
    if rows:
        with (directory/'distance_measurements.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        plot(directory,rows)
    write_readme(directory,result)
    return result


def plot(directory,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(15,4.7))
    for board,color in zip('ABC',('#2365a8','#cb7630','#39926b')):
        group=[r for r in rows if r['board']==board]
        if not group:continue
        h=[r['hops'] for r in group]
        counts='/'.join(str(n) for n in sorted({r['valid_acquisitions'] for r in group}))
        if all(r['measured_mean_ns'] is not None for r in group):
            axes[0].errorbar(h,[r['measured_mean_ns'] for r in group],
                             yerr=[r['sample_sd_ns'] or 0 for r in group],fmt='o',capsize=4,color=color,label=f'FPGA {board}, n={counts}')
            axes[2].plot(h,[r['measured_max_abs_ns'] for r in group],'o-',color=color,label=f'FPGA {board}')
        axes[1].plot(h,[r['sample_sd_ns'] for r in group],'o-',color=color,label=f'FPGA {board}')
    basis='corrigée' if rows[0]['timing_basis']=='common_net_bias_corrected' else 'brute, sans calibration'
    axes[0].set(title=f'Moyenne {basis} ± écart-type',ylabel='OBS − REF (ns)')
    axes[1].set(title='Dispersion des acquisitions',ylabel='Écart-type échantillon (ns)')
    axes[2].set(title='Maximum absolu observé',ylabel='|OBS − REF| (ns)')
    for row in rows:
        if not row['health_verified'] and row['measured_mean_ns'] is not None:
            for axis,key in zip(axes,('measured_mean_ns','sample_sd_ns','measured_max_abs_ns')):
                axis.plot(row['hops'],row[key],'o',markerfacecolor='none',markeredgecolor='red',markersize=11)
    for axis in axes:
        axis.set_xlabel('Sauts dirigés depuis M1');axis.set_xticks(range(9));axis.grid(alpha=.2)
        for crossing in (2.5,5.5):axis.axvline(crossing,color='gray',linestyle=':',alpha=.6)
    axes[0].legend(fontsize=8)
    fig.suptitle('DSO-X 3014T, CH1/CH3 — N=9, dérives logiques uniformes ±4 ppm\nMesures physiques successives ; maxima finis, sans extrapolation',fontsize=11)
    fig.tight_layout();fig.savefig(directory/'distance_offset_jitter.png',dpi=180);plt.close(fig)


def write_readme(directory,result):
    rows=result['modules'];cal=result['instrument_calibration']
    lines=['# Qualification PTP selon le nombre de sauts — DSOX3014T','',
           '**État : '+('acquisitions complètes, contrôles nominaux passants.' if result['nominal_checks_passed'] else
                        'acquisitions complètes, avec événements d’état PTP à qualifier.' if result['campaign_complete'] else 'campagne partielle.')+'**',
           f'Configuration K=3/N=9, run_id={result["configuration"]["run_id"]}, `config_id={result["config_id"]}`.',
           'Trois FPGA A/B/C, trois modules par carte ; neuf accumulateurs logiques avec un tirage fixe uniforme ±4 ppm.',
           'CH1 reste sur TEST_SYNC de A/M1 ; CH3 mesure successivement les sorties OBS de A, B puis C.',
           'Période logique 100 µs, maintenance 1 ms. La sélection MOSI est relue par JTAG ; le branchement est confirmé par l’opérateur.',
           '', '![Résultats selon les sauts](distance_offset_jitter.png)','',
           '| Module | FPGA | Sauts h | Frontières physiques | Dérive (ppm) | N valides | Moyenne OBS−REF (ns) | SD (ns) | RMS (ns) | Max. absolu observé (ns) |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        def f(key):return f'{r[key]:.3f}' if r[key] is not None else '—'
        lines.append(f'| {r["module"]} | {r["board"]} | {r["hops"]} | {r["physical_crossings"]} | {r["drift_ppb"]/1000:+.3f} | {r["valid_acquisitions"]} | {f("measured_mean_ns")} | {f("sample_sd_ns")} | {f("measured_rms_ns")} | {f("measured_max_abs_ns")} |')
    lines+=['','Le délai signé vaut front OBS moins front REF. Une valeur négative indique un front observé en avance.',
            ('La moyenne corrigée retire uniquement le biais commun des voies et sondes ; les différences de sorties FPGA et de pistes restent incluses.' if cal['available'] else
             '**Mesures brutes sans calibration des sondes, conformément au choix de l’opérateur.** Les décalages des voies, sondes et pistes sont inclus ; aucun biais d’un essai précédent n’est soustrait.'),
            'SD utilise n−1 ; RMS comprend le décalage moyen. Une valeur par enregistrement déclenché. Les segments d’une rafale peuvent être corrélés.', '']
    if cal['available']:
        lines.append(f'Calibration sur le même net TEST_SYNC de A : biais moyen CH3−CH1 = **{cal["mean_s"]*1e9:+.3f} ns**. Aucune variance de calibration n’est soustraite.')
    try:reproduction_path=directory.relative_to(ROOT).as_posix()
    except ValueError:reproduction_path=directory.as_posix()
    try:configuration_path=Path(result['configuration_path']).relative_to(ROOT).as_posix()
    except ValueError:configuration_path=Path(result['configuration_path']).as_posix()
    raw_flag=' --allow-uncalibrated' if result['uncalibrated_measurements_authorized'] else ''
    lines+=['','## Données et traçabilité','',
            '- [Tableau par saut, quantiles et dépassements](distance_measurements.csv).',
            '- [Qualification détaillée](distance_qualification.json) et [analyse des acquisitions](analysis.json).',
            '- [Programmation et configuration des trois cartes](provenance/programming.json).',
            '- [Événements d’état PTP conservés](provenance/health_events.json). Les points entourés en rouge ont un contrôle JTAG associé non nominal ; leurs formes d’onde restent visibles dans les résultats.',
            '- Les fichiers `single_*.npz` et leurs préambules JSON conservent les octets CH1/CH3 et les origines temporelles distinctes fournies par l’instrument.',
            '- Les captures larges `wide_before` vérifient la période ; elles sont exclues des statistiques fines.',
            '- En mode segmenté, les horodatages UTC des fichiers sont ceux de leur export. Les étiquettes relatives `segment_time_tag_s` et les rafales sont conservées ; 200 fronts successifs couvrent environ 20 ms.',
            '', '## Portée des résultats','',
            'Les sauts suivent M1 → M2 → … → M9 : h=0..8, avec une frontière FPGA à M4 puis M7. Ce sont des résultats pour cette topologie et ce tirage de fréquences ; ils ne séparent pas à eux seuls l’effet du saut, de la fréquence et du chemin physique.',
            'Les lectures JTAG avant/après sont ponctuelles. Les sélections successives ne mesurent pas simultanément tous les modules et ne prouvent pas l’absence de pulses perdus pendant les temps morts USB.',
            'Les maxima et quantiles sont empiriques. Les fractions au-delà de 20/50/64 ns sont descriptives ; aucun critère d’acceptation n’a été imposé par l’utilisateur.',
            'Le DSOX3014T est utilisé en acquisition normale, sans moyennage ni correction temporelle de sonde. L’instrument exporte la fenêtre RAW visible à son pas ADC natif ; celle-ci peut être plus petite que la mémoire d’acquisition interne. Les origines temporelles propres aux voies sont conservées.',
            'La cadence effectivement relue et chaque préambule sont archivés. L’interpolation des fronts ne démontre pas une exactitude absolue à la picoseconde.',
            '', '[Guide de programmation officiel Keysight 3000T](https://www.keysight.com/us/en/assets/9023-40024/miscellaneous/3kT_X-Series_prog_guide.pdf) : transfert BYTE, axes temporels par voie et acquisition DIGitize.',
            '', 'Reproduction offline :','',
            '```powershell',f'py -3 scripts/report_ptp_scope_distance.py "{reproduction_path}" --config "{configuration_path}"{raw_flag}','```','']
    if (directory/'02_A_same_sync').exists():
        lines+=['La première calibration `02_A_same_sync` est exclue : 126 paires valides puis une capture CH3 plate, CH1 restant active ; cause indéterminée. La série complète suivante contient 200 captures valides. Les essais de mise au point et le timeout d’armement `04_A_identity_reenabled` sont conservés comme diagnostics.','']
    for event in result['health_events']:
        for card in event['cards']:
            lines.append(f'Événement JTAG {event["phase"]} {event["case"]} : carte `{card.get("serial")}`, '
                         f'`all_local_locked={card.get("all_local_locked")}`, `operational={card.get("operational")}`. '
                         'Le statut agrégé ne permet pas d’identifier le module concerné ni la durée du déverrouillage.')
    if result['problems']:lines+=['Écarts aux contrôles : '+ '; '.join(result['problems'])+'.','']
    (directory/'README.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--config',type=Path,default=ROOT/'config/ptp_emulation_9_uniform_4ppm.json')
    p.add_argument('--minimum-count',type=int,default=200)
    p.add_argument('--allow-uncalibrated',action='store_true',help='Report raw OBS-minus-REF delays when the operator waived common-net calibration')
    args=p.parse_args()
    if args.minimum_count<2:p.error('--minimum-count must be at least 2')
    result=qualify(args.directory,args.config,minimum_count=args.minimum_count,allow_uncalibrated=args.allow_uncalibrated)
    print(json.dumps(dict(status=result['status'],campaign_complete=result['campaign_complete'],
                          measured_modules=len(result['modules']),missing_modules=result['missing_modules'])))


if __name__=='__main__':main()
