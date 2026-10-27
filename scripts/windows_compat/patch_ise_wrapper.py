"""Use Vivado's legacy WSH launcher without optional WMI host profiling.
Only generated wrappers below this project or in the active run directory
are changed, never AMD installation files. The vendor's own begin/end/error handling and actual tool exits remain.
"""
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[2]
for arg in sys.argv[1:]:
    if Path(arg).name.lower() != 'rundef.js':
        continue
    script = Path(arg).resolve()
    try:
        script.relative_to(root)
    except ValueError:
        if script.parent != Path.cwd().resolve():
            continue
    wrapper = script.with_name('ISEWrap.js')
    if wrapper.is_file():
        text = wrapper.read_text()
        old = 'var ISEOldVersionWSH = false;'
        if old in text:
            wrapper.write_text(text.replace(old, 'var ISEOldVersionWSH = true;'))
