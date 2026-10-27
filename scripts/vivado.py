#!/usr/bin/env python3
"""Cross-platform Vivado launcher. No hard-coded workstation paths."""
from pathlib import Path
import argparse,os,shutil,subprocess,sys
p=argparse.ArgumentParser()
p.add_argument('action',choices=['project','build','capture','program','dump','runtime'])
p.add_argument('params',nargs='*')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
vivado=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat')
if not vivado: p.error('Vivado absent du PATH. Ouvrir le terminal Vivado 2025.2 ou définir VIVADO.')
script={'project':'create_project.tcl','build':'build.tcl','capture':'capture.tcl','program':'program.tcl','dump':'dump_log.tcl','runtime':'build_runtime.tcl'}[a.action]
cmd=[vivado,'-mode','batch','-nojournal','-nolog','-source',str(root/'scripts'/script)]
if a.params:cmd += ['-tclargs',*a.params]
env=os.environ.copy()
if os.name == 'nt':
    env['OBSIDIAN_BUILD_PYTHON']=sys.executable
    env['PATH']=str(root/'scripts/windows_compat')+os.pathsep+env.get('PATH','')
sys.exit(subprocess.call(cmd,cwd=root,env=env))
