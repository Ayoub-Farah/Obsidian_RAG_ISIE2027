"""Package only a source-matched, timing-accepted common image and real evidence."""
from pathlib import Path
import datetime,hashlib,json,shutil,zipfile
ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write_report(build,tests,execution):
    lines=(build/'timing_summary.rpt').read_text(errors='replace').splitlines()
    index=next(i for i,line in enumerate(lines) if 'WNS(ns)' in line and 'TNS(ns)' in line)
    values=lines[index+2].split();wns=float(values[0]);whs=float(values[4])
    if wns<0 or whs<0 or int(values[2]) or int(values[6]):raise RuntimeError('Timing report contradicts accepted status')
    table=(build/'implementation_utilization.rpt').read_text(errors='replace').splitlines()
    row=next(line for line in table if '| obsidian_physical_top ' in line)
    cells=[s.strip() for s in row.split('|')[1:-1]]
    lut=int(cells[2]);ff=int(cells[6]);bram=int(cells[7])+.5*int(cells[8])
    bitsha=digest(build/'obsidian_benchmark.bit');ltxsha=digest(build/'obsidian_benchmark.ltx')
    text=f'''# Validation du banc physique CT/RAG

Le BIT/LTX commun a été produit avec Vivado 2025.2 pour XC7A35T-CSG325-2.
Les paramètres de caractérisation et le rôle A/B/C sont des registres VIO.
L'image contient un seul moteur physique, sans nœud virtuel.

| Vérification finale | Résultat |
|---|---|
| Setup WNS | {wns:.3f} ns, aucun endpoint en échec |
| Hold WHS | {whs:.3f} ns, aucun endpoint en échec |
| LUT | {lut} / 20800 |
| Registres | {ff} / 41600 |
| BRAM équivalentes RAMB36 | {bram:g} / 50 |
| Bus skew, DRC Error, horloges/chemins internes non contraints | critères de construction passants |
| Scénarios XSim | {len(tests['rtl_cases'])} passants, empreintes de sources vérifiées |
| Tests Python/Tcl simulé | {tests['python_tests']} passants |

La construction a réellement exécuté génération des IP Aurora/VIO/ILA,
synthèse, placement, routage et optimisation physique. Les reprises de
checkpoints vérifient les empreintes RTL/XDC ; leur provenance est conservée
dans `build/physical_runtime/execution.json` et `attempts/`.

Les tests couvrent CT → RAG → CT dans une élaboration, tailles paires/impaires
et maximales, contributions, cut-through, H jusqu'à 65535 avec petit payload,
pauses, CRC corrompu dans un emplacement remplacé, configurations divergentes,
configuration/arrêt pendant trafic, arrêt pendant préparation différée,
maintien prolongé, période de 10 ms avec maintenance pendant l'attente,
absence de maintenance pendant DATA et 129 essais paginés.
L'acquittement JTAG maintenu haut ne libère qu'une page. Le contre-exemple avant
correction reste dans `reports/physical_validation/ack_held_before_fix.log`.

Les CSV et courbes de `reports/physical_validation/` proviennent de simulations
RTL et portent cette étiquette. Les modèles de transport numériques ne sont
pas une simulation analogique des transceivers Aurora ni une mesure de fibre.
Les métriques intercartes restent absentes sans calibration externe valide.

**Aucune carte n'a été programmée et aucune mesure matérielle n'a été fabriquée.**
Le chargement manuel, le contrôle des liens et la calibration sur le banc réel
restent à effectuer par l'utilisateur.

BIT SHA256 : `{bitsha}`  
LTX SHA256 : `{ltxsha}`

Voir [le guide](physical_runtime.md), [les tests](../reports/physical_validation/validation.json)
et [les rapports de construction](../build/physical_runtime/execution.json).
'''
    (ROOT/'docs/validation_physique.md').write_text(text,encoding='utf-8')

