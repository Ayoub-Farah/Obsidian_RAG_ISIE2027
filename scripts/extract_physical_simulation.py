"""Export actual PHYS_SUMMARY records from an XSim transcript, never hardware data."""
from pathlib import Path
import argparse,csv,hashlib,json,re
from decode_physical import decode_page,FIELDS

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    text=a.log.read_text(errors='replace')
    if 'PASS tb_physical_system' not in text or re.search(r'(Failure:|Fatal:|ERROR:)',text):raise ValueError('Simulation transcript did not pass')
    rows=[]
    for index,(board,hex_value) in enumerate(re.findall(r'PHYS_SUMMARY,([ABC]),([0-9A-Fa-f]{512})',text)):
        s=int(hex_value,16);words=[0]*8192
        for j in range(32):words[j]=s>>(64*j)&((1<<64)-1)
        # Internal adapter to the shared summary decoder. Only transcript words
        # are interpreted; no fabricated page/capture is written to disk.
        page=dict(source='rtl_simulation',words=words,board=board,page=index//3,summary_count=1,event_count=0,calibration_count=0)
        r,_,_=decode_page(page);rows+=r
    if not rows:raise ValueError('No actual summary records in transcript')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(rows)
    a.output.with_suffix('.provenance.json').write_text(json.dumps(dict(source='rtl_simulation',log=str(a.log),log_sha256=hashlib.sha256(a.log.read_bytes()).hexdigest(),rows=len(rows),hardware_measurements=0),indent=2)+'\n')
if __name__=='__main__':main()