def main():
    build=ROOT/'build/physical_runtime';validation=ROOT/'reports/physical_validation'
    execution=json.loads((build/'execution.json').read_text());tests=json.loads((validation/'validation.json').read_text())
    if execution.get('status')!='passed' or tests.get('status')!='passed':raise RuntimeError('Accepted implementation and tests required')
    manifest=(build/'build_manifest.txt').read_text()
    if 'schema=physical_v3' not in manifest or 'status=implemented_timing_pass_bitstream_generated' not in manifest:raise RuntimeError('Wrong/unaccepted firmware manifest')
    for source in (build/'source_sha256.json',validation/'source_sha256.json'):
        for name,expected in json.loads(source.read_text()).items():
            if digest(ROOT/name)!=expected:raise RuntimeError('Evidence source changed: '+name)
    accepted=json.loads((build/'artifacts_sha256.json').read_text())
    for name in ('obsidian_benchmark.bit','obsidian_benchmark.ltx'):
        if accepted.get(name)!=digest(build/name):raise RuntimeError('Artifact hash mismatch: '+name)
    write_report(build,tests,execution)
    legacy=ROOT/'reference/legacy_manifest';legacy.mkdir(parents=True,exist_ok=True)
    for name in ('ARTIFACT_MANIFEST.json','SHA256SUMS'):
        if (ROOT/name).exists() and not (legacy/name).exists():shutil.copy2(ROOT/name,legacy/name)
    selected=set()
    for folder in ('rtl','constraints','config','scripts','sim','tools','docs','reference','.vscode'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix.lower() in ('.vhd','.xdc','.json','.py','.tcl','.md','.txt','.bat','.ps1','.sh','.js'):
                selected.add(p)
    for name in ('README.md','LICENSE','Obsidian_RAG.code-workspace','SOURCE_PROVENANCE.json','family.json','family.tcl','.gitignore'):
        if (ROOT/name).exists():selected.add(ROOT/name)
    for p in validation.iterdir():
        if p.is_file():selected.add(p)
    for p in build.iterdir():
        if p.is_file() and p.suffix.lower() in ('.bit','.ltx','.rpt','.json','.txt','.log'):selected.add(p)
    for p in (build/'attempts').rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.rpt','.json','.txt','.log'):selected.add(p)
    hashes={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(selected)}
    delivery=dict(schema='obsidian_physical_delivery_v1',created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status='implemented_timing_pass_bitstream_generated',top='obsidian_physical_top',physical_boards=3,virtual_nodes=0,
        common_bitstream='build/physical_runtime/obsidian_benchmark.bit',common_probes='build/physical_runtime/obsidian_benchmark.ltx',
        roles={'A':0,'B':1,'C':2},runtime_modes={'CT':1,'RAG':2},max_payload_bytes=4096,max_local_bytes=1365,max_hops=65535,
        rtl_cases=len(tests['rtl_cases']),python_tests=tests['python_tests'],hardware_programmed=False,hardware_measurements=0,
        archive_scope='Source project, common BIT/LTX, accepted reports and validation. IP caches/checkpoints are regenerated by the build scripts.',
        historical_profiles='Legacy reports/specifications are retained and do not validate the new image.',files_sha256=hashes)
    artifact_manifest=ROOT/'ARTIFACT_MANIFEST.json';artifact_manifest.write_text(json.dumps(delivery,indent=2)+'\n',encoding='utf-8')
    selected.add(artifact_manifest);hashes[artifact_manifest.relative_to(ROOT).as_posix()]=digest(artifact_manifest)
    sums=ROOT/'SHA256SUMS';sums.write_text(''.join(f'{value}  {name}\n' for name,value in sorted(hashes.items())),encoding='utf-8');selected.add(sums)
    out=ROOT/'dist';out.mkdir(exist_ok=True);archive=out/'Obsidian_RAG_physical.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(selected):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP CRC verification failed')
    checksum=digest(archive);archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n')
    print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,sha256=checksum,files=len(selected),hardware_programmed=False),indent=2))
if __name__=='__main__':main()
